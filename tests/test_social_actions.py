from copy import deepcopy
import unittest

from werewolf_web.ai.brain import Speech
from werewolf_web.session_codec import freeze, thaw
from werewolf_web.social_actions import make, annotate


class SocialActionTest(unittest.TestCase):
    def test_roundtrip_independent_and_legacy_optional(self):
        action = make("defer", "P7", [3], 3)
        speech = Speech(text="Hear them out", social_action=action)
        action["sources"].append(4)
        restored = thaw(freeze(speech))
        self.assertEqual(restored.social_action["sources"], [3])
        restored.social_action["sources"].append(5)
        self.assertEqual(speech.social_action["sources"], [3])
        self.assertIsNone(thaw({"__speech__": True, "text": "old"}).social_action)

    def test_malformed_metadata_rejected(self):
        for field, value in (("version", True), ("kind", []), ("sources", [True]),
                             ("sources", [2, 2]), ("target", {}), ("reply_to", -1)):
            action = make("listen")
            action[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Speech(social_action=action)

    def test_annotate_does_not_parse_prose_or_mutate_input(self):
        option = {"id": "wait", "label": "I accuse P7", "speech": {"text": "I accuse P7"}}
        before = deepcopy(option)
        result = annotate(option)
        self.assertEqual(result["speech"]["social_action"]["kind"], "listen")
        self.assertEqual(option, before)
