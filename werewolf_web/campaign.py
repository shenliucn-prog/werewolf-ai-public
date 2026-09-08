"""Main-line single-player campaign level table (CAMPAIGN_DESIGN.md §4).

The teaching order is *hand-curated*; this module only validates role↔board
compatibility, win-side mapping and full coverage of the playable roster — it
never derives the order from configuration.  The divine-witch boards (a witch
rule variant, not a separate role) and the model+conjecture pairing are excluded
here: they belong to the experimental challenges.
"""
from __future__ import annotations

from .game.engine import BOARD_MAP, ROLE_META
from .game.models import WOLF_ROLES

# ---- Attempt lifecycle states (CAMPAIGN_DESIGN §3.3) ---------------------
# preparing / in_progress are archive-level (owned by the campaign archive);
# paused / faulted / abandoned / ended are the session-level view exposed by
# ``GameSession.terminal_state``.
PREPARING = "preparing"
IN_PROGRESS = "in_progress"
PAUSED = "paused"
FAULTED = "faulted"
ABANDONED = "abandoned"
ENDED = "ended"

ATTEMPT_STATES = (PREPARING, IN_PROGRESS, PAUSED, FAULTED, ABANDONED, ENDED)

# Legal transitions: only ``ended`` (normal endgame) and ``abandoned`` end the
# attempt; ``faulted`` and ``paused`` keep the resume position + pending action
# and must never settle.  Terminal states have no outgoing edges.
ATTEMPT_TRANSITIONS = {
    PREPARING: {IN_PROGRESS, ABANDONED},
    IN_PROGRESS: {PAUSED, FAULTED, ABANDONED, ENDED},
    PAUSED: {IN_PROGRESS, FAULTED, ABANDONED, ENDED},
    FAULTED: {IN_PROGRESS, ABANDONED},
    ABANDONED: set(),
    ENDED: set(),
}


def validate_transitions() -> list[str]:
    """Return problems with the attempt transition table (empty = valid)."""
    problems: list[str] = []
    known = set(ATTEMPT_STATES)
    if len(known) != len(ATTEMPT_STATES):
        problems.append("duplicate state names")
    for state, targets in ATTEMPT_TRANSITIONS.items():
        if state not in known:
            problems.append(f"unknown source state {state!r}")
        for target in targets:
            if target not in known:
                problems.append(f"unknown target state {target!r} from {state!r}")
    missing = known - set(ATTEMPT_TRANSITIONS)
    if missing:
        problems.append(f"states without transition entries: {sorted(missing)}")
    for terminal in (ABANDONED, ENDED):
        if ATTEMPT_TRANSITIONS.get(terminal) != set():
            problems.append(f"terminal state {terminal!r} must have no outgoing transitions")
    # A recoverable fault must never be a direct terminal/settling edge.
    if FAULTED in ATTEMPT_TRANSITIONS.get(ENDED, ()) or FAULTED in ATTEMPT_TRANSITIONS.get(ABANDONED, ()):
        problems.append("faulted is not a terminal state")
    return problems

# One level per playable role, ordered 好人后狼、先基础后进阶.  ``board`` is the
# fixed board for that level; ``goal_*`` is the single-sentence learning goal.
LEVELS = [
    {"role": "civilian",        "board": "classic",            "goal_cn": "从发言与票型判断身份",         "goal_en": "Read identities from speech and ballots."},
    {"role": "seer",            "board": "classic",            "goal_cn": "用查验建立可信度",             "goal_en": "Build credibility from your checks."},
    {"role": "witch",           "board": "classic",            "goal_cn": "权衡技能与身份暴露",           "goal_en": "Balance potions against exposure."},
    {"role": "hunter",          "board": "classic",            "goal_cn": "开枪时机与自证",               "goal_en": "Time your gunshot to self-confirm."},
    {"role": "guard",           "board": "classic",            "goal_cn": "守人博弈",                     "goal_en": "Win the protection mind-game."},
    {"role": "gravekeeper",     "board": "stone_ghost",        "goal_cn": "验尸信息利用",                 "goal_en": "Exploit burial-check information."},
    {"role": "knight",          "board": "white_wolf_knight",  "goal_cn": "决斗时机",                     "goal_en": "Time your duel."},
    {"role": "crow",            "board": "hidden_wolf_crow",   "goal_cn": "诽谤与票型操纵",               "goal_en": "Sway the ballot with slander."},
    {"role": "werewolf",        "board": "classic",            "goal_cn": "协同、伪装、引导投票",         "goal_en": "Coordinate, dissemble, steer votes."},
    {"role": "wolf_king",       "board": "wolf_king",          "goal_cn": "出局开枪",                     "goal_en": "Trade your death for a kill."},
    {"role": "white_wolf_king", "board": "white_wolf_knight",  "goal_cn": "白天技能",                     "goal_en": "Use the daytime self-burst."},
    {"role": "wolf_beauty",     "board": "wolf_beauty_knight", "goal_cn": "魅惑博弈",                     "goal_en": "Play the charm game."},
    {"role": "hidden_wolf",     "board": "hidden_wolf_crow",   "goal_cn": "深水潜伏",                     "goal_en": "Lurk deep as a hidden wolf."},
    {"role": "stone_ghost",     "board": "stone_ghost",        "goal_cn": "查验 + 隔离狼队",              "goal_en": "Probe roles while isolated from the pack."},
    {"role": "evil_knight",     "board": "evil_knight",        "goal_cn": "反制技能",                     "goal_en": "Turn god skills against them."},
    {"role": "bomber",          "board": "bomber",             "goal_cn": "放逐威慑",                     "goal_en": "Deter exile with your explosion."},
]


def player_side(role: str) -> str:
    """Win side per CAMPAIGN_DESIGN §3.1: wolf roles -> "wolf", else -> "god".

    This must match the engine's faction-level ``winner`` ("god"/"wolf"), so a
    good-side player (including ``civilian``) wins when ``winner == "god"``.
    """
    return "wolf" if role in WOLF_ROLES else "god"


def played_roles() -> set[str]:
    """Every distinct role that appears on at least one board (the playable
    roster).  Excludes the unused ``grave`` ROLE_META alias and the stale
    ``stone_ghost_grave`` entry in ``GOD_ROLES``, neither of which is on a board.
    """
    roles: set[str] = set()
    for board in BOARD_MAP.values():
        roles.update(board["roles"])
    return roles


def validate_levels() -> list[str]:
    """Return problems with the level table (empty list = valid)."""
    problems: list[str] = []
    seen_roles: set[str] = set()
    seen_boards: set[str] = set()
    for i, level in enumerate(LEVELS, start=1):
        role = level["role"]
        board_id = level["board"]
        board = BOARD_MAP.get(board_id)
        if board is None:
            problems.append(f"level {i}: unknown board {board_id!r}")
            continue
        if role not in board["roles"]:
            problems.append(f"level {i}: {role!r} not on board {board_id!r}")
        if role not in ROLE_META:
            problems.append(f"level {i}: role {role!r} has no ROLE_META entry")
        if role in seen_roles:
            problems.append(f"level {i}: duplicate role {role!r}")
        seen_roles.add(role)
        seen_boards.add(board_id)
        if not level.get("goal_cn") or not level.get("goal_en"):
            problems.append(f"level {i}: missing learning goal")
        # Win-side cross-check against the authoritative ROLE_META faction.
        meta_faction = ROLE_META.get(role, {}).get("faction")
        if meta_faction is not None:
            expected = "wolf" if meta_faction == "wolf" else "god"
            if player_side(role) != expected:
                problems.append(
                    f"level {i}: win side for {role!r} disagrees with faction {meta_faction!r}")

    missing = played_roles() - seen_roles
    if missing:
        problems.append(f"playable roles not covered: {sorted(missing)}")
    extra = seen_roles - played_roles()
    if extra:
        problems.append(f"levels reference non-playable roles: {sorted(extra)}")
    for board_id in seen_boards:
        if board_id in ("divine_witch", "divine_witch_dual"):
            problems.append(f"experimental board {board_id!r} in the main line")
    return problems
