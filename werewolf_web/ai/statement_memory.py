"""Read-only attributed statement projection of the public ledger.

The archive is authoritative; no private beliefs or inferred truth enter this
projection. A changed claim is another statement, not proof of deception.
Legacy observation logs supply only unlinked fallback records.
"""


def statement_summaries(entries, brain, claim_limit=16, relation_limit=16):
    groups = []
    specs = (
        ("role_claims", "claim", "claimed_role", brain.claim_order, claim_limit),
        ("accusations", "accuse", "accused", brain.accuse_log, relation_limit),
        ("defences", "defend", "defended", brain.defend_log, relation_limit),
    )
    for kind, field, label, legacy, limit in specs:
        linked, identities = [], set()
        for row in entries:
            event = row["event"]
            value, who = event.get(field), event.get("name")
            if event.get("type") != "speech" or not value or not who:
                continue
            number = event.get("event_no")
            exact = type(number) is int and number > 0
            item = {"who": who, label: value, "day": row.get("day"),
                    "night": row.get("night"), "phase": row.get("phase"),
                    "event_no": number if exact else None,
                    "reference_status": "recorded_statement" if exact else "unknown"}
            linked.append(item)
            identities.add((who, value) if field == "claim" else
                           (row.get("day"), who, value))
        fallback = []
        for record in legacy:
            if tuple(record) in identities:
                continue
            day, who, value = (None, *record) if field == "claim" else record
            fallback.append({"who": who, label: value, "day": day,
                             "night": None, "phase": None, "event_no": None,
                             "reference_status": "unknown"})
        # Unknown legacy sources precede the recorded tail; never invent an
        # exact source by text matching or by selecting a later statement.
        items = (fallback + linked)[-limit:]
        if items:
            groups.append({"kind": kind, "items": items})
    return groups
