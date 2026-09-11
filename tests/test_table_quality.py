"""Public-table invariants, not a benchmark claiming optimal play."""
import json
import unittest
from unittest.mock import patch

from werewolf_web.ai.brain import Style
from werewolf_web.ai.model_player import ModelNPCAgent
from werewolf_web.offline_dialogue import choose_reaction, contextual_choices
from werewolf_web.offline_game import OfflineSession
from werewolf_web.check_claims import report_line


class TableQualityTest(unittest.IsolatedAsyncioTestCase):
    async def test_other_speakers_question_is_not_repeated(self):
        seats = {n: f"P{n}" for n in range(1, 13)}
        entries = [{"night": 1, "event": {"type": "speech", "seat": n,
                    "event_no": n, "text": report_line(1, 4, "good", "en")}}
                   for n in (3, 7)]
        options = contextual_choices(entries, seats, 8, "en")
        first = choose_reaction(options, [], Style())
        second = choose_reaction(options, [], Style(), [{"text": first["label"]}])
        self.assertNotEqual(first, second)
        self.assertIsNone(choose_reaction(options, [], Style(),
                                        [{"text": c["label"]} for c in options]))

    async def test_reply_closes_question_and_survives_restore(self):
        s = OfflineSession(seed=23, player_role="civilian", locale="en")
        await s._step_setup()
        agent = next(iter(s.agents.values()))
        s.emit({"type": "speech", "seat": agent.seat.pos, "name": agent.name,
                "text": "I distrust the report, but have no decisive evidence."})
        before = agent.table_reply("Asker")
        self.assertIsNone(before.question_to)
        self.assertIn("no additional public evidence", before.text)
        restored = OfflineSession(seed=99, player_role="civilian", locale="en")
        restored.restore(json.loads(json.dumps(s.snapshot())))
        self.assertEqual(before, restored.agents[agent.name].table_reply("Asker"))

    async def test_model_reply_has_explicit_no_counterquestion_contract(self):
        agent = object.__new__(ModelNPCAgent)
        with patch.object(ModelNPCAgent, "speak", return_value=None) as speak:
            agent.table_reply("Asker")
        self.assertEqual(speak.call_args.kwargs["asker"], "Asker")
        self.assertIn("explicitly decline", speak.call_args.kwargs["reply_contract"])
