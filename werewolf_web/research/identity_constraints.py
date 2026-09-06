"""Lawful closure for the fixed 2-wolf/1-seer/4-villager research board only.

Accepts an actor's supplied facts, NEVER a ground-truth role map. Enumerates
feasible assignments and derives only conclusions true in every such world.
This does not validate natural-language rationales or ordinary-game variants.
"""
from itertools import combinations


def faction(role):
    return "wolf" if role == "werewolf" else "good"


def possibilities(players, own_facts):
    worlds = []
    for wolves in combinations(players, 2):
        for seer in players:
            if seer in wolves:
                continue
            world = {p: "werewolf" if p in wolves else "seer" if p == seer else "villager"
                     for p in players}
            if all((faction(world[p]) == role if role in {"good", "wolf"} else world[p] == role)
                   for p, (role, _) in own_facts.items()):
                worlds.append(world)
    if not worlds:
        raise ValueError("inconsistent owner facts")
    sources = ["E000001", *dict.fromkeys(ref for _, ref in own_facts.values())]
    return {p: {"possible_roles": sorted({w[p] for w in worlds}),
                "role": next(iter({w[p] for w in worlds})) if len({w[p] for w in worlds}) == 1 else "",
                "faction": next(iter({faction(w[p]) for w in worlds}))
                           if len({faction(w[p]) for w in worlds}) == 1 else "",
                "evidence": sources.copy()} for p in players}
