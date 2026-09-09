"""Transport-neutral action envelopes; rule validation stays with the engine.

IDs derive from existing durable counters, not a second sequence. Model binding
is context-local and crosses asyncio.to_thread without mutable agent fields.
No request IDs/slots are added to the provider's model prompt.
"""
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass

from .participants import Participant


def request_id(match_id, channel, number):
    if type(number) is not int or number < 1:
        raise ValueError("Action request requires a positive durable counter")
    raw = json.dumps([match_id, channel, number], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_decision_binding = ContextVar("werewolf_decision_binding", default=None)


@contextmanager
def bind_decision(match_id, number):
    token = _decision_binding.set((match_id, number))
    try:
        yield
    finally:
        _decision_binding.reset(token)


@dataclass(frozen=True)
class ActionProposal:
    request_id: str | None
    participant: Participant
    payload: dict

    def __post_init__(self):
        object.__setattr__(self, "payload", deepcopy(self.payload))


@dataclass(frozen=True)
class ActionRequest:
    request_id: str | None
    participant: Participant
    phase: str
    kind: str
    data: dict

    def __post_init__(self):
        object.__setattr__(self, "data", deepcopy(self.data))

    @classmethod
    def human(cls, participant, event_no, phase, kind, data):
        return cls(request_id(participant.match_id, "human", event_no),
                   participant, phase, kind, data)

    @classmethod
    def model(cls, observation, properties):
        binding = _decision_binding.get()
        if binding is not None and binding[0] != observation.participant.match_id:
            raise ValueError("Decision belongs to a different match")
        # Direct adapter unit/research calls have no durable session decision.
        # Explicit None is local-only; all session model calls are bound.
        identity = request_id(binding[0], "model", binding[1]) if binding else None
        return cls(identity, observation.participant,
                   observation.payload["information"]["phase"],
                   observation.payload["task"], properties)

    def accept(self, proposal):
        if (proposal.request_id != self.request_id
                or proposal.participant != self.participant):
            raise ValueError("Stale action or different participant")
        return deepcopy(proposal.payload)

    def to_event(self):
        return {"type": "request", "kind": self.kind, "data": deepcopy(self.data),
                "request_id": self.request_id, "participant_id": self.participant.participant_id}
