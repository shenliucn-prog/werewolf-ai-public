"""Independent, seeded names and preset personalities; no role information."""
import random
import unicodedata

from .i18n import cast


PLAYER_ID = "acheng"
CAST_IDS = tuple(p["id"] for p in cast("en"))
PERSONA_IDS = tuple(p for p in CAST_IDS if p != PLAYER_ID)


def validate_names(names):
    if names is None:
        return {}
    if type(names) is not dict or not set(names) <= set(CAST_IDS):
        raise ValueError("Names must use valid player IDs.")
    result = {}
    for key, value in names.items():
        if not isinstance(value, str):
            raise ValueError("Names must be text.")
        value = unicodedata.normalize("NFKC", value).strip()
        if not 1 <= len(value) <= 24 or not any(c.isalpha() for c in value):
            raise ValueError("Names need 1–24 characters, including a letter.")
        if not all(unicodedata.category(c)[0] in "LMN" or c in " -'’·" for c in value):
            raise ValueError("Names may contain letters, numbers, spaces, hyphens and apostrophes.")
        if value.casefold() in {"host", "system", "主持人", "系统"}:
            raise ValueError("That name is reserved for the host/system.")
        result[key] = value
    if len({v.casefold() for v in result.values()}) != len(result):
        raise ValueError("Each player needs a unique name.")
    return result


def random_names(locale, seed=None, overrides=None):
    overrides = validate_names(overrides)
    pool = [p["name"] for p in cast(locale)]
    rng = random.Random(f"{seed}:names") if seed is not None else random.Random()
    rng.shuffle(pool)
    used = {v.casefold() for v in overrides.values()}
    available = iter(n for n in pool if n.casefold() not in used)
    return {key: overrides[key] if key in overrides else next(available) for key in CAST_IDS}


def random_personas(seed=None):
    presets = list(PERSONA_IDS)
    rng = random.Random(f"{seed}:personas") if seed is not None else random.Random()
    rng.shuffle(presets)
    return {PLAYER_ID: PLAYER_ID, **dict(zip(PERSONA_IDS, presets))}


def assign_personas(seed=None, choices=None):
    """Each NPC chooses random or a fixed trusted preset, independently of roles."""
    if choices is None:
        choices = {}
    if type(choices) is not dict or not set(choices) <= set(PERSONA_IDS):
        raise ValueError("Personality choices must use NPC IDs; human behavior is not scripted.")
    if any(not isinstance(v, str) or v not in (*PERSONA_IDS, "random") for v in choices.values()):
        raise ValueError("Choose random or a listed personality preset.")
    fixed = {p: v for p, v in choices.items() if v != "random"}
    if not fixed:
        return random_personas(seed)
    rng = random.Random(f"{seed}:personas") if seed is not None else random.Random()
    available = [p for p in PERSONA_IDS if p not in fixed.values()]
    rng.shuffle(available)
    result = {PLAYER_ID: PLAYER_ID, **fixed}
    for p in PERSONA_IDS:
        if p not in result:
            result[p] = available.pop()
    return result


def persona_options(locale):
    from .ai.npc import parse_persona, PERSONA_DIR
    from .i18n import persona as localized_persona
    import os
    result = []
    for p in PERSONA_IDS:
        persona = parse_persona(os.path.join(PERSONA_DIR, f"player-{p}.md"))
        persona = localized_persona(locale, p, p) or persona
        result.append({"id": p, "label": persona.get("traits") or p})
    return result
