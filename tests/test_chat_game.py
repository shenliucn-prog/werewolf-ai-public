import unittest

from werewolf_web.chat_game import parse_action
from werewolf_web.run import GameSession


CANDIDATES = [{"pos": 2, "name": "阿墨"}, {"pos": 5, "name": "小鹿"}]


class ChatGameTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_actions_are_explicit_and_legal(self):
        self.assertEqual(parse_action("vote", {"candidates": CANDIDATES}, "投 2 号"),
                         {"target": 2})
        self.assertIsNone(parse_action("vote", {"candidates": CANDIDATES}, "投 8 号"))
        self.assertEqual(parse_action("night", {"role": "女巫", "candidates": CANDIDATES},
                                      "救 2 毒 5"), {"save": 2, "poison": 5})
        self.assertEqual(parse_action("night", {"role": "女巫", "candidates": CANDIDATES},
                                      "save 2 poison 5"), {"save": 2, "poison": 5})
        self.assertEqual(parse_action("election_up", {}, "不上警"), {"up": False})
        self.assertEqual(parse_action("table_reply", {}, "我先保留意见"),
                         {"text": "我先保留意见"})

    async def test_session_core_is_not_bound_to_sse(self):
        session = GameSession("classic", {"enabled": False},
                              session_id="test-chat-core", seed=88)
        event = {"type": "narration", "text": "测试事件"}
        session.emit(event)
        self.assertEqual(session.event_q.get_nowait(), event)
        self.assertEqual(session.engine.rng.random(),
                         GameSession("classic", {"enabled": False},
                                     session_id="test-chat-core-2", seed=88).engine.rng.random())


if __name__ == "__main__":
    unittest.main()
