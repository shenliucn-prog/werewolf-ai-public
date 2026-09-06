from dataclasses import FrozenInstanceError, replace
import json
import unittest

from werewolf_web.research.conjecture import (
    Guess, PrivateNotebook, PrivateTable, PublicArchive, PublicTable,
)
from werewolf_web.research.fixtures import seven_player_scenario


class ConjectureArchiveTest(unittest.TestCase):
    def setUp(self):
        self.archive = PublicArchive(("A", "B", "C"))
        self.old = self.archive.append_statement("B", "D1", "I lean good on C.")

    def tables(self):
        return tuple(PublicTable(actor, 1, "D1", self.archive.sequence,
                                 tuple(Guess(p) for p in self.archive.players))
                     for actor in self.archive.players)

    def test_full_round_same_cutoff_and_stable_order(self):
        records = self.archive.publish_round(tuple(reversed(self.tables())))
        self.assertEqual([r.actor for r in records], ["A", "B", "C"])
        self.assertEqual({r.table.as_of for r in records}, {1})
        self.assertEqual(len(self.archive.history()), 4)

    def test_invalid_late_table_cannot_partially_publish(self):
        tables = self.tables()
        invalid = replace(tables[-1], guesses=(Guess("A"), Guess("B")))
        with self.assertRaises(ValueError):
            self.archive.publish_round(tables[:-1] + (invalid,))
        self.assertEqual(self.archive.history(), (self.old,))
        with self.assertRaises(KeyError):
            self.archive.table("A", 1)
        self.archive.publish_round(tables)

    def test_duplicate_or_missing_actor_rejected(self):
        tables = self.tables()
        for invalid in (tables[:-1], (tables[0], tables[0], tables[2])):
            with self.assertRaises(ValueError):
                self.archive.publish_round(invalid)
        self.assertEqual(self.archive.sequence, 1)

    def test_duplicate_target_rejected(self):
        tables = self.tables()
        duplicate = replace(tables[0], guesses=(Guess("A"), Guess("B"), Guess("B")))
        with self.assertRaises(ValueError):
            self.archive.publish_round((duplicate,) + tables[1:])

    def test_round_cannot_mix_phases_or_cutoffs(self):
        tables = self.tables()
        for bad in (replace(tables[0], phase="D2"), replace(tables[0], as_of=0)):
            with self.assertRaises(ValueError):
                self.archive.publish_round((bad,) + tables[1:])
        self.assertEqual(self.archive.sequence, 1)

    def test_no_future_or_same_batch_citations(self):
        tables = self.tables()
        for ref in ("E000002", "E999999"):
            bad = replace(tables[-1], guesses=(Guess("A", ("werewolf",), "inferred",
                                                     evidence=(ref,)), Guess("B"), Guess("C")))
            with self.assertRaisesRegex(ValueError, "unavailable public evidence"):
                self.archive.publish_round(tables[:-1] + (bad,))
        self.assertEqual(self.archive.sequence, 1)

    def test_private_objects_and_references_cannot_enter_public_archive(self):
        tables = self.tables()
        private = PrivateTable("A", 1, "D1", 1, tables[0].guesses)
        with self.assertRaises(ValueError):
            self.archive.publish_round((private,) + tables[1:])
        for status, refs in (("known", (self.old.event_id,)), ("inferred", ("P:A:1",))):
            bad = replace(tables[0], guesses=(Guess("A", ("seer",), status,
                                                   evidence=refs), Guess("B"), Guess("C")))
            with self.assertRaises(ValueError):
                self.archive.publish_round((bad,) + tables[1:])
        self.assertEqual(self.archive.sequence, 1)

    def test_public_bluff_and_uncertainty_are_legal(self):
        tables = self.tables()
        bluff = replace(tables[0], guesses=(
            Guess("A", ("seer",), "claimed", "high", rationale="I checked C."),
            Guess("B", ("seer", "werewolf"), "inferred", alternatives="Either hypothesis."),
            Guess("C", status="withheld")))
        self.archive.publish_round((bluff,) + tables[1:])
        self.assertEqual(self.archive.table("A", 1), bluff)

    def test_revisions_preserve_original_and_report_neutral_changes(self):
        self.archive.publish_round(self.tables())
        original = self.archive.table("A", 1)
        event = self.archive.append_event("D2", "C publicly revealed as a villager.")
        changed = replace(original, version=2, phase="D2", as_of=self.archive.sequence,
                          guesses=(Guess("A"), Guess("B"),
                                   Guess("C", ("villager",), "inferred", "high", (event.event_id,))),
                          revision_reason="New public evidence.")
        self.archive.publish_revision(changed)
        self.assertEqual(self.archive.table("A", 1), original)
        differences = self.archive.changes("A", 1, 2)
        self.assertEqual([d.player for d in differences], ["C"])
        self.assertFalse(hasattr(differences[0], "is_contradiction"))

    def test_overwrite_skipped_version_and_missing_reason_rejected(self):
        self.archive.publish_round(self.tables())
        original = self.archive.table("A", 1)
        for version in (1, 3):
            with self.assertRaises(ValueError):
                self.archive.publish_revision(replace(original, version=version,
                    as_of=self.archive.sequence, revision_reason="change"))
        with self.assertRaises(ValueError):
            replace(original, version=2)

    def test_initial_revision_requires_full_round(self):
        with self.assertRaises(ValueError):
            self.archive.publish_revision(self.tables()[0])

    def test_immutable_history_and_detached_export(self):
        self.archive.publish_round(self.tables())
        table = self.archive.table("A", 1)
        with self.assertRaises(FrozenInstanceError):
            table.guesses[0].rationale = "rewritten"
        with self.assertRaises(ValueError):
            replace(table, guesses=list(table.guesses))
        exported = self.archive.export()
        exported["records"][0]["text"] = "rewritten"
        exported["records"][1]["table"]["guesses"][0]["rationale"] = "rewritten"
        self.assertEqual(self.archive.lookup(self.old.event_id), self.old)
        self.assertEqual(table.guesses[0].rationale, "")

    def test_exact_memory_never_truncated(self):
        self.archive.publish_round(self.tables())
        for number in range(250):
            self.archive.append_statement("A", f"D{number + 2}", f"statement {number}")
        self.assertEqual(len(self.archive.history()), 254)
        self.assertEqual(self.archive.lookup(self.old.event_id).text, "I lean good on C.")
        self.assertEqual(self.archive.table("B", 1).version, 1)


class PrivateNotebookTest(unittest.TestCase):
    def setUp(self):
        self.archive = PublicArchive(("A", "B"))
        self.a = PrivateNotebook("A", self.archive)
        self.b = PrivateNotebook("B", self.archive)
        self.own = self.a.observe("SECRET_SELF_SEER")
        self.other = self.b.observe("SECRET_OTHER_WOLF")

    def table(self, version=1, reason=""):
        return PrivateTable("A", version, "D1", self.archive.sequence,
                            (Guess("A", ("seer",), "known", "high", (self.own.event_id,)),
                             Guess("B")), revision_reason=reason)

    def test_private_table_saved_without_public_side_effect(self):
        before = self.archive.export()
        self.a.save(self.table())
        self.assertEqual(self.archive.export(), before)
        self.assertEqual(self.a.history(), (self.table(),))
        public = json.dumps(self.archive.export())
        self.assertNotIn("SECRET", public)
        self.assertNotIn("P:A", public)
        self.assertNotIn("tables", self.b.export_for_owner()["observations"][0])

    def test_owner_and_other_private_reference_isolation(self):
        with self.assertRaises(ValueError):
            self.b.save(self.table())
        bad = replace(self.table(), guesses=(self.table().guesses[0],
            Guess("B", ("werewolf",), "known", "high", (self.other.event_id,))))
        with self.assertRaisesRegex(ValueError, "unavailable evidence"):
            self.a.save(bad)
        self.assertEqual(self.a.history(), ())

    def test_private_history_is_append_only(self):
        self.a.save(self.table())
        with self.assertRaises(ValueError):
            self.a.save(self.table())
        self.a.save(self.table(2, "Reconsidered the same evidence."))
        self.assertEqual([t.version for t in self.a.history()], [1, 2])

    def test_private_known_requires_evidence_and_cannot_be_public_presentation(self):
        for status, refs in (("known", ()), ("claimed", (self.own.event_id,))):
            bad = replace(self.table(), guesses=(Guess("A", ("seer",), status,
                                                      evidence=refs), Guess("B")))
            with self.assertRaises(ValueError):
                self.a.save(bad)

    def test_decision_cannot_use_nonexistent_or_old_table(self):
        with self.assertRaises(ValueError):
            self.a.record_decision(1, "vote B")
        self.a.save(self.table())
        decision = self.a.record_decision(1, "vote B")
        self.assertEqual(decision.table_version, 1)
        self.a.save(self.table(2, "reassess"))
        with self.assertRaises(ValueError):
            self.a.record_decision(1, "vote B")

    def test_unknown_may_not_hide_asserted_roles(self):
        with self.assertRaises(ValueError):
            Guess("B", ("werewolf",), "unknown")


class SevenPlayerFixtureTest(unittest.TestCase):
    def test_bilingual_fixture_complete_public_and_private_tables(self):
        for locale in ("zh-CN", "en"):
            with self.subTest(locale=locale):
                fixture = seven_player_scenario(locale)
                for actor in tuple("ABCDEFG"):
                    self.assertEqual(len(fixture.archive.table(actor, 1).guesses), 7)
                    self.assertEqual(len(fixture.notebooks[actor].history()[0].guesses), 7)
                private = fixture.notebooks["B"].history()[0]
                public = fixture.archive.table("B", 1)
                self.assertEqual(next(g for g in private.guesses if g.player == "B").roles, ("werewolf",))
                self.assertEqual(next(g for g in public.guesses if g.player == "B").roles, ("seer",))

    def test_shared_testimony_provenance_and_old_statement_survive(self):
        fixture = seven_player_scenario("en")
        archive = fixture.archive
        changed = archive.changes("F", 1, 2)
        self.assertEqual([d.player for d in changed], ["D"])
        source = archive.lookup(changed[0].after.evidence[0])
        self.assertEqual((source.actor, source.table.version), ("B", 1))
        self.assertIn("lean good", archive.lookup("E000001").text)
        self.assertTrue(any("hiding my role" in r.text for r in archive.history()))

    def test_export_has_no_private_observation_or_reference(self):
        fixture = seven_player_scenario("en")
        public = json.dumps(fixture.archive.export())
        for notebook in fixture.notebooks.values():
            for observation in notebook.export_for_owner()["observations"]:
                self.assertNotIn(observation["event_id"], public)
                self.assertNotIn(observation["text"], public)

    def test_language_does_not_change_ids_or_role_codes(self):
        zh = seven_player_scenario("zh-CN").archive
        en = seven_player_scenario("en").archive
        self.assertEqual([r.event_id for r in zh.history()], [r.event_id for r in en.history()])
        for actor in zh.players:
            self.assertEqual([g.roles for g in zh.table(actor, 1).guesses],
                             [g.roles for g in en.table(actor, 1).guesses])


if __name__ == "__main__":
    unittest.main()
