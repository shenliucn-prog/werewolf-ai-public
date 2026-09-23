"""Replayable social reactions. Rapport is not probability of alignment.

Only public speech acts enter this module. No engine, hidden role, RNG, disk,
or model dependency; replaying the ledger reconstructs the same state.
"""
from dataclasses import asdict

from .ai.brain import Speech
from .social_actions import make

FEEDBACK = {"acknowledge", "stand_firm", "reconsider"}


def relationships(events, observer, style):
    rows, seen = {}, set()
    for event in events:
        action = event.get("social_action")
        who = event.get("name")
        if event.get("type") != "speech" or not action or not who or who == observer:
            continue
        signature = (event.get("day"), who, action["kind"], action["target"], tuple(action["sources"]))
        if signature in seen:
            continue
        seen.add(signature)
        row = rows.setdefault(who, {"rapport": 0.0, "openness": 0.0})
        kind = action["kind"]
        if action["target"] == observer:
            row["rapport"] += {"support": .08 * style.loyalty,
                               "suspect": -.08 * style.aggression,
                               "acknowledge": .02}.get(kind, 0)
            row["openness"] += {"explain_stance": .04 * style.logic,
                                "reserve_judgment": .02 * style.caution,
                                "refuse": -.04 * style.aggression}.get(kind, 0)
        for key in row:
            row[key] = round(max(-.3, min(.3, row[key])), 4)
    return rows


def feedback_choices(events, observer, style, locale):
    """One bounded follow-up to an answer addressed to this observer.

    No feedback creates a further question or mechanically certifies anyone.
    Returning to this function after recovery/replay cannot reopen a used reply.
    """
    used = {source for event in events if event.get("name") == observer
            and (event.get("social_action") or {}).get("kind") in FEEDBACK
            for source in event["social_action"]["sources"]}
    for event in reversed(events):
        action = event.get("social_action") or {}
        if (event.get("type") != "speech" or action.get("target") != observer
                or action.get("kind") not in {"explain_stance", "reserve_judgment", "refuse", "admit"}
                or type(event.get("event_no")) is not int):
            continue
        ref, who = event["event_no"], event["name"]
        if ref in used:
            continue
        # Don't revive an old day's conversation after the host moved on.
        latest_day = max((e.get("day", 0) for e in events), default=0)
        if event.get("day", 0) != latest_day:
            return []
        rapport = relationships(events, observer, style).get(who, {}).get("rapport", 0)
        en = locale == "en"
        texts = {
            "acknowledge": f"{who}, I heard your answer in record {ref}. That closes my question, not your identity." if en else
                f"{who}，记录{ref}的解释我听到了。这条先说到这，不代表身份已经确定。",
            "stand_firm": f"{who}, record {ref} answers my question, but does not settle my doubts. I will hear the others." if en else
                f"{who}，记录{ref}回答了问题，但我仍有保留。先听其他人，不继续追着你问。",
            "reconsider": f"{who}, after record {ref}, I will leave my judgment open and hear other accounts." if en else
                f"{who}，听完记录{ref}，我先不把判断说死，再听其他人的说法。",
        }
        preferred = ("stand_firm" if style.caution + style.aggression > 1.25 and rapport <= .1
                     else "acknowledge" if style.loyalty + rapport > .65 else "reconsider")
        kinds = [preferred] + [k for k in texts if k != preferred]
        return [{"id": f"feedback:{ref}:{kind}", "topic": "social_feedback",
                 "group": "After the answer" if en else "听完解释之后",
                 "label": texts[kind], "speech": asdict(Speech(text=texts[kind],
                 social_action=make(kind, who, [ref], ref)))} for kind in kinds]
    return []
