"""Hand-authored offline debates; labels are fixtures, not classifier outputs.

CLI defaults to one player's view. All-owner research export requires the
explicit --research flag. No models, live game, or network are involved.
"""

import argparse
from dataclasses import replace
import json

from .conjecture import Guess, PrivateNotebook, PrivateTable, PublicArchive, PublicTable
from .debate import CATEGORIES, DebateSession


def prepare_case(category: str = "unresolved_contradiction", locale: str = "zh-CN"):
    if category not in CATEGORIES or locale not in {"zh-CN", "en"}:
        raise ValueError("unsupported case or locale")
    en = locale == "en"
    roster = tuple("ABCDEFG")
    archive = PublicArchive(roster)
    old_text = ("If E is a wolf, D leans good." if en else "如果 E 是狼，D 偏好人。") \
        if category == "different_conditions" else (
            "D's explanation makes sense; I lean good on D." if en else "D 的解释说得通，我偏向 D 是好人。")
    old = archive.append_statement("B", "D0", old_text)
    evidence = (old.event_id,)
    if category == "reasonable_revision":
        reveal = archive.append_statement("D", "D1", (
            "I fabricated my earlier accusation against E." if en else "我之前对 E 的指控是编造的。"))
        evidence += (reveal.event_id,)
    notebooks = {a: PrivateNotebook(a, archive) for a in roster}
    roles = dict(zip(roster, ("seer", "werewolf", "villager", "villager",
                             "villager", "werewolf", "villager")))
    observations = {a: notebooks[a].observe(
        f"PRIVATE[{a}] role={roles[a]}") for a in roster}
    mate_refs = {}
    for a in roster:
        if roles[a] == "werewolf":
            mate = next(p for p in roster if p != a and roles[p] == "werewolf")
            mate_refs[a] = (mate, notebooks[a].observe(f"PRIVATE[{a}] teammate={mate}"))
    session = DebateSession(archive, notebooks, sensitivities={"A": 1.2, "G": 0.8})
    for a in roster:
        private_rows = []
        public_rows = []
        for p in roster:
            if p == a:
                private_rows.append(Guess(p, (roles[a],), "known", "high", (observations[a].event_id,)))
            elif a in mate_refs and p == mate_refs[a][0]:
                private_rows.append(Guess(p, ("werewolf",), "known", "high", (mate_refs[a][1].event_id,)))
            elif a == "A" and p == "D":
                private_rows.append(Guess(p, ("werewolf",), "inferred", "medium",
                                          rationale="Initial hypothesis." if en else "初始假设。"))
            else:
                private_rows.append(Guess(p))
            if a == "B" and p == "D":
                rationale = {
                    "reasonable_revision": "New public evidence." if en else "依据新的公开证据。",
                    "different_conditions": "If E is good, D is a wolf." if en else "如果 E 是好人，D 是狼。",
                }.get(category, "I claim I checked D as wolf on night one." if en else "我声称首夜查验 D 为狼。")
                public_rows.append(Guess(p, ("werewolf",), "claimed", "high",
                                         evidence[1:] if category == "reasonable_revision" else (), rationale))
            elif p == a:
                public_rows.append(Guess(p, ("good",), "claimed", rationale=(
                    "I claim to be good." if en else "我自述为好人。")))
            else:
                public_rows.append(Guess(p))
        session.submit(a, PrivateTable(a, 1, "D1", archive.sequence, tuple(private_rows)),
                       PublicTable(a, 1, "D1", archive.sequence, tuple(public_rows)))
    session.open_debate()
    return session, evidence


def run_case(category: str = "unresolved_contradiction", locale: str = "zh-CN") -> DebateSession:
    session, evidence = prepare_case(category, locale)
    en = locale == "en"
    question = "Explain your current judgment on D relative to your earlier statement." if en else "请解释你现在对 D 的判断与之前说法的关系。"
    challenge = session.challenge("A", "B", 1, "D", evidence, question)
    responses = {
        "reasonable_revision": ("D's public admission changed my assessment, without proving a role.",
                                "D 的公开承认改变了我的判断，但不等于证实身份。"),
        "different_conditions": ("The two judgments have different conditions about E.", "两条判断对 E 的身份有不同前提。"),
        "strategic_concealment": ("I was hiding my role to observe D's reaction.", "我是在隐藏身份，观察 D 的反应。"),
        "unresolved_contradiction": ("I never said D leaned good.", "我从未说过 D 偏好人。"),
        "insufficient_evidence": ("I am not ready to explain that yet.", "我暂时不准备解释。"),
    }
    session.respond("B", challenge, responses[category][0 if en else 1])
    annotation = "Hand-labelled fixture assessment based on the cited public record and response." if en else "基于所引公开记录与回应的人工案例标注。"
    # Observers receive their own labels. C deliberately withholds judgment;
    # no single omniscient classification is broadcast to the entire table.
    for observer in ("A", "F", "G"):
        session.assess(observer, challenge, category, annotation)
    session.assess("C", challenge, "insufficient_evidence",
                   "I reserve judgment." if en else "我保留判断。")
    if category == "unresolved_contradiction":
        original = session.archive.table("A", 1)
        guesses = tuple(Guess("B", ("werewolf",), "inferred", "medium", evidence,
                              "The denial conflicts with the public record." if en else "否认与公开历史冲突。")
                        if g.player == "B" else g for g in original.guesses)
        session.revise("A", replace(original, version=2, as_of=session.archive.sequence,
                                    guesses=guesses, revision_reason=(
                                        "Publishing my revised position." if en else "公开修订我的立场。")))
    session.close("Discussion closed; choose actions independently." if en else "讨论收束，各自选择行动。")
    for actor in session.archive.players:
        # F can publicly support the attack on D despite its private assessment
        # of B. This is a deliberate action policy, not a leak of F's notebook.
        target = "D" if actor == "F" else session.suggested_target(actor)
        session.act(actor, target, "My public voting choice." if en else "这是我的公开投票选择。")
    return session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(CATEGORIES), default="unresolved_contradiction")
    parser.add_argument("--locale", choices=("zh-CN", "en"), default="zh-CN")
    parser.add_argument("--actor", choices=tuple("ABCDEFG"), default="A")
    parser.add_argument("--research", action="store_true", help="Explicitly export ALL private views")
    args = parser.parse_args()
    session = run_case(args.case, args.locale)
    output = session.research_replay() if args.research else session.player_replay(args.actor)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
