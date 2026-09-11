"""Offline dialogue choices using lawful memory; models keep their own policy.

No hidden world reads: only the caller's public-story summary, character style,
public board roles and its own previously fabricated check commitments.
"""


def new_check(brain, story, pool, previous):
    """Never contradict a previous fabricated report about the same target."""
    if not pool:
        return None
    by_target = {row["target"]: row for row in story["targets"]}
    old = {}
    for check in previous.values():
        old.setdefault(check["target"], set()).add(check["result"])
    # Prefer an unchecked target. Legacy contradictory records are retained,
    # but never arbitrarily select one of their competing results to repeat.
    eligible = [s for s in pool if s.pos not in old]
    if not eligible:
        eligible = [s for s in pool if len(old.get(s.pos, set())) == 1]
    if not eligible:
        return None
    best = max(by_target[s.pos]["pressure_score"] for s in eligible)
    target = brain.rng.choice([s for s in eligible if by_target[s.pos]["pressure_score"] == best])
    row = by_target[target.pos]
    if target.pos in old:
        result = next(iter(old[target.pos]))
    else:
        # No public pressure before anyone speaks: a fabricated good result
        # can build an alliance, rather than mechanically issuing a black check.
        result = "wolf" if row["accusers"] and row["pressure_score"] > 0 else "good"
    return {"night": brain.engine.night_count, "target": target.pos,
            "name": target.name, "result": result}


def public_move(brain, story):
    """Return a legal menu ID, or let the ordinary target policy continue."""
    if not story["own_claims"] and brain.wolf_strategy != "bluff":
        # A claimed role is a bluff, never access to its skill or private data.
        role = "hunter" if brain.style.aggression > .65 and "hunter" in brain.engine.board["roles"] else "civilian"
        if role in brain.engine.board["roles"]:
            return f"claim:{role}"
    support = [r for r in story["targets"]
               if r["defenders"] and not r["accusers"] and "accuse" not in r["own_stance"]
               and not any(check["target"] == r["target"] and check["result"] == "wolf"
                           for check in getattr(brain, "_bluff_checks", {}).values())]
    if support and brain.style.loyalty >= .5:
        target = max(support, key=lambda r: (len(r["defenders"]), -r["target"]))
        return f"support:{target['target']}"
    return None


def reversal_prefix(story, target, locale):
    row = next((r for r in story["targets"] if r["target"] == target), None)
    if not row or row["own_stance"] != ["defend"]:
        return ""
    sources = row["new_attributed_accusations"]
    if not sources:
        # Avoid an unexplained reversal in the scripted mode. The caller asks
        # a question instead; models may choose another explanation themselves.
        return None
    evidence = sources[-1]
    if locale == "en":
        return (f"I supported #{target} on day {row['own_stance_day']}. "
                f"On day {evidence['day']}, {evidence['speaker']} accused them. "
                "I am reconsidering; that accusation is not a verified fact. ")
    return (f"我在第{row['own_stance_day']}天保过{target}号。"
            f"第{evidence['day']}天，{evidence['speaker']}提出了对其的怀疑。"
            "我现在重新考虑，但这条指控不是已证实的事实。")
