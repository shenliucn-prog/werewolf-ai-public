"""Public speech acts, not identity evidence or executable instructions."""
from copy import deepcopy

KINDS = frozenset({"suspect", "support", "question", "claim", "report", "cite",
                   "challenge", "listen", "admit", "refuse", "defer",
                   "explain_stance", "reserve_judgment", "request_basis",
                   "acknowledge", "stand_firm", "reconsider"})


def validate(action):
    if action is None:
        return
    if not isinstance(action, dict) or set(action) != {"version", "kind", "target", "sources", "reply_to"}:
        raise ValueError("Invalid social action fields")
    if (type(action["version"]) is not int or action["version"] != 1
            or not isinstance(action["kind"], str) or action["kind"] not in KINDS):
        raise ValueError("Unsupported social action")
    if action["target"] is not None and (not isinstance(action["target"], str) or not action["target"]):
        raise ValueError("Invalid social target")
    if (not isinstance(action["sources"], list)
            or any(type(n) is not int or n < 1 for n in action["sources"])
            or len(set(action["sources"])) != len(action["sources"])):
        raise ValueError("Invalid social sources")
    if action["reply_to"] is not None and (type(action["reply_to"]) is not int or action["reply_to"] < 1):
        raise ValueError("Invalid social reply")


def make(kind, target=None, sources=(), reply_to=None):
    action = {"version": 1, "kind": kind, "target": target,
              "sources": list(dict.fromkeys(sources)), "reply_to": reply_to}
    validate(action)
    return action


def validate_public(action, events, roster):
    """Validate references against the already-public prefix, never secrets."""
    validate(action)
    if action is None:
        return
    if action["target"] is not None and action["target"] not in roster:
        raise ValueError("Unknown social target")
    sources = {e.get("event_no"): e for e in events
               if e.get("type") in {"speech", "ballots", "death", "flip", "exile"}}
    if any(n not in sources for n in action["sources"]):
        raise ValueError("Social source is not an existing public record")
    reply = action["reply_to"]
    if reply is not None and (reply not in action["sources"]
            or sources[reply].get("type") != "speech"
            or sources[reply].get("name") != action["target"]):
        raise ValueError("Reply does not reference the addressed speaker")


def annotate(choice):
    """Attach semantics to authored options, never parse a player's prose."""
    choice = deepcopy(choice)
    speech = choice["speech"]
    if speech.get("social_action") is not None:
        return choice
    prefix = choice["id"].split(":")[0]
    kind = {"wait": "listen", "admit": "admit", "refuse": "refuse", "suspect": "suspect",
            "support": "support", "ask": "question", "claim": "claim", "report": "report",
            "cite": "cite", "audit": "challenge"}.get(prefix)
    target = speech.get("question_to") or speech.get("accuse") or speech.get("defend")
    if kind is None:
        kind = "question" if speech.get("question_to") else "defer"
    sources = []
    if prefix in ("cite", "audit"):
        sources = [int(choice["id"].split(":")[1])]
    speech["social_action"] = make(kind, target, sources)
    return choice
