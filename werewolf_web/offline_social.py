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
            return []  # Do not revive older answers after closing the latest.
        # Don't revive an old day's conversation after the host moved on.
        latest_day = max((e.get("day", 0) for e in events), default=0)
        if event.get("day", 0) != latest_day:
            return []
        rapport = relationships(events, observer, style).get(who, {}).get("rapport", 0)
        en = locale == "en"
        texts = {
            "acknowledge": f"{who}, that answers my question. It doesn't settle your role, but I'll leave it there." if en else
                f"{who}，解释我听到了，这个问题先放下。身份还得继续看。",
            "stand_firm": f"{who}, I hear you, but I'm not convinced. Let's hear the others." if en else
                f"{who}，你解释了，但我还没被说服。先听其他人。",
            "reconsider": f"{who}, I'll rethink my read after that. I want to hear another side." if en else
                f"{who}，听完你的解释，我再想想，也听听别人怎么说。",
        }
        preferred = ("stand_firm" if style.caution + style.aggression > 1.25 and rapport <= .1
                     else "acknowledge" if style.loyalty + rapport > .65 else "reconsider")
        kinds = [preferred] + [k for k in texts if k != preferred]
        return [{"id": f"feedback:{ref}:{kind}", "topic": "social_feedback",
                 "group": "After the answer" if en else "听完解释之后",
                 "label": texts[kind], "speech": asdict(Speech(text=texts[kind],
                 social_action=make(kind, who, [ref], ref)))} for kind in kinds]
    return []
