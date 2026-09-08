"""Role teaching and post-loss short review (§7): model-generated, cached, retryable.

The model writes the *presentation* — teaching and critique — while the rules,
skill legality and win/loss stay in deterministic code, which also supplies the
teaching material (so the model never has to guess a rule).  Each real request
reserves one call-budget unit first; a failed generation is a ``ModelTurnError``
("暂不可用，请重试"), never a canned text masquerading as model output.  A cache
hit costs no call and is invalidated when the deterministic material changes.
"""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy

from . import config
from .campaign import LEVELS, player_side
from .ai.decision_runtime import ModelTurnError
from .game.engine import BOARD_MAP, ROLE_META
from .i18n import t, witch_rule_text

TEACHING_PATH = os.path.join(config.DATA_DIR, "teaching.json")

_TEXT_SCHEMA = {"type": "object",
                "properties": {"text": {"type": "string", "maxLength": 1200}},
                "required": ["text"], "additionalProperties": False}


def _level(role: str):
    for level in LEVELS:
        if level["role"] == role:
            return level
    return None


def _goal(level, locale: str) -> str:
    return level["goal_cn"] if locale != "en" else level["goal_en"]


def teaching_material(role: str, locale: str) -> dict:
    """Deterministic teaching material for one level: the role/board rule text the
    model may not guess.  Board-specific variants (witch potions, guard limits)
    come from code, not the model's memory."""
    level = _level(role)
    if level is None:
        raise ValueError(f"campaign: {role!r} is not a campaign level role")
    board = BOARD_MAP[level["board"]]
    meta = ROLE_META.get(role, {})
    material = {
        "role": role,
        "role_rules": meta.get("desc", ""),
        "board": level["board"],
        "board_name": board.get("name", ""),
        "board_rules": board.get("desc", ""),
        "goal": _goal(level, locale),
        "win_side": player_side(role),
    }
    if board.get("witch_rules"):
        material["witch_rules"] = witch_rule_text(locale, board)
    material["win_conditions"] = {
        "god": t(locale, "win_god"),
        "wolf": t(locale, "win_wolf"),
    }
    return material


def _material_digest(role: str, locale: str) -> str:
    blob = json.dumps(teaching_material(role, locale), sort_keys=True,
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _reserve(planner) -> None:
    reserve = getattr(planner, "reserve", None)
    if reserve is None:
        raise ModelTurnError("Model teaching/review requires a budgeted runtime.")
    reserve()


def _persist(persist) -> None:
    if persist is not None:
        persist()


def _complete(planner, request) -> str:
    value = planner.complete(request, deepcopy(_TEXT_SCHEMA))
    if not isinstance(value, dict) or not isinstance(value.get("text"), str) or not value["text"].strip():
        raise ModelTurnError("Model teaching/review failed; no offline substitution.")
    return value["text"].strip()


def role_teaching(planner, role: str, locale: str, persist=None) -> str:
    """Model-generated teaching for one campaign level (rules supplied, not guessed)."""
    request = {
        "task": "role_teaching", "language": locale,
        "rules": teaching_material(role, locale),
        "instructions": (
            "Explain this role's skill, its timing, and its win condition in two "
            "or three sentences for a first-time player, using ONLY the supplied "
            "rules and goal."
            if locale == "en" else
            "用两三句话向首次玩家讲清该角色的技能、使用时机与阵营胜利条件；只使用给定规则与学习目标。"
        ),
    }
    _reserve(planner)                     # a real request costs one call
    _persist(persist)                     # persist the reservation before the request
    return _complete(planner, request)


def short_review(planner, decision_log, public_facts, role: str, locale: str,
                 persist=None) -> str:
    """Model-generated short review: one or two key decisions, attributed, after a loss."""
    request = {
        "task": "short_review", "language": locale,
        "role": role,
        "own_decisions": decision_log[-12:],
        "public_facts": public_facts[-20:],
        "instructions": (
            "Point out ONE or TWO concrete decisions by this player that most "
            "changed the game, as attributed observations ('your day-2 vote went "
            "against the revealed flip'), never invented events, never a full "
            "coaching lecture."
            if locale == "en" else
            "指出该玩家这一两个最影响局势的决策，作为归属化观察（例如『你第2天的票与翻牌相矛盾』），"
            "不编造事件、不做长篇说教。"
        ),
    }
    _reserve(planner)
    _persist(persist)
    return _complete(planner, request)


def load_teaching_cache() -> dict:
    if not os.path.exists(TEACHING_PATH):
        return {}
    try:
        with open(TEACHING_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_teaching_cache(cache: dict) -> None:
    directory = os.path.dirname(os.path.abspath(TEACHING_PATH))
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    tmp = TEACHING_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, TEACHING_PATH)


def _cache_key(role: str, locale: str, model: str) -> str:
    return hashlib.sha256(
        f"{role}:{locale}:{model}:{_material_digest(role, locale)}".encode("utf-8")
    ).hexdigest()[:16]


def cached_role_teaching(planner, role: str, locale: str, model: str, persist=None) -> str:
    """Teaching with a per-role/locale/model/material cache.  A valid cache hit
    costs no call; a miss generates once (reserving one call)."""
    cache = load_teaching_cache()
    key = _cache_key(role, locale, model)
    hit = cache.get(key)
    if isinstance(hit, str) and hit.strip():
        return hit
    text = role_teaching(planner, role, locale, persist=persist)
    cache[key] = text
    save_teaching_cache(cache)
    return text
