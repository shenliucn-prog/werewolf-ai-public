"""狼人杀 Web 版 后端主程序。

FastAPI + SSE 事件流。游戏主循环在独立 task 中运行，通过队列把事件推给 SSE；
玩家输入经 /api/action 被主循环 await。无 LLM Key 时自动降级，照样跑通。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import logging
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .game import engine as eng_mod
from .ai.brain import Speech
from .ai.llm import LLMClient, LLMRuntimeConfig
from .ai.decision_runtime import ModelTurnError, create_runtime
from .ai.strategic_agent import StrategicNPCAgent
from .ai.host import HostAgent
from .i18n import normalize_locale, t, list_sep, role_name, board_display, role_desc, board_role_name, witch_rule_text
from .casting import random_names, persona_options, CAST_IDS, PLAYER_ID
from .public_record import PublicRecord, ballot_event, target_label

config.ensure_dirs()
app = FastAPI(title="狼人杀 Web 版")

GAMES: dict[str, "GameSession"] = {}
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
                 planner=None):
        if planner is not None and not planner.verified:
            raise ValueError("Model preflight required before opening a game.")
        if planner is not None and conjecture:
            raise ValueError("Model-player conjecture tables are not yet integrated; choose normal mode.")
        self.planner = planner
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
        self._pending_questions = {}
        self._questions_answered = 0
        self._table_cooldown = False

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

    def emit(self, obj: dict):
        self.public_record.observe(obj, self.engine.day_count)
        self.event_q.put_nowait(obj)

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

    async def ask_player(self, kind: str, data: dict) -> dict:
        self.pending = {"kind": kind, "data": data}
        self.emit({"type": "request", "kind": kind, "data": data})
        return await self.q.get()

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
        self.q.put_nowait(resp)
        return True

    # ---------------- 主循环 ----------------
    async def events(self):
        """Yield game events as dictionaries, independent of presentation."""
        if self._events_started:
            raise RuntimeError("A session has one event consumer; start a new game to play again.")
        self._events_started = True
        task = asyncio.create_task(self._game_task())
        try:
            while True:
                item = await self.event_q.get()
                if item is _SENTINEL:
                    break
                yield item
            await task
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def run(self):
        """Backward-compatible SSE view used by the existing Web adapter."""
        async for item in self.events():
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    async def _game_task(self):
        try:
            await self._play()
        except ModelTurnError:
            self.emit({"type": "error", "text": (
                "Model decision failed, timed out or exceeded budget. Game stopped; no offline substitution. Resume is not supported."
                if self.engine.locale == "en" else "模型决策失败、超时或调用额度耗尽。对局已停止，未切换离线玩家；目前不支持断线续局。")})
        except Exception:
            logging.getLogger(__name__).exception("Game session failed")
            self.emit({"type": "error", "text": (
                "The game stopped unexpectedly. Please start a new game."
                if self.engine.locale == "en" else "对局意外中断，请重新开局。")})
        finally:
            self.pending = None
            self.finished = True
            self.event_q.put_nowait(_SENTINEL)

    async def _npc_call(self, call, *args, **kwargs):
        if self.planner is None:
            return call(*args, **kwargs)
        agent = getattr(call, "__self__", None)
        while True:
            memory = getattr(agent, "model_decisions", [])
            checkpoint = len(memory)
            try:
                return await asyncio.to_thread(call, *args, **kwargs)
            except ModelTurnError:
                del memory[checkpoint:]
                self.emit({"type": "narration", "text": (
                    "Model response failed. Game paused without substituting a local player. Retry after checking the connection, or stop. Budget limits still apply."
                    if self.engine.locale == "en" else "模型响应失败，对局已暂停，未替换为离线玩家。检查连接后可重试，或结束本局；调用上限仍有效。")})
                response = await self.ask_player("model_retry", {})
                if not response["retry"]:
                    raise ModelTurnError("Player stopped after model failure.") from None

    async def _play(self):
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
                        planner=self.planner, public_record=self.public_record)
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

        if self.onboarding:
            from .onboarding import introduction
            e.phase = "onboarding"
            self.emit({"type": "narration", "phase": "onboarding",
                       "text": introduction(e, self.conjecture)})
            await self.ask_player("ready", {})

        if e.witch_unlimited:
            self.emit({"type": "narration", "text": witch_rule_text(e.locale, e.board)})

        game_over = False
        while not game_over:
            if e.check_round_limit():
                self.emit({"type": "narration", "text": e.end_reason})
                break
            self.emit({"type": "narration", "phase": "night", "text": self.host.narrate("night_start", "")})
            await asyncio.sleep(0.3)
            requests = e.start_night()
            self._deliver_grave_result()
            actions = await self._gather_night(requests)
            night_events = e.resolve_night(actions)
            for ev in night_events:
                await self._emit_event(ev)
            await self._post_death_triggers()
            if e.check_win():
                self.emit({"type": "narration", "text": self.host.narrate("win", e.end_reason)})
                break
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

            e.start_day()
            self._reset_table_talk()
            self.emit({"type": "narration", "phase": "day", "text": self.host.narrate("day_start", t(self.engine.locale, "day_start", d=e.day_count))})
            if not any(ev.type == "death" for ev in night_events):
                self.emit({"type": "narration", "text": "Host Raven: No one died last night." if e.locale == "en" else "主持人夜鸦：昨夜平安，无人死亡。"})
            await asyncio.sleep(0.3)

            if e.day_count == 1:
                await self._election()
            e.phase = "day"

            if self.conjecture:
                await self._conjecture_round()

            order = e.speech_order()
            self.speech_events = []
            self.player_last_speech = ""
            for pos in order:
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
                    pos, text, claim=speech.claim,
                    accuse=speech.accuse, defend=speech.defend,
                )
                self.emit({"type": "speech", "seat": pos, "name": seat.name, "text": text})
                await asyncio.sleep(0.3)
                await self._maybe_table_talk(seat, speech)

            if e.check_win():
                self.emit({"type": "narration", "text": self.host.narrate("win", e.end_reason)})
                break
            if e.phase == "night":
                self.emit({"type": "narration", "text": t(e.locale, "skill_ends_day")})
                continue

            await self._answer_table_questions()
            for seat in e.alive_seats():
                if seat.role == "crow":
                    await self._day_skill(seat, crow=True)

            rule = self.host.maybe_invent_rule(e)
            if rule:
                self.emit({"type": "host_rule", "text": rule})

            if self.conjecture:
                # A second snapshot lets the human revise after discussion.
                await self._conjecture_round()
            await self._vote_phase()
            await self._post_death_triggers()

            win = e.check_win()
            if win:
                game_over = True
                self.emit({"type": "narration", "text": self.host.narrate("win", e.end_reason)})
                break

        perf = self._npc_performances()
        review = self.host.review(e, perf)
        self.host.evolve(e, review)
        for a in self.agents.values():
            a.save_memory()
        reveal = "\n".join(f"#{s.pos} {s.name}: {s.role_cn}" for s in sorted(e.seats.values(), key=lambda s: s.pos))
        review += "\n\n" + ("Final roles\n" if e.locale == "en" else "最终身份\n") + reveal
        review += "\n\n" + self.public_record.query("/history")
        self.emit({"type": "review", "text": review, "winner": e.winner})
        self.emit({"type": "gameover", "winner": e.winner, "reason": e.end_reason})

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
                        self._pending_questions[target.name] = self.engine.player_seat().name
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
        if speech.question_to and speech.question_to in self.agents:
            self._pending_questions[speech.question_to] = seat.name
        for agent in self.agents.values():
            agent.observe_speech(self.engine.day_count, seat.name, speech)

    async def _answer_table_questions(self):
        """A bounded public clarification window after ordered speeches."""
        for target, asker in list(self._pending_questions.items()):
            del self._pending_questions[target]
            agent = self.agents.get(target)
            if not agent or not agent.seat.alive or self._questions_answered >= 2:
                continue
            self._questions_answered += 1
            self.emit({"type": "narration", "text":
                       (f"Host: Before voting, {target}, answer {asker}'s question. This is a claim, not a host-verified result." if self.engine.locale == "en" else
                        f"主持人：投票前请 {target} 回答 {asker} 的追问。这是玩家口径，不代表主持人认证。")})
            response = await self._npc_call(agent.table_reply, asker) if self.planner is not None else agent.brain.answer_check_question()
            await self._publish_table_speech(agent.seat, response, "clarification")

    def _reset_table_talk(self):
        self._table_extra_turns = 0
        self._table_extra_by_name = {}
        self._table_pairs = set()
        self._pending_questions = {}
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
        self.emit({"type": "speech", "seat": seat.pos, "name": seat.name,
                   "text": speech.text, "table_talk": True})
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
        actions = {}
        prio = {"seer": 0, "wolves": 1, "witch": 2, "guard": 3,
                "stone_ghost_kill": 1, "wolf_beauty": 4, "stone_ghost": 5}
        requests = sorted(requests, key=lambda r: prio.get(r[0], 9))
        knife = None
        for actor, pos in requests:
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
        return await self._npc_call(self.agents[sg.name].night_action, "stone_ghost", cands)

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
        return await self._npc_call(self.agents[sg.name].night_action, "wolves", cands)

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
        await self._post_death_triggers()

    # ---------------- 警长选举（仅第一天） ----------------
    async def _election(self):
        e = self.engine
        e.phase = "election"
        up_players = []
        election_speeches: list[tuple[str, Speech]] = []
        for s in e.alive_seats():
            if s.is_player:
                resp = await self.ask_player("election_up", {})
                if resp.get("up"):
                    up_players.append(s)
            else:
                agent = self.agents[s.name]
                up = await self._npc_call(agent.election_choice) if self.planner is not None else (s.role == "seer" or
                      (s.is_wolf and agent.brain.wolf_strategy == "bluff") or
                      agent.style.aggression > 0.82)
                if up:
                    up_players.append(s)
        if not up_players:
            self.emit({"type": "narration", "text": t(e.locale, "sheriff_nobody")})
            return
        self.emit({"type": "narration", "text": ("Sheriff candidates: " if e.locale == "en" else "本轮上警名单：") +
                   ", ".join(f"#{s.pos} {s.name}" for s in up_players)})
        for s in sorted(up_players, key=lambda x: x.pos):
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
            self.emit({"type": "speech", "seat": s.pos, "name": s.name, "text": text, "election": True})
            await asyncio.sleep(0.3)
        await self._answer_table_questions()
        # Human-facing adapters expose a withdrawal window; unattended
        # research callers retain their existing no-prompt election protocol.
        if self.onboarding:
            remaining = []
            for s in up_players:
                if s.is_player:
                    response = await self.ask_player("election_withdraw", {})
                    withdraw = response["withdraw"]
                else:
                    own_claim = next(sp.claim for name, sp in election_speeches if name == s.name)
                    withdraw = (await self._npc_call(self.agents[s.name].election_choice, withdraw=True) if self.planner is not None else
                                own_claim != "seer" and any(sp.claim == "seer" for name, sp in election_speeches if name != s.name) and self.agents[s.name].style.aggression < 0.9)
                if withdraw:
                    self.emit({"type": "narration", "text": f"#{s.pos} {s.name} " + ("withdraws." if e.locale == "en" else "退警。")})
                else:
                    remaining.append(s)
            up_players = remaining
            if not up_players:
                self.emit({"type": "narration", "text": t(e.locale, "sheriff_nobody")})
                return
        votes = {}
        for s in e.alive_seats():
            if s.is_player:
                resp = await self.ask_player("vote",
                    {"candidates": [{"pos": u.pos, "name": u.name} for u in up_players], "sheriff": True})
                votes[s.pos] = resp.get("target")
            else:
                votes[s.pos] = await self._npc_call(self.agents[s.name].vote,
                    [{"pos": u.pos, "name": u.name} for u in up_players], sheriff=True)
        self._broadcast_votes(votes)
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

    # ---------------- 投票阶段 ----------------
    async def _vote_phase(self):
        e = self.engine
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
        votes = {}
        for s in alive:
            if s.is_player:
                resp = await self.ask_player("vote", {"candidates": [c for c in candidates if c["pos"] != s.pos] +
                                             [{"pos": 0, "name": target_label(0, e.locale)}]})
                votes[s.pos] = resp.get("target")
            else:
                cands = [{"pos": x.pos, "name": x.name} for x in alive] + [{"pos": 0, "name": target_label(0, e.locale)}]
                votes[s.pos] = await self._npc_call(self.agents[s.name].vote, cands)
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

    def _broadcast_votes(self, votes: dict[int, int | None]):
        e = self.engine
        for voter_pos, target_pos in votes.items():
            voter_name = e.seat_at(voter_pos).name
            target_name = target_label(0, e.locale) if target_pos == 0 else e.seat_at(target_pos).name if target_pos else None
            for agent in self.agents.values():
                agent.observe_vote(e.day_count, voter_name, target_name)

    async def _post_death_triggers(self):
        e = self.engine
        # Drain newly created deaths too, regardless of seating order.
        while True:
            s = next((s for s in e.seats.values()
                      if not s.alive and s.pos not in self._triggered), None)
            if s is None:
                break
            self._triggered.add(s.pos)
            if s.role == "hunter" and s.death_cause not in ("poison", "knight_duel"):
                tgt = await self._gun_target(s, "猎人")
                if tgt:
                    events = []
                    e.trigger_hunter(s.pos, tgt, events)
                    self._triggered.add(s.pos)
                    for ev in events:
                        await self._emit_event(ev)
            elif s.role == "wolf_king" and s.death_cause in ("exile", "hunter_gun"):
                tgt = await self._gun_target(s, "狼王")
                if tgt:
                    events = []
                    e.trigger_wolf_king(s.pos, tgt, events)
                    self._triggered.add(s.pos)
                    for ev in events:
                        await self._emit_event(ev)

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
        et = ev.type
        if et == "death":
            self.emit({"type": "death", "seat": ev.seat, "text": ev.text})
        elif et == "flip":
            self.emit({"type": "flip", "seat": ev.seat, "text": ev.text, "role_cn": ev.data.get("role_cn")})
            seat = self.engine.seat_at(ev.seat)
            for agent in self.agents.values():
                agent.observe_flip(seat.name, seat.role_cn, seat.is_wolf)
        elif et == "exile":
            self.emit({"type": "exile", "seat": ev.seat, "text": ev.text})
            seat = self.engine.seat_at(ev.seat)
            for agent in self.agents.values():
                agent.observe_exile(self.engine.day_count, seat.name, seat.is_wolf)
        elif et == "system":
            self.emit({"type": "narration", "text": self.host.narrate("system", ev.text)})
        await asyncio.sleep(0.3)

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


# ---------------- API ----------------
async def _json_object(req: Request) -> dict:
    """Reject malformed input consistently instead of returning a server error."""
    try:
        body = await req.json()
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail="Expected a JSON object.") from error
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Expected a JSON object.")
    if "game_id" in body and not isinstance(body["game_id"], str):
        raise HTTPException(status_code=422, detail="game_id must be a string.")
    return body


@app.get("/api/boards")
async def boards(locale: str = "zh-CN"):
    with open(config.BOARDS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for board in data["boards"]:
        board.update(board_display(locale, board))
        board["role_labels"] = {key: board_role_name(locale, board, key, data["roles"][key]["cn"])
                                for key in set(board["roles"])}
    for key, meta in data["roles"].items():
        meta["cn"] = role_name(locale, key, meta["cn"])
        meta["desc"] = role_desc(locale, key, meta)
    return data


@app.post("/api/start")
async def start(req: Request):
    body = await _json_object(req)
    board_id = body.get("board_id", "classic")
    game_id = secrets.token_urlsafe(18)
    try:
        runner = GameSession(board_id, body.get("llm"), session_id=game_id,
                             locale=body.get("locale", "zh-CN"), names=body.get("names"),
                             personalities=body.get("personalities"),
                             conjecture=body.get("conjecture", False),
                             player_role=body.get("player_role"), onboarding=True)
        # Only explicit offline selection bypasses a real-model preflight.
        # Runtime commands come from trusted local configuration, never HTTP.
        offline = isinstance(body.get("llm"), dict) and body["llm"].get("enabled") is False
        if not offline:
            if runner.conjecture:
                raise ValueError("Model-player conjecture tables are not yet integrated; choose normal mode.")
            planner = create_runtime(backend="api" if body.get("llm") else None, options=body.get("llm"))
            await asyncio.to_thread(planner.preflight)
            runner.planner = planner
            runner.llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
            runner.host = HostAgent(runner.llm, locale=runner.engine.locale)
    except ModelTurnError:
        raise HTTPException(status_code=503, detail="LLM connection check failed. No game started and no offline fallback. / 模型预检失败，未开局、未降级。") from None
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    GAMES[game_id] = runner
    return {"ok": True, "game_id": game_id,
            "llm_status": runner._model_status()}


@app.get("/api/cast")
async def cast_options(locale: str = "zh-CN"):
    names = random_names(locale)
    return {"players": [{"id": key, "name": names[key], "is_player": key == PLAYER_ID}
                         for key in CAST_IDS], "personalities": persona_options(locale)}


@app.get("/api/stream")
async def stream(game_id: Optional[str] = None):
    runner = GAMES.get(game_id or "")
    if not runner:
        raise HTTPException(status_code=404, detail="No active game. Start a new game.")
    # Reserve before returning the response: two GETs must never start two
    # game loops or split one player's private events between consumers.
    if runner.stream_claimed or runner.finished:
        raise HTTPException(status_code=409, detail="Game stream already opened; resume is not supported.")
    runner.stream_claimed = True

    async def event_source():
        try:
            async for event in runner.run():
                yield event
        finally:
            GAMES.pop(game_id or "", None)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.post("/api/action")
async def action(req: Request):
    body = await _json_object(req)
    runner = GAMES.get(body.get("game_id", ""))
    if not runner:
        return {"ok": False, "error": "no game"}
    body.pop("game_id", None)
    return {"ok": runner.submit(body)}


@app.post("/api/host_chat")
async def host_chat(req: Request):
    """Rules tutoring is deliberately separate from the turn/action queue."""
    body = await _json_object(req)
    runner = GAMES.get(body.get("game_id", ""))
    if not runner:
        return {"ok": False, "error": "no game"}
    question = body.get("question", "")
    if not isinstance(question, str) or not question.strip() or len(question) > 320:
        return {"ok": False, "error": "invalid question"}
    return {"ok": True,
            "reply": runner.answer_question(question)}


@app.get("/api/host_style")
async def host_style():
    if os.path.exists(config.HOST_STYLE_PATH):
        with open(config.HOST_STYLE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config.CONFIG.PORT, log_level="info")


if __name__ == "__main__":
    main()
