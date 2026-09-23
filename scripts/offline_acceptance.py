"""Synthetic offline comparison; no transcript, credentials or model requests.

Run: python -m scripts.offline_acceptance --games 12 --ablation
Outputs aggregate measurements, not a playing-strength/balance certification.
"""
import argparse
import asyncio
from collections import Counter
import contextlib
import io
import json
import tempfile
from unittest.mock import AsyncMock, patch

from werewolf_web.offline_game import OfflineSession, play
from werewolf_web.offline_cast import CHARACTERS
from werewolf_web.social_actions import validate_public


async def run_case(seed, locale, spectator, feedback=True):
    with tempfile.TemporaryDirectory(prefix="offline-acceptance-") as directory:
        session = OfflineSession(seed=seed, locale=locale, spectator=spectator,
                                 character=CHARACTERS[seed % len(CHARACTERS)].id)
        session.memory_dir = directory
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(session.llm, "chat", side_effect=AssertionError("No model calls")))
            stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("No network")))
            stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("No network")))
            stack.enter_context(patch("socket.socket.connect_ex", side_effect=AssertionError("No network")))
            if not feedback:
                stack.enter_context(patch.object(session, "_social_feedback", new=AsyncMock()))
            code = await play(session, automatic=True)
        if code or not session.finished or session.faulted or session.engine.winner not in {"god", "wolf", "draw"}:
            raise AssertionError("Offline game did not reach a clean result")
        if session.campaign_counted or session.campaign_profile is not None:
            raise AssertionError("Offline game contaminated campaign results")
        prefix, kinds, texts = [], Counter(), Counter()
        roster = {s.name for s in session.engine.seats.values()}
        feedback_by_day = Counter()
        for event in session._events:
            if event["type"] == "speech":
                action = event.get("social_action")
                validate_public(action, prefix, roster)
                if action:
                    kinds[action["kind"]] += 1
                texts[event["text"]] += 1
                if event.get("talk_kind") == "social_feedback":
                    feedback_by_day[event.get("day", 0)] += 1
            prefix.append(event)
        if any(n > 3 for n in feedback_by_day.values()):
            raise AssertionError("Feedback exceeded the daily bound")
        return {"seed": seed, "locale": locale, "spectator": spectator, "feedback": feedback,
                "winner": session.engine.winner, "days": session.engine.day_count,
                "speeches": sum(texts.values()), "exact_repeats": sum(n - 1 for n in texts.values()),
                "social_feedback": sum(feedback_by_day.values()), "actions": dict(kinds)}


async def run_batch(games, ablation=False):
    rows = []
    for i in range(games):
        for enabled in ((True, False) if ablation else (True,)):
            rows.append(await run_case(i, "en" if i % 2 else "zh-CN", bool((i // 2) % 2), enabled))
    return {"synthetic": True, "balance_certified": False, "cases": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=12)
    parser.add_argument("--ablation", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.games <= 100:
        parser.error("--games must be between 1 and 100")
    print(json.dumps(asyncio.run(run_batch(args.games, args.ablation)), ensure_ascii=False, indent=2))
