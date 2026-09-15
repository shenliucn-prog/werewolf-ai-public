import contextlib
import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from werewolf_web.ai.brain import Speech
from werewolf_web.ai.codex_player import CodexNPCAgent, CodexPlayerRuntime, ModelTurnError
from werewolf_web.ai.llm import LLMClient, LLMRuntimeConfig
from werewolf_web.chat_game import main, play
from werewolf_web.game.engine import GameEngine
from werewolf_web.public_record import PublicRecord
from werewolf_web.run import GameSession


class CodexPlayerTest(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, role="civilian", locale="zh-CN"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        engine = GameEngine("classic", seed=19, locale=locale)
        engine.setup(); engine.start_night(); engine.start_day()
        seat = next(s for s in engine.seats.values() if s.role == role)
        planner = SimpleNamespace(verified=True, complete=Mock())
        record = PublicRecord(locale)
        agent = CodexNPCAgent(seat.name, engine,
            LLMClient(LLMRuntimeConfig.from_request({"enabled": False})),
            memory_dir=directory.name, planner=planner, public_record=record)
        return agent, planner, record

    def test_model_decides_vote_and_retains_own_decisions(self):
        agent, planner, record = self.make_agent()
        target = next(s for s in agent.engine.alive_seats() if s.name != agent.name)
        planner.complete.return_value = {"target": target.pos}
        with patch.object(agent.brain, "vote", side_effect=AssertionError("local vote called")):
            self.assertEqual(agent.vote([{"pos": target.pos, "name": target.name}]), target.pos)
        self.assertEqual(agent.model_decisions[-1]["decision"], {"target": target.pos})

    def test_model_receives_budgeted_context_not_other_private_results(self):
        agent, planner, record = self.make_agent()
        agent.engine.seer_results = [{"name": "SECRET_CHECK_CANARY"}]
        record.observe({"type": "private", "text": "SECRET_PLAYER_CANARY"}, 1)
        for day in range(1, 4):
            record.observe({"type": "speech", "seat": 8, "name": "阿承", "text": f"D{day}公开口径"}, day)
        record.observe({"type": "flip", "text": "11号阿岚翻牌——平民。"}, 2)
        planner.complete.return_value = {"target": 0}
        agent.vote([{"pos": 0, "name": "平安日"}])
        request = planner.complete.call_args.args[0]
        encoded = json.dumps(request, ensure_ascii=False)
        self.assertNotIn("SECRET_", encoded)
        # The bounded public context carries recent speeches verbatim and the
        # flip as a settled fact — not the whole unbounded transcript.
        self.assertIn("public_context", request)
        self.assertIn("D1公开口径", encoded)
        self.assertIn("11号阿岚翻牌", encoded)
        self.assertLessEqual(len(request["own_previous_decisions"]), 8)

    def test_own_decision_memory_is_bounded(self):
        agent, planner, record = self.make_agent()
        agent.model_decisions = [
            {"day": 1, "night": 1, "task": f"t{i}", "decision": {"target": 0}}
            for i in range(20)
        ]
        planner.complete.return_value = {"target": 0}
        agent.vote([{"pos": 0, "name": "平安日"}])
        request = planner.complete.call_args.args[0]
        # Only the most recent decisions are shown to the model.
        self.assertEqual(len(request["own_previous_decisions"]), 8)
        self.assertEqual(request["own_previous_decisions"][-1]["task"], "t19")

    def test_final_request_stays_within_budget(self):
        from werewolf_web.ai import model_context
        agent, planner, record = self.make_agent()
        # Flood the public record with long speeches — far beyond the verbatim
        # window — so the budget, not the per-field counts, is what binds.
        for i in range(40):
            record.observe({"type": "speech", "seat": 8, "name": "阿承",
                            "text": "长篇公开发言" + "具体内容" * 60 + str(i)}, 1)
        planner.complete.return_value = {"target": 0}
        agent.vote([{"pos": 0, "name": "平安日"}])
        request = planner.complete.call_args.args[0]
        size = len(json.dumps(request, ensure_ascii=False))
        self.assertLessEqual(size, model_context.MAX_REQUEST_CHARS)

    def test_long_legal_speeches_do_not_raise_budget_error(self):
        """Shawn's repro: 14 legal 1600-char in-round speeches pushed the request
        over budget even after other history was trimmed, raising ValueError.

        ``details.earlier_this_round`` duplicates the public statements, so the
        budget must trim it too — legal long speeches must never stop the game.
        """
        from werewolf_web.ai import model_context
        agent, planner, record = self.make_agent()
        long_text = "长" * 1600
        today = [(f"p{i}", Speech(text=long_text)) for i in range(14)]
        planner.complete.return_value = dict(text="回答", claim=None, accuse=None,
                                             defend=None, question_to=None)
        agent.speak(today)   # must not raise
        request = planner.complete.call_args.args[0]
        size = len(json.dumps(request, ensure_ascii=False))
        self.assertLessEqual(size, model_context.MAX_REQUEST_CHARS)

    def test_private_check_is_available_only_to_own_seer(self):
        agent, planner, _ = self.make_agent("seer")
        agent.engine.seer_results = [{"night": 1, "target": 8, "name": "OWN_CHECK", "result": "wolf"}]
        planner.complete.return_value = {"target": None}
        agent.night_action("seer", [1])
        self.assertIn("OWN_CHECK", json.dumps(planner.complete.call_args.args[0]))

    def test_speech_and_interruption_are_model_generated_not_locked(self):
        agent, planner, _ = self.make_agent()
        text = "11号已经翻牌为平民，8号此前的查杀不成立。我撤回昨天的站边。"
        planner.complete.return_value = dict(text=text, claim=None, accuse=None, defend=None, question_to=None)
        with patch.object(agent.brain, "speak", side_effect=AssertionError("template called")):
            self.assertEqual(agent.speak([]).text, text)
            self.assertEqual(agent.table_interject("8号", Speech(text="发言")).text, text)

    def test_invalid_target_or_boolean_target_stops_without_local_fallback(self):
        for target in (999, True):
            agent, planner, _ = self.make_agent()
            planner.complete.return_value = {"target": target}
            with self.assertRaises(ModelTurnError):
                agent.vote([{"pos": 1, "name": "A"}])

    def test_witch_may_not_use_spent_or_dual_potions(self):
        agent, planner, _ = self.make_agent("witch")
        planner.complete.return_value = {"save": 1, "poison": 3}
        with self.assertRaises(ModelTurnError):
            agent.night_action("witch", [3], knife=1, antidote=True, poison=True)
        planner.complete.return_value = {"save": 1, "poison": None}
        with self.assertRaises(ModelTurnError):
            agent.night_action("witch", [3], knife=1, antidote=False, poison=True)

    def test_preflight_is_required_and_conjecture_not_misrepresented(self):
        with self.assertRaises(ValueError):
            GameSession("classic", planner=SimpleNamespace(verified=False))
        with self.assertRaises(ValueError):
            GameSession("classic", planner=SimpleNamespace(verified=True), conjecture=True)

    async def test_failed_preflight_does_not_create_or_deal_game(self):
        with patch.object(CodexPlayerRuntime, "preflight", side_effect=ModelTurnError("failed")), \
             patch("werewolf_web.chat_game.GameSession") as session, contextlib.redirect_stdout(io.StringIO()):
            await play("classic", 1, False, "en", backend="codex")
        session.assert_not_called()

    async def test_failure_mid_game_emits_error_and_no_substitute_vote(self):
        session = GameSession("classic", {"enabled": False}, planner=SimpleNamespace(verified=True))
        with patch.object(session, "_play", new=AsyncMock(side_effect=ModelTurnError("PRIVATE_CANARY"))):
            await session._game_task()
        event = session.event_q.get_nowait()
        self.assertEqual(event["type"], "error")
        self.assertNotIn("PRIVATE_CANARY", json.dumps(event))
        # A model fault is recoverable, not a finished game (CAMPAIGN_DESIGN §3.3).
        self.assertTrue(session.faulted)
        self.assertFalse(session.finished)
        self.assertIsNone(session.pending)

    def test_board_selection_precedes_launch(self):
        with patch("sys.argv", ["chat", "--lang", "en"]), patch("builtins.input", return_value="divine_witch"), \
             patch("werewolf_web.chat_game.play", new_callable=AsyncMock) as launch, contextlib.redirect_stdout(io.StringIO()):
            main()
        self.assertEqual(launch.call_args.args[0], "divine_witch")
        self.assertFalse(launch.call_args.args[2])

    def test_host_candidacy_question_returns_public_list_without_advancing(self):
        session = GameSession("classic", {"enabled": False})
        session.emit({"type": "narration", "text": "本轮上警名单：#8 阿承, #10 大山"})
        session.pending = {"kind": "vote", "data": {}}
        answer = session.answer_question("本轮只有8号和10号上警吗？其他人现在还能上警吗？")
        self.assertIn("#8 阿承", answer)
        self.assertIn("之后不能加入", answer)
        self.assertEqual(session.pending["kind"], "vote")

    def test_support_is_not_treated_as_accusation(self):
        for locale in ("en", "zh-CN"):
            agent, _, _ = self.make_agent(locale=locale)
            reply = agent.brain.table_interjection("speaker", Speech(text="I support you", defend=agent.name))
            self.assertIsNone(reply.accuse)
            self.assertNotIn("不同意", reply.text)
            self.assertNotIn("disagree", reply.text)

    def test_two_addressed_human_questions_are_queued_without_rewriting(self):
        session = GameSession("classic", {"enabled": False}, planner=SimpleNamespace(verified=True))
        session.engine.setup()
        targets = [s for s in session.engine.alive_seats() if not s.is_player][:2]
        text = f"{targets[0].pos}号怎么咬的人？另外{targets[1].pos}号你觉得10不对劲怎么还投他。我懵了"
        speech = session._player_speech(text)
        self.assertEqual(speech.text, text)
        self.assertEqual({t for t, _a in session._pending_questions}, {s.name for s in targets})

    def test_runtime_rejects_tool_events_and_counts_budget(self):
        runtime = CodexPlayerRuntime(max_calls=1)
        stdout = '\n'.join(json.dumps(e) for e in [
            {"type": "item.completed", "item": {"type": "command_execution"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ready":true}'}},
            {"type": "turn.completed"}])
        with patch("werewolf_web.ai.codex_player.shutil.which", return_value="codex"), \
             patch("werewolf_web.ai.codex_player.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=stdout)):
            with self.assertRaises(ModelTurnError):
                runtime.preflight()
        self.assertFalse(runtime.verified)
        with self.assertRaisesRegex(ModelTurnError, "budget"):
            runtime.preflight()

    def test_cli_startup_diagnostic_is_distinct_from_in_turn_error(self):
        for before_turn in (True, False):
            error = {"type": "item.completed", "item": {"type": "error", "message": "startup diagnostic"}}
            start = {"type": "turn.started"}
            events = ([error, start] if before_turn else [start, error]) + [
                {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ready":true}'}},
                {"type": "turn.completed"}]
            runtime = CodexPlayerRuntime(max_calls=1)
            with patch("werewolf_web.ai.codex_player.shutil.which", return_value="codex"), \
                 patch("werewolf_web.ai.codex_player.subprocess.run", return_value=SimpleNamespace(
                     returncode=0, stdout='\n'.join(json.dumps(e) for e in events))):
                if before_turn:
                    runtime.preflight()
                    self.assertTrue(runtime.verified)
                else:
                    with self.assertRaises(ModelTurnError):
                        runtime.preflight()

    def test_coherence_assertion_accepts_correct_seat_not_unrelated_number(self):
        from werewolf_web.research.player_coherence_check import mentions_player
        seat = SimpleNamespace(pos=6, name="小满")
        self.assertTrue(mentions_player("今天6号翻平民，事实推翻了你的查杀", seat))
        self.assertTrue(mentions_player("小满翻牌是平民", seat))
        self.assertFalse(mentions_player("16号翻平民", seat))

    async def test_model_adapter_runs_night_election_speech_and_vote_in_real_session(self):
        runtime = CodexPlayerRuntime()
        runtime.verified = True
        tasks = []
        def complete(request, schema):
            tasks.append(request["task"])
            answer = {}
            for key, spec in schema["properties"].items():
                if key == "text":
                    answer[key] = "I will compare the public statements and ballots before deciding."
                elif key == "up":
                    answer[key] = True
                elif key == "withdraw":
                    answer[key] = False
                elif key == "target":
                    valid = [p for p in spec["enum"] if p is not None and p != 2]
                    answer[key] = valid[-1] if valid else None
                else:
                    answer[key] = None
            return answer
        session = GameSession("classic", {"enabled": False}, planner=runtime,
                              seed=19, player_role="guard", locale="en", onboarding=True)
        with tempfile.TemporaryDirectory() as directory:
            session.memory_dir = directory
            with patch.object(runtime, "complete", side_effect=complete), \
                 patch("werewolf_web.run.asyncio.sleep", return_value=None):
                async with contextlib.aclosing(session.events()) as events:
                    async for event in events:
                        self.assertNotEqual(event["type"], "error", event)
                        if event["type"] == "init":
                            self.assertEqual(event["settings"]["npc_driver"], "codex")
                        if event["type"] != "request":
                            continue
                        kind = event["kind"]
                        if session.engine.night_count >= 2:
                            break
                        if kind == "ready":
                            action = {"ready": True}
                        elif kind == "election_up":
                            action = {"up": False}
                        elif kind == "table_answer": action = {"skip": True}
                        elif kind in ("speech", "table_reply"):
                            action = {"text": "I am listening."}
                        else:
                            action = {"target": event["data"]["candidates"][0]["pos"]}
                        self.assertTrue(session.submit(action), event)
        for expected in ("seer", "wolves", "witch potions", "decide whether to join sheriff election",
                         "public speech", "decide whether to withdraw from election", "sheriff vote", "exile vote"):
            self.assertIn(expected, tasks)
