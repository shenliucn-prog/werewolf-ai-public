"""Conversation queues and floor policy without engine/model/transport access.

Questions retain the legacy name-pair format; a single active interruption uses
stable participant IDs and a source reference. The caller persists mutations
with speech events, then publishes; these primitives do no IO.
"""
from copy import deepcopy
import uuid

from .actions import request_id


class FloorPolicy:
    """Existing deterministic arbitration, using scores/public counters only."""
    EXTRA_LIMIT = 3
    SPEAKER_LIMIT = 2
    NEUTRAL_CHANCE = 0.16

    @staticmethod
    def choose(contenders):
        # (interest, seat, participant_id); never completion/arrival time.
        return max(contenders, key=lambda item: (item[0], -item[1])) if contenders else None

    @staticmethod
    def close_reason(*, topic_turns, extra_turns, speaker_extra_turns, repeated_pair):
        # Preserve the host's separate total-discussion ceiling, including its
        # existing priority over pair/speaker reasons and localized wording.
        if extra_turns >= 7:
            return "space"
        if repeated_pair or topic_turns >= 3:
            return "pair"
        if speaker_extra_turns >= 2:
            return "speaker"
        return None


class InterruptionIntent:
    """One durable interrupt/reply chain stored in the existing step_state.

    This is a single active intent, not a new all-player polling scheduler.
    Payloads contain public speech and stable participant IDs, never roles.
    """
    STAGES = ("select", "interrupt", "reply_gate", "reply", "close")
    FIELDS = {"version", "intent_id", "source_id", "source_event_no", "source_speech",
              "stage", "interrupter_id", "interruption", "interruption_event_no", "reply_event_no"}

    @classmethod
    def new(cls, match_id, source_id, speech, event_no=None):
        return {"version": 1,
                "intent_id": request_id(match_id, "table-talk", event_no) if event_no is not None else uuid.uuid4().hex,
                "source_id": source_id, "source_event_no": event_no,
                "source_speech": deepcopy(speech), "stage": "select",
                "interrupter_id": None, "interruption": None,
                "interruption_event_no": None, "reply_event_no": None}

    @staticmethod
    def _speech(value):
        fields = {"text", "claim", "accuse", "defend", "question_to", "protected_facts"}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("Invalid interruption speech fields")
        if not isinstance(value["text"], str):
            raise ValueError("Invalid interruption speech text")
        if any(value[k] is not None and not isinstance(value[k], str)
               for k in ("claim", "accuse", "defend", "question_to")):
            raise ValueError("Invalid interruption speech metadata")
        if (not isinstance(value["protected_facts"], (list, tuple))
                or any(not isinstance(x, str) for x in value["protected_facts"])):
            raise ValueError("Invalid interruption protected facts")

    @classmethod
    def validate(cls, value, match_id, roster, events):
        if not isinstance(value, dict) or set(value) != cls.FIELDS:
            raise ValueError("Invalid interruption intent fields")
        if type(value["version"]) is not int or value["version"] != 1 or value["stage"] not in cls.STAGES:
            raise ValueError("Unsupported interruption intent version/stage")
        identity = value["intent_id"]
        if not isinstance(identity, str) or len(identity) not in (32, 64) or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("Invalid interruption intent ID")
        if not isinstance(value["source_id"], str) or value["source_id"] not in roster:
            raise ValueError("Unknown interruption source")
        source = roster[value["source_id"]]
        cls._speech(value["source_speech"])

        def speech_event(number, participant, text=None):
            if type(number) is not int or not 1 <= number <= len(events):
                raise ValueError("Unknown interruption event")
            event = events[number - 1]
            if (event.get("type") != "speech" or event.get("seat") != participant.seat
                    or (text is not None and event.get("text") != text)):
                raise ValueError("Interruption event does not match its speaker/text")

        origin = value["source_event_no"]
        if origin is not None:
            speech_event(origin, source, value["source_speech"]["text"])
            if identity != request_id(match_id, "table-talk", origin):
                raise ValueError("Interruption ID does not match its source event")
        selected = value["interrupter_id"]
        stage = value["stage"]
        if stage == "select":
            if any(value[k] is not None for k in ("interrupter_id", "interruption", "interruption_event_no", "reply_event_no")):
                raise ValueError("Unselected interruption already has results")
        else:
            if (not isinstance(selected, str) or selected not in roster or selected == value["source_id"]
                    or roster[selected].controller == "human"):
                raise ValueError("Invalid selected interrupter")
            if stage == "interrupt":
                if any(value[k] is not None for k in ("interruption", "interruption_event_no", "reply_event_no")):
                    raise ValueError("Uncommitted interruption already has speech")
            else:
                cls._speech(value["interruption"])
                speech_event(value["interruption_event_no"], roster[selected], value["interruption"]["text"])
                if origin is not None and value["interruption_event_no"] <= origin:
                    raise ValueError("Interruption predates its source")
                if stage == "close":
                    speech_event(value["reply_event_no"], source)
                    if value["reply_event_no"] <= value["interruption_event_no"]:
                        raise ValueError("Reply predates interruption")
                elif value["reply_event_no"] is not None:
                    raise ValueError("Reply event before reply completion")


class QuestionQueue:
    LIMIT = 2

    def __init__(self, pending=None, answered=0):
        self.pending = deepcopy(pending or [])
        self.answered = answered

    @staticmethod
    def _pairs(raw, where):
        if not isinstance(raw, list):
            raise ValueError(f"{where} must be a list")
        pairs = []
        for pair in raw:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or any(not isinstance(name, str) or not name for name in pair)):
                raise ValueError(f"{where} must contain non-empty target/asker pairs")
            pair = list(pair)
            if pair in pairs:
                raise ValueError(f"{where} contains duplicate pairs")
            pairs.append(pair)
        return pairs

    @classmethod
    def from_snapshot(cls, snapshot):
        """Validate before the caller applies any restored session fields."""
        raw = snapshot.get("pending_questions", [])
        if isinstance(raw, dict):
            raw = [[target, asker] for target, asker in raw.items()]
        pending = cls._pairs(raw, "pending_questions")
        answered = snapshot.get("questions_answered", 0)
        if type(answered) is not int or not 0 <= answered <= cls.LIMIT:
            raise ValueError("questions_answered must be an integer in 0..2")
        state = snapshot.get("step_state", {})
        if not isinstance(state, dict):
            raise ValueError("step_state must be an object")
        if "question_window" in state:
            window = cls._pairs(state["question_window"], "question_window")
            if any(pair not in pending for pair in window):
                raise ValueError("question_window contains a non-pending question")
        if "answering_question" in state:
            active = cls._pairs([state["answering_question"]], "answering_question")[0]
            if active not in pending or answered >= cls.LIMIT:
                raise ValueError("answering_question is not eligible")
            if "question_window" in state and active not in state["question_window"]:
                raise ValueError("answering_question is outside its window")
        return cls(pending, answered)

    def snapshot_fields(self):
        return {"pending_questions": deepcopy(self.pending),
                "questions_answered": self.answered}

    def enqueue(self, target, asker):
        pair = self._pairs([[target, asker]], "question")[0]
        if pair in self.pending:
            return False
        self.pending.append(pair)
        return True

    def window(self, state):
        # Replies can enqueue more questions, but cannot expand this window.
        # Persisting the remaining window makes restart follow the same rule.
        if "question_window" not in state:
            state["question_window"] = deepcopy(self.pending)
        return deepcopy(state["question_window"])

    def begin(self, pair, state):
        if pair not in self.pending or self.answered >= self.LIMIT:
            raise ValueError("Question is no longer eligible")
        active = state.get("answering_question")
        if active is not None and active != pair:
            raise ValueError("Another question is already being answered")
        state["answering_question"] = list(pair)
        return active is None

    def finish(self, pair, state, *, consume=True):
        """Exactly-once dequeue; caller commits this together with the reply.

        Answer/skip consumes an opportunity. Dead/unknown targets and excess
        questions are removed without consumption, preserving the old policy.
        """
        if pair not in self.pending:
            return False
        if consume and (state.get("answering_question") != pair or self.answered >= self.LIMIT):
            raise ValueError("Cannot consume an inactive question")
        self.pending.remove(pair)
        if pair in state.get("question_window", []):
            state["question_window"].remove(pair)
        if state.get("answering_question") == pair:
            state.pop("answering_question")
        if consume:
            self.answered += 1
        return True

    def close_window(self, state):
        if state.get("question_window") or state.get("answering_question"):
            raise ValueError("Cannot close an unfinished clarification window")
        # Keep the empty window until the next day's reset. A crash in a later
        # day-wrap ability must not reopen it for questions created by replies.
        state["question_window"] = []

    def reset(self, state):
        self.pending = []
        self.answered = 0
        state.pop("answering_question", None)
        state.pop("question_window", None)
