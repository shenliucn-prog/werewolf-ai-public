import asyncio
import random
import unittest

from werewolf_web.ai.brain import Brain, Speech
from werewolf_web.ai.host import HostAgent
from werewolf_web.ai.llm import LLMClient
from werewolf_web.game.engine import GameEngine
from werewolf_web.run import GameRunner


class TableTalkTest(unittest.TestCase):
    def setUp(self):
        self.engine = GameEngine("classic", seed=67)
        self.engine.setup()
        self.engine.day_count = 1

    def test_interruption_is_public_discourse_not_a_hidden_action(self):
        source = self.engine.alive_seats()[0]
        responder = self.engine.alive_seats()[1]
        brain = Brain(responder, self.engine, {}, random.Random(9))
        original = Speech(text=f"我怀疑 {responder.name}", accuse=responder.name)

        interruption = brain.table_interjection(source.name, original)

        self.assertEqual(interruption.accuse, source.name)
        self.assertTrue(interruption.text)
        self.assertEqual(brain.table_reply(source.name).claim, None)

    def test_host_closes_repeated_or_overlong_threads(self):
        host = HostAgent(LLMClient())
        self.assertIsNone(host.moderate_table_talk(
            topic_turns=2, extra_turns=2, speaker_extra_turns=0, repeated_pair=False))
        self.assertIn("两个人", host.moderate_table_talk(
            topic_turns=3, extra_turns=3, speaker_extra_turns=1, repeated_pair=True))
        self.assertIn("收一收", host.moderate_table_talk(
            topic_turns=1, extra_turns=7, speaker_extra_turns=0, repeated_pair=False))

    def test_extra_utterance_uses_the_same_public_ledger(self):
        runner = GameRunner("classic", {"enabled": False}, session_id="test-table-talk")
        runner.engine.setup()
        runner.engine.day_count = 1
        seat = runner.engine.alive_seats()[0]
        speech = Speech(text="我补一句，先听完再投票。")

        asyncio.run(runner._publish_table_speech(seat, speech, "interrupt"))

        event = runner.engine.history[-1]
        self.assertEqual(event.type, "speech")
        self.assertEqual(event.data["phase"], "table_talk")
        self.assertEqual(event.data["talk_kind"], "interrupt")
        self.assertEqual(runner._table_extra_turns, 1)


if __name__ == "__main__":
    unittest.main()
