"""The choice game's fixed cast. Personalities never determine game roles."""
from dataclasses import dataclass
from .ai.brain import Style
from .i18n import cast


@dataclass(frozen=True)
class Character:
    id: str
    description: tuple[str, str]
    phrase: tuple[str, str]
    # aggression, logic, bluff, loyalty, caution, verbosity
    weights: tuple[float, ...]

    def style(self):
        return Style(*self.weights)


CHARACTERS = (
    Character("acheng", ("温和组织者，重视合作，但可能过度调和。", "A warm organizer; cooperative, sometimes too conciliatory."), ("先让每个人说清楚。", "Let's hear everyone out."), (.4,.7,.4,.8,.6,.5)),
    Character("xiaoman", ("锋利辩手，善抓矛盾，但有时过度解读措辞。", "A sharp debater who can overread wording."), ("把前后两句话放在一起看。", "Compare those two statements."), (.8,.8,.7,.4,.3,.7)),
    Character("laomai", ("幽默老玩家，化解紧张，但玩笑容易损害可信度。", "A witty veteran whose humor can undermine credibility."), ("先别急着把茶杯摔了。", "Let's not smash the teacups yet."), (.4,.6,.7,.6,.6,.6)),
    Character("yexiao", ("安静观察者，注重细节，但不常主动带队。", "A quiet observer, attentive but reluctant to lead."), ("我补一个细节。", "One detail to add."), (.2,.8,.3,.6,.9,.2)),
    Character("tiandou", ("热情联结者，乐于支持别人，也容易轻信。", "A sociable ally who sometimes trusts too readily."), ("我们可以先把话说开。", "Let's talk this through."), (.5,.4,.4,.9,.3,.7)),
    Character("dashan", ("坚定行动派，敢带队，也不容易改判。", "A decisive leader who is slow to change course."), ("我先给结论。", "Here is my call."), (.9,.4,.5,.8,.2,.6)),
    Character("xicao", ("谨慎分析者，区分事实与声明，但可能过于保守。", "An evidence-focused analyst, sometimes overcautious."), ("证据具体是哪一条？", "Which record supports that?"), (.3,.95,.3,.5,.9,.5)),
    Character("aman", ("挑战权威者，质疑共识，但容易过度反对。", "A challenger of consensus who can be contrarian."), ("多数人的意见也要检查。", "The majority needs scrutiny too."), (.8,.7,.6,.3,.4,.6)),
    Character("xiaolu", ("善于倾听，准确回应，但可能替别人解释过多。", "An attentive listener who sometimes over-defends others."), ("我听到的意思是这样。", "Here is what I heard."), (.3,.7,.4,.8,.6,.5)),
    Character("alan", ("灵活谈判者，愿意调整立场，但容易显得摇摆。", "A flexible negotiator who can look inconsistent."), ("有新信息，我会改判断。", "New evidence can change my mind."), (.5,.7,.8,.5,.5,.5)),
    Character("aji", ("大胆试探者，制造信息，也可能误伤。", "A bold tester whose probes can backfire."), ("我想试探一下这个说法。", "Let's test that claim."), (.85,.5,.85,.4,.15,.6)),
    Character("amo", ("冷幽默怀疑者，找替代解释，也可能怀疑过头。", "A dry skeptic who explores alternatives, sometimes too many."), ("也有另一种解释。", "There is another explanation."), (.5,.8,.6,.4,.7,.4)),
)
BY_ID = {p.id: p for p in CHARACTERS}


def cast_settings(replace, locale, name=None):
    if replace not in BY_ID:
        raise ValueError("Unknown character")
    mapping = {p["id"]: p["id"] for p in cast(locale)}
    mapping["acheng"], mapping[replace] = mapping[replace], mapping["acheng"]
    display = {p["id"]: p["name"] for p in cast(locale)}
    names = {identity: display[character] for identity, character in mapping.items()}
    if name:
        names["acheng"] = name
    return mapping, names
