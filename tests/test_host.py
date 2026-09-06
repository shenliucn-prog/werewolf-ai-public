import unittest

from werewolf_web.ai.host import HostAgent, ROLE_CONTRACTS
from werewolf_web.ai.llm import LLMClient
from werewolf_web.game.engine import GameEngine


class HostGovernanceTest(unittest.TestCase):
    def test_host_has_separate_referee_director_and_coach_contracts(self):
        host = HostAgent(LLMClient())

        self.assertEqual(set(host.role_contracts), {"referee", "director", "coach"})
        self.assertEqual(host.role_contracts, ROLE_CONTRACTS)
        self.assertIn("personality", host.style)
        self.assertIn("skills", host.style)
        self.assertIn("growth", host.style)

    def test_live_host_cannot_invent_unimplemented_rules(self):
        host = HostAgent(LLMClient())
        engine = GameEngine("classic", seed=3)
        engine.setup()
        engine.day_count = 6

        before = list(host.style.get("invented_rules", []))
        self.assertIsNone(host.maybe_invent_rule(engine))
        self.assertEqual(host.style.get("invented_rules", []), before)

    def test_host_can_teach_board_rules_without_leaking_or_directing(self):
        host = HostAgent(LLMClient())
        engine = GameEngine("classic", seed=7)
        engine.setup()

        rule_answer = host.answer_rule_question("女巫怎么用药？", engine)
        self.assertIn("女巫", rule_answer)
        self.assertIn("解药", rule_answer)

        flow_answer = host.answer_rule_question("白天流程是什么？", engine)
        self.assertIn("投票", flow_answer)

        protected = host.answer_rule_question("3号谁是狼，帮我投谁？", engine)
        self.assertIn("不能", protected)
        self.assertNotIn("平民", protected)


if __name__ == "__main__":
    unittest.main()
