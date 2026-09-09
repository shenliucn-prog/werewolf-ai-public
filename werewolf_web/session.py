"""Transport-neutral playable game session.

Holds ``GameSession`` — the single game core shared by the FastAPI/SSE adapter
(``run.py``), the terminal chat adapter (``chat_game.py``), and research
callers.  It has no FastAPI or DOM dependency; adapters consume ``events()``
and submit validated action dictionaries via ``submit()``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from copy import deepcopy
from dataclasses import replace
from typing import Optional

from . import config
from . import driver as driver_mod
from . import perf
from .game import engine as eng_mod
from .ai.brain import Speech
from .ai.llm import LLMClient, LLMRuntimeConfig
from .ai.decision_runtime import ModelTurnError
from .ai.strategic_agent import StrategicNPCAgent
from .ai.host import HostAgent
from .i18n import t, role_name, board_display, witch_rule_text
from .public_record import PublicRecord, ballot_event, target_label

_SENTINEL = object()


class GameSession:
    """The transport-neutral playable game session.

    Web SSE, terminal chat, and future voice clients consume the same emitted
    events and submit the same action dictionaries.  None of the game loop
    below depends on a DOM, HTTP response, or chat provider.
    """

    def __init__(self, board_id: str, llm_options: dict | None = None,
                 session_id: str = "local", seed: int | None = None,
                 locale: str = "zh-CN", names: dict | None = None,
                 personalities: dict | None = None, conjecture: bool = False,
                 player_role: str | None = None, onboarding: bool = False,
                 planner=None, checkpoint_path: Optional[str] = None,
                 perf_path: Optional[str] = None,
                 _defer_preflight: bool = False):
        if planner is not None and not planner.verified and not _defer_preflight:
            raise ValueError("Model preflight required before opening a game.")
        if planner is not None and conjecture:
            raise ValueError("Model-player conjecture tables are not yet integrated; choose normal mode.")
        self.planner = planner
        self.session_id = session_id
        # Optional local-only perf sink (opt-in; never affects game behavior).
        self.perf_recorder = perf.Recorder(perf_path)
        # Gameplay driver lock: how NPC decisions are produced ("api"/"agent"/
        # "offline"), and the agent adapter ("command"/"codex").  Durable, so a
        # restore can refuse an offline->counted (or vice versa) switch and
        # re-derive the runtime from trusted local config.
        self.driver, self.adapter = driver_mod.driver_from_planner(planner)
        # Campaign association (durable): the profile this game settles into, or
        # None for a free-play game.  Lets a restored game re-attach its hook.
        self.campaign_profile = None
        # Whether this campaign game counts toward progression (False for an
        # explicit offline simulation).  Durable, so reconnect keeps the label.
        self.campaign_counted = None
        # Durable post-loss short-review state for a campaign game: None (not yet
        # generated), "done", or "unavailable".  Snapshotted so a restore knows a
        # finished review already ran and never re-triggers (or re-charges) it —
        # only an explicit retry re-requests.
        self.campaign_review_state = None
        # Optional recovery sink: when set, the game writes checkpoints at turn
        # boundaries and around every external call; None disables persistence.
        self.checkpoint_path = checkpoint_path
        if type(conjecture) is not bool:
            raise ValueError("Conjecture mode must be true or false.")
        self.conjecture = conjecture
        self.onboarding = onboarding
        self.conjecture_ledger = None
        self.engine = eng_mod.GameEngine(board_id, seed=seed, locale=locale, names=names,
                                        personalities=personalities, player_role=player_role)
        # Freeze provider settings at game start.  No key is persisted in NPC
        # memory, reviews, SSE events, or public state.
        self.llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False} if planner is not None else llm_options))
        self.host = HostAgent(self.llm, locale=self.engine.locale)
        self.public_record = PublicRecord(self.engine.locale)
        # A hosted game's carry/memory is scoped to its random session, so one
        # user's games cannot influence another user's NPC profiles.
        self.memory_dir = os.path.join(config.DATA_DIR, "npc_memory", session_id)
        self.agents: dict[str, StrategicNPCAgent] = {}
        self._q: Optional[asyncio.Queue] = None
        self._event_q: Optional[asyncio.Queue] = None
        self.pending: Optional[dict] = None
        self.speech_events: list[tuple[str, Speech]] = []
        self.player_last_speech = ""
        self._triggered: set[int] = set()
        self._last_llm_status: tuple[str, str] | None = None
        self.finished = False
        self.stream_claimed = False
        self._events_started = False
        self._table_extra_turns = 0
        self._table_extra_by_name: dict[str, int] = {}
        self._table_pairs: set[frozenset[str]] = set()
        self._pending_questions: list[list[str, str]] = []  # [target, asker] pairs
        self._questions_answered = 0
        self._table_cooldown = False
        # 显式状态机游标：_play() 被分解为一系列小步骤，由 _step 驱动。
        # _step_state 存放跨步骤的循环局部值（夜间行动、夜间事件等），
        # 是后续检查点（预调用预留 + 本地原子提交）的挂载点。
        self._step: Optional[str] = None
        self._step_state: dict = {}
        # 决策日志（§4.5）：decision_no 是单调的逻辑决策槽位，用于对已提交
        # 动作去重；attempt_no 是同一槽位上的第几次物理调用，每次调用都消耗
        # 预算（重试是新 attempt，不是旧 replay）。committed 在检查点提交边界
        # 置真（块 3），此处先记录调用与结果。
        self._decision_no = 0
        self.decision_log: list[dict] = []
        self._current_step: Optional[str] = None
        # 事件账本（§5.4 / §6）：emit 给每个事件一个单调 event_no 并留存全量，
        # 供断线重连时按编号追赶（无缺失、无重复）。对局生命周期由 _game_task
        # 拥有：SSE 断开不再结束对局，它会在 ask_player 处继续等待输入。
        self._event_no = 0
        self._events: list[dict] = []
        self._init_event: Optional[dict] = None
        self._pending_event_no: Optional[int] = None
        # How many ledger events have been handed to the live queue.  ``emit``
        # records every event to the durable ledger and (by default) publishes
        # it immediately; speech paths instead record first, checkpoint, and
        # then flush, so an event is never visible before it is durable.
        self._published_upto = 0
        self.stream_active = False
        self._game_task_ref: Optional[asyncio.Task] = None
        # 中途续局（§5.1/§5.3）：崩溃发生在步骤内时 _step 已在派发时清空、
        # _current_step 仍指向崩溃步骤。恢复时重新派发该步骤，并用决策日志
        # 回放该步骤内已提交的决策（不再外呼、不耗预算）；未提交的在途调用
        # 没有已提交条目，会被当作一次新 attempt 重新发出。这些字段是瞬态的，
        # 每次 _play() 进入时从 decision_log 重新推导，不写入快照。
        self._resume_step: Optional[str] = None
        self._replay_committed: list[dict] = []
        self._replay_cursor = 0
        # Abandon (§7) removes the on-disk save; the game-task finalizer must not
        # re-write a checkpoint after that removal.  Transient, never snapshotted.
        self._abandoned = False
        # Recoverable fault (§3.3): a model/internal error paused the game.  The
        # game is NOT finished and stays resumable; transient, never snapshotted.
        self.faulted = False
        # Optional lifecycle hook called after every durable checkpoint with
        # ``self`` (campaign wiring uses it to count/settle).  Transient.
        self.progress_hook = None

    @property
    def q(self):
        if self._q is None:
            self._q = asyncio.Queue()
        return self._q

    @property
    def event_q(self):
        if self._event_q is None:
            self._event_q = asyncio.Queue()
        return self._event_q

    def emit(self, obj: dict, publish: bool = True):
        self._record_event(obj)
        if publish:
            self._flush_publish()

    def _record_event(self, obj: dict) -> dict:
        """Append an event to the durable ledger + public record and assign its
        ``event_no`` — without handing it to the live queue.  Speech paths call
        this (via ``emit(..., publish=False)``), checkpoint, then flush, so a
        published event is always already on disk."""
        self._event_no += 1
        obj["event_no"] = self._event_no
        if obj.get("type") == "init":
            self._init_event = obj
        if obj.get("type") == "request":
            self._pending_event_no = self._event_no
        self.public_record.observe(
            obj, obj.get("day", self.engine.day_count),
            obj.get("night", self.engine.night_count),
            obj.get("phase", self.engine.phase))
        self._events.append(obj)
        return obj

    def _flush_publish(self):
        """Hand every recorded-but-unpublished ledger event to the live queue."""
        while self._published_upto < len(self._events):
            self.event_q.put_nowait(self._events[self._published_upto])
            self._published_upto += 1

    def answer_question(self, question):
        if question.strip().casefold() in ("座次", "座次表", "/seats", "seats"):
            from .onboarding import seating_text
            return seating_text(self.engine.public_state())
        if (re.search(r"上警|退警|sheriff|candid", question, re.I) and
                re.search(r"只有|名单|还能|什么时候|only|list|when|still", question, re.I) and
                not re.search(r"该|建议|should|recommend|谁是狼", question, re.I)):
            rows = [row["event"]["text"] for row in self.public_record.entries
                    if row["event"].get("type") == "narration" and
                    row["event"].get("text", "").startswith(("本轮上警名单：", "Sheriff candidates:"))]
            rules = ("Candidacy opens once before day-one speeches; no late entry. Withdrawal follows speeches."
                     if self.engine.locale == "en" else "仅首日发言前统一报名上警，之后不能加入；警上发言结束后可退警。")
            return "\n".join(rows[-1:] + [rules])
        record = self.public_record.query(question)
        return record if record is not None else self.host.answer_rule_question(question, self.engine)

    def _open_decision(self, slot: str) -> dict:
        """Open a logical decision slot and return its log entry.

        ``decision_no`` is the monotonic dedup key for committed game actions;
        each physical invocation of the external service for that slot is a new
        ``attempt`` (recorded separately, each consuming budget).  ``committed``
        is flipped at the checkpoint commit boundary (phase 3, later block).
        """
        self._decision_no += 1
        entry = {
            "decision_no": self._decision_no,
            "slot": slot,
            "attempts": [],
            "result": None,
            "committed": False,
        }
        self.decision_log.append(entry)
        return entry

    def _begin_attempt(self, entry: dict, calls_before: int) -> None:
        entry["attempts"].append({
            "attempt_no": len(entry["attempts"]) + 1,
            "calls_before": calls_before,
            "calls_after": calls_before,
            "outcome": "pending",
        })

    def _end_attempt(self, entry: dict, calls_after: int, outcome: str) -> None:
        attempt = entry["attempts"][-1]
        attempt["calls_after"] = calls_after
        attempt["outcome"] = outcome

    def _slot_instance(self) -> str:
        """Durable day/phase instance discriminator for decision slots (§4.5).

        Step names repeat across the game ("vote" on day one and day two), so a
        slot keyed only by step+agent would let a day-2 resume replay a stale
        day-1 decision of the same name.  Night steps are keyed by
        ``night_count``, everything else by ``day_count``; both counters are
        durable (part of the engine snapshot), so the discriminator is stable
        across a restore and unique per day/phase instance.
        """
        if self._current_step in ("night", "resolve_night"):
            return f"n{self.engine.night_count}"
        return f"d{self.engine.day_count}"

    @staticmethod
    def _slot_step(slot) -> Optional[str]:
        """Recover the step name from a decision slot string.

        NPC slots are ``"{step}:{instance}:{agent_name}:{action}"``; human slots
        are ``"human:{step}:{instance}:{kind}"``.  Returns ``None`` for
        malformed slots so a caller can treat them as un-replayable rather than
        crashing.
        """
        if not isinstance(slot, str):
            return None
        if slot.startswith("human:"):
            parts = slot.split(":", 2)
            return parts[1] if len(parts) >= 2 else None
        parts = slot.split(":", 1)
        return parts[0] if parts else None

    def _replay_decision(self, slot: str) -> Optional[dict]:
        """Return the next committed decision for ``slot`` during a resume pass.

        Replay is scoped to the step being resumed: only committed decisions
        whose slot belongs to ``self._current_step`` are candidates, consumed in
        ``decision_no`` order.  A committed decision is reused verbatim — no new
        external call, no budget; an uncommitted in-flight decision has no entry
        here, so the caller re-issues it as a fresh attempt.
        """
        if self._resume_step is None or self._resume_step != self._current_step:
            return None
        for index in range(self._replay_cursor, len(self._replay_committed)):
            entry = self._replay_committed[index]
            if entry.get("slot") == slot:
                self._replay_cursor = index + 1
                return entry
        return None

    # ---------------- 检查点 / 快照 ----------------
    def _checkpoint(self) -> None:
        """Persist the current logical state at a checkpoint boundary.

        A no-op when ``checkpoint_path`` is not configured, so normal play and
        the existing test suite are untouched until recovery is enabled.
        """
        if not self.checkpoint_path:
            return
        from . import checkpoint as cp
        t0 = perf.now()
        cp.save_checkpoint(self.checkpoint_path, self.snapshot())
        self.perf_recorder.checkpoint(
            dur_ms=perf.elapsed_ms(t0), bytes=os.path.getsize(self.checkpoint_path))
        hook = self.progress_hook
        if hook is not None:
            hook(self)

    def _commit_batch(self) -> None:
        """Atomically commit a recorded settlement batch, then publish it once.

        A settlement produces a list of events (deaths, flips, exiles) plus
        engine mutations.  The caller records every event via ``_emit_event``
        (``publish=False``) and then calls this: one checkpoint makes the *whole
        batch* durable before the first event reaches the queue, then a single
        flush publishes it.  A crash at any point leaves either none or all of
        the batch in the ledger — never a torn batch.
        """
        self._checkpoint()
        self._flush_publish()

    @staticmethod
    def _freeze(value):
        """Recursively convert non-JSON game objects for the snapshot."""
        if isinstance(value, Speech):
            return {"__speech__": True, "text": value.text, "claim": value.claim,
                    "accuse": value.accuse, "defend": value.defend,
                    "question_to": value.question_to,
                    "protected_facts": list(value.protected_facts)}
        if isinstance(value, eng_mod.GameEvent):
            return {"__event__": True, **value.to_dict()}
        if isinstance(value, dict):
            return {key: GameSession._freeze(val) for key, val in value.items()}
        if isinstance(value, (list, tuple)):
            return [GameSession._freeze(val) for val in value]
        return value

    @staticmethod
    def _thaw(value):
        """Inverse of :meth:`_freeze`."""
        if isinstance(value, dict):
            if value.get("__speech__"):
                return Speech(text=value.get("text", ""), claim=value.get("claim"),
                              accuse=value.get("accuse"), defend=value.get("defend"),
                              question_to=value.get("question_to"),
                              protected_facts=tuple(value.get("protected_facts", [])))
            if value.get("__event__"):
                return eng_mod.GameEvent.from_dict(value)
            return {key: GameSession._thaw(val) for key, val in value.items()}
        if isinstance(value, list):
            return [GameSession._thaw(val) for val in value]
        return value

    def snapshot(self) -> dict:
        """Full logical-state snapshot (whitelisted; never emitted or stored
        with credentials)."""
        from .recovery import SCHEMA_VERSION
        planner = self.planner
        return {
            "schema_version": SCHEMA_VERSION,
            "board_id": self.engine.board_id,
            "locale": self.engine.locale,
            "session_id": self.session_id,
            "driver": self.driver,
            "adapter": self.adapter,
            "campaign_profile": self.campaign_profile,
            "campaign_counted": self.campaign_counted,
            "campaign_review_state": self.campaign_review_state,
            "conjecture": self.conjecture,
            "onboarding": self.onboarding,
            "engine": self.engine.snapshot(),
            "agents": {name: agent.snapshot() for name, agent in self.agents.items()},
            "planner": planner.snapshot() if planner is not None and hasattr(planner, "snapshot") else None,
            "llm": self.llm.snapshot(),
            "conjecture_ledger": (self.conjecture_ledger.snapshot()
                                  if self.conjecture_ledger is not None else None),
            "public_record": deepcopy(self.public_record.entries),
            "pending": deepcopy(self.pending),
            "speech_events": [[name, self._freeze(sp)] for name, sp in self.speech_events],
            "player_last_speech": self.player_last_speech,
            "triggered": sorted(self._triggered),
            "table_extra_turns": self._table_extra_turns,
            "table_extra_by_name": dict(self._table_extra_by_name),
            "table_pairs": [sorted(pair) for pair in self._table_pairs],
            "pending_questions": [list(pair) for pair in self._pending_questions],
            "questions_answered": self._questions_answered,
            "table_cooldown": self._table_cooldown,
            "last_llm_status": (list(self._last_llm_status)
                                if self._last_llm_status is not None else None),
            "step": self._step,
            "current_step": self._current_step,
            "step_state": self._freeze(self._step_state),
            "decision_no": self._decision_no,
            "decision_log": self._freeze(self.decision_log),
            "finished": self.finished,
            # Event ledger (§5.4 / §6): durable so a process restart re-presents
            # the same numbered transcript with no missing/duplicate events.
            "event_no": self._event_no,
            "events": deepcopy(self._events),
            "pending_event_no": self._pending_event_no,
        }

    def restore(self, snapshot: dict) -> None:
        """Restore full logical state in place (strict, validate-then-apply).

        The session shell (board/seed/session_id/planner) must already exist;
        this fills it from a whitelisted snapshot.  Transient run state — the
        asyncio queues, ``stream_claimed``, ``_events_started`` — is reset, not
        resurrected (see §4.2).

        The restore is atomic: the *whole* snapshot is validated against
        throwaway copies of the live components before any attribute on
        ``self`` is touched, so a corrupt snapshot — however deep the defect —
        raises with the session left unchanged, never half-restored.
        """
        from .recovery import check_version
        check_version(snapshot, "GameSession.snapshot")
        snapshot = deepcopy(snapshot)

        # ================= Phase 1: validate (no mutation of ``self``) ======
        board_id = snapshot.get("board_id")
        if not isinstance(board_id, str) or not board_id:
            raise ValueError("GameSession.snapshot: board_id must be a non-empty string")
        session_id = snapshot.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("GameSession.snapshot: session_id must be a non-empty string")
        review_state = snapshot.get("campaign_review_state")
        if review_state not in (None, "done", "unavailable"):
            raise ValueError(
                "GameSession.snapshot: campaign_review_state must be null, 'done' or 'unavailable'")

        planner_snap = snapshot.get("planner")
        if planner_snap is not None:
            if self.planner is None or not hasattr(self.planner, "restore"):
                raise ValueError("GameSession.snapshot: planner snapshot without a live planner")
        elif self.planner is not None:
            raise ValueError("GameSession.snapshot: legacy snapshot but a live planner is attached")

        # Driver lock: infer a legacy save's driver, then enforce it against the
        # live runtime *before* any mutation.  The runtime is always re-derived
        # from trusted local config; this refuses offline<->counted switches and
        # adapter mismatches instead of guessing.
        counted_raw = snapshot.get("campaign_counted")
        if counted_raw is not None and not isinstance(counted_raw, bool):
            raise ValueError("GameSession.snapshot: campaign_counted must be a boolean or null")
        driver = snapshot.get("driver")
        adapter = snapshot.get("adapter")
        if driver is None:
            driver, adapter = driver_mod.infer_legacy_driver(planner_snap, counted_raw)
        if driver not in driver_mod.DRIVERS:
            raise ValueError(f"GameSession.snapshot: unknown driver {driver!r}")
        if adapter is not None and adapter not in driver_mod.ADAPTERS:
            raise ValueError(f"GameSession.snapshot: unknown adapter {adapter!r}")
        driver_mod.validate_restore(driver, adapter, counted_raw, self.planner)

        entries = snapshot.get("public_record")
        if not isinstance(entries, list):
            raise ValueError("GameSession.snapshot: public_record must be an array")

        ledger_snap = snapshot.get("conjecture_ledger")

        agents = snapshot.get("agents")
        if not isinstance(agents, dict):
            raise ValueError("GameSession.snapshot: agents must be an object")
        for name in agents:
            if not isinstance(name, str) or not name:
                raise ValueError("GameSession.snapshot: agent names must be non-empty strings")

        # Event ledger (§5.4 / §6): restored verbatim so reattach after a
        # process restart re-presents the exact numbered transcript.  The
        # contiguous numbering invariant (1..event_no) is checked, not assumed.
        event_no = snapshot.get("event_no", 0)
        if type(event_no) is not int or event_no < 0:
            raise ValueError("GameSession.snapshot: event_no must be a non-negative integer")
        events = snapshot.get("events", [])
        if not isinstance(events, list):
            raise ValueError("GameSession.snapshot: events must be an array")
        if len(events) != event_no:
            raise ValueError("GameSession.snapshot: event ledger length does not match event_no")
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError("GameSession.snapshot: events must be objects")
            if event.get("event_no") != index + 1:
                raise ValueError("GameSession.snapshot: event ledger numbering is not contiguous")
        pending_event_no = snapshot.get("pending_event_no")
        if pending_event_no is not None and (type(pending_event_no) is not int or pending_event_no < 0):
            raise ValueError("GameSession.snapshot: pending_event_no must be an integer or null")

        # Validate every component snapshot by restoring it into a throwaway
        # copy of the live object, so any component defect fires here too.
        probe_engine = deepcopy(self.engine)
        probe_engine.restore(snapshot["engine"])

        # The live key is bound to the configured endpoint; a probe client
        # mirrors that endpoint (disabled, so no network/client side effects)
        # and re-runs llm.restore's endpoint-trust + budget checks untouched.
        probe_llm = LLMClient(replace(self.llm.runtime, enabled=False, api_key=""))
        probe_llm.restore(snapshot["llm"])

        probe_planner = None
        if planner_snap is not None:
            probe_planner = deepcopy(self.planner)
            probe_planner.restore(planner_snap)

        probe_public = PublicRecord(probe_engine.locale)
        probe_public.entries = deepcopy(entries)

        probe_ledger = None
        if ledger_snap is not None:
            from .game.conjecture import GameConjectures
            probe_ledger = GameConjectures(probe_engine)
            probe_ledger.restore(ledger_snap)

        memory_dir = os.path.join(config.DATA_DIR, "npc_memory", session_id)
        probe_agents = {}
        for name, agent_snap in agents.items():
            if probe_planner is not None:
                from .ai.model_player import ModelNPCAgent
                probe_agents[name] = ModelNPCAgent.restore_agent(
                    agent_snap, probe_engine, probe_llm, probe_planner,
                    probe_public, memory_dir=memory_dir)
            else:
                probe_agents[name] = StrategicNPCAgent.restore_agent(
                    agent_snap, probe_engine, probe_llm, memory_dir=memory_dir)

        # ================= Phase 2: apply (cannot fail) ====================
        # Everything above has validated, so each in-place restore below re-runs
        # the same checks against the live object and succeeds.
        self.engine.restore(snapshot["engine"])
        self.llm.restore(snapshot["llm"])
        if planner_snap is not None:
            self.planner.restore(planner_snap)

        self.public_record = PublicRecord(self.engine.locale)
        self.public_record.entries = deepcopy(entries)

        if ledger_snap is not None:
            from .game.conjecture import GameConjectures
            self.conjecture_ledger = GameConjectures(self.engine)
            self.conjecture_ledger.restore(ledger_snap)
        else:
            self.conjecture_ledger = None

        # Rebuild agents side-effect-free (no engine RNG, no match_start),
        # against the restored engine/llm/planner and the restored memory_dir.
        self.agents = {}
        for name, agent_snap in agents.items():
            if self.planner is not None:
                from .ai.model_player import ModelNPCAgent
                self.agents[name] = ModelNPCAgent.restore_agent(
                    agent_snap, self.engine, self.llm, self.planner,
                    self.public_record, memory_dir=memory_dir,
                    recorder=self.perf_recorder)
            else:
                self.agents[name] = StrategicNPCAgent.restore_agent(
                    agent_snap, self.engine, self.llm, memory_dir=memory_dir)

        # Session loop state (durable fields only).
        self.session_id = session_id
        profile = snapshot.get("campaign_profile")
        if profile is not None and not isinstance(profile, str):
            raise ValueError("GameSession.snapshot: campaign_profile must be a string or null")
        self.campaign_profile = profile
        counted = snapshot.get("campaign_counted")
        if counted is not None and not isinstance(counted, bool):
            raise ValueError("GameSession.snapshot: campaign_counted must be a boolean or null")
        self.campaign_counted = counted
        self.campaign_review_state = review_state
        self.driver = driver
        self.adapter = adapter
        self.memory_dir = memory_dir
        self.conjecture = bool(snapshot.get("conjecture"))
        self.onboarding = bool(snapshot.get("onboarding"))
        self.finished = bool(snapshot.get("finished"))
        self.pending = deepcopy(snapshot.get("pending"))
        self.speech_events = [(name, self._thaw(sp))
                              for name, sp in snapshot.get("speech_events", [])]
        self.player_last_speech = snapshot.get("player_last_speech", "")
        self._triggered = set(snapshot.get("triggered", []))
        self._table_extra_turns = snapshot.get("table_extra_turns", 0)
        self._table_extra_by_name = dict(snapshot.get("table_extra_by_name", {}))
        self._table_pairs = {frozenset(pair) for pair in snapshot.get("table_pairs", [])}
        raw_questions = snapshot.get("pending_questions", [])
        if isinstance(raw_questions, dict):
            # Legacy format {target: asker}; a key->value is a reliable target->asker
            # pair, so this migration fabricates nothing.
            self._pending_questions = [[t, a] for t, a in raw_questions.items()]
        elif isinstance(raw_questions, list):
            self._pending_questions = [list(pair) for pair in raw_questions
                                       if isinstance(pair, (list, tuple)) and len(pair) == 2]
        else:
            self._pending_questions = []
        self._questions_answered = snapshot.get("questions_answered", 0)
        self._table_cooldown = bool(snapshot.get("table_cooldown"))
        last = snapshot.get("last_llm_status")
        self._last_llm_status = tuple(last) if isinstance(last, list) else None
        self._step = snapshot.get("step")
        self._current_step = snapshot.get("current_step")
        self._step_state = self._thaw(snapshot.get("step_state", {}))
        self._decision_no = snapshot.get("decision_no", 0)
        self.decision_log = self._thaw(snapshot.get("decision_log", []))
        self._event_no = event_no
        self._events = deepcopy(events)
        self._init_event = next((e for e in self._events if e.get("type") == "init"), None)
        self._pending_event_no = pending_event_no
        # Transient, deliberately not restored (see §4.2).
        self.stream_claimed = False
        self._events_started = False
        self._q = None
        self._event_q = None
        self.stream_active = False
        self._game_task_ref = None
        self.faulted = False
        self.progress_hook = None
        # The restored ledger is already durable and re-presented by the
        # ``events(after)`` catch-up path, not the live queue.  Align the
        # publish cursor to the ledger end so a subsequent ``_flush_publish``
        # hands only *newly* emitted events to the fresh queue — never re-publishes
        # the pre-restart transcript from a stale cursor.
        self._published_upto = len(self._events)


    async def ask_player(self, kind: str, data: dict) -> dict:
        slot = f"human:{self._current_step}:{self._slot_instance()}:{kind}"
        replayed = self._replay_decision(slot)
        if replayed is not None:
            # The action was already accepted and committed; return the accepted
            # response without re-presenting the prompt or re-blocking on input.
            return replayed["result"]
        self.pending = {"kind": kind, "data": data}
        decision = self._open_decision(slot)
        calls = getattr(self.planner, "calls", 0)
        self._begin_attempt(decision, calls)
        # Emit the request (which assigns ``_pending_event_no``) *before* the
        # checkpoint, so the pending action, its event number and the request
        # event commit atomically — a crash while the player is deciding restores
        # a consistent prompt, never a pending action without its event number.
        self.emit({"type": "request", "kind": kind, "data": data})
        self._checkpoint()
        t0 = perf.now()
        resp = await self.q.get()
        self.perf_recorder.human_idle(kind=kind, dur_ms=perf.elapsed_ms(t0))
        self._end_attempt(decision, calls, "accepted")
        decision["result"] = resp
        decision["committed"] = True
        # Post-result commit: the accepted action is durable before it is applied.
        self._checkpoint()
        return resp

    def submit(self, resp: dict):
        if not self.pending or not isinstance(resp, dict):
            return False
        kind, data = self.pending["kind"], self.pending["data"]
        if kind == "conjecture":
            try:
                self.conjecture_ledger.validate_human(resp)
            except (ValueError, TypeError, KeyError):
                return False
        elif kind == "ready":
            if resp.get("ready") is not True:
                return False
        elif kind == "model_retry":
            if type(resp.get("retry")) is not bool:
                return False
        elif kind in ("speech", "table_reply"):
            if not isinstance(resp.get("text"), str) or len(resp["text"]) > 4000:
                return False
        elif kind == "table_answer":
            # Answer (non-empty text) or explicit skip; anything else is invalid.
            if resp.get("skip") is True:
                pass
            elif not (isinstance(resp.get("answer"), str) and resp["answer"].strip()
                      and len(resp["answer"]) <= 4000):
                return False
        elif kind in ("election_up", "election_withdraw"):
            if not isinstance(resp.get("up" if kind == "election_up" else "withdraw"), bool):
                return False
        else:
            candidates = {c["pos"] for c in data.get("candidates", [])}
            if kind == "night" and data.get("role_key") == "witch":
                save, poison = resp.get("save"), resp.get("poison")
                save_candidates = {c["pos"] for c in data.get("save_candidates", [])}
                if save is not None and (type(save) is not int or save not in save_candidates or not data.get("antidote")):
                    return False
                if poison is not None and (type(poison) is not int or poison not in candidates or not data.get("poison")):
                    return False
                if save is not None and poison is not None and not self.engine.witch_dual:
                    return False
            else:
                target = resp.get("target")
                if target is not None and (type(target) is not int or target not in candidates):
                    return False
                if kind == "vote" and target is None:
                    return False
        self.pending = None
        self._pending_event_no = None
        self.q.put_nowait(resp)
        return True

    # ---------------- 主循环 / 断线重连 ----------------
    def ensure_game_task(self):
        """Start the game loop exactly once.  The game task owns the session's
        lifetime: a closed SSE stream no longer ends the game — it keeps running
        while blocked on ``ask_player`` until gameover or an explicit abandon."""
        if self._game_task_ref is None or self._game_task_ref.done():
            self._game_task_ref = asyncio.create_task(self._game_task())
        return self._game_task_ref

    def abandon(self):
        """Explicit leave/abandon: end the game without waiting for a stream."""
        self._abandoned = True
        self.finished = True
        self.pending = None
        self._pending_event_no = None
        self.event_q.put_nowait(_SENTINEL)
        if self._game_task_ref is not None and not self._game_task_ref.done():
            self._game_task_ref.cancel()
        self.perf_recorder.flush()

    async def events(self, after: int = 0):
        """Yield events with ``event_no > after``, then live until the end.

        Catch-up reads the retained event ledger (idempotent, so a reattaching
        client neither misses nor duplicates an event); the live tail drains the
        queue the game task fills.  Closing this consumer does *not* cancel the
        game task — reattach is supported until the game ends or is abandoned.
        """
        self.ensure_game_task()
        seen = after
        for ev in list(self._events):
            if ev["event_no"] > seen:
                yield ev
                seen = ev["event_no"]
        while True:
            item = await self.event_q.get()
            if item is _SENTINEL:
                break
            if item["event_no"] > seen:
                yield item
                seen = item["event_no"]

    async def run(self, after: int = 0):
        """SSE view; ``after`` joins the stream at that event number (reattach)."""
        async for item in self.events(after=after):
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    def recovery_view(self, last_event_no: int = 0) -> dict:
        """Player-scoped recovery payload (§6): the init the player received,
        their own private results, the numbered public events for catch-up, and
        the current pending action — plus the event number where the live stream
        rejoins (no missing, no duplicate).

        ``public_events`` is the public transcript (numbered); ``private_events``
        is only this seat's own ``private`` result lines, re-renderable as text.
        Nothing here can leak another seat's private data — it is all read from
        the single human seat's own view.
        """
        public_events = [
            row["event"] for row in self.public_record.entries
            if (row["event"].get("event_no") or 0) > last_event_no
        ]
        private_events = [
            e for e in self._events
            if e.get("event_no", 0) > last_event_no and e.get("type") == "private"
        ]
        pending = None
        if self.pending is not None:
            pending = {"type": "request", "kind": self.pending["kind"],
                       "data": self.pending["data"],
                       "event_no": self._pending_event_no}
        # End-of-game signals (public only: winner/reason/review/error) so a
        # reattaching client can render the final result after a finished game.
        terminal = [e for e in self._events
                    if e.get("event_no", 0) > last_event_no
                    and e.get("type") in ("gameover", "review", "error")]
        private = None
        if self.engine.seats:
            private = self.engine.player_view()
        # Review status (§1/§7): "finished" alone means the winner is decided, not
        # that the result stream is fully received.  A reattaching client must be
        # able to distinguish "review pending" (crash before review ran) from
        # "review done/unavailable" instead of treating finished as all-received.
        review_status = None
        if self.finished:
            reviews = [e for e in self._events if e.get("type") == "review"]
            if reviews:
                review_status = "unavailable" if reviews[-1].get("unavailable") else "done"
            else:
                review_status = "pending"
        return {
            "game_id": self.session_id,
            "finished": self.finished,
            "review_status": review_status,
            "counted": self.campaign_counted,
            "init": self._init_event,
            "private": private,
            "public_events": public_events,
            "private_events": private_events,
            "pending": pending,
            "terminal": terminal,
            "next_event_no": self._event_no + 1,
        }

    async def _game_task(self):
        # Re-entering the loop is the fault -> in_progress transition: a retry in
        # the *same* process (no restore()) must not stay stuck in the "faulted"
        # terminal view after it eventually ends.
        self.faulted = False
        try:
            await self._play()
            # Normal endgame: _step_endgame already set finished=True.  Clear the
            # now-stale prompt so a finished game shows no pending action.
            self.pending = None
            self._pending_event_no = None
        except ModelTurnError:
            self._fault(
                "Model decision failed, timed out or exceeded budget. The game is paused — fix the connection and rejoin to continue; no offline substitution."
                if self.engine.locale == "en" else
                "模型决策失败、超时或调用额度耗尽。对局已暂停，请检查连接后重连继续；未切换离线玩家。")
        except Exception:
            logging.getLogger(__name__).exception("Game session failed")
            self._fault(
                "The game paused due to an unexpected error; rejoin to continue or abandon this game."
                if self.engine.locale == "en" else
                "对局因意外错误暂停；可重连继续，或放弃本局。")
        finally:
            self.event_q.put_nowait(_SENTINEL)
            # Persist the paused/faulted state (or the finished flag) so a restart
            # resumes the exact position.  Skipped on abandon: the caller removes
            # the save, and a finalizer must not resurrect it.
            if not self._abandoned:
                self._checkpoint()

    def _fault(self, text: str) -> None:
        """Mark a recoverable fault (§3.3): pause, keep the resume position and
        pending action, and do NOT finish — a fault is neither a loss nor a
        settlement trigger."""
        self.faulted = True
        self.emit({"type": "error", "text": text})

    @property
    def terminal_state(self) -> str:
        """Session-level attempt state (CAMPAIGN_DESIGN §3.3).

        Only ``ended`` (normal endgame) and ``abandoned`` end the attempt.
        ``faulted`` and ``paused`` are resumable and must not settle.  The
        archive-level ``preparing`` / ``in_progress`` live in the campaign
        archive, not here.
        """
        if self._abandoned:
            return "abandoned"
        if self.faulted:
            return "faulted"
        if self.finished:
            return "ended"
        if self.pending is not None:
            return "paused"
        return "in_progress"

    async def _npc_call(self, call, *args, action=None, **kwargs):
        if self.planner is None:
            return call(*args, **kwargs)
        agent = getattr(call, "__self__", None)
        name = agent.name if agent is not None else "?"
        # The decision identity must name the *concrete action*, not just the
        # step + actor: within one election an agent 上警/发言/退警/投票, and the
        # stone ghost acts twice a night.  A method-name default is unambiguous
        # for speak/vote/table_*; callers that repeat one method per step pass an
        # explicit ``action`` (election_up/election_withdraw/stone_ghost/…).
        act = action if action is not None else getattr(call, "__name__", "call")
        if not isinstance(act, str):
            act = "call"
        slot = f"{self._current_step}:{self._slot_instance()}:{name}:{act}"
        replayed = self._replay_decision(slot)
        if replayed is not None:
            # Committed decision reused verbatim — no new call, no budget.
            return replayed["result"]
        decision = self._open_decision(slot)
        # Perf metadata (privacy-safe: seat position only, never name/role).
        seat_pos = agent.seat.pos if agent is not None and getattr(agent, "seat", None) is not None else None
        backend = getattr(self.planner, "backend", None)
        model = getattr(self.planner, "model", None)
        effort = getattr(self.planner, "effort", None)
        while True:
            memory = getattr(agent, "model_decisions", [])
            checkpoint = len(memory)
            calls_before = getattr(self.planner, "calls", 0)
            self._begin_attempt(decision, calls_before)
            # Reserve the budget *before* the pre-call checkpoint: the external
            # request may still fail or the process may crash, but the consumed
            # attempt must survive a restore.  ``complete()`` no longer reserves.
            reserve = getattr(self.planner, "reserve", None)
            if reserve is not None:
                reserve()
            # Pre-call reservation: state-before-call + attempt are durable
            # before the external request goes out.
            self._checkpoint()
            t0 = perf.now()
            try:
                result = await asyncio.to_thread(call, *args, **kwargs)
            except ModelTurnError:
                del memory[checkpoint:]
                self._end_attempt(decision, getattr(self.planner, "calls", 0), "error")
                self._checkpoint()
                self.perf_recorder.decision(
                    decision_no=decision["decision_no"], step=self._current_step,
                instance=self._slot_instance(), seat=seat_pos,
                    kind=act, attempt_no=len(decision["attempts"]), backend=backend,
                    model=model, effort=effort, calls_before=calls_before,
                    calls_after=getattr(self.planner, "calls", 0), outcome="error",
                    dur_ms=perf.elapsed_ms(t0))
                self.emit({"type": "narration", "text": (
                    "Model response failed. Game paused without substituting a local player. Retry after checking the connection, or stop. Budget limits still apply."
                    if self.engine.locale == "en" else "模型响应失败，对局已暂停，未替换为离线玩家。检查连接后可重试，或结束本局；调用上限仍有效。")})
                response = await self.ask_player("model_retry", {})
                if not response["retry"]:
                    raise ModelTurnError("Player stopped after model failure.") from None
                continue
            self._end_attempt(decision, getattr(self.planner, "calls", 0), "accepted")
            decision["result"] = result
            decision["committed"] = True
            self.perf_recorder.decision(
                decision_no=decision["decision_no"], step=self._current_step,
                instance=self._slot_instance(), seat=seat_pos,
                kind=act, attempt_no=len(decision["attempts"]), backend=backend,
                model=model, effort=effort, calls_before=calls_before,
                calls_after=getattr(self.planner, "calls", 0), outcome="accepted",
                dur_ms=perf.elapsed_ms(t0))
            # Post-result commit: the accepted result is durable before the
            # engine applies it in the calling step.
            self._checkpoint()
            return result

    async def _play(self):
        """Run the game as an explicit state machine.

        Each ``_step_*`` method is a small, resumable unit driven by the
        ``_step`` cursor.  Loop-local values that must cross a step boundary
        (night actions, the night's resolved events) travel through
        ``_step_state``.  This is the seam where phase 3 hangs checkpoint
        writes (pre-call reservation + local atomic commit).

        A restored session enters with its ``_step`` cursor already set; a
        fresh session (undealt engine, no cursor) starts at ``setup``.  A turn
        boundary checkpoint is written before each step so the common refresh
        case resumes from the last committed step.
        """
        if self._step is None and not self.finished:
            if not self.engine.seats:
                self._step = "setup"
                self._step_state = {}
            elif self._current_step and self._current_step != "endgame":
                # Mid-step crash: dispatching the step cleared ``_step`` but the
                # crashed step is still recorded.  Re-dispatch it and replay its
                # committed decisions (see ``_replay_decision``) instead of
                # halting or re-running the whole step from scratch.
                self._resume_step = self._current_step
                self._replay_committed = [
                    d for d in self.decision_log
                    if d.get("committed")
                    and self._slot_step(d.get("slot")) == self._current_step
                ]
                self._replay_cursor = 0
                self._step = self._current_step
        while self._step is not None:
            self._checkpoint()
            step, self._step = self._step, None
            self._current_step = step
            if self._resume_step is not None and step != self._resume_step:
                # The resumed step finished; stop replaying its committed
                # decisions (a later normal occurrence of the same step name
                # must not reuse a stale replay queue).
                self._resume_step = None
                self._replay_committed = []
                self._replay_cursor = 0
            handler = getattr(self, f"_step_{step}", None)
            if handler is None:
                raise RuntimeError(f"Unknown game step {step!r}")
            t0 = perf.now()
            await handler()
            self.perf_recorder.step(step=step, dur_ms=perf.elapsed_ms(t0))

    async def _step_setup(self):
        e = self.engine
        e.setup()
        if self.conjecture:
            from .game.conjecture import GameConjectures
            self.conjecture_ledger = GameConjectures(e)
        for s in e.seats.values():
            if not s.is_player:
                if self.planner is not None:
                    from .ai.model_player import ModelNPCAgent
                    self.agents[s.name] = ModelNPCAgent(
                        s.name, e, self.llm, memory_dir=self.memory_dir,
                        planner=self.planner, public_record=self.public_record,
                        recorder=self.perf_recorder)
                else:
                    self.agents[s.name] = StrategicNPCAgent(
                        s.name, e, self.llm, memory_dir=self.memory_dir)
        wolf_agents = sorted(
            (agent for agent in self.agents.values()
             if agent.is_wolf and agent.brain.role != "stone_ghost"),
            key=lambda agent: -(agent.style.bluff * 0.6 +
                                agent.style.aggression * 0.4),
        )
        for rank, agent in enumerate(wolf_agents):
            agent.assign_wolf_strategy(rank, len(wolf_agents))

        pv = e.player_view()
        host_intro = (("Host Raven: Welcome to the Night Teahouse. Take your seat; we will explain the rules before night one." if e.locale == "en" else
                       "主持人夜鸦：欢迎来到暗夜茶馆。请各位入座，先讲清规则，再开始第一夜。") if self.onboarding else
                      self.host.intro(board_display(e.locale, e.board)["name"], self._seats_desc()))
        self.emit({"type": "init", "state": e.public_state(), "player": pv,
                   "host_intro": host_intro,
                   "llm_status": self._model_status(),
                   "settings": {"medium": "text", "voice_available": False,
                                "visual_gameplay_available": False, "conjecture": self.conjecture,
                                "npc_driver": self._model_status().get("backend", "model") if self.planner is not None else "legacy_rules"}})
        self._remember_llm_status()
        self._step = "onboarding" if self.onboarding else "witch_rule"

    async def _step_onboarding(self):
        e = self.engine
        from .onboarding import introduction
        e.phase = "onboarding"
        self.emit({"type": "narration", "phase": "onboarding",
                   "text": introduction(e, self.conjecture)})
        await self.ask_player("ready", {})
        self._step = "witch_rule"

    async def _step_witch_rule(self):
        e = self.engine
        if e.witch_unlimited:
            self.emit({"type": "narration", "text": witch_rule_text(e.locale, e.board)})
        self._step = "night"

    async def _step_night(self):
        e = self.engine
        if e.check_round_limit():
            self.emit({"type": "narration", "text": e.end_reason})
            self._step = "endgame"
            return
        # The night prologue (night_start narration + start_night) is guarded so
        # a mid-step resume re-enters gather without re-incrementing night_count
        # or re-announcing nightfall.
        if not self._step_state.get("night_started"):
            self.emit({"type": "narration", "phase": "night", "text": self.host.narrate("night_start", "")})
            await asyncio.sleep(0.3)
            requests = e.start_night()
            self._deliver_grave_result()
            self._step_state["night_started"] = True
            self._step_state["night_requests"] = requests
            self._step_state["gather_actions"] = {}
            self._step_state["gather_cursor"] = 0
            self._checkpoint()
        requests = self._step_state.get("night_requests", [])
        actions = await self._gather_night(requests)
        self._step_state["actions"] = actions
        for key in ("night_started", "night_requests"):
            self._step_state.pop(key, None)
        self._step = "resolve_night"

    async def _step_resolve_night(self):
        e = self.engine
        # Settlement is applied exactly once.  ``night_events`` in ``_step_state``
        # is the execution-position marker: a mid-step resume (e.g. a crash while
        # the hunter death-skill prompt is open, which checkpoints) re-enters here
        # and must not re-pop ``actions`` nor re-apply ``resolve_night``.
        night_events = self._step_state.get("night_events")
        if night_events is None:
            actions = self._step_state.pop("actions")
            night_events = e.resolve_night(actions)
            self._step_state["night_events"] = night_events
            for ev in night_events:
                await self._emit_event(ev)
            # Commit the whole settlement batch (engine state + every event)
            # atomically before publishing: a resume after a crash either replays
            # the full batch or skips it wholesale — never a torn half-batch.
            self._commit_batch()
        await self._post_death_triggers()
        if e.check_win():
            self.emit({"type": "narration", "text": self.host.narrate("win", e.end_reason)})
            self._step = "endgame"
            return
        if e.player_seat().role == "seer":
            for r in e.seer_results:
                if r["night"] == e.night_count:
                    self.emit({"type": "private",
                               "text": t(self.engine.locale, "seer_result",
                                         n=r["night"], target=r["target"],
                                         name=r["name"],
                                         result=t(self.engine.locale, "result_wolf" if r["result"] == "wolf" else "result_good"))})
        if e.player_seat().role == "stone_ghost":
            for r in e.sg_results:
                if r["night"] == e.night_count:
                    self.emit({"type": "private",
                               "text": t(self.engine.locale, "sg_result",
                                         n=r["night"], target=r["target"],
                                         name=r["name"], role=r["role_cn"])})
        await asyncio.sleep(0.4)
        self._step = "day_start"

    async def _step_day_start(self):
        e = self.engine
        night_events = self._step_state.pop("night_events", [])
        e.start_day()
        self._reset_table_talk()
        self.emit({"type": "narration", "phase": "day", "text": self.host.narrate("day_start", t(self.engine.locale, "day_start", d=e.day_count))})
        if not any(ev.type == "death" for ev in night_events):
            self.emit({"type": "narration", "text": "Host Raven: No one died last night." if e.locale == "en" else "主持人夜鸦：昨夜平安，无人死亡。"})
        await asyncio.sleep(0.3)
        if e.day_count == 1:
            self._step = "election"
        elif self.conjecture:
            self._step = "conjecture_pre"
        else:
            self._step = "speeches"

    async def _step_election(self):
        await self._election()
        self.engine.phase = "day"
        if self.conjecture:
            self._step = "conjecture_pre"
        else:
            self._step = "speeches"

    async def _step_conjecture_pre(self):
        await self._conjecture_round()
        self._step = "speeches"

    async def _step_speeches(self):
        e = self.engine
        order = e.speech_order()
        # ``speech_events``/``player_last_speech`` are instance fields restored
        # from the snapshot; they are only reset on a *fresh* step (a mid-step
        # resume re-enters mid-loop with the accumulated speeches intact).
        if self._resume_step != "speeches":
            self.speech_events = []
            self.player_last_speech = ""
        start = self._step_state.get("speeches_cursor", 0) if self._resume_step == "speeches" else 0
        for i in range(start, len(order)):
            pos = order[i]
            seat = e.seat_at(pos)
            if not seat.alive:
                continue
            await self._day_skill(seat)
            if e.check_win() or e.phase == "night":
                break
            if not seat.alive:
                continue
            if seat.is_player:
                resp = await self.ask_player("speech", {"phase": t(self.engine.locale, "phase_day", n=e.day_count)})
                text = resp.get("text", "").strip()
                self.player_last_speech = text
                speech = self._player_speech(text)
            else:
                speech = await self._npc_call(self.agents[seat.name].speak,
                    self.speech_events, self.player_last_speech)
                text = speech.text
                self._emit_llm_status_if_changed()
            self.speech_events.append((seat.name, speech))
            self._broadcast_speech(seat, speech)
            e.record_speech(
                pos, text, phase="day", claim=speech.claim,
                accuse=speech.accuse, defend=speech.defend,
            )
            self._step_state["speeches_cursor"] = i + 1
            # Durability before visibility: the speech event, the cursor and the
            # agent/engine mutations commit atomically before the speech reaches
            # the live queue — a crash here loses nothing the player already saw,
            # and a resume re-enters at the next seat instead of re-emitting.
            self.emit({"type": "speech", "seat": pos, "name": seat.name, "text": text,
                       "phase": "day"}, publish=False)
            self._checkpoint()
            self._flush_publish()
            await asyncio.sleep(0.3)
            await self._maybe_table_talk(seat, speech)
            self._checkpoint()

        self._step_state.pop("speeches_cursor", None)
        if e.check_win():
            self.emit({"type": "narration", "text": self.host.narrate("win", e.end_reason)})
            self._step = "endgame"
            return
        if e.phase == "night":
            self.emit({"type": "narration", "text": t(e.locale, "skill_ends_day")})
            self._step = "night"
            return
        self._step = "day_wrap"

    async def _step_day_wrap(self):
        e = self.engine
        await self._answer_table_questions()
        for seat in e.alive_seats():
            if seat.role == "crow":
                await self._day_skill(seat, crow=True)

        rule = self.host.maybe_invent_rule(e)
        if rule:
            self.emit({"type": "host_rule", "text": rule})

        if self.conjecture:
            # A second snapshot lets the human revise after discussion.
            self._step = "conjecture_post"
        else:
            self._step = "vote"

    async def _step_conjecture_post(self):
        await self._conjecture_round()
        self._step = "vote"

    async def _step_vote(self):
        e = self.engine
        await self._vote_phase()
        await self._post_death_triggers()
        # The vote (and its death-trigger chain) is fully settled; drop the
        # execution-position marker so the *next* day's vote runs fresh.
        self._step_state.pop("vote_settled", None)

        if e.check_win():
            self.emit({"type": "narration", "text": self.host.narrate("win", e.end_reason)})
            self._step = "endgame"
            return
        self._step = "night"

    async def _step_endgame(self):
        e = self.engine
        reveal = "\n".join(f"#{s.pos} {s.name}: {s.role_cn}" for s in sorted(e.seats.values(), key=lambda s: s.pos))
        # 1) Commit the normal endgame atomically, *before* any review runs: the
        #    winner/reason, the final-role reveal and finished=True are durable
        #    first.  A review failure (or a crash mid-review) must never leave a
        #    finished game looking unfinished (CAMPAIGN_DESIGN §1 / §7).
        self.emit({"type": "gameover", "winner": e.winner, "reason": e.end_reason})
        self.emit({"type": "narration",
                   "text": ("Final roles\n" if e.locale == "en" else "最终身份\n") + reveal})
        self.finished = True
        self._step = None
        self._checkpoint()
        # 2) Campaign post-loss short review (§7): generated exactly once here,
        #    after the game settled and *before* the host review, so a Web SSE
        #    client receives it in order.  Guarded by the durable
        #    ``campaign_review_state`` — a restore never re-triggers it, only an
        #    explicit retry does.
        if self.campaign_profile:
            from . import campaign_flow
            campaign_flow.generate_review_once(self)
        # 3) The model review is a separate, retryable step after the commit.
        await self._write_review(reveal)
        self.perf_recorder.flush()

    async def _write_review(self, reveal: str):
        """Generate and publish the post-game review, retryably.

        Runs *after* the endgame commit: a failure here leaves the game finished
        and settled, emits a fallback marker, and can be retried later — it never
        re-faults or un-finishes the game.
        """
        e = self.engine
        try:
            perf = self._npc_performances()
            review = self.host.review(e, perf)
            self.host.evolve(e, review)
            for a in self.agents.values():
                a.save_memory()
            review += "\n\n" + self.public_record.query("/history")
            self.emit({"type": "review", "text": review, "winner": e.winner})
        except Exception:
            logging.getLogger(__name__).exception("Endgame review failed")
            self.emit({"type": "review",
                       "text": ("The review is temporarily unavailable; retry later."
                                if e.locale == "en" else "复盘暂不可用，可稍后重试。"),
                       "winner": e.winner, "unavailable": True})
        self._checkpoint()

    async def _conjecture_round(self):
        ledger = self.conjecture_ledger
        drafts = ledger.npc_drafts(self.agents)
        if self.engine.player_seat().alive:
            response = await self.ask_player("conjecture", ledger.human_request())
            drafts[self.engine.player_seat().name] = ledger.validate_human(response)
        published = ledger.publish(drafts, self.agents)
        self.emit({"type": "conjecture", "tables": published,
                   "history": ledger.public_history(), "labels": dict(ledger.labels)})

    def _player_speech(self, text: str) -> Speech:
        """Extract only explicit public claims/targets from human text."""
        claim = None
        question_to = None
        # Addressed clauses, not merely the first seat mentioned in a paragraph.
        # No model is allowed to rewrite or manufacture the human's statement.
        if self.planner is not None:
            for clause in re.split(r"[。！？!?；;]|另外|also", text, flags=re.I):
                if not re.search(r"怎么|为什么|凭什么|为何|请问|解释|why|how|explain", clause, re.I):
                    continue
                match = re.search(r"(?<!\d)(\d+)\s*号|#\s*(\d+)\b|(?:seat|player)\s+(\d+)\b", clause, re.I)
                if match:
                    pos = int(next(g for g in match.groups() if g is not None))
                    target = next((s for s in self.engine.alive_seats() if s.pos == pos and not s.is_player), None)
                    if target:
                        pair = [target.name, self.engine.player_seat().name]
                        if pair not in self._pending_questions:
                            self._pending_questions.append(pair)
        if re.search(r"验|查验|check|result", text, re.I) and re.search(r"吗|呢|谁|不说|报出来|请|[?？]|who|which|why|please", text, re.I):
            for seat in self.engine.alive_seats():
                if not seat.is_player and (re.search(rf"(?<!\d){seat.pos}\s*号|#\s*{seat.pos}\b|(?:seat|player)\s+{seat.pos}\b", text, re.I) or seat.name.casefold() in text.casefold()):
                    question_to = seat.name
                    break
        if self.engine.locale == "en":
            lower = text.casefold().replace("’", "'")
            for key in ("seer", "witch", "hunter", "guard"):
                label = r"(?:divine )?witch" if key == "witch" else key
                if re.search(rf"\bi(?: am|'m) (?:the |a )?{label}\b", lower):
                    claim = key
                    break
            accuse = defend = None
            for seat in self.engine.alive_seats():
                if seat.is_player:
                    continue
                target = rf"(?:#\s*{seat.pos}\b|\b(?:seat|player)\s+{seat.pos}\b|\b{re.escape(seat.name.casefold())}\b)"
                if (re.search(rf"\b(?:suspect|accuse|vote for|exile)\s+{target}", lower)
                        or re.search(rf"{target}\s+is (?:a |the )?(?:wolf|werewolf)\b", lower)):
                    accuse = seat.name
                if (re.search(rf"\b(?:trust|defend|clear)\s+{target}", lower)
                        or re.search(rf"{target}\s+is (?:good|innocent)\b", lower)):
                    defend = seat.name
            return Speech(text=text, claim=claim, accuse=accuse, defend=defend, question_to=question_to)
        for role, role_name in (("seer", "预言家"), ("witch", "女巫"),
                                ("hunter", "猎人"), ("guard", "守卫")):
            if f"我是{role_name}" in text.replace(" ", "") or (role == "witch" and "我是神女巫" in text.replace(" ", "")):
                claim = role
                break
        accuse = defend = None
        compact = text.replace(" ", "")
        for seat in self.engine.alive_seats():
            if seat.is_player or f"{seat.pos}号" not in compact:
                continue
            if re.search(rf"(?:怀疑|投|出|踩|查杀|狼).{{0,8}}{seat.pos}号", compact) or \
               re.search(rf"{seat.pos}号.{{0,8}}(?:是狼|查杀|有问题)", compact):
                accuse = seat.name
                break
            if re.search(rf"(?:保|金水|好人|站).{{0,8}}{seat.pos}号", compact):
                defend = seat.name
                break
        return Speech(text=text, claim=claim, accuse=accuse, defend=defend, question_to=question_to)

    def _broadcast_speech(self, seat, speech: Speech):
        # Queue the question whether it targets an NPC or the human player, as an
        # order-preserving [target, asker] pair.  Distinct askers of one target are
        # both kept (never silently overwritten); a duplicate pair is idempotent.
        if speech.question_to:
            pair = [speech.question_to, seat.name]
            if pair not in self._pending_questions:
                self._pending_questions.append(pair)
        # Every call site emits the speech immediately after this broadcast, so
        # ``event_no + 1`` is the event number that speech will receive; pass it
        # so a dispute can reference the *exact* statement by ledger number.
        event_no = self._event_no + 1
        for agent in self.agents.values():
            agent.observe_speech(self.engine.day_count, seat.name, speech, event_no)

    async def _answer_table_questions(self):
        """A bounded public clarification window after ordered speeches.

        NPCs and the human player both answer.  A question is removed from the
        pending set — and the answer budget spent — only *after* its reply (or an
        explicit skip) is committed.  The in-flight question is recorded in
        ``_step_state["answering_question"]`` before the call, so a crash before
        the commit re-asks it on resume instead of dropping it permanently.

        The human's reply is persisted before it is published (``_publish_table_speech``
        checkpoints first) and a duplicate submit of the same request is a no-op,
        so the same reply is never posted twice.  A skip publishes nothing and
        consumes no model budget, but it does spend one clarification opportunity
        — the ``_questions_answered`` cap keeps the window bounded.
        """
        player_name = self.engine.player_seat().name
        for pair in list(self._pending_questions):
            target, asker = pair
            if self._questions_answered >= 2:
                # Budget spent: drop the rest durably and move on.
                self._pending_questions.remove(pair)
                self._step_state.pop("answering_question", None)
                self._checkpoint()
                continue
            if target == player_name:
                await self._answer_human_question(pair, asker)
                continue
            agent = self.agents.get(target)
            if not agent or not agent.seat.alive:
                # Unanswerable: drop it durably and move on.
                self._pending_questions.remove(pair)
                self._step_state.pop("answering_question", None)
                self._checkpoint()
                continue
            # Announce on first entry only (a resume re-enters mid-question with
            # the marker already set, skips the announcement, and re-asks through
            # the decision replay path).
            if self._step_state.get("answering_question") != [target, asker]:
                self.emit({"type": "narration", "text":
                           (f"Host: Before voting, {target}, answer {asker}'s question. This is a claim, not a host-verified result." if self.engine.locale == "en" else
                            f"主持人：投票前请 {target} 回答 {asker} 的追问。这是玩家口径，不代表主持人认证。")},
                          publish=False)
            self._step_state["answering_question"] = [target, asker]
            self._checkpoint()
            self._flush_publish()
            response = await self._npc_call(agent.table_reply, asker) if self.planner is not None else agent.brain.answer_check_question()
            # Commit the reply and the question bookkeeping atomically: apply the
            # budget/question mutations *before* ``_publish_table_speech``, whose
            # checkpoint persists the spent budget, the answered question and the
            # reply together, then publishes once.
            self._questions_answered += 1
            self._pending_questions.remove(pair)
            self._step_state.pop("answering_question", None)
            await self._publish_table_speech(agent.seat, response, "clarification")

    async def _answer_human_question(self, pair, asker):
        """Ask the human to answer a public clarification (answer or skip).

        Answering publishes a table speech (persisted before visible); skipping
        publishes nothing and consumes no model budget, but spends one
        clarification opportunity so a player cannot stall the window forever.
        """
        target, _asker = pair
        player = self.engine.player_seat()
        if not player.alive:
            self._pending_questions.remove(pair)
            self._step_state.pop("answering_question", None)
            self._checkpoint()
            return
        if self._step_state.get("answering_question") != [target, asker]:
            self.emit({"type": "narration", "text": (
                f"Host: Before voting, you are asked to answer {asker}'s question. This is a claim, not a host-verified result." if self.engine.locale == "en" else
                f"主持人：投票前，请你回答 {asker} 的追问。这是玩家口径，不代表主持人认证。")},
                publish=False)
        self._step_state["answering_question"] = [target, asker]
        self._checkpoint()
        self._flush_publish()
        response = await self.ask_player("table_answer", {"from": asker})
        self._questions_answered += 1
        self._pending_questions.remove(pair)
        self._step_state.pop("answering_question", None)
        if response.get("skip"):
            self._checkpoint()
            return
        text = (response.get("answer") or "").strip()
        if not text:
            self._checkpoint()
            return
        speech = self._player_speech(text)
        await self._publish_table_speech(player, speech, "clarification")

    def _reset_table_talk(self):
        self._table_extra_turns = 0
        self._table_extra_by_name = {}
        self._table_pairs = set()
        self._pending_questions = []
        self._questions_answered = 0
        self._table_cooldown = False

    async def _publish_table_speech(self, seat, speech: Speech, kind: str):
        """One public, ledgered extra utterance; it is never a hidden chat."""
        self.speech_events.append((seat.name, speech))
        self._broadcast_speech(seat, speech)
        self.engine.record_speech(
            seat.pos, speech.text, phase="table_talk", talk_kind=kind,
            claim=speech.claim, accuse=speech.accuse, defend=speech.defend,
        )
        self._table_extra_turns += 1
        self._table_extra_by_name[seat.name] = self._table_extra_by_name.get(seat.name, 0) + 1
        # Durability before visibility: the table speech and its counters persist
        # before the event reaches the live queue.
        self.emit({"type": "speech", "seat": seat.pos, "name": seat.name,
                   "text": speech.text, "table_talk": True, "phase": "table_talk"}, publish=False)
        self._checkpoint()
        self._flush_publish()
        await asyncio.sleep(0.25)

    async def _maybe_table_talk(self, source, source_speech: Speech):
        """Let the host allow a bounded public interruption after a main turn."""
        if self._table_cooldown:
            self._table_cooldown = False
            return
        if self._table_extra_turns >= 3 or source_speech.question_to:
            return
        # Most free chat follows a public point; a small fraction is social
        # colour around an otherwise neutral statement.
        if not (source_speech.accuse or source_speech.defend or source_speech.claim) \
                and self.engine.rng.random() > 0.16:
            return

        contenders = []
        for agent in self.agents.values():
            seat = agent.seat
            if not seat.alive or seat.name == source.name:
                continue
            if self._table_extra_by_name.get(seat.name, 0) >= 2:
                continue
            interest = agent.table_interruption_interest(source.name, source_speech)
            contenders.append((interest, seat.pos, agent))
        if not contenders:
            return
        interest, _pos, interrupter = max(contenders, key=lambda item: (item[0], -item[1]))
        if self.engine.rng.random() > interest:
            return

        pair = frozenset((source.name, interrupter.name))
        repeated_pair = pair in self._table_pairs
        opening = self.host.moderate_table_talk(
            topic_turns=1, extra_turns=self._table_extra_turns,
            speaker_extra_turns=self._table_extra_by_name.get(interrupter.name, 0),
            repeated_pair=repeated_pair,
        )
        if opening:
            self.emit({"type": "narration", "text": opening})
            return

        interruption = await self._npc_call(interrupter.table_interject, source.name, source_speech)
        self._table_cooldown = True
        self._table_pairs.add(pair)
        await self._publish_table_speech(interrupter.seat, interruption, "interrupt")

        if self._table_extra_turns >= 3:
            self.emit({"type": "narration", "text": "Host: Continue in speaking order." if self.engine.locale == "en" else "主持人：继续按顺序发言。"})
            return

        # The original speaker may give exactly one short reply.  This keeps
        # the interaction human, while the host closes it before it becomes a
        # private two-person debate.
        closing = self.host.moderate_table_talk(
            topic_turns=2, extra_turns=self._table_extra_turns,
            speaker_extra_turns=self._table_extra_by_name.get(source.name, 0),
            repeated_pair=False,
        )
        if closing:
            self.emit({"type": "narration", "text": closing})
            return
        if source.is_player:
            response = await self.ask_player("table_reply", {
                "from": interrupter.name,
                "text": interruption.text,
            })
            text = response.get("text", "").strip()
            if not text:
                self.emit({"type": "narration", "text": "Host: Continue in speaking order." if self.engine.locale == "en" else "主持人：继续按顺序发言。"})
                return
            reply = self._player_speech(text)
        else:
            reply = await self._npc_call(self.agents[source.name].table_reply, interrupter.name)
        await self._publish_table_speech(source, reply, "reply")
        closing = self.host.moderate_table_talk(
            topic_turns=3, extra_turns=self._table_extra_turns,
            speaker_extra_turns=self._table_extra_by_name.get(source.name, 0),
            repeated_pair=True,
        )
        if closing:
            self.emit({"type": "narration", "text": closing})

    def _remember_llm_status(self):
        state = self._model_status()
        self._last_llm_status = (state["mode"], state.get("reason", ""))

    def _emit_llm_status_if_changed(self):
        state = self._model_status()
        marker = (state["mode"], state.get("reason", ""))
        if marker != self._last_llm_status:
            self.emit({"type": "llm_status", "llm_status": state})
            self._last_llm_status = marker

    def _model_status(self):
        return self.planner.public_status() if self.planner is not None else self.llm.public_status()

    # ---------------- 夜晚 ----------------
    async def _gather_night(self, requests) -> dict:
        e = self.engine
        prio = {"seer": 0, "wolves": 1, "witch": 2, "guard": 3,
                "stone_ghost_kill": 1, "wolf_beauty": 4, "stone_ghost": 5}
        requests = sorted(requests, key=lambda r: prio.get(r[0], 9))
        # Mid-step resume: the accumulated per-actor actions (and the knife the
        # witch is told about) survive in ``_step_state`` so a re-run continues
        # at the first actor not yet gathered instead of re-asking everyone.
        resuming = self._resume_step == "night"
        actions = self._step_state.get("gather_actions", {}) if resuming else {}
        knife = actions.get("wolves", actions.get("stone_ghost_kill", {})).get("target") \
            if resuming else None
        start = self._step_state.get("gather_cursor", 0) if resuming else 0
        for i in range(start, len(requests)):
            actor, pos = requests[i]
            if actor == "seer":
                actions["seer"] = await self._seer_action()
            elif actor == "wolves":
                res = await self._wolves_action()
                actions["wolves"] = res
                knife = res.get("target")
            elif actor == "witch":
                actions["witch"] = await self._witch_action(knife)
            elif actor == "guard":
                actions["guard"] = await self._guard_action()
            elif actor == "wolf_beauty":
                actions["wolf_beauty"] = await self._beauty_action()
            elif actor == "stone_ghost":
                actions["stone_ghost"] = await self._sg_action()
            elif actor == "stone_ghost_kill":
                res = await self._sg_kill_action()
                actions[actor] = res
                knife = res.get("target")
            self._step_state["gather_actions"] = actions
            self._step_state["gather_cursor"] = i + 1
            self._checkpoint()
        self._step_state.pop("gather_actions", None)
        self._step_state.pop("gather_cursor", None)
        return actions

    def _alive_others(self, exclude_name: str) -> list[int]:
        return [s.pos for s in self.engine.alive_seats() if s.name != exclude_name]

    async def _seer_action(self):
        e = self.engine
        seer = next(s for s in e.seats.values() if s.role == "seer")
        cands = self._alive_others(seer.name)
        if seer.is_player:
            resp = await self.ask_player("night", {"role_key": "seer",
                "role": role_name(self.engine.locale, "seer", "预言家"),
                "desc": t(self.engine.locale, "seer_check"),
                "candidates": [{"pos": p, "name": e.seat_at(p).name} for p in cands]})
            return {"target": resp.get("target")}
        return await self._npc_call(self.agents[seer.name].night_action, "seer", cands)

    async def _wolves_action(self):
        e = self.engine
        wolves = e.wolves()
        wolf_pos = {w.pos for w in wolves}
        # 全部存活玩家都可选 —— 含自刀（悍跳骗药/做金水/骗盲毒/倒钩卖队友等战术）
        all_alive = [s.pos for s in e.alive_seats()]
        tactic = t(e.locale, "wolf_tactic")
        if any(w.is_player for w in wolves):
            cands = []
            for p in all_alive:
                s = e.seat_at(p)
                if s.is_player:
                    note = t(e.locale, "note_self")
                elif p in wolf_pos:
                    note = t(e.locale, "note_mate")
                else:
                    note = ""
                cands.append({"pos": p, "name": s.name, "note": note})
            resp = await self.ask_player("night", {"role_key": "wolves",
                "role": role_name(self.engine.locale, "werewolf", "狼人"), "desc": tactic,
                "candidates": cands})
            return {"target": resp.get("target")}
        proposals = []
        for wolf in wolves:
            action = await self._npc_call(self.agents[wolf.name].night_action, "wolves", all_alive)
            if action.get("target") is not None:
                proposals.append((wolf, action["target"]))
        if not proposals:
            return {"target": None}
        tally = {}
        for _wolf, target in proposals:
            tally[target] = tally.get(target, 0) + 1
        highest = max(tally.values())
        tied = {target for target, count in tally.items() if count == highest}
        if len(tied) == 1:
            return {"target": next(iter(tied))}
        _decisive_wolf, target = max(
            ((wolf, target) for wolf, target in proposals if target in tied),
            key=lambda item: self.agents[item[0].name].style.aggression,
        )
        return {"target": target}

    async def _witch_action(self, knife):
        e = self.engine
        witch = next(s for s in e.seats.values() if s.role == "witch")
        if witch.is_player:
            cands = [{"pos": p, "name": e.seat_at(p).name} for p in self._alive_others(witch.name)]
            can_save = (e.witch_antidote and knife is not None
                        and (knife != witch.pos or e.night_count == 1))
            resp = await self.ask_player("night", {"role_key": "witch",
                "role": witch.role_cn,
                "desc": (t(self.engine.locale, "witch_knife", pos=knife) if knife is not None
                        else ("No player was attacked tonight." if e.locale == "en" else "今晚无人被刀。"))
                        + "\n" + witch_rule_text(e.locale, e.board), "candidates": cands,
                "save_candidates": [{"pos": knife, "name": e.seat_at(knife).name}] if can_save else [],
                "antidote": can_save, "poison": e.witch_poison,
                "dual_potions": e.witch_dual, "unlimited_potions": e.witch_unlimited})
            return {"save": resp.get("save"), "poison": resp.get("poison")}
        agent = self.agents[witch.name]
        return await self._npc_call(agent.night_action,
            "witch", self._alive_others(witch.name), knife=knife,
            antidote=e.witch_antidote, poison=e.witch_poison,
        )

    async def _guard_action(self):
        e = self.engine
        guard = next(s for s in e.seats.values() if s.role == "guard")
        cands = [s.pos for s in e.alive_seats() if s.pos != e.guard_last]
        if guard.is_player:
            resp = await self.ask_player("night", {"role_key": "guard", "role": guard.role_cn, "desc": t(e.locale, "guard_desc"),
                "candidates": [{"pos": p, "name": e.seat_at(p).name} for p in cands]})
            return {"target": resp.get("target")}
        return await self._npc_call(self.agents[guard.name].night_action, "guard", cands)

    async def _beauty_action(self):
        e = self.engine
        b = next(s for s in e.seats.values() if s.role == "wolf_beauty")
        cands = self._alive_others(b.name)
        if b.is_player:
            resp = await self.ask_player("night", {"role_key": "wolf_beauty", "role": b.role_cn,
                "desc": t(e.locale, "beauty_desc"),
                "candidates": [{"pos": p, "name": e.seat_at(p).name} for p in cands]})
            return {"target": resp.get("target")}
        return await self._npc_call(self.agents[b.name].night_action, "wolf_beauty", cands)

    async def _sg_action(self):
        e = self.engine
        sg = next(s for s in e.seats.values() if s.role == "stone_ghost")
        cands = self._alive_others(sg.name)
        if sg.is_player:
            resp = await self.ask_player("night", {"role_key": "stone_ghost", "role": sg.role_cn,
                "desc": t(e.locale, "sg_desc"),
                "candidates": [{"pos": p, "name": e.seat_at(p).name} for p in cands]})
            return {"target": resp.get("target")}
        return await self._npc_call(self.agents[sg.name].night_action, "stone_ghost", cands, action="stone_ghost")

    async def _sg_kill_action(self):
        e = self.engine
        sg = e._seat_of_role("stone_ghost")
        cands = self._alive_others(sg.name)
        if sg.is_player:
            resp = await self.ask_player("night", {
                "role_key": "stone_ghost_kill", "role": sg.role_cn,
                "desc": t(e.locale, "sg_kill_desc"),
                "candidates": [{"pos": p, "name": e.seat_at(p).name} for p in cands]})
            return {"target": resp.get("target")}
        return await self._npc_call(self.agents[sg.name].night_action, "wolves", cands, action="stone_ghost_kill")

    def _deliver_grave_result(self):
        e = self.engine
        if e.player_seat().role != "gravekeeper" or not e.player_seat().alive:
            return
        for result in e.grave_results:
            if result["night"] == e.night_count:
                self.emit({"type": "private", "text": t(e.locale, "grave_result",
                    n=result["night"], target=result["target"], name=result["name"],
                    result=t(e.locale, "result_" + result["result"]))})

    async def _day_skill(self, seat, crow=False):
        e = self.engine
        allowed = ("crow",) if crow else ("knight", "white_wolf_king")
        if not seat.alive or seat.role not in allowed or (seat.role == "knight" and e.knight_used):
            return
        candidates = [{"pos": p, "name": e.seat_at(p).name}
                      for p in self._alive_others(seat.name)]
        if not candidates:
            return
        if seat.is_player:
            response = await self.ask_player("day_skill", {
                "role_key": seat.role, "role": seat.role_cn,
                "desc": t(e.locale, seat.role + "_desc"), "candidates": candidates})
            target = response.get("target")
        else:
            agent = self.agents[seat.name]
            target = ((await self._npc_call(agent.night_action, seat.role, candidates)).get("target") if self.planner is not None else
                      agent.brain.day_skill([c["pos"] for c in candidates]).target)
        for event in e.resolve_day_skill(seat.pos, target):
            await self._emit_event(event)
        self._commit_batch()
        await self._post_death_triggers()

    # ---------------- 警长选举（仅第一天） ----------------
    async def _election(self):
        e = self.engine
        e.phase = "election"
        phase = self._step_state.get("election_phase", 0)

        # ---- Phase 0: 收集上警名单 ----
        if phase == 0:
            alive = e.alive_seats()
            up_positions = list(self._step_state.get("election_up", []))
            start = self._step_state.get("election_cursor", 0)
            for i in range(start, len(alive)):
                s = alive[i]
                if s.is_player:
                    resp = await self.ask_player("election_up", {})
                    if resp.get("up"):
                        up_positions.append(s.pos)
                else:
                    agent = self.agents[s.name]
                    up = await self._npc_call(agent.election_choice, action="election_up") if self.planner is not None else (s.role == "seer" or
                          (s.is_wolf and agent.brain.wolf_strategy == "bluff") or
                          agent.style.aggression > 0.82)
                    if up:
                        up_positions.append(s.pos)
                self._step_state["election_up"] = up_positions
                self._step_state["election_cursor"] = i + 1
                self._checkpoint()
            self._step_state.pop("election_cursor", None)
            up_players = [e.seat_at(p) for p in up_positions]
            if not up_players:
                self.emit({"type": "narration", "text": t(e.locale, "sheriff_nobody")})
                self._clear_election_state()
                return
            self.emit({"type": "narration", "text": ("Sheriff candidates: " if e.locale == "en" else "本轮上警名单：") +
                       ", ".join(f"#{s.pos} {s.name}" for s in up_players)})
            self._step_state["election_phase"] = 1
            self._step_state["election_speeches"] = []
            self._step_state["election_cursor"] = 0
            self._checkpoint()

        # ---- Phase 1: 候选人发言 ----
        if self._step_state.get("election_phase", 0) == 1:
            up_players = sorted((e.seat_at(p) for p in self._step_state.get("election_up", [])),
                                key=lambda x: x.pos)
            election_speeches = self._step_state.get("election_speeches", [])
            start = self._step_state.get("election_cursor", 0)
            for i in range(start, len(up_players)):
                s = up_players[i]
                if s.is_player:
                    resp = await self.ask_player("speech", {"phase": t(e.locale, "election_phase")})
                    text = resp.get("text", "")
                    speech = self._player_speech(text)
                else:
                    speech = await self._npc_call(self.agents[s.name].speak, election_speeches)
                    text = speech.text
                election_speeches.append((s.name, speech))
                self._broadcast_speech(s, speech)
                e.record_speech(
                    s.pos, text, phase="election", claim=speech.claim,
                    accuse=speech.accuse, defend=speech.defend,
                )
                self._step_state["election_speeches"] = election_speeches
                self._step_state["election_cursor"] = i + 1
                # Persist the speech, its cursor and state before publishing it,
                # so a crash can never strand a published speech off the ledger.
                self.emit({"type": "speech", "seat": s.pos, "name": s.name,
                           "text": text, "election": True, "phase": "election"}, publish=False)
                self._checkpoint()
                self._flush_publish()
                await asyncio.sleep(0.3)
            self._step_state.pop("election_cursor", None)
            await self._answer_table_questions()
            self._step_state["election_phase"] = 2
            self._step_state["election_cursor"] = 0
            self._checkpoint()

        # ---- Phase 2: 退警窗口（仅 onboarding；研究调用方无此提示） ----
        if self._step_state.get("election_phase", 0) == 2:
            if self.onboarding:
                election_speeches = self._step_state.get("election_speeches", [])
                up_positions = self._step_state.get("election_up", [])
                remaining = list(self._step_state.get("election_remaining", []))
                start = self._step_state.get("election_cursor", 0)
                for i in range(start, len(up_positions)):
                    p = up_positions[i]
                    s = e.seat_at(p)
                    if s.is_player:
                        response = await self.ask_player("election_withdraw", {})
                        withdraw = response["withdraw"]
                    else:
                        own_claim = next(sp.claim for name, sp in election_speeches if name == s.name)
                        withdraw = (await self._npc_call(self.agents[s.name].election_choice, withdraw=True, action="election_withdraw") if self.planner is not None else
                                    own_claim != "seer" and any(sp.claim == "seer" for name, sp in election_speeches if name != s.name) and self.agents[s.name].style.aggression < 0.9)
                    if withdraw:
                        self.emit({"type": "narration", "text": f"#{s.pos} {s.name} " + ("withdraws." if e.locale == "en" else "退警。")})
                    else:
                        remaining.append(p)
                    self._step_state["election_remaining"] = remaining
                    self._step_state["election_cursor"] = i + 1
                    self._checkpoint()
                self._step_state.pop("election_cursor", None)
                self._step_state["election_up"] = remaining
                self._step_state.pop("election_remaining", None)
                if not remaining:
                    self.emit({"type": "narration", "text": t(e.locale, "sheriff_nobody")})
                    self._clear_election_state()
                    return
            self._step_state["election_phase"] = 3
            self._step_state["election_cursor"] = 0
            self._checkpoint()

        # ---- Phase 3: 警长投票（int 键字典以 [pos, target] 对持久化） ----
        if self._step_state.get("election_phase", 0) == 3:
            up_positions = self._step_state.get("election_up", [])
            candidates = [{"pos": p, "name": e.seat_at(p).name} for p in up_positions]
            alive = e.alive_seats()
            votes = dict(self._step_state.get("election_vote_pairs", []))
            start = self._step_state.get("election_cursor", 0)
            for i in range(start, len(alive)):
                s = alive[i]
                if s.is_player:
                    resp = await self.ask_player("vote", {"candidates": candidates, "sheriff": True})
                    votes[s.pos] = resp.get("target")
                else:
                    votes[s.pos] = await self._npc_call(self.agents[s.name].vote, candidates, sheriff=True)
                self._step_state["election_vote_pairs"] = sorted(votes.items())
                self._step_state["election_cursor"] = i + 1
                self._checkpoint()
            self._step_state.pop("election_cursor", None)
            self._step_state["election_phase"] = 4
            self._checkpoint()

        # ---- Phase 4: 统计 + 揭晓警长（无外部调用） ----
        if self._step_state.get("election_phase", 0) == 4:
            votes = dict(self._step_state.get("election_vote_pairs", []))
            self._broadcast_votes(votes, sheriff=True)
            tally = {}
            for v in votes.values():
                if v:
                    tally[v] = tally.get(v, 0) + 1
            self.emit(ballot_event(e, votes, tally, sheriff=True))
            leaders = [pos for pos in tally if tally[pos] == max(tally.values())] if tally else []
            if len(leaders) == 1:
                sheriff = leaders[0]
                e.sheriff = sheriff
                self.emit({"type": "narration",
                           "sheriff": sheriff,
                           "text": t(e.locale, "sheriff_elected", pos=sheriff, name=e.seat_at(sheriff).name)})
            else:
                self.emit({"type": "narration", "text": t(e.locale, "sheriff_tie")})
            self._clear_election_state()

    def _clear_election_state(self):
        """Drop the per-step election cursor/accumulators after the sheriff is
        settled (or the election aborts with no candidates)."""
        for key in ("election_phase", "election_up", "election_speeches",
                    "election_remaining", "election_vote_pairs", "election_cursor"):
            self._step_state.pop(key, None)

    # ---------------- 投票阶段 ----------------
    async def _vote_phase(self):
        e = self.engine
        if self._step_state.get("vote_settled"):
            # The vote + exile were already applied and committed atomically
            # (the marker is set with the batch commit below).  A resume after a
            # mid-death-trigger crash re-enters here and must skip straight past
            # the vote instead of re-asking every seat.
            return
        e.phase = "vote"
        alive = e.alive_seats()
        # 玩家投票候选时附带其已知信息
        pv = e.player_view()
        candidates = []
        for s in alive:
            note = ""
            if pv["role"] == "seer":
                for r in pv["seer_results"]:
                    if r["target"] == s.pos:
                        note = t(e.locale, "note_hunt" if r["result"] == "wolf" else "note_safe")
            candidates.append({"pos": s.pos, "name": s.name, "note": note})
        resuming = self._resume_step == "vote"
        # ``votes`` is int-keyed; persisted as a sorted list of ``[pos, target]``
        # pairs so a JSON checkpoint round-trip cannot turn its keys into strings.
        votes = dict(self._step_state.get("vote_pairs", [])) if resuming else {}
        start = self._step_state.get("vote_cursor", 0) if resuming else 0
        for i in range(start, len(alive)):
            s = alive[i]
            if s.is_player:
                resp = await self.ask_player("vote", {"candidates": [c for c in candidates if c["pos"] != s.pos] +
                                             [{"pos": 0, "name": target_label(0, e.locale)}]})
                votes[s.pos] = resp.get("target")
            else:
                cands = [{"pos": x.pos, "name": x.name} for x in alive] + [{"pos": 0, "name": target_label(0, e.locale)}]
                votes[s.pos] = await self._npc_call(self.agents[s.name].vote, cands)
            self._step_state["vote_pairs"] = sorted(votes.items())
            self._step_state["vote_cursor"] = i + 1
            self._checkpoint()
        self._step_state.pop("vote_pairs", None)
        self._step_state.pop("vote_cursor", None)
        self._broadcast_votes(votes)
        tally = e.vote_tally(votes)
        self.emit(ballot_event(e, votes, tally))
        self.emit({"type": "vote_result", "tally": tally})
        exiled = None
        if tally:
            maxv = max(tally.values())
            top = [k for k, v in tally.items() if v == maxv]
            exiled = top[0] if len(top) == 1 else None
        for ev in e.resolve_vote(votes, exiled):
            await self._emit_event(ev)
        # Record the settled position *with* the batch commit: a resume re-enters
        # and skips the vote, proceeding straight to the death-trigger chain
        # (which is idempotent via ``_triggered``).  Without this marker a crash
        # after settlement re-ran the whole vote (a second ballot + re-requests).
        self._step_state["vote_settled"] = True
        self._commit_batch()

    def _broadcast_votes(self, votes: dict[int, int | None], sheriff: bool = False):
        e = self.engine
        for voter_pos, target_pos in votes.items():
            voter_name = e.seat_at(voter_pos).name
            target_name = target_label(0, e.locale) if target_pos == 0 else e.seat_at(target_pos).name if target_pos else None
            for agent in self.agents.values():
                agent.observe_vote(e.day_count, voter_name, target_name, sheriff)

    async def _post_death_triggers(self):
        e = self.engine
        # Drain newly created deaths too, regardless of seating order.  A seat is
        # marked triggered only *after* its (possibly replayed) gun decision is
        # resolved, so a crash while the shooter prompt is open leaves the seat
        # untriggered — the resume re-finds it and re-applies the committed shot
        # instead of losing it or double-firing.
        while True:
            s = next((s for s in e.seats.values()
                      if not s.alive and s.pos not in self._triggered), None)
            if s is None:
                break
            if s.role == "hunter" and s.death_cause not in ("poison", "knight_duel"):
                tgt = await self._gun_target(s, "猎人")
                self._triggered.add(s.pos)
                if tgt:
                    events = []
                    e.trigger_hunter(s.pos, tgt, events)
                    for ev in events:
                        await self._emit_event(ev)
                    # Commit the shot's state + events atomically, then publish.
                    self._commit_batch()
                else:
                    self._checkpoint()
            elif s.role == "wolf_king" and s.death_cause in ("exile", "hunter_gun"):
                tgt = await self._gun_target(s, "狼王")
                self._triggered.add(s.pos)
                if tgt:
                    events = []
                    e.trigger_wolf_king(s.pos, tgt, events)
                    for ev in events:
                        await self._emit_event(ev)
                    self._commit_batch()
                else:
                    self._checkpoint()
            else:
                self._triggered.add(s.pos)
                self._checkpoint()

    async def _gun_target(self, shooter, role_cn) -> Optional[int]:
        e = self.engine
        cands = [s.pos for s in e.alive_seats() if s.pos != shooter.pos]
        if shooter.is_player:
            resp = await self.ask_player("night", {"role_key": shooter.role, "role": shooter.role_cn, "desc": t(e.locale, "gun_desc"),
                "candidates": [{"pos": p, "name": e.seat_at(p).name} for p in cands]})
            return resp.get("target")
        candidates = [{"pos": pos, "name": e.seat_at(pos).name} for pos in cands]
        if self.planner is not None and candidates:
            return (await self._npc_call(self.agents[shooter.name].night_action, "death-trigger shot", candidates)).get("target")
        return await self._npc_call(self.agents[shooter.name].vote, candidates) if candidates else None

    # ---------------- 事件广播 ----------------
    async def _emit_event(self, ev):
        """Record one settlement event and apply its agent observations.

        Publishing and durability are the *caller's* responsibility.  A
        settlement (resolve_night, a death-trigger shot, a day skill, a vote)
        produces a *batch* of events plus engine mutations; the caller records
        every event, then calls ``_commit_batch()`` (one checkpoint + one flush)
        so the whole batch is durable before the first event becomes visible.

        A per-event checkpoint here would tear the batch: the settle marker is
        already set, so a crash after the first event would let a resume skip
        the rest (Shawn's wolf-knife + witch-poison repro: engine had both
        deaths, the ledger only the first).
        """
        et = ev.type
        ev_data = getattr(ev, "data", None) or {}
        if et == "death":
            self.emit({"type": "death", "seat": ev.seat, "text": ev.text,
                       "day": ev_data.get("day"), "night": ev_data.get("night"),
                       "phase": ev_data.get("phase")}, publish=False)
        elif et == "flip":
            self.emit({"type": "flip", "seat": ev.seat, "text": ev.text,
                       "role_cn": ev_data.get("role_cn"),
                       "day": ev_data.get("day"), "night": ev_data.get("night"),
                       "phase": ev_data.get("phase")}, publish=False)
            seat = self.engine.seat_at(ev.seat)
            for agent in self.agents.values():
                agent.observe_flip(seat.name, seat.role_cn, seat.is_wolf)
        elif et == "exile":
            self.emit({"type": "exile", "seat": ev.seat, "text": ev.text,
                       "day": ev_data.get("day"), "night": ev_data.get("night"),
                       "phase": ev_data.get("phase")}, publish=False)
            seat = self.engine.seat_at(ev.seat)
            for agent in self.agents.values():
                agent.observe_exile(self.engine.day_count, seat.name, seat.is_wolf)
        elif et == "system":
            self.emit({"type": "narration", "text": self.host.narrate("system", ev.text)},
                      publish=False)

    # ---------------- 辅助 ----------------
    def _seats_desc(self) -> str:
        return "\n".join((f"  #{s.pos} {s.name}" if self.engine.locale == "en" else f"  {s.pos}号 {s.name}")
                         for s in self.engine.seats.values())

    def _npc_performances(self) -> str:
        lines = []
        for name, a in self.agents.items():
            lr = a.memory.get("learnings", [])
            last = lr[-1] if lr else "无"
            start = a.brain.starting_state
            final = a.brain.match_state.snapshot()
            lines.append(
                f"- {name}（{a.role_cn}）：状态 {start['condition_label']}/{start['mood']}→"
                f"{final['condition_label']}/{final['mood']}，事件{','.join(final['events'][-4:]) or '无'}；"
                f"发言/行动{len(a.reasoning)}次，最近学习「{last}」。")
        return "\n".join(lines)


# Compatibility name for existing callers.  New transports should import the
# core name above rather than treating the Web runner as the game itself.
GameRunner = GameSession
