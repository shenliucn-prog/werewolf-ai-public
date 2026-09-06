from dataclasses import replace
import json
import unittest

from werewolf_web.research.conjecture import Guess, PrivateNotebook, PrivateTable, PublicArchive, PublicTable
from werewolf_web.research.debate import CATEGORIES, DebateSession
from werewolf_web.research.debate_fixtures import prepare_case, run_case


class DebateProtocolTest(unittest.TestCase):
    def fresh(self):
        archive = PublicArchive(("A", "B", "C"))
        notebooks = {a: PrivateNotebook(a, archive) for a in archive.players}
        session = DebateSession(archive, notebooks)
        tables = {a: (PrivateTable(a, 1, "D1", 0, tuple(Guess(p) for p in archive.players)),
                      PublicTable(a, 1, "D1", 0, tuple(Guess(p) for p in archive.players)))
                  for a in archive.players}
        return session, tables

    def test_drafts_are_sealed_and_incomplete_round_cannot_open(self):
        session, tables = self.fresh()
        before = session.player_view("B")
        replay_before = session.player_replay("B")
        session.submit("A", *tables["A"])
        self.assertEqual(session.player_view("B"), before)
        self.assertEqual(session.player_replay("B"), replay_before)
        with self.assertRaises(ValueError):
            session.open_debate()
        self.assertEqual(session.archive.sequence, 0)
        self.assertEqual(session.player_view("A")["own"]["notebook"]["tables"], [])
        for a in ("B", "C"):
            session.submit(a, *tables[a])
        session.open_debate()
        self.assertEqual(session.state, "debating")
        self.assertEqual(len(session.archive.history()), 3)

    def test_bad_submission_is_retryable_without_saving_private_state(self):
        session, tables = self.fresh()
        private, public = tables["A"]
        with self.assertRaises(ValueError):
            session.submit("A", private, replace(public, guesses=(Guess("A"),)))
        self.assertEqual(session.player_view("A")["own"]["notebook"]["tables"], [])
        session.submit("A", private, public)
        with self.assertRaises(ValueError):
            session.submit("A", private, public)

    def test_wrong_owner_phase_and_stale_archive_rejected(self):
        session, tables = self.fresh()
        with self.assertRaises(ValueError):
            session.submit("B", *tables["A"])
        with self.assertRaises(ValueError):
            session.submit("A", tables["A"][0], replace(tables["A"][1], phase="D2"))
        session.archive.append_event("D1", "External mutation")
        with self.assertRaises(ValueError):
            session.submit("A", *tables["A"])

    def test_response_must_match_target_and_pending_question(self):
        session, evidence = prepare_case()
        cid = session.challenge("A", "B", 1, "D", evidence, "Explain")
        before = session.archive.sequence
        with self.assertRaises(ValueError):
            session.respond("C", cid, "Answer")
        with self.assertRaises(ValueError):
            session.respond("B", "wrong", "Answer")
        with self.assertRaises(ValueError):
            session.challenge("C", "B", 1, "D", evidence, "Interrupt")
        with self.assertRaises(ValueError):
            session.assess("A", cid, "unresolved_contradiction", "Too early")
        self.assertEqual(session.archive.sequence, before)
        session.respond("B", cid, "Response")
        with self.assertRaises(ValueError):
            session.respond("B", cid, "Duplicate")

    def test_challenge_references_and_budgets(self):
        session, evidence = prepare_case()
        before = session.archive.sequence
        for ref in ("P:B:1", "E999999"):
            with self.assertRaises(KeyError):
                session.challenge("A", "B", 1, "D", (ref,), "Explain")
        with self.assertRaises(KeyError):
            session.challenge("A", "B", 999, "D", evidence, "Explain")
        self.assertEqual(session.archive.sequence, before)
        cid = session.challenge("A", "B", 1, "D", evidence, "Explain")
        session.respond("B", cid, "Response")
        with self.assertRaises(ValueError):
            session.challenge("A", "B", 1, "D", evidence, "Repeat")
        second = session.challenge("C", "B", 1, "D", evidence, "Again")
        session.respond("B", second, "Response")
        with self.assertRaises(ValueError):
            session.challenge("G", "B", 1, "D", evidence, "Third")

    def test_host_closure_and_one_action_per_actor(self):
        session, evidence = prepare_case()
        with self.assertRaises(ValueError):
            session.act("A", "B", "Too early")
        session.challenge("A", "B", 1, "D", evidence, "Explain")
        with self.assertRaises(ValueError):
            session.close("Close")
        session.close("Host explicitly closes unanswered discussion", force=True)
        with self.assertRaises(ValueError):
            session.challenge("C", "B", 1, "D", evidence, "Too late")
        session.act("A", "B", "Choice")
        with self.assertRaises(ValueError):
            session.act("A", "C", "Duplicate")
        with self.assertRaises(ValueError):
            session.act("B", "B", "Self")
        self.assertEqual(session.player_view("A")["own"]["notebook"]["decisions"][0]["action"], "vote:B")


class ObserverReactionTest(unittest.TestCase):
    def responded(self, category="unresolved_contradiction"):
        session, evidence = prepare_case(category)
        cid = session.challenge("A", "B", 1, "D", evidence, "Explain")
        session.respond("B", cid, "Hand-authored response")
        return session, evidence, cid

    def test_strong_independent_updates_and_private_table_drives_choice(self):
        session, _, cid = self.responded()
        self.assertEqual(session.suggested_target("A"), "D")
        for a in ("A", "G"):
            session.assess(a, cid, "unresolved_contradiction", "History denial")
        a = session.player_view("A")["own"]
        g = session.player_view("G")["own"]
        self.assertAlmostEqual(a["opinions"]["B"]["suspicion"], 0.77)
        self.assertAlmostEqual(g["opinions"]["B"]["suspicion"], 0.63)
        self.assertEqual(session.suggested_target("A"), "B")
        row = next(r for r in a["notebook"]["tables"][-1]["guesses"] if r["player"] == "B")
        self.assertEqual(row["roles"], ("werewolf",))
        self.assertEqual(session.archive.table("A", 1).guesses[1].status, "unknown")

    def test_reasonable_conditional_hidden_and_uncertain_are_not_penalized(self):
        for category in CATEGORIES - {"unresolved_contradiction"}:
            with self.subTest(category=category):
                session, _, cid = self.responded(category)
                before = session.player_view("A")["own"]["opinions"]["B"]
                session.assess("A", cid, category, "Accept or reserve judgment")
                self.assertEqual(session.player_view("A")["own"]["opinions"]["B"], before)

    def test_known_wolf_identity_survives_loss_of_credibility(self):
        session, _, cid = self.responded()
        session.assess("F", cid, "unresolved_contradiction", "My ally contradicted itself")
        own = session.player_view("F")["own"]
        self.assertEqual(own["opinions"]["B"]["suspicion"], 1.0)
        self.assertAlmostEqual(own["opinions"]["B"]["credibility"], 0.7)
        row = next(r for r in own["notebook"]["tables"][-1]["guesses"] if r["player"] == "B")
        self.assertEqual((row["roles"], row["status"]), (("werewolf",), "known"))

    def test_known_good_identity_is_not_overwritten(self):
        archive = PublicArchive(("A", "B"))
        old = archive.append_statement("B", "D0", "Prior statement")
        books = {a: PrivateNotebook(a, archive) for a in archive.players}
        fact = books["A"].observe("Lawful check: B is good")
        session = DebateSession(archive, books)
        session.submit("A", PrivateTable("A", 1, "D1", 1, (Guess("A"),
            Guess("B", ("good",), "known", "high", (fact.event_id,)))),
            PublicTable("A", 1, "D1", 1, (Guess("A"), Guess("B"))))
        session.submit("B", PrivateTable("B", 1, "D1", 1, (Guess("A"), Guess("B"))),
                       PublicTable("B", 1, "D1", 1, (Guess("A"), Guess("B"))))
        session.open_debate()
        cid = session.challenge("A", "B", 1, "A", (old.event_id,), "Explain")
        session.respond("B", cid, "Denial")
        session.assess("A", cid, "unresolved_contradiction", "Bad public argument")
        own = session.player_view("A")["own"]
        self.assertEqual(own["opinions"]["B"]["suspicion"], 0.0)
        self.assertLess(own["opinions"]["B"]["credibility"], 1.0)

    def test_repeated_source_does_not_stack(self):
        session, evidence, cid = self.responded()
        session.assess("A", cid, "unresolved_contradiction", "First")
        before = session.player_view("A")
        with self.assertRaises(ValueError):
            session.assess("A", cid, "unresolved_contradiction", "Duplicate")
        second = session.challenge("C", "B", 1, "D", evidence, "Same underlying dispute")
        session.respond("B", second, "Again")
        with self.assertRaises(ValueError):
            session.assess("A", second, "unresolved_contradiction", "Another person said it")
        self.assertEqual(session.player_view("A")["own"], before["own"])

    def test_different_observers_may_disagree(self):
        session, _, cid = self.responded()
        session.assess("A", cid, "unresolved_contradiction", "Not explained")
        session.assess("C", cid, "strategic_concealment", "Plausible cover")
        self.assertGreater(session.player_view("A")["own"]["opinions"]["B"]["suspicion"], 0.7)
        self.assertEqual(session.player_view("C")["own"]["opinions"]["B"]["suspicion"], 0.35)


class ReplayAndFixtureTest(unittest.TestCase):
    def test_private_updates_do_not_leak_through_views_or_frame_counts(self):
        session, evidence = prepare_case()
        cid = session.challenge("A", "B", 1, "D", evidence, "Explain")
        session.respond("B", cid, "Answer")
        other_view, other_replay = session.player_view("C"), session.player_replay("C")
        research_len = len(session.research_replay())
        session.assess("A", cid, "unresolved_contradiction", "PRIVATE_ASSESSMENT_A")
        self.assertEqual(session.player_view("C"), other_view)
        self.assertEqual(session.player_replay("C"), other_replay)
        self.assertEqual(len(session.research_replay()), research_len + 1)
        self.assertNotIn("PRIVATE_ASSESSMENT_A", json.dumps(session.player_replay("C")))
        self.assertIn("PRIVATE_ASSESSMENT_A", json.dumps(session.player_replay("A")))

    def test_replay_is_historical_and_detached(self):
        session = run_case(locale="en")
        replay = session.research_replay()
        initial = next(f for f in replay if f["cause"] == "tables_released")
        final = replay[-1]
        self.assertEqual(len(initial["owners"]["A"]["notebook"]["tables"]), 1)
        self.assertEqual(len(final["owners"]["A"]["notebook"]["tables"]), 2)
        replay[-1]["owners"]["A"]["notebook"]["actor"] = "tampered"
        self.assertEqual(session.research_replay()[-1]["owners"]["A"]["notebook"]["actor"], "A")

    def test_all_labelled_cases_complete_in_both_languages(self):
        for category in CATEGORIES:
            for locale in ("zh-CN", "en"):
                with self.subTest(category=category, locale=locale):
                    session = run_case(category, locale)
                    self.assertEqual(session.state, "complete")
                    for actor in session.archive.players:
                        owner = session.player_view(actor)["own"]
                        self.assertEqual(len(owner["notebook"]["decisions"]), 1)
                        self.assertEqual(owner["notebook"]["decisions"][0]["table_version"],
                                         owner["notebook"]["tables"][-1]["version"])
                    public = json.dumps(session.archive.export())
                    self.assertNotIn("PRIVATE[", public)
                    self.assertNotIn("hand_authored_observer_annotation", public)
                    self.assertNotIn("known_faction", public)

    def test_public_action_can_differ_from_private_view(self):
        session = run_case(locale="en")
        f = session.player_view("F")["own"]
        self.assertEqual(f["opinions"]["B"]["known_faction"], True)
        self.assertEqual(f["notebook"]["decisions"][0]["action"], "vote:D")
        self.assertEqual(session.archive.table("F", 1).guesses[1].status, "unknown")


if __name__ == "__main__":
    unittest.main()
