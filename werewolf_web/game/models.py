"""游戏数据模型：座位、玩家、事件。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Seat:
    pos: int               # 座位号 1-12
    player_id: str         # stable identity, never localized
    name: str              # display name, chosen before the match
    role: str              # 角色 key（见 boards.json roles）
    role_cn: str = ""
    faction: str = ""      # god / wolf / civilian
    emoji: str = ""
    alive: bool = True
    is_player: bool = False
    is_wolf: bool = False  # 是否属于狼阵营（含隐狼）
    death_cause: Optional[str] = None
    persona_id: str = ""   # independent preset identity, never selected by display name

    def to_public(self) -> dict:
        return {
            "pos": self.pos,
            "player_id": self.player_id,
            "name": self.name,
            "alive": self.alive,
            "is_player": self.is_player,
        }

    def to_dict(self) -> dict:
        """Whitelisted snapshot fields; display-only ``emoji`` is re-derived."""
        return {
            "pos": self.pos,
            "player_id": self.player_id,
            "name": self.name,
            "role": self.role,
            "role_cn": self.role_cn,
            "faction": self.faction,
            "alive": self.alive,
            "is_player": self.is_player,
            "is_wolf": self.is_wolf,
            "death_cause": self.death_cause,
            "persona_id": self.persona_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Seat":
        return cls(
            pos=data["pos"],
            player_id=data["player_id"],
            name=data["name"],
            role=data["role"],
            role_cn=data["role_cn"],
            faction=data["faction"],
            alive=data["alive"],
            is_player=data["is_player"],
            is_wolf=data["is_wolf"],
            death_cause=data["death_cause"],
            persona_id=data["persona_id"],
        )


@dataclass
class GameEvent:
    type: str              # night_start / death / speech / vote / flip / win / system
    seat: Optional[int] = None
    text: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "seat": self.seat,
            "text": self.text,
            "data": deepcopy(self.data),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameEvent":
        return cls(
            type=data["type"],
            seat=data["seat"],
            text=data["text"],
            data=deepcopy(data.get("data") or {}),
        )


WOLF_ROLES = {"werewolf", "wolf_king", "white_wolf_king", "wolf_beauty",
              "hidden_wolf", "stone_ghost", "evil_knight"}
GOD_ROLES = {"seer", "witch", "hunter", "guard", "knight", "crow",
             "gravekeeper", "bomber", "stone_ghost_grave"}
