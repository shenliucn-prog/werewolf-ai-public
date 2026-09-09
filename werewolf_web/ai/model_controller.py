"""Engine-free model invocation and response validation.

Budget reservation, retries, commit and memory remain with the existing
session/agent owners. No model choice or fallback policy is added here.
"""
import json
from copy import deepcopy

from .. import perf
from ..actions import ActionProposal, ActionRequest
from .decision_runtime import ModelTurnError


def object_schema(properties):
    return {"type": "object", "properties": deepcopy(properties),
            "required": list(properties), "additionalProperties": False}


class ModelController:
    def __init__(self, planner, recorder=None):
        self.planner = planner
        self.recorder = recorder

    def decide(self, observation, properties):
        action = ActionRequest.model(observation, properties)
        return action.accept(self.propose(action, observation))

    def propose(self, action, observation):
        if (action.participant != observation.participant
                or action.kind != observation.payload["task"]):
            raise ModelTurnError("Action does not match its observation")
        return ActionProposal(action.request_id, action.participant,
                              self._complete(observation, action.data))

    def _complete(self, observation, properties):
        request = observation.to_request()
        request_chars = len(json.dumps(request, ensure_ascii=False))
        t0 = perf.now()
        value = self.planner.complete(request, object_schema(properties))
        if self.recorder is not None:
            self.recorder.model_call(
                seat=observation.participant.seat, task=request["task"],
                backend=getattr(self.planner, "backend", None),
                request_chars=request_chars, dur_ms=perf.elapsed_ms(t0))
        if not isinstance(value, dict) or set(value) != set(properties):
            raise ModelTurnError("Invalid decision fields; no offline substitution.")
        for key, spec in properties.items():
            item = value[key]
            if "enum" in spec and item not in spec["enum"]:
                raise ModelTurnError("Illegal model decision; no offline substitution.")
            kind = spec.get("type")
            valid = ((kind == "boolean" and type(item) is bool) or
                     (kind == "string" and isinstance(item, str) and 0 < len(item.strip()) <= spec.get("maxLength", 2000)) or
                     (isinstance(kind, list) and (item is None or
                        ("integer" in kind and type(item) is int) or
                        ("string" in kind and isinstance(item, str)))))
            if not valid:
                raise ModelTurnError("Malformed model decision; no offline substitution.")
        return deepcopy(value)
