"""狼人杀 12人局 游戏引擎（纯逻辑，不含LLM）。

负责：角色分配、昼夜状态机、夜间技能结算、白天发言/投票、胜负判定。
引擎只产出结构化事件，叙事与NPC决策由 ai/ 层包裹。
"""
from __future__ import annotations

import json
import os
import random
from typing import Optional

from .models import Seat, GameEvent, WOLF_ROLES
from ..i18n import cast, normalize_locale, role_name, role_desc, t, list_sep, board_display, board_role_name, witch_rule_text
from ..casting import random_names, assign_personas

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARDS_PATH = os.path.join(BASE_DIR, "data", "boards.json")

PLAYER_ID = "acheng"

with open(BOARDS_PATH, "r", encoding="utf-8") as f:
    _BOARDS = json.load(f)
BOARD_MAP = {b["id"]: b for b in _BOARDS["boards"]}
ROLE_META = _BOARDS["roles"]


def role_info(key: str) -> dict:
    return ROLE_META.get(key, {"cn": key, "faction": "civilian", "emoji": "👤", "desc": ""})


class GameEngine:
    def __init__(self, board_id: str = "classic", seed: Optional[int] = None,
                 locale: str = "zh-CN", names: dict | None = None,
                 personalities: dict | None = None, player_role: str | None = None):
        self.board_id = board_id
        self.board = BOARD_MAP[board_id]
        self.witch_unlimited = self.board.get("witch_rules", {}).get("unlimited", False)
        self.witch_dual = self.board.get("witch_rules", {}).get("dual", False)
        if player_role is not None and (not isinstance(player_role, str) or
                player_role not in ("random", *self.board["roles"])):
            raise ValueError("Choose random or a role available on this board.")
        self.player_role = None if player_role == "random" else player_role
        self.locale = normalize_locale(locale)
        self.cast_names = random_names(self.locale, seed, names)
        self.cast_personas = assign_personas(seed, personalities)
        self.rng = random.Random(seed)
        self.seats: dict[int, Seat] = {}
        self.history: list[GameEvent] = []
        self.phase = "prep"
        self.day_count = 0
        self.night_count = 0
        self.sheriff: Optional[int] = None
        # 技能状态
        self.witch_antidote = True
        self.witch_poison = True
        self.guard_last: Optional[int] = None
        self.seer_results: list[dict] = []
        self.sg_results: list[dict] = []               # 石像鬼查验结果
        self.grave_results: list[dict] = []
        self.knight_used = False
        self.crow_used_day: Optional[int] = None
        self.charmed: Optional[str] = None          # 被狼美人魅惑的玩家名
        self.last_exiled: Optional[str] = None      # 上一轮放逐者（守墓人用）
        self.last_exiled_wolf: Optional[bool] = None
        self.crow_target: Optional[int] = None      # 当日诽谤目标
        self.evil_knight_reflection_used = False    # 恶灵骑士的一次反制是否已用
        self.winner: Optional[str] = None           # god / wolf
        self.end_reason = ""

    # ---------- 初始化 ----------
    def setup(self):
        identities = cast(self.locale)
        self.rng.shuffle(identities)
        roles = list(self.board["roles"])
        self.rng.shuffle(roles)
        if self.player_role is not None:
            # Keep the seat shuffle and role multiset; deal the remaining roles
            # uniformly to NPCs. The default random path remains unchanged.
            roles.remove(self.player_role)
            self.rng.shuffle(roles)
            roles.insert(next(i for i, identity in enumerate(identities)
                              if identity["id"] == PLAYER_ID), self.player_role)
        for i in range(12):
            pos = i + 1
            identity = identities[i]
            name = self.cast_names[identity["id"]]
            role = roles[i]
            info = role_info(role)
            is_player = (identity["id"] == PLAYER_ID)
            seat = Seat(
                pos=pos, player_id=identity["id"], name=name, role=role,
                role_cn=board_role_name(self.locale, self.board, role, info["cn"]),
                faction=info["faction"], emoji=info["emoji"],
                is_player=is_player, is_wolf=(role in WOLF_ROLES),
                persona_id=self.cast_personas[identity["id"]],
            )
            self.seats[pos] = seat
        self.phase = "night"
        # The first call to start_night() owns the transition into night one.
        self.night_count = 0
        return self.seats

    # ---------- 查询辅助 ----------
    def alive_seats(self) -> list[Seat]:
        return [s for s in self.seats.values() if s.alive]

    def seat_by_name(self, name: str) -> Optional[Seat]:
        for s in self.seats.values():
            if s.name == name:
                return s
        return None

    def wolves(self) -> list[Seat]:
        """Return the communicating wolf pack, excluding isolated roles."""
        return [
            seat for seat in self.seats.values()
            if seat.is_wolf and seat.role != "stone_ghost" and seat.alive
        ]

    def player_seat(self) -> Seat:
        return next(s for s in self.seats.values() if s.is_player)

    def stone_ghost_can_kill(self) -> bool:
        return not self.wolves() and any(
            s.alive and s.role == "stone_ghost" for s in self.seats.values())

    def seat_at(self, pos: int) -> Seat:
        return self.seats[pos]

    def record_speech(self, pos: int, text: str, **data) -> GameEvent:
        """Record a public speech once so agents and coaches share one ledger."""
        seat = self.seat_at(pos)
        event = GameEvent(
            type="speech",
            seat=pos,
            text=text,
            data={"name": seat.name, **data},
        )
        self.history.append(event)
        return event

    # ---------- 夜晚 ----------
    def start_night(self):
        self.phase = "night"
        self.night_count += 1
        self.history.append(GameEvent(type="night_start", text=t(self.locale, "night_start", n=self.night_count)))
        # 返回本夜需要行动的角色请求
        requests = []
        if any(s.role == "seer" and s.alive for s in self.seats.values()):
            requests.append(("seer", self._seat_of_role("seer").pos))
        if any(s.is_wolf and s.alive and s.role != "stone_ghost" for s in self.seats.values()):
            requests.append(("wolves", None))
        elif self.stone_ghost_can_kill():
            requests.append(("stone_ghost_kill", self._seat_of_role("stone_ghost").pos))
        if self.witch_antidote or self.witch_poison:
            if any(s.role == "witch" and s.alive for s in self.seats.values()):
                requests.append(("witch", self._seat_of_role("witch").pos))
        if any(s.role == "guard" and s.alive for s in self.seats.values()):
            requests.append(("guard", self._seat_of_role("guard").pos))
        if any(s.role == "wolf_beauty" and s.alive for s in self.seats.values()):
            requests.append(("wolf_beauty", self._seat_of_role("wolf_beauty").pos))
        if any(s.role == "stone_ghost" and s.alive for s in self.seats.values()):
            requests.append(("stone_ghost", self._seat_of_role("stone_ghost").pos))
        if self.last_exiled is not None and any(
                s.role == "gravekeeper" and s.alive for s in self.seats.values()):
            exiled = self.seat_by_name(self.last_exiled)
            self.grave_results.append({
                "night": self.night_count, "target": exiled.pos,
                "name": exiled.name,
                "result": "wolf" if self.last_exiled_wolf else "good",
            })
        return requests

    def _seat_of_role(self, role: str) -> Seat:
        return next(s for s in self.seats.values() if s.role == role)

    def resolve_night(self, actions: dict) -> list[GameEvent]:
        """actions: {actor: {target/...}}。返回死亡等事件。"""
        self._validate_night(actions)
        events: list[GameEvent] = []
        knife = actions.get("wolves", actions.get("stone_ghost_kill", {})).get("target")
        save = actions.get("witch", {}).get("save")
        poison = actions.get("witch", {}).get("poison")
        guard = actions.get("guard", {}).get("target")
        beauty = actions.get("wolf_beauty", {}).get("target")
        sg = actions.get("stone_ghost", {}).get("target")

        # 预言家验人
        seer_act = actions.get("seer")
        if seer_act and seer_act.get("target"):
            tgt = self.seat_at(seer_act["target"])
            res = "good" if tgt.role not in WOLF_ROLES else "wolf"
            # 隐狼：显示好人
            if tgt.role == "hidden_wolf":
                res = "good"
            # 恶灵骑士反弹：预言家死亡，恶灵骑士不翻牌，且不获得验人结果。
            if tgt.role == "evil_knight" and not self.evil_knight_reflection_used:
                self.evil_knight_reflection_used = True
                events.append(GameEvent(type="system",
                                        text=t(self.locale, "seer_reflect")))
                self._kill(self._seat_of_role("seer").pos, "reflect", events)
            else:
                self.seer_results.append({
                    "night": self.night_count, "target": tgt.pos,
                    "name": tgt.name, "result": res,
                })
            # 验人结果不广播——仅通过 run.py 私聊发给预言家本人

        # 石像鬼查验（具体身份）——不广播，仅私聊给石像鬼
        if sg:
            tgt = self.seat_at(sg)
            self.sg_results.append({
                "night": self.night_count, "target": tgt.pos,
                "name": tgt.name, "role_cn": tgt.role_cn
            })

        # 狼美人魅惑
        self.charmed = self.seat_at(beauty).name if beauty is not None else None

        # 结算死亡
        pending: dict[int, str] = {}
        # 刀：守+救同时=奶穿；守或救单独=活
        if knife is not None:
            if guard == knife and save == knife:
                pending[knife] = "knife"  # 奶穿
            elif guard == knife:
                pass  # 被守
            elif save == knife:
                pass  # 被救
            else:
                pending[knife] = "knife"
        if poison is not None:
            poison_target = self.seat_at(poison)
            if poison_target.role == "evil_knight" and not self.evil_knight_reflection_used:
                self.evil_knight_reflection_used = True
                witch = self._seat_of_role("witch")
                events.append(GameEvent(type="system",
                                        text=t(self.locale, "witch_reflect")))
                pending[witch.pos] = "reflect"
            else:
                pending[poison] = "poison"
        # 恶灵骑士反弹已在验人处处理

        # 区分刀杀与毒杀：被毒死的猎人不能开枪，被刀死的可以
        for p, cause in pending.items():
            self._kill(p, cause, events)

        # 记录女巫用药
        if save is not None and not self.witch_unlimited:
            self.witch_antidote = False
        if poison is not None and not self.witch_unlimited:
            self.witch_poison = False
        self.guard_last = guard

        self.phase = "dawn"
        self.history.extend(events)
        return events

    def _validate_night(self, actions: dict):
        """Reject an entire invalid action batch before changing any state."""
        fields = {"wolves": {"target"}, "stone_ghost_kill": {"target"},
                  "seer": {"target"}, "witch": {"save", "poison"},
                  "guard": {"target"}, "wolf_beauty": {"target"},
                  "stone_ghost": {"target"}}
        for actor, action in actions.items():
            if actor not in fields or not isinstance(action, dict) or set(action) - fields[actor]:
                raise ValueError("Invalid night action")
            if actor == "wolves":
                if not self.wolves():
                    raise ValueError("The pack cannot act")
                owner = None
            else:
                role = "stone_ghost" if actor == "stone_ghost_kill" else actor
                owner = next((s for s in self.alive_seats() if s.role == role), None)
                if owner is None or (actor == "stone_ghost_kill" and not self.stone_ghost_can_kill()):
                    raise ValueError("Role cannot act")
            for field, target in action.items():
                if target is None:
                    continue
                if type(target) is not int or target not in self.seats or not self.seat_at(target).alive:
                    raise ValueError("Invalid night target")
                if owner and target == owner.pos and actor not in ("guard", "witch"):
                    raise ValueError("Self target not allowed")
                if actor == "guard" and target == self.guard_last:
                    raise ValueError("Consecutive guarding not allowed")
                if actor == "witch" and field == "poison" and (not self.witch_poison or target == owner.pos):
                    raise ValueError("Poison unavailable or invalid")
            if actor == "witch":
                save, poison = action.get("save"), action.get("poison")
                knife = actions.get("wolves", actions.get("stone_ghost_kill", {})).get("target")
                if save is not None and (not self.witch_antidote or save != knife or
                                        (save == owner.pos and self.night_count != 1)):
                    raise ValueError("Antidote unavailable or invalid")
                if save is not None and poison is not None and not self.witch_dual:
                    raise ValueError("Only one potion per night")

    # ---------- 死亡处理（含连锁） ----------
    def _kill(self, pos: int, cause: str, events: list[GameEvent], _chain=None):
        if _chain is None:
            _chain = set()
        seat = self.seat_at(pos)
        if not seat.alive or pos in _chain:
            return
        _chain.add(pos)
        seat.alive = False
        seat.death_cause = cause
        role_cn = seat.role_cn
        events.append(GameEvent(type="death", seat=pos,
                                text=t(self.locale, "death", pos=pos, name=seat.name),
                                data={"name": seat.name, "role": seat.role, "cause": cause}))
        # 翻牌公告
        events.append(GameEvent(type="flip", seat=pos,
                                text=t(self.locale, "flip", pos=pos, name=seat.name, role=role_cn),
                                data={"name": seat.name, "role": seat.role, "role_cn": role_cn}))
        # 连锁触发
        if seat.role == "hunter" and cause not in ("poison", "knight_duel"):
            pass  # 猎人开枪由外部（runner）收集目标后调用 trigger_hunter
        if seat.role == "wolf_king" and cause in ("exile", "hunter_gun"):
            pass  # 外部触发
        if seat.role == "wolf_beauty" and self.charmed:
            charm_seat = self.seat_by_name(self.charmed)
            if charm_seat and charm_seat.alive:
                self._kill(charm_seat.pos, "charm", events, _chain)
        if seat.role == "bomber" and cause == "exile":
            victims = self.rng.sample([s.pos for s in self.alive_seats()],
                                      min(1, len(self.alive_seats())))
            for v in victims:
                self._kill(v, "bomb", events, _chain)

    def trigger_hunter(self, shooter_pos: int, target_pos: int, events: list[GameEvent]) -> bool:
        start_index = len(events)
        shooter = self.seat_at(shooter_pos)
        tgt = self.seat_at(target_pos)
        if tgt.role == "evil_knight" and not self.evil_knight_reflection_used:
            self.evil_knight_reflection_used = True
            events.append(GameEvent(type="system",
                                    text=t(self.locale, "hunter_reflect")))
            self.history.extend(events[start_index:])
            return False
        events.append(GameEvent(type="system",
                                text=t(self.locale, "hunter_shot", pos=shooter.pos,
                                      name=shooter.name, target=target_pos, tname=tgt.name)))
        self._kill(target_pos, "hunter_gun", events)
        self.history.extend(events[start_index:])
        return True

    def trigger_wolf_king(self, king_pos: int, target_pos: int, events: list[GameEvent]):
        start_index = len(events)
        events.append(GameEvent(type="system",
                                text=t(self.locale, "wolf_king_shot", pos=king_pos, target=target_pos)))
        self._kill(target_pos, "wolf_king_gun", events)
        self.history.extend(events[start_index:])

    # ---------- 白天 ----------
    def resolve_day_skill(self, actor_pos: int, target_pos: Optional[int]) -> list[GameEvent]:
        actor = self.seat_at(actor_pos)
        if self.phase != "day" or not actor.alive or self.winner:
            raise ValueError("Day skill unavailable")
        if actor.role not in ("knight", "white_wolf_king", "crow"):
            raise ValueError("No day skill")
        if actor.role == "knight" and self.knight_used:
            raise ValueError("Duel already used")
        if actor.role == "crow" and self.crow_used_day == self.day_count:
            raise ValueError("Slander already used today")
        if target_pos is None:
            return []
        if type(target_pos) is not int or target_pos not in self.seats:
            raise ValueError("Invalid day target")
        target = self.seat_at(target_pos)
        if not target.alive or target_pos == actor_pos:
            raise ValueError("Invalid day target")
        events = []
        if actor.role == "crow":
            self.crow_target = target_pos
            self.crow_used_day = self.day_count
            # Only the affected seat, not the Crow's identity, is announced.
            events.append(GameEvent(type="system", text=t(self.locale, "crow_mark", target=target_pos)))
        elif actor.role == "knight":
            self.knight_used = True
            events.append(GameEvent(type="system", text=t(self.locale, "knight_duel", pos=actor_pos, target=target_pos)))
            self._kill(target_pos if target.is_wolf else actor_pos, "knight_duel", events)
            if target.is_wolf:
                self.phase = "night"
        else:
            events.append(GameEvent(type="system", text=t(self.locale, "white_explode", pos=actor_pos, target=target_pos)))
            self._kill(actor_pos, "self_destruct", events)
            self._kill(target_pos, "white_wolf_blast", events)
            self.phase = "night"
        self.history.extend(events)
        return events

    def vote_tally(self, votes: dict[int, Optional[int]]) -> dict[int, float]:
        tally = {}
        alive = {s.pos for s in self.alive_seats()}
        for voter, target in votes.items():
            if voter not in alive or (target != 0 and target not in alive) or voter == target:
                continue
            tally[target] = tally.get(target, 0) + (1.5 if voter == self.sheriff else 1.0)
        if self.crow_target in alive:
            tally[self.crow_target] = tally.get(self.crow_target, 0) + 1.0
        return tally

    def start_day(self):
        self.phase = "day"
        self.day_count += 1
        self.crow_target = None
        self.last_exiled = None
        self.last_exiled_wolf = None
        event = GameEvent(type="day_start", text=t(self.locale, "day_start", d=self.day_count))
        self.history.append(event)
        return [event]

    def speech_order(self) -> list[int]:
        """从警长开始顺时针；无警长则从1号起。"""
        alive = [s.pos for s in self.alive_seats()]
        if self.sheriff and self.sheriff in alive:
            start = self.sheriff
        else:
            start = min(alive)
        order = []
        for i in range(12):
            p = ((start - 1 + i) % 12) + 1
            if p in alive:
                order.append(p)
        return order

    # ---------- 投票 ----------
    def resolve_vote(self, votes: dict[int, int], exiled: Optional[int]) -> list[GameEvent]:
        """votes: {voter_pos: target_pos}。exiled 已确定（由runner计算）。"""
        vote_text = list_sep(self.locale).join(
            ((f"#{voter}→Peaceful Day" if self.locale == "en" else f"{voter}号→平安日")
             if target == 0 else t(self.locale, "vote_arrow", v=voter, t=target))
            for voter, target in votes.items() if target is not None
        ) or t(self.locale, "vote_none")
        events: list[GameEvent] = [GameEvent(
            type="vote",
            text=t(self.locale, "vote_header", d=self.day_count, votes=vote_text),
            data={"day": self.day_count, "votes": dict(votes)},
        )]
        if exiled is None or exiled == 0:
            text = (("Peaceful Day wins: nobody is exiled." if self.locale == "en" else "平安日最高票，今日无人被放逐。")
                    if exiled == 0 else t(self.locale, "vote_tie"))
            events.append(GameEvent(type="system", text=text))
            self.history.extend(events)
            return events
        seat = self.seat_at(exiled)
        self.last_exiled = seat.name
        self.last_exiled_wolf = seat.is_wolf
        events.append(GameEvent(type="exile", seat=exiled,
                                text=t(self.locale, "exile", pos=exiled, name=seat.name),
                                data={"name": seat.name, "role": seat.role}))
        # 翻牌由 _kill 统一播报，这里不再重复发一次（否则同一个人翻两次牌，
        # 观察者会把踩保关系的权重算两遍）
        self._kill(exiled, "exile", events)
        self.history.extend(events)
        return events

    # ---------- 胜负 ----------
    def check_round_limit(self) -> bool:
        """Only called between complete night/day cycles; normal boards uncapped."""
        limit = self.board.get("round_limit")
        if not self.winner and limit and self.night_count >= limit and self.day_count >= limit:
            if self.check_win():
                return False
            self.winner = "draw"
            self.end_reason = ("Experimental round limit reached: draw after 20 complete night/day cycles."
                               if self.locale == "en" else "实验对局达到20个完整昼夜上限，按公开规则判为平局。")
            self.history.append(GameEvent(type="win", text=self.end_reason, data={"winner": "draw"}))
            return True
        return False

    def check_win(self) -> Optional[str]:
        if self.winner:
            return self.winner
        alive = self.alive_seats()
        wolves_alive = [s for s in alive if s.is_wolf]
        gods_alive = [s for s in alive if s.faction == "god"]
        civ_alive = [s for s in alive if s.faction == "civilian"]
        if not wolves_alive:
            self.winner = "god"
            self.end_reason = t(self.locale, "win_god")
            self.history.append(GameEvent(
                type="win", text=self.end_reason, data={"winner": self.winner}))
            return "god"
        # 屠边：神全灭 或 民全灭
        if not gods_alive or not civ_alive:
            self.winner = "wolf"
            self.end_reason = t(self.locale, "win_wolf")
            self.history.append(GameEvent(
                type="win", text=self.end_reason, data={"winner": self.winner}))
            return "wolf"
        return None

    # ---------- 快照 ----------
    def public_state(self) -> dict:
        return {
            "locale": self.locale,
            "board": board_display(self.locale, self.board)["name"],
            "board_id": self.board_id,
            "phase": self.phase,
            "day": self.day_count,
            "night": self.night_count,
            "sheriff": self.sheriff,
            "seats": [s.to_public() for s in self.seats.values()],
            "alive_count": len(self.alive_seats()),
            "winner": self.winner,
            "end_reason": self.end_reason,
        }

    def player_view(self) -> dict:
        ps = self.player_seat()
        return {
            "pos": ps.pos,
            "name": ps.name,
            "role": ps.role,
            "role_cn": ps.role_cn,
            "ability": (witch_rule_text(self.locale, self.board) if ps.role == "witch"
                        else role_desc(self.locale, ps.role, role_info(ps.role))),
            "is_wolf": ps.is_wolf,
            "wolfmates": [s.pos for s in self.seats.values()
                          if s.is_wolf and s.role != "stone_ghost" and s.pos != ps.pos]
                         if ps.is_wolf and ps.role != "stone_ghost" else [],
            "seer_results": self.seer_results if ps.role == "seer" else [],
            "grave_results": self.grave_results if ps.role == "gravekeeper" else [],
        }
