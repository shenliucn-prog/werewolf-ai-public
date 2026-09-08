"""Playable dual-table adapter. Private drafts never enter public events.

This local-strategy beta is separate from the seven-seat Codex research game.
It preserves every public version, but does not claim perfect semantic judgment.
"""
from copy import deepcopy

from ..ai.brain import Speech
from ..i18n import role_name, board_role_name
from ..recovery import SCHEMA_VERSION, check_version
from .engine import ROLE_META


class GameConjectures:
    def __init__(self, engine):
        self.engine = engine
        self.history = []
        self.private = {s.name: [] for s in engine.seats.values()}
        self.roster = tuple(s.name for s in engine.seats.values())
        self.options = ("unknown", "good", "wolf", *dict.fromkeys(engine.board["roles"]))
        self.labels = {k: board_role_name(engine.locale, engine.board, k, ROLE_META.get(k, {}).get("cn", k)) for k in self.options}
        self.labels.update(dict(zip(("unknown", "good", "wolf"),
            ("Unknown", "Good faction", "Wolf faction") if engine.locale == "en" else ("未知", "好人阵营", "狼人阵营"))))

    def _role_key(self, label):
        return next((key for key, value in self.labels.items() if value == label), label)

    def _row(self, name, judgment="unknown", reason=""):
        return {"player": name, "judgment": judgment, "reason": reason}

    def _human_known(self):
        e = self.engine
        player = e.player_seat()
        known = {player.name: player.role}
        for pos in e.player_view().get("wolfmates", []):
            known[e.seat_at(pos).name] = "wolf"
        if player.role == "seer":
            for result in e.seer_results:
                known[result["name"]] = "wolf" if result["result"] == "wolf" else "good"
        if player.role == "stone_ghost":
            known.update({r["name"]: self._role_key(r["role_cn"]) for r in e.sg_results})
        if player.role == "gravekeeper":
            known.update({r["name"]: r["result"] for r in e.grave_results})
        known.update({event.data["name"]: event.data["role"] for event in e.history
                      if event.type == "flip"})
        return known

    def human_request(self):
        e = self.engine
        player = e.player_seat()
        previous = self.private[player.name]
        private = deepcopy(previous[-1]["private"]) if previous else [self._row(n) for n in self.roster]
        public = deepcopy(previous[-1]["public"]) if previous else [self._row(n) for n in self.roster]
        known = self._human_known()
        for row in private:
            if row["player"] in known:
                row["judgment"] = known[row["player"]]
        return {"players": list(self.roster), "options": list(self.options),
                "option_labels": dict(self.labels),
                "locked_private": dict(known),
                "private": private, "public": public,
                "hint": ("Private = your belief; public = what you choose to argue. All players required."
                         if e.locale == "en" else "私有表是你的判断；公开表是你选择辩论的说法。请覆盖所有人，允许未知。")}

    def validate_human(self, response):
        if type(response) is not dict or set(response) != {"private", "public"}:
            raise ValueError("Two tables required")
        for kind in ("private", "public"):
            rows = response[kind]
            if type(rows) is not list or len(rows) != len(self.roster):
                raise ValueError("Incomplete table")
            seen = set()
            for row in rows:
                if type(row) is not dict or set(row) != {"player", "judgment", "reason"}:
                    raise ValueError("Invalid row")
                if row["player"] not in self.roster or row["player"] in seen:
                    raise ValueError("Invalid player")
                seen.add(row["player"])
                if row["judgment"] not in self.options:
                    raise ValueError("Invalid identity")
                if not isinstance(row["reason"], str) or len(row["reason"]) > 500:
                    raise ValueError("Invalid reason")
        for row in response["private"]:
            known = self._human_known().get(row["player"])
            if known and row["judgment"] != known:
                raise ValueError("Keep lawful known facts in your private table")
        return deepcopy(response)

    def npc_drafts(self, agents):
        drafts = {}
        en = self.engine.locale == "en"
        for name, agent in agents.items():
            if not agent.seat.alive:
                continue
            b = agent.brain
            info = agent.information_set()
            known = {name: b.role}
            known.update({r["name"]: "wolf" for r in info.private.get("wolf_mates", [])})
            for r in info.private.get("seer_results", []):
                known[r["name"]] = "wolf" if r["result"] == "wolf" else "good"
            for r in info.public_flips:
                known[r["name"]] = self._role_key(r["role"])
            for r in info.private.get("stone_ghost_results", []):
                known[r["name"]] = self._role_key(r["role_cn"])
            for r in info.private.get("grave_results", []):
                known[r["name"]] = r["result"]
            private, public = [], []
            for target in self.roster:
                suspicion = b.suspicion(target) if target != name else 0.35
                guess = "wolf" if suspicion >= 0.6 else "good" if suspicion <= 0.25 else "unknown"
                private.append(self._row(target, known.get(target, guess),
                    ("Own lawful knowledge" if en else "自身合法已知信息") if target in known else
                    ("Current evidence-based inclination" if en else "当前证据下的倾向")))
                # Deliberate account: only already-public own claims, never copy private facts.
                claim = b.my_claims[-1] if target == name and b.my_claims else ""
                public.append(self._row(target, claim if claim in self.options else guess,
                    "Current public position; not verified truth." if en else "当前公开立场，不代表已核实的事实。"))
            drafts[name] = {"private": private, "public": public}
        return drafts

    def publish(self, drafts, agents):
        if set(drafts) != {s.name for s in self.engine.alive_seats()}:
            raise ValueError("Only all living players may publish")
        published = []
        for actor, draft in drafts.items():
            self.private[actor].append(deepcopy(draft))
            table = {"actor": actor, "day": self.engine.day_count,
                     "version": len(self.private[actor]), "rows": deepcopy(draft["public"])}
            published.append(table)
        self.history.extend(deepcopy(published))
        for agent in agents.values():
            agent.conjecture_history = self.public_history()
            for table in published:
                if table["actor"] == agent.name:
                    continue
                target = next((r["player"] for r in table["rows"]
                               if r["judgment"] in ("wolf", "werewolf") and r["player"] != table["actor"]), None)
                own = next(r for r in table["rows"] if r["player"] == table["actor"])
                claim = own["judgment"] if own["judgment"] in self.engine.board["roles"] else None
                agent.observe_speech(self.engine.day_count, table["actor"],
                    Speech(text=str(table), claim=claim, accuse=target))
        return published

    def public_history(self):
        return deepcopy(self.history)

    def snapshot(self) -> dict:
        """Whitelisted conjecture ledger; ``engine`` is re-derived on restore."""
        return {
            "schema_version": SCHEMA_VERSION,
            "history": deepcopy(self.history),
            "private": deepcopy(self.private),
            "roster": list(self.roster),
            "options": list(self.options),
            "labels": dict(self.labels),
        }

    def restore(self, data: dict) -> None:
        """Restore the conjecture ledger in place; ``engine`` stays wired.

        Validate-then-apply: every field is read, checked, and converted before
        any attribute is replaced, so a corrupt snapshot cannot leave a
        half-restored table.
        """
        where = "GameConjectures.snapshot"
        check_version(data, where)
        data = deepcopy(data)

        # ---- validate (no mutation) ----
        history = data.get("history")
        if not isinstance(history, list):
            raise ValueError(f"{where}: history must be an array")
        private = data.get("private")
        if not isinstance(private, dict):
            raise ValueError(f"{where}: private must be an object")
        for name, drafts in private.items():
            if not isinstance(name, str):
                raise ValueError(f"{where}: private keys must be player names")
            if not isinstance(drafts, list):
                raise ValueError(f"{where}: private values must be arrays")

        roster = data.get("roster")
        if not isinstance(roster, list) or any(
                not isinstance(n, str) for n in roster):
            raise ValueError(f"{where}: roster must be an array of names")
        roster = tuple(roster)
        if roster != tuple(s.name for s in self.engine.seats.values()):
            raise ValueError(f"{where}: roster does not match engine seats")

        options = data.get("options")
        if not isinstance(options, list) or any(
                not isinstance(o, str) for o in options):
            raise ValueError(f"{where}: options must be an array of strings")
        options = tuple(options)

        labels = data.get("labels")
        if not isinstance(labels, dict):
            raise ValueError(f"{where}: labels must be an object")

        # ---- apply ----
        self.history = deepcopy(history)
        self.private = deepcopy(private)
        self.roster = roster
        self.options = options
        self.labels = dict(labels)
