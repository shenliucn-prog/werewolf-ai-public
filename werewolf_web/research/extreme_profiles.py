"""Frozen endpoint interventions, NOT claims of controlling model intelligence."""
STYLE = ("aggression", "logic", "bluff", "loyalty", "caution", "verbosity")
COGNITION = ("evidence_processing", "recursive_reasoning", "social_reading", "deception",
             "calibration", "decisiveness", "learning_rate")
STATE = {"form": (-.85, .85), "valence": (-1., 1.), "arousal": (.10, .90),
         "confidence": (.18, .88), "stress": (.08, .82), "momentum": (-.75, .75)}


def profile(high, mixed=False):
    # Complementary mixed profiles decouple logic/caution from aggression/bluff.
    high_keys = {"logic", "caution", "evidence_processing", "recursive_reasoning",
                 "calibration", "learning_rate", "form", "confidence", "momentum"}
    bit = lambda key: (key in high_keys) == high if mixed else high
    return {"style": {**{k: .95 if bit(k) else .05 for k in STYLE},
                      "argument": "logic" if high else "gut"},
            "cognition": {**{k: .95 if bit(k) else .05 for k in COGNITION},
                          "preferred_depth": 5 if bit("recursive_reasoning") else 1,
                          "max_depth": 5 if bit("recursive_reasoning") else 1},
            "state": {k: bounds[int(bit(k))] for k, bounds in STATE.items()},
            "frozen": True,
            "excluded": {"experience": "unbounded counter; fixed at zero",
                         "argument": "categorical, logic/gut intervention, no numeric endpoints",
                         "derived_values": "not independent dimensions",
                         "learning": "no intergame carry or within-game parameter updates"}}


def validate_profile(value):
    for section, keys in (("style", STYLE), ("cognition", COGNITION)):
        if any(value[section][k] not in (.05, .95) for k in keys):
            raise ValueError("non-endpoint trait")
    if any(value["state"][k] not in bounds for k, bounds in STATE.items()):
        raise ValueError("non-endpoint state")
    if any(value["cognition"][k] not in (1, 5) for k in ("preferred_depth", "max_depth")):
        raise ValueError("non-endpoint depth")
    if value["cognition"]["preferred_depth"] > value["cognition"]["max_depth"]:
        raise ValueError("inconsistent depth")


def roster_profiles(index, players):
    mixed, swap = index // 2 == 1, index % 2 == 1
    return {p: profile((i % 2 == 0) != swap, mixed) for i, p in enumerate(players)}
