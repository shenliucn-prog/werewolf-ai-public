"""Deterministic situational dialogue derived exclusively from public sources.

No role allocations, private results or model calls belong in this layer.
Candidates are options, not a correct-answer recommendation.
"""
from dataclasses import asdict
from .ai.brain import Speech
from .check_claims import audit


def contextual_choices(entries, seats, actor, locale):
    en = locale == "en"
    choices = []
    def add(key, text, topic, **fields):
        choices.append({"id": "context:" + key, "group": "This discussion" if en else "接着桌上的话",
                        "label": text, "topic": topic,
                        "speech": asdict(Speech(text=text, **fields))})
    reports = audit(entries)["reports"]
    # A revealed role is public evidence, but the report remains attributed.
    # Include dead claimants here; filtering all reports to alive seats loses
    # exactly the information the table should revisit after a seer dies.
    for row in reversed(entries):
        ev = row["event"]
        if (ev.get("type") != "flip" or type(ev.get("event_no")) is not int
                or (ev.get("role") or ev.get("role_cn")) not in ("seer", "预言家", "Seer")):
            continue
        who = ev.get("seat")
        for r in reports:
            if r["actor"] != who or r["target"] not in seats:
                continue
            target, ref = r["target"], r["event_no"]
            result = r["result"] if en else ("好人" if r["result"] == "good" else "狼人")
            add(f"revealed:{ev['event_no']}:{ref}",
                f"Record {ev['event_no']} reveals #{who} as Seer. In record {ref}, they called #{target} {result}. That report deserves review, not automatic certainty." if en else
                f"记录{ev['event_no']}显示{who}号翻牌为预言家；其记录{ref}称{target}号是{result}。应重新考虑这份声明，但不能自动当作查验已证实。",
                "revealed_report")
    latest = {}
    for report in reports:
        if report["actor"] in seats:
            latest[report["actor"]] = report
    if not latest:
        add("opening", "Let's hear anyone with a report before rushing to a target." if en else
            "先让有信息的人把话说完，不急着选出局对象。", "opening")
    # Respond to a personal report before moving on to an unrelated target.
    for r in reversed(list(latest.values())):
        who, target = r["actor"], r["target"]
        if who == actor or target != actor:
            continue
        ref = r["event_no"]
        if r["result"] == "good":
            add(f"thanks:{ref}", f"#{who}, I heard your good report on me. I will hear the other claims before trusting you." if en else
                f"{who}号，你给我的金水我听到了，但我还要听其他人的说法，不能因此就认你。",
                "receive_good")
            add(f"probe:{ref}", f"#{who}, why did you choose to check me? A good report alone does not win my trust." if en else
                f"{who}号，为什么选择验我？给我金水不等于我就信你。", "receive_good", question_to=seats[who])
        else:
            add(f"deny:{ref}", f"#{who}, I reject your wolf report on me. Explain why the table should trust your claim." if en else
                f"{who}号，你给我的查杀我不认。请说明大家为什么应该相信你的预言家声明。",
                "receive_wolf", question_to=seats[who])
    if len(latest) > 1:
        names = ", ".join(f"#{n}" for n in latest)
        for who, r in latest.items():
            if who == actor:
                continue
            add(f"contest:{r['event_no']}", f"#{who}, {names} all claim seer. How do you account for the competing reports?" if en else
                f"{who}号，{names}都跳了预言家，你怎么看另外几份报告？",
                "counterclaim", question_to=seats[who])
        add("hear:" + "-".join(str(r["event_no"]) for r in latest.values()),
            "Several seers have claimed. Hear their reasons before treating any report as established." if en else
            "现在有预言家对跳，先把各自的理由听完整，别把任何一份报告直接当结论。",
            "counterclaim")
    # Respond to direct public suspicion rather than emitting a generic slogan.
    for row in reversed(entries[-24:]):
        ev = row["event"]
        who = ev.get("seat")
        if who not in seats or who == actor or ev.get("type") != "speech":
            continue
        if ev.get("accuse") == seats.get(actor):
            add(f"basis:{ev['event_no']}", f"#{who}, which statement or ballot of mine supports your suspicion?" if en else
                f"{who}号，你怀疑我，依据是我的哪句话或哪一票？", "accused", question_to=seats[who])
            break
    # An attributed alternative to echoing a naked suspicion. No accuse field:
    # quoting a report is not another independent piece of evidence.
    for who, r in latest.items():
        if who == actor or r["result"] != "wolf" or r["target"] not in seats:
            continue
        target = r["target"]
        add(f"hear-target:{r['event_no']}", f"#{target}, #{who} reported you as wolf. I want your response before deciding whether that report is credible." if en else
            f"{target}号，{who}号给了你查杀，我想先听你的回应，再判断这份报告可信不可信。",
            "hear_target", question_to=seats[target])
    return choices


def shortlist(options):
    """At most three different discussion topics plus a neutral pass."""
    selected, topics = [], set()
    for option in options:
        topic = option.get("topic")
        if topic and topic not in topics and len(selected) < 3:
            selected.append(option)
            topics.add(topic)
    wait = next((o for o in options if o["id"] == "wait"), None)
    if wait:
        selected.append(wait)
    return selected


def choose_reaction(options, own_speeches, style, table_speeches=()):
    # Cross-speaker repetition is still repetition. Only public recent speech
    # is consulted; the candidate text includes the report reference/target.
    fresh = [c for c in options if c.get("topic") and
             not any(ev.get("text", "").endswith(c["label"])
                     for ev in [*own_speeches, *table_speeches])]
    priorities = {"revealed_report": 6, "receive_wolf": 5, "receive_good": 4, "accused": 3,
                  "counterclaim": 2 + style.logic, "hear_target": 1 + style.aggression, "opening": 0}
    def score(c):
        social = style.loyalty if ":thanks:" in c["id"] else style.caution
        return priorities[c["topic"]], social, -len(c["label"])
    return max(fresh, key=score) if fresh else None
