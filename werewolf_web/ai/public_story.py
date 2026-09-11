"""Bounded public-pressure and own-commitment aid, never an identity oracle.

Only attributed public memory is read. Audience support is a weak heuristic,
not a prediction of future votes or permission to invent evidence.
"""


def for_brain(brain):
    alive = {s.name: s.pos for s in brain.engine.alive_seats()}
    actor = brain.name
    latest = {}
    for kind, rows in (("accuse", brain.accuse_log), ("defend", brain.defend_log)):
        for day, speaker, target in rows:
            if speaker not in alive or target not in alive or speaker == target:
                continue
            key = speaker, target
            previous = latest.get(key)
            if previous is None or day > previous[0]:
                latest[key] = (day, {kind})
            elif day == previous[0]:
                previous[1].add(kind)
    # Sheriff support is not exile intent. Only the latest exile ballot per
    # voter contributes; repeated log entries never amplify the signal.
    votes = {}
    for day, voter, target, kind in brain.vote_log:
        if kind == "exile" and voter in alive and voter != actor:
            if voter not in votes or day >= votes[voter][0]:
                votes[voter] = day, target
    rows = []
    for target, pos in alive.items():
        if target == actor:
            continue
        pressure = 0.0
        supporters, defenders = [], []
        for (speaker, name), (day, kinds) in latest.items():
            if name != target or speaker == actor or len(kinds) != 1:
                continue
            weight = 1 / (1 + max(0, brain.engine.day_count - day))
            if "accuse" in kinds:
                supporters.append(speaker)
                pressure += weight
            else:
                defenders.append(speaker)
                pressure -= weight
        ballot_pressure = sum(0.5 / (1 + max(0, brain.engine.day_count - day))
                              for day, name in votes.values() if name == target)
        own = latest.get((actor, target))
        stance = sorted(own[1]) if own else []
        # The legacy logs only date statements by day. Do not invent ordering
        # between statements on the same day, or call new accusations facts.
        reconsideration = []
        if stance == ["defend"]:
            reconsideration = [{"day": day, "speaker": speaker, "target": target,
                                "kind": "accuse"}
                               for (speaker, name), (day, kinds) in latest.items()
                               if name == target and speaker != actor
                               and kinds == {"accuse"} and day > own[0]]
            reconsideration.sort(key=lambda r: (r["day"], r["speaker"]))
        # Maintaining a position is not evidence that the position is true.
        cost = 0.5 if "defend" in stance else 0.0
        score = (pressure + ballot_pressure) / max(1, len(alive) - 1) - cost
        rows.append({"target": pos, "name": target,
                     "accusers": sorted(supporters), "defenders": sorted(defenders),
                     "own_stance": stance, "reversal_cost": cost,
                     "own_stance_day": own[0] if own else None,
                     "new_attributed_accusations": reconsideration,
                     "pressure_score": round(score, 6)})
    return {"method": "public story v2", "calibrated": False,
            "discussion_options": ["support", "ask", "suspect", "wait"],
            "own_claims": list(dict.fromkeys(role for who, role in brain.claim_order if who == actor)),
            "targets": sorted(rows, key=lambda r: r["target"]),
            "limitations": "Public opinions only, not verified roles or future votes. "
                "A reversal can be justified by new evidence; explain it rather than inventing history."}
