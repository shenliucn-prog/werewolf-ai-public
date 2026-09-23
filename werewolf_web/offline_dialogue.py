"""Deterministic situational dialogue derived exclusively from public sources.

No role allocations, private results or model calls belong in this layer.
Candidates are options, not a correct-answer recommendation.
"""
from dataclasses import asdict
from .ai.brain import Speech
from .check_claims import audit
from .social_actions import make


def reply_choices(events, actor, asker, locale, questions=()):
    """Answer this person's latest public question, without private evidence.

    Explicit stance fields are authoritative; quoted text is never re-parsed.
    Derived from the durable ledger so recovery needs no parallel memory.
    """
    en = locale == "en"
    refs = {q.get("event_no") for q in questions if q.get("from") == asker
            and type(q.get("event_no")) is int}
    question = next((e for e in reversed(events) if e.get("type") == "speech"
                     and e.get("name") == asker
                     and (e.get("event_no") in refs or e.get("question_to") == actor
                          or e.get("accuse") == actor)), None)
    if question is None or type(question.get("event_no")) is not int:
        return []
    ref = question["event_no"]
    options = []

    def add(intent, text):
        options.append({"id": f"reply:{ref}:{intent}", "topic": "direct_reply",
                        "group": "Answer this question" if en else "回应这次追问",
                        "label": text, "action": make(intent, asker, [ref], ref),
                        "speech": asdict(Speech(text=text, social_action=make(intent, asker, [ref], ref)))})

    own = next((e for e in reversed(events) if e.get("type") == "speech"
                and e.get("name") == actor and e.get("event_no", ref) < ref), None)
    if own and (own.get("accuse") or own.get("defend")):
        target = own.get("accuse") or own.get("defend")
        position = ("suspected" if own.get("accuse") else "supported") if en else (
            "怀疑" if own.get("accuse") else "支持")
        add("explain_stance", f"{asker}, in record {own['event_no']} I {position} {target}. That was my judgment, not a confirmed check." if en else
            f"{asker}，我在记录{own['event_no']}里{position}{target}。那是我的判断，不是已证实的查验。")
    add("reserve_judgment", f"{asker}, I heard your question in record {ref}. I have no new public evidence; I am reserving judgment, not clearing anyone." if en else
        f"{asker}，记录{ref}的追问我听到了。我没有新的公开依据，先保留判断，不代表认谁是好人。")
    if question.get("accuse") == actor:
        add("request_basis", f"{asker}, record {ref} suspects me. Please identify the statement or ballot behind that judgment." if en else
            f"{asker}，记录{ref}里你怀疑我，请指出依据是哪句话或哪一票。")
    return options


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
    priorities = {"social_feedback": 7, "revealed_report": 6, "receive_wolf": 5, "receive_good": 4, "accused": 3,
                  "counterclaim": 2 + style.logic, "hear_target": 1 + style.aggression, "opening": 0}
    def score(c):
        if c["topic"] == "social_feedback":
            return priorities[c["topic"]], -options.index(c), 0
        social = style.loyalty if ":thanks:" in c["id"] else style.caution
        return priorities[c["topic"]], social, -len(c["label"])
    return max(fresh, key=score) if fresh else None
