"""Four-call, synthetic public-fact regression; not a full-game quality claim."""
import argparse
import json
import re
from pathlib import Path
import tempfile

from ..ai.brain import Speech
from ..ai.codex_player import CodexNPCAgent, CodexPlayerRuntime
from ..ai.llm import LLMClient, LLMRuntimeConfig
from ..game.engine import GameEngine
from ..public_record import PublicRecord


def mentions_player(text, seat):
    return seat.name in text or bool(re.search(rf"(?<!\d){seat.pos}\s*号|#\s*{seat.pos}\b", text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-codex", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.run_codex:
        parser.error("--run-codex required; maximum four account-backed calls")
    runtime = CodexPlayerRuntime(max_calls=4)
    runtime.preflight()
    print("Connection verified (1/4)", flush=True)
    e = GameEngine("classic", seed=19, locale="zh-CN")
    e.setup(); e.start_night(); e.start_day()
    actor, victim = [s for s in e.alive_seats() if s.role == "civilian"][:2]
    claimant = next(s for s in e.alive_seats() if s.is_wolf)
    record = PublicRecord(e.locale)
    with tempfile.TemporaryDirectory(prefix="werewolf-coherence-") as directory:
        agent = CodexNPCAgent(actor.name, e, LLMClient(LLMRuntimeConfig.from_request({"enabled": False})),
                              memory_dir=directory, planner=runtime, public_record=record)
        statements = [(claimant, Speech(text=f"我是预言家。第1夜：{victim.pos}号{victim.name}——查杀。", claim="seer", accuse=victim.name)),
                      (actor, Speech(text=f"我暂时支持{claimant.pos}号{claimant.name}，要核对他的查验。", defend=claimant.name))]
        for seat, speech in statements:
            record.observe({"type": "speech", "seat": seat.pos, "name": seat.name, "text": speech.text}, 1)
            agent.observe_speech(1, seat.name, speech)
        record.observe({"type": "ballots", "sheriff": True,
                        "text": f"警长投票：{actor.pos}号{actor.name}投给{claimant.pos}号{claimant.name}。"}, 1)
        victim.alive = False
        e.day_count = e.night_count = 2
        record.observe({"type": "flip", "text": f"{victim.pos}号{victim.name}死亡，公开翻牌——平民。"}, 2)
        agent.observe_flip(victim.name, "平民", False)
        speech = agent.speak([])
        record.observe({"type": "speech", "seat": actor.pos, "name": actor.name, "text": speech.text}, 2)
        print("Public speech returned (2/4)", flush=True)
        candidates = [{"pos": s.pos, "name": s.name} for s in e.alive_seats() if s.name != actor.name]
        target = agent.vote(candidates + [{"pos": 0, "name": "平安日"}])
        print("Vote returned (3/4)", flush=True)
        record.observe({"type": "speech", "seat": claimant.pos, "name": claimant.name,
                        "text": f"{actor.name}，你昨天还投我当警长，今天为什么改口？"}, 2)
        reply = agent.table_reply(claimant.name)
        checks = {"accuses_disproved_claimant": speech.accuse == claimant.name,
                  "votes_disproved_claimant": target == claimant.pos,
                  "speech_mentions_revealed_villager": mentions_player(speech.text, victim) and "平民" in speech.text,
                  "reply_accounts_for_flip": "平民" in reply.text and mentions_player(reply.text, victim)}
        report = {"scope": "Synthetic regression, not a complete game or balance experiment",
                  "calls": runtime.calls, "checks": checks,
                  "fixture": {"claimant": claimant.pos, "victim": victim.pos, "victim_name": victim.name},
                  "public_speech": speech.text, "vote": target, "public_reply": reply.text}
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if not all(checks.values()):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
