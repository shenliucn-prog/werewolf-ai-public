"""Deterministic seven-seat paper scenario; no engine, network, or model calls.

Run ``python -m werewolf_web.research.fixtures --locale en`` to print only the
public archive. This is a data/protocol demonstration, not AI reasoning evidence.
"""

import argparse
from dataclasses import dataclass, replace
import json

from .conjecture import Guess, PrivateNotebook, PrivateTable, PublicArchive, PublicTable


@dataclass
class ResearchFixture:
    archive: PublicArchive
    notebooks: dict[str, PrivateNotebook]


def seven_player_scenario(locale: str = "zh-CN") -> ResearchFixture:
    if locale not in {"zh-CN", "en"}:
        raise ValueError("supported locales: zh-CN, en")
    en = locale == "en"
    players = tuple("ABCDEFG")
    archive = PublicArchive(players)
    old = archive.append_statement(
        "B", "D1.discussion",
        "D's explanation makes sense for now; I lean good on D." if en
        else "D 的解释暂时说得通，我偏向 D 是好人。")
    notebooks = {actor: PrivateNotebook(actor, archive) for actor in players}
    # Ground truth is used only to provision this hand-authored fixture's lawful
    # private observations. It is never stored in PublicArchive.
    actual = dict(zip(players, ("seer", "werewolf", "villager", "villager",
                               "villager", "werewolf", "villager")))
    private_refs = {}
    for actor in players:
        private_refs[actor] = notebooks[actor].observe(
            f"Your role: {actual[actor]}" if en else f"你的身份：{actual[actor]}").event_id
    checked = notebooks["A"].observe("C checks good." if en else "查验 C：好人。").event_id
    b_mate = notebooks["B"].observe("F is your wolf teammate." if en else "F 是你的狼队友。").event_id
    f_mate = notebooks["F"].observe("B is your wolf teammate." if en else "B 是你的狼队友。").event_id

    for actor in players:
        rows = []
        for target in players:
            if target == actor:
                rows.append(Guess(target, (actual[target],), "known", "high",
                                  (private_refs[actor],)))
            elif actor == "A" and target == "C":
                rows.append(Guess(target, ("good",), "known", "high", (checked,)))
            elif (actor, target) in {("B", "F"), ("F", "B")}:
                rows.append(Guess(target, ("werewolf",), "known", "high",
                                  (b_mate if actor == "B" else f_mate,)))
            else:
                rows.append(Guess(target))
        notebooks[actor].save(PrivateTable(actor, 1, "D1.discussion", archive.sequence, tuple(rows)))

    tables = []
    for actor in players:
        rows = []
        for target in players:
            if actor == "B" and target == "B":
                rows.append(Guess(target, ("seer",), "claimed", "high", rationale=(
                    "I claim to be the seer." if en else "我声称自己是预言家。")))
            elif actor == "B" and target == "D":
                rows.append(Guess(target, ("werewolf",), "claimed", "high", rationale=(
                    "I claim I checked D on night one and found a wolf." if en
                    else "我声称第一夜查验 D 为狼。")))
            elif actor == target:
                rows.append(Guess(target, ("good",), "claimed", "medium", rationale=(
                    "I claim to be good; I am not declaring an exact role." if en
                    else "我自述为好人，暂不公开具体身份。")))
            else:
                rows.append(Guess(target, rationale="Undetermined." if en else "暂不判断。"))
        tables.append(PublicTable(actor, 1, "D1.discussion", archive.sequence, tuple(rows)))
    records = archive.publish_round(tuple(tables))
    b_public = next(r.event_id for r in records if r.actor == "B")
    archive.append_statement("A", "D1.challenge", (
        f"Compare {old.event_id} with {b_public}: why did you lean good on D after your claimed check?"
        if en else f"对照 {old.event_id} 和 {b_public}：为什么声称查验后还说 D 偏好人？"))
    archive.append_statement("B", "D1.response", (
        "I was hiding my role to observe D's reaction." if en
        else "我是在隐藏身份，观察 D 的反应。"))

    # Only AFTER all initial tables are public may F cite B's new testimony.
    original = archive.table("F", 1)
    rows = tuple(Guess("D", ("werewolf",), "inferred", "medium", (b_public,),
                       "Based on B's claim, not an independent check." if en
                       else "根据 B 的声称，不是我的独立查验。")
                 if row.player == "D" else row for row in original.guesses)
    archive.publish_revision(replace(
        original, version=2, phase="D1.revision", as_of=archive.sequence, guesses=rows,
        revision_reason="Responding to B's public claim." if en else "回应 B 的公开声称。"))
    return ResearchFixture(archive, notebooks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", choices=("zh-CN", "en"), default="zh-CN")
    args = parser.parse_args()
    fixture = seven_player_scenario(args.locale)
    print(json.dumps(fixture.archive.export(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
