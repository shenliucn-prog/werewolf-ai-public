"""Opt-in, public-information discussion prototype; not a Werewolf match.

No engine, model, credentials, hidden roles, saves or campaign writes. The
fixed scenario lets designers compare choices before integrating a full game.
"""
from dataclasses import dataclass
import argparse


def localized(pair, lang):
    return pair[lang == "en"]


@dataclass(frozen=True)
class Persona:
    seat: int
    name: tuple[str, str]
    evidence_weight: float
    admission_weight: float
    refusal_weight: float


# Weights are experimental policy sensitivities, NOT truth probabilities.
PERSONAS = (
    Persona(2, ("大山", "Dashan"), .65, .15, .9),
    Persona(3, ("细草", "Xicao"), 1.0, .4, .25),
    Persona(4, ("阿蛮", "Aman"), .45, .25, .3),
    Persona(5, ("甜豆", "Tiandou"), .7, .8, .7),
)


@dataclass(frozen=True)
class Record:
    number: int
    actor: int
    kind: str
    target: int
    text: tuple[str, str]


RECORDS = (
    Record(1, 1, "support", 2, ("第1天发言：你说暂时支持2号。", "Day 1 speech: you tentatively supported seat 2.")),
    Record(2, 3, "claim", 2, ("随后3号声称是预言家，报告2号为狼；身份和报告均未证实。", "Later, seat 3 claimed seer and reported seat 2 as wolf; neither claim is verified.")),
    Record(3, 1, "vote", 2, ("之后的放逐投票：你投了2号，平票无人出局。", "Subsequent exile ballot: you voted for seat 2. A tie meant no exile.")),
)


@dataclass(frozen=True)
class Choice:
    id: str
    text: tuple[str, str]
    kind: str
    target: int
    evidence: tuple[int, ...] = ()


REPLIES = (
    Choice("reply:evidence", ("引用记录2：新报告让我改判，但报告还不是事实。", "Cite record 2: the new report changed my view, but it is not proven."), "explain", 1, (2,)),
    Choice("reply:admit", ("承认改判：当时跟了票，没有更多证据。", "Admit changing my view: I followed the vote without additional evidence."), "admit", 1),
    Choice("reply:refuse", ("拒绝解释这次改票。", "Decline to explain the changed vote."), "refuse", 1),
)
MOVES = (
    Choice("move:accuse", ("怀疑2号：引用3号的报告，但保留真假判断。", "Suspect seat 2, citing seat 3's still-unverified report."), "accuse", 2, (2,)),
    Choice("move:challenge", ("追问3号：报告之外，有没有公开证据支持？", "Ask seat 3: is there public evidence beyond your report?"), "question", 3, (2,)),
    Choice("move:support", ("暂时保留2号：单方面报告不足以定案。", "Provisionally defend seat 2: one claim is not enough to settle this."), "support", 2, (2,)),
)


class DiscussionLab:
    """One bounded reply/topic/vote loop with immutable source references.

    submit validates against the current menu before mutating anything. IDs
    are stage-specific so stale/repeated actions cannot be applied twice.
    """
    def __init__(self, lang="zh-CN"):
        if lang not in ("zh-CN", "en"):
            raise ValueError("Unsupported locale")
        self.lang = lang
        self.stage = "reply"
        self.answered = False
        self.events = []
        self.votes = {}
        self.scores = {
            p.seat: {seat: (0.55 if seat == 1 else 0.45) for seat in range(1, 6) if seat != p.seat}
            for p in PERSONAS
        }
        self._emit(0, "question", ("主持人：2号追问你，为什么先支持他、后来又投他？请回应。", "Host: seat 2 asks why you supported them and then voted for them. Please respond."), (1, 3))

    def _emit(self, actor, kind, text, evidence=()):
        self.events.append({"event_no": len(self.events) + 1, "actor": actor,
                            "kind": kind, "text": localized(text, self.lang),
                            "source_records": list(evidence)})

    def choices(self):
        if self.stage == "reply":
            return REPLIES
        if self.stage == "move":
            return MOVES
        if self.stage == "vote":
            return tuple(Choice(f"vote:{seat}", (f"投{seat}号", f"Vote for seat {seat}"), "vote", seat)
                         for seat in range(2, 6)) + (Choice("vote:skip", ("弃票", "Abstain"), "vote", 0),)
        return ()

    def _adjust(self, observer, target, delta):
        if target in self.scores[observer]:
            self.scores[observer][target] = round(max(0, min(1, self.scores[observer][target] + delta)), 4)

    def submit(self, choice_id):
        choice = next((c for c in self.choices() if c.id == choice_id), None)
        if choice is None:
            raise ValueError("Choose an option from the current stage")
        start = len(self.events)
        self._emit(1, choice.kind, choice.text, choice.evidence)
        if self.stage == "reply":
            for p in PERSONAS:
                delta = {"explain": -.3 * p.evidence_weight,
                         "admit": -.15 * p.admission_weight,
                         "refuse": .2 * p.refusal_weight}[choice.kind]
                self._adjust(p.seat, 1, delta)
            # Response consumed exactly once, including a refusal. The pending
            # question is never inferred answered just because someone spoke.
            self.answered = True
            reply = {
                "explain": ("细草：记录2确实早于你的投票，时间说得通；但这不证明你或报告是真的。", "Xicao: record 2 preceded your vote. That explains the timing, not your alignment or the report's truth."),
                "admit": ("细草：你承认了跟票，这回答了问题，但没有增加身份方面的证据。", "Xicao: admitting you followed answers the question, but adds no alignment evidence."),
                "refuse": ("细草：这次是拒绝回答，不是没收到问题。不能因此直接判你为狼。", "Xicao: this is a refusal, not a missed question. It does not establish that you are a wolf."),
            }[choice.kind]
            self._emit(3, "response", reply, (1, 2, 3))
            self._emit(0, "floor", ("主持人：这条追问已收束。你可以提出一个议题，其他人再回应。", "Host: that question is closed. Raise one topic, then others can respond."))
            self.stage = "move"
        elif self.stage == "move":
            if choice.kind in ("accuse", "support"):
                sign = 1 if choice.kind == "accuse" else -1
                for p in PERSONAS:
                    self._adjust(p.seat, 2, sign * .18 * p.evidence_weight)
                response = (
                    "大山：报告只是3号的说法。先把我列为嫌疑和直接认定我是狼，是两件事。",
                    "Dashan: that is seat 3's claim. Suspecting me and proving I am a wolf are different things.") if choice.kind == "accuse" else (
                    "大山：谢谢你没有直接定案。但你替我说话，也不能证明我们任何一人的身份。",
                    "Dashan: thanks for withholding judgment. Defending me does not prove either of our alignments.")
                self._emit(2, "response", response, (2,))
                self._emit(4, "interruption", (
                    "阿蛮：别只盯被报的人，也要审视报信息的人。现在没有独立验证。",
                    "Aman: examine the reporter too, not just the target. There is no independent verification."), (2,))
            else:
                # No invented investigation results. This scenario contains no
                # independent public confirmation; a question is not an accusation.
                self._emit(3, "response", ("细草：没有独立的公开证据。现在这仍只是我的查验声明。", "Xicao: there is no independent public evidence. This remains my claimed check."), (2,))
                self._emit(5, "interruption", ("甜豆：至少说清楚了证据边界，我们别把声明当翻牌。", "Tiandou: the evidence boundary is clearer. A claim is not a public role reveal."), (2,))
            self._emit(0, "close", ("主持人：本议题到此为止，进入投票。票型不是身份揭晓。", "Host: this topic is closed. Vote now; ballots do not reveal alignment."))
            self.stage = "vote"
        else:
            self.votes[1] = choice.target
            # Simultaneous information cutoff: NPC ballots depend on scores
            # before this ballot, never on the human's unrevealed vote.
            for p in PERSONAS:
                self.votes[p.seat] = max(self.scores[p.seat], key=lambda s: (self.scores[p.seat][s], -s))
            for actor, target in self.votes.items():
                self._emit(actor, "ballot", (f"{actor}号 → " + (f"{target}号" if target else "弃票"),
                                               f"Seat {actor} → " + (f"seat {target}" if target else "abstain")))
            self.stage = "done"
            self._emit(0, "complete", ("主持人：讨论样板结束。没有隐藏身份、出局或胜负；可重新运行比较另一种选择。", "Host: prototype complete. No hidden roles, elimination or winner; rerun to compare another choice."))
        return [dict(event, source_records=list(event["source_records"])) for event in self.events[start:]]


def main(argv=None, *, read=input, write=print):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=("zh-CN", "en"), default="zh-CN")
    args = parser.parse_args(argv)
    lab = DiscussionLab(args.lang)
    write(localized(("离线选项讨论样板 · 非完整对局 · 不计成绩 · 输入 q 退出", "Offline choice prototype · not a full match · no score · q to quit"), args.lang))
    write(localized(("1号：你", "Seat 1: you"), args.lang))
    for p in PERSONAS:
        write(f"{p.seat}: {localized(p.name, args.lang)}")
    for r in RECORDS:
        write(f"[{r.number}] {localized(r.text, args.lang)}")
    write(lab.events[0]["text"])
    while lab.choices():
        options = lab.choices()
        for index, option in enumerate(options, 1):
            write(f"{index}. {localized(option.text, args.lang)}")
        try:
            value = read("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if value.lower() == "q":
            return 0
        if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= len(options):
            write(localized(("请输入当前选项编号。", "Enter a current option number."), args.lang))
            continue
        for event in lab.submit(options[int(value) - 1].id):
            write(event["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
