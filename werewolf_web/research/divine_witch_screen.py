"""Offline, frozen-extreme screening using the playable GameSession.

All actors, including the normally human Witch, use the local strategic Brain.
Conjecture beta is on; this is NOT the seven-seat Codex dual-table planner.
No external requests, host evolution, or persistent NPC memory writes.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import gzip
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from ..run import GameSession
from ..ai.affect import MatchState
from ..ai.brain import Style
from ..ai.growth import CognitiveProfile
from ..ai.strategic_agent import StrategicNPCAgent
from .extreme_profiles import roster_profiles, validate_profile

BOARDS = ("classic", "divine_witch", "divine_witch_dual")


class FrozenState(MatchState):
    def react(self, event):
        pass


class ScreenSession(GameSession):
    def __init__(self, board, seed, condition, memory):
        super().__init__(board, {"enabled": False}, seed=seed, player_role="witch", conjecture=True)
        self.memory_dir = memory
        self.condition = condition
        self.seed = seed
        self.samples = []
        self.nights = []
        self.errors = []
        self.profiles = {}
        self.host.evolve = lambda *args: None
        self.last_speech = None

    def emit(self, event):
        if event["type"] == "init":
            e = self.engine
            human = e.player_seat()
            self.agents[human.name] = StrategicNPCAgent(human.name, e, self.llm, memory_dir=self.memory_dir)
            ids = tuple(sorted(s.player_id for s in e.seats.values()))
            self.profiles = roster_profiles(self.condition, ids)
            for agent in self.agents.values():
                p = self.profiles[agent.seat.player_id]; validate_profile(p)
                agent.brain.style = Style(**p["style"])
                agent.brain.cognition = CognitiveProfile(**p["cognition"], experience=0)
                agent.brain.match_state = FrozenState(**p["state"])
                agent.brain.starting_state = agent.brain.match_state.snapshot()
                agent.save_memory = lambda: None
            wolves = sorted((a for a in self.agents.values() if a.is_wolf),
                            key=lambda a: -(a.style.bluff * .6 + a.style.aggression * .4))
            for rank, agent in enumerate(wolves): agent.assign_wolf_strategy(rank, len(wolves))
        if event["type"] == "error": self.errors.append(event["text"])
        super().emit(event)

    async def ask_player(self, kind, data):
        e = self.engine; human = self.agents[e.player_seat().name]
        if kind == "conjecture":
            answer = self.conjecture_ledger.npc_drafts({human.name: human})[human.name]
        elif kind in ("speech", "table_reply"):
            self.last_speech = human.speak(self.speech_events)
            answer = {"text": self.last_speech.text}
        elif kind == "election_up": answer = {"up": human.style.aggression > .82}
        elif kind == "vote": answer = {"target": human.vote(data["candidates"], sheriff=data.get("sheriff", False))}
        elif kind == "night":
            victim = getattr(self, "knife", None)
            answer = human.night_action("witch", data["candidates"], knife=victim,
                                        antidote=e.witch_antidote, poison=e.witch_poison)
        else: raise ValueError(f"unexpected Witch action: {kind}")
        self.pending = {"kind": kind, "data": data}
        if not self.submit(answer): raise ValueError(f"illegal autoplay response for {kind}")
        result = await self.q.get()
        self.samples.append({"night": e.night_count, "day": e.day_count, "kind": kind,
                             "request": deepcopy(data), "response": deepcopy(result)})
        return result

    def _player_speech(self, text):
        return self.last_speech if self.last_speech and self.last_speech.text == text else super()._player_speech(text)

    async def _witch_action(self, knife):
        self.knife = knife
        return await super()._witch_action(knife)

    async def _gather_night(self, requests):
        if self.engine.night_count > 20:
            raise ValueError("research safety bound exceeded")
        actions = await super()._gather_night(requests)
        e = self.engine; witch = e.player_seat()
        self.nights.append({"night": e.night_count, "alive_before": [s.pos for s in e.alive_seats()],
            "witch_alive_before": witch.alive, "actions": deepcopy(actions)})
        return actions

    def export(self):
        e = self.engine
        for agent in self.agents.values():
            p = self.profiles[agent.seat.player_id]
            assert asdict(agent.style) == p["style"]
            assert asdict(agent.brain.cognition) == {**p["cognition"], "experience": 0}
            assert {k: getattr(agent.brain.match_state, k) for k in p["state"]} == p["state"]
        return {"board": e.board_id, "seed": self.seed, "condition": self.condition,
            "status": "failed" if self.errors else "complete" if e.winner else "stopped",
            "winner": e.winner, "end_reason": e.end_reason, "errors": self.errors,
            "profiles": self.profiles, "seats": [asdict(s) for s in e.seats.values()],
            "nights": self.nights, "history": [asdict(ev) for ev in e.history],
            "human_proxy_actions": self.samples,
            "public_tables": self.conjecture_ledger.public_history(),
            "research_only_private_tables": deepcopy(self.conjecture_ledger.private)}


async def run_one(board, seed, condition):
    with tempfile.TemporaryDirectory(prefix="divine-witch-") as memory:
        game = ScreenSession(board, seed, condition, memory)
        async for _ in game.events(): pass
        return game.export()


def summarize(games):
    result = {}
    for board in BOARDS:
        rows = [g for g in games if g["board"] == board]
        counts = Counter(g["winner"] or g["status"] for g in rows)
        potions = Counter()
        for g in rows:
            seats = {s["pos"]: s for s in g["seats"]}
            for n in g["nights"]:
                a = n["actions"].get("witch", {})
                if a.get("save") is not None: potions["saves_attempted"] += 1
                if a.get("poison") is not None:
                    potions["poisons_attempted"] += 1
                    potions["poison_wolf" if seats[a["poison"]]["is_wolf"] else "poison_good"] += 1
                if a.get("save") is not None and a.get("poison") is not None: potions["dual_nights"] += 1
                if n["witch_alive_before"]: potions["witch_action_nights"] += 1
                guard = n["actions"].get("guard", {}).get("target")
                if a.get("save") is not None and a["save"] == guard: potions["guard_save_collision"] += 1
        result[board] = {"attempts": len(rows), "outcomes": dict(counts), **dict(potions),
            "max_nights": max((len(g["nights"]) for g in rows), default=0)}
    return result


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    files = [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]
    files += [root / "data/boards.json"]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


async def screen(seeds):
    games = []
    sources = source_hashes()
    original_sleep = asyncio.sleep
    async def fast_sleep(_): await original_sleep(0)
    with patch("werewolf_web.run.asyncio.sleep", fast_sleep):
        for seed in seeds:
            for condition in range(4):
                for board in BOARDS:
                    game = await run_one(board, seed, condition)
                    games.append(game)
                    print(json.dumps({k: game[k] for k in ("board", "seed", "condition", "status", "winner")}), flush=True)
    if sources != source_hashes(): raise RuntimeError("sources changed during screening")
    return {"protocol": "divine-witch-local-screen-v2", "scope": "RESEARCH ONLY: contains all identities and private tables",
        "created_at": datetime.now(timezone.utc).isoformat(), "provider_calls": 0,
        "decision_maker": "local heuristic Brain for all twelve actors, including a Witch proxy for the human",
        "conjecture": "playable beta, NOT the Codex research planner", "seeds": list(seeds),
        "source_sha256": sources, "games": games, "summary": summarize(games)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 32: parser.error("seeds must be between 1 and 32")
    path = Path(args.output)
    if path.exists(): parser.error("output exists; preserve earlier experiments")
    artifact = asyncio.run(screen(range(args.seeds)))
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "xt", encoding="utf-8") as file: json.dump(artifact, file, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(artifact["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
