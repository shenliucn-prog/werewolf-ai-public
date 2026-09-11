"""Bounded faction-assignment inference, not calibrated truth or a role solver.

Inspired by AIWolf's whole-assignment reasoning; no external code is copied.
The solver accepts detached observations only and never consumes a game engine.
"""
from itertools import combinations
import math


def infer_factions(names, wolf_count, known, weights, relations=()):
    names = tuple(sorted(names))
    if len(names) > 15 or len(set(names)) != len(names):
        raise ValueError("Expected at most 15 unique players")
    if type(wolf_count) is not int or not 0 <= wolf_count <= len(names):
        raise ValueError("Invalid public wolf count")
    if any(n not in names or type(v) is not bool for n, v in known.items()):
        raise ValueError("Invalid known faction")
    wolves = {n for n, value in known.items() if value}
    unknown = [n for n in names if n not in known]
    remaining = wolf_count - len(wolves)
    if not 0 <= remaining <= len(unknown):
        raise ValueError("Contradictory faction evidence")
    probabilities = {}
    # Opinions are soft pairwise factors, never private checks. Deduplicate and
    # normalize by speaker so repetition/verbosity cannot manufacture evidence.
    links = set()
    for row in relations:
        speaker, target, kind = row['speaker'], row['target'], row['kind']
        if speaker not in names or target not in names or speaker == target or kind not in ('accuse', 'defend'):
            raise ValueError('Invalid attributed relation')
        links.add((speaker, target, kind))
    links = sorted(links)
    counts = {speaker: sum(s == speaker for s, _, _ in links) for speaker, _, _ in links}
    for name in unknown:
        p = weights.get(name, .5)
        if not isinstance(p, (int, float)) or not math.isfinite(p):
            raise ValueError("Non-finite evidence weight")
        probabilities[name] = min(.98, max(.02, p))
    worlds = []
    for subset in combinations(unknown, remaining):
        pack = wolves | set(subset)
        score = sum(math.log(p if n in pack else 1 - p) for n, p in probabilities.items())
        for speaker, target, kind in links:
            same_side = (speaker in pack) == (target in pack)
            compatible = same_side if kind == 'defend' else not same_side
            # Fixed weak heuristic: true accusation AND deceptive accusation
            # of a good target remain alternatives. Mistakes/bussing remain
            # possible; no world is eliminated by somebody's speech.
            score += (.35 if compatible else -.35) / counts[speaker]
        worlds.append((pack, score))
    peak = max(score for _, score in worlds)
    mass = [math.exp(score - peak) for _, score in worlds]
    total = sum(mass)
    marginal = {n: sum(w for (pack, _), w in zip(worlds, mass) if n in pack) / total for n in names}
    ranked = sorted(zip(worlds, mass), key=lambda row: (-row[1], sorted(row[0][0])))
    return {"method": "fixed-roster faction combinations v2", "calibrated": False,
            "world_count": len(worlds), "wolf_count": wolf_count,
            "wolf_weights": marginal,
            "top_hypotheses": [{"wolves": sorted(pack), "weight": w / total}
                               for (pack, _), w in ranked[:3]],
            "relation_count": len(links),
            "relation_assumption": "Weak heuristic: accusations favor opposite factions, "
                "defenses favor the same faction. Deception, mistakes and bussing remain possible. "
                "Repeated opinions are deduplicated; influence is normalized per speaker. "
                "These are attributed opinions, not verified checks.",
            "limitations": "Heuristic faction hypotheses, not facts or full role assignments. "
                           "Top three are not exhaustive. Soft evidence is not independently calibrated."}


def for_brain(brain):
    """Trusted adapter: public roster/rules, own facts, and attributed evidence.

    No inspection of another seat's role/is_wolf; known teammates are supplied
    by the existing per-seat information policy. Recomputed after restore,
    without changing RNG, memory, engine, or the checkpoint schema.
    """
    from .strategy import InformationSet
    from ..game.models import WOLF_ROLES
    info = InformationSet.from_brain(brain)
    roles = brain.engine.board["roles"]  # public multiset, not dealt assignments
    names = [s.name for s in brain.engine.seats.values()]
    known = {brain.name: brain.role in WOLF_ROLES}
    evidence = [{"source": "own_role", "player": brain.name}]

    def establish(name, value, source):
        if name in known and known[name] != value:
            raise ValueError("Contradictory lawful evidence")
        known[name] = value
        evidence.append({"source": source, "player": name})

    for row in info.public_flips:
        establish(row["name"], row["is_wolf"], "public_flip")
    for mate in info.private.get("wolf_mates", []):
        establish(mate["name"], True, "known_teammate")
    for row in info.private.get("seer_results", []):
        if row.get("name") not in names or row.get("result") not in ("good", "wolf"):
            continue  # unfamiliar legacy evidence stays in the source, not inferred
        # Hidden wolves return human: that result cannot establish good faction.
        if row["result"] == "wolf":
            establish(row["name"], True, "own_check")
        elif "hidden_wolf" not in roles:
            establish(row["name"], False, "own_check")
    weights = {n: brain.sus_of(n) for n in names}
    # Flipped-target evidence already feeds sus_of through observe_flip; don't
    # add that same evidence again. Select the latest round for each pair.
    flipped = {row['name'] for row in info.public_flips}
    latest = {}
    for kind, rows in (('accuse', brain.accuse_log), ('defend', brain.defend_log)):
        for day, speaker, target in rows:
            if speaker not in names or target not in names or speaker in (target, brain.name) or target in flipped:
                continue
            pair = (speaker, target)
            if pair not in latest or day > latest[pair][0]:
                latest[pair] = (day, {kind})
            elif day == latest[pair][0]:
                latest[pair][1].add(kind)
    relations = [{'speaker': speaker, 'target': target, 'kind': kind}
                 for (speaker, target), (_, kinds) in sorted(latest.items())
                 for kind in sorted(kinds)]
    result = infer_factions(names, sum(r in WOLF_ROLES for r in roles), known, weights, relations)
    result["hard_evidence"] = evidence
    return result
