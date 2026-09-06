"""Provider JSON Schema for v3 table outputs, not a semantic correctness oracle."""
from .shadow_debate import PLAYERS, ROLE_WORDS


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def table_schema(task):
    if task not in ("initial", "revision"):
        return None
    def rows(private):
        common = {"player": {"type": "string", "enum": list(PLAYERS)},
                  "candidate_roles": {"type": "array", "items": {"type": "string", "enum": sorted(ROLE_WORDS)},
                                      "minItems": 1 if private else 0, "maxItems": 3},
                  "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                  "faction": {"type": "string", "enum": ["", "good", "wolf"]},
                  "faction_status": {"type": "string", "enum": ["unknown", "inferred", "known"] if private
                                     else ["unknown", "withheld", "inferred", "claimed"]},
                  "evidence": {"type": "array", "items": {"type": "string"}},
                  "rationale": {"type": "string"}, "alternatives": {"type": "string"}}
        variants = []
        for asserted in (False, True):
            statuses = (["inferred", "known"] if private else ["inferred", "claimed"]) if asserted else (
                        ["unknown"] if private else ["unknown", "withheld"])
            variants.append(obj({**common, "status": {"type": "string", "enum": statuses},
                "roles": {"type": "array", "items": {"type": "string", "enum": sorted(ROLE_WORDS)},
                          "minItems": 1 if asserted else 0, "maxItems": 1 if asserted else 0}}))
        return {"type": "array", "minItems": 7, "maxItems": 7, "items": {"anyOf": variants}}
    fields = {"private": rows(True), "public": rows(False), "reason": {"type": "string"}}
    if task == "revision":
        fields["public_reason"] = {"type": "string"}
    return obj(fields)


def output_schema(request):
    task = request.get("task")
    if task in ("initial", "revision"):
        return table_schema(task)
    text = {"type": "string"}
    if task == "challenge":
        return obj({"target": {"type": ["string", "null"], "enum": [None, *(
                    p for p in request.get("active_players", PLAYERS) if p != request["actor"])]},
                    "row_player": {"type": ["string", "null"], "enum": [None, *PLAYERS]},
                    "evidence": {"type": "array", "items": text}, "text": text})
    if task == "response":
        return obj({"text": text})
    if task == "vote":
        return obj({"target": {"type": "string", "enum": [p for p in request.get("active_players", PLAYERS) if p != request["actor"]]},
                    "reason": text})
    if task in ("night_kill", "night_check"):
        return obj({"target": {"type": "string", "enum": request["candidates"]}, "reason": text})
    context = request["input"]
    return obj({**{key: {"type": "string", "enum": [context[key]]}
                  for key in ("request_id", "observer", "target")},
                "verdict": {"type": "string", "enum": request["response_fields"]["verdict"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": text, "citations": {"type": "array", "items": obj({"event_id": text, "quote": text})}})
