"""A conversational renderer for the shared ``GameSession`` core.

Run ``python -m werewolf_web.chat_game`` to play the same game without the
Web UI.  Prefix a question with ``?`` whenever the host is waiting for an
action to get private rules help without spending that action.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import json
import secrets

from .run import GameSession


def _number(text: str, candidates: list[dict]) -> int | None:
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    target = int(match.group(1))
    return target if target in {item["pos"] for item in candidates} else None


def parse_action(kind: str, data: dict, text: str) -> dict | None:
    """Convert a deliberately small, unambiguous chat vocabulary to actions."""
    text = text.strip()
    if kind == "ready":
        return {"ready": True} if text.casefold() in ("ready", "start", "开始", "准备好了", "准备好") else None
    if kind == "election_withdraw":
        if text.casefold() in ("退警", "withdraw"):
            return {"withdraw": True}
        if text.casefold() in ("不退", "不退警", "继续竞选", "stay"):
            return {"withdraw": False}
        return None
    if kind == "conjecture":
        if text.casefold() in ("keep", "保留", "done", "提交"):
            return {key: data[key] for key in ("private", "public")}
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except ValueError:
            return None
    if kind == "election_up":
        text = text.casefold()
        if text in ("上警", "上", "是", "yes", "y"):
            return {"up": True}
        if text in ("不上警", "不上", "否", "不", "no", "n"):
            return {"up": False}
        return None
    if kind in ("speech", "table_reply"):
        return {"text": text}

    candidates = data.get("candidates", [])
    if kind == "vote":
        if text.casefold() in ("平安日", "支持平安日", "peaceful day", "peace") and not data.get("sheriff"):
            return {"target": 0} if any(c["pos"] == 0 for c in candidates) else None
        target = _number(text, candidates)
        return {"target": target} if target is not None else None
    if kind == "night" and (data.get("role_key") == "witch" or data.get("role") == "女巫"):
        if text.casefold() in ("pass", "skip", "不救不毒", "不用药"):
            return {"save": None, "poison": None}
        save = re.search(r"(?:救|save)\s*(\d+)", text, re.I)
        poison = re.search(r"(?:毒|poison)\s*(\d+)", text, re.I)
        valid = {item["pos"] for item in candidates}
        save_pos = int(save.group(1)) if save else None
        poison_pos = int(poison.group(1)) if poison else None
        save_valid = {item["pos"] for item in data.get("save_candidates", candidates)}
        if not save and not poison:
            return None
        if save and (save_pos not in save_valid or data.get("antidote") is False):
            return None
        if poison and (poison_pos not in valid or data.get("poison") is False):
            return None
        if save and poison and "role_key" in data and not data.get("dual_potions", False):
            return None
        return {"save": save_pos, "poison": poison_pos}
    if kind in ("night", "day_skill"):
        if text.casefold() in ("pass", "skip", "跳过", "不行动"):
            return {"target": None}
        target = _number(text, candidates)
        return {"target": target} if target is not None else None
    return None


def _render(event: dict, locale: str = "zh-CN"):
    en = locale == "en"
    seat_label = lambda pos: f"#{pos}" if en else f"{pos}号"
    kind = event["type"]
    if kind == "conjecture":
        for table in event["tables"]:
            print(f"\n📋 {table['actor']} v{table['version']}")
            for row in table["rows"]:
                print(f"  {row['player']}: {event.get('labels', {}).get(row['judgment'], row['judgment'])} — {row['reason']}")
    if kind == "init":
        player = event["player"]
        print(f"\n🎙️ {event['host_intro']}")
        from .onboarding import seating_text
        print(seating_text(event["state"]))
        print(f"\n🔒 {'Your role: ' if en else '你的身份：'}{seat_label(player['pos'])} {player['name']} · {player['role_cn']}")
        if player.get("ability"):
            print(player["ability"])
        if player.get("wolfmates"):
            print(("🔒 Wolf teammates: " if en else "🔒 狼队友：") + ", ".join(seat_label(pos) for pos in player["wolfmates"]))
    elif kind == "speech":
        prefix = "💬" if event.get("table_talk") else "🗣️"
        print(f"{prefix} {seat_label(event['seat'])} {event['name']}：{event['text']}")
    elif kind == "private":
        print(f"🔒 {event['text']}")
    elif kind in ("narration", "death", "flip", "exile", "gameover", "ballots"):
        print(f"🎙️ {event.get('text') or event.get('reason', '')}")
    elif kind == "vote_result":
        from .public_record import target_label
        print("🗳️ " + ", ".join(f"{target_label(pos, locale)}: {votes} {'votes' if en else '票'}" for pos, votes in event["tally"].items()))
    elif kind == "review":
        print(("\n📋 Post-game review\n" if en else "\n📋 赛后复盘\n") + event["text"])
    elif kind == "error":
        print("⚠️ " + event["text"])


def _request_prompt(kind: str, data: dict, locale: str = "zh-CN") -> str:
    en = locale == "en"
    if kind == "conjecture":
        lines = ["\n" + data["hint"]]
        for i, name in enumerate(data["players"], 1):
            lines.append(f"{i}. {name}: private={data['private'][i-1]['judgment']}; public={data['public'][i-1]['judgment']}")
        lines.append(" / ".join(data["options"]))
        lines.append("Edit: private 3 wolf reason / public 3 unknown reason. Submit: done. Rules: ?question.\n> " if en else
                     "逐条编辑：私有 3 wolf 理由 / 公开 3 unknown 理由（数字为上表序号）。完成后输入 提交；?问题 可问规则。\n> ")
        return "\n".join(lines)
    return _ordinary_request_prompt(kind, data, locale)


def edit_conjecture(data, text):
    """Small chat editor; mutates only the local draft, never the live ledger."""
    match = re.fullmatch(r"(private|public|私有|公开)\s+(\d+)\s+(\S+)(?:\s+(.*))?", text.strip(), re.I)
    if not match:
        return False
    scope, index, judgment, reason = match.groups()
    scope = {"私有": "private", "公开": "public"}.get(scope, scope.lower())
    index = int(index) - 1
    judgment = next((key for key, label in data.get("option_labels", {}).items() if label == judgment), judgment)
    if not 0 <= index < len(data[scope]) or judgment not in data["options"]:
        return False
    if scope == "private" and data.get("locked_private", {}).get(data[scope][index]["player"], judgment) != judgment:
        return False
    data[scope][index].update(judgment=judgment, reason=reason or "")
    return True


def _ordinary_request_prompt(kind: str, data: dict, locale: str = "zh-CN") -> str:
    en = locale == "en"
    if kind == "ready":
        return "\nAsk ?question, or type ready to start night one:\n> " if en else "\n输入 ?规则问题，或输入 开始 进入第一夜：\n> "
    if kind == "election_withdraw":
        return "\nCandidacy withdrawal window: withdraw / stay:\n> " if en else "\n警上发言结束，是否退警？输入 退警 / 不退警：\n> "
    if kind == "speech":
        return ("\nYour turn to speak. Type your statement; use ? followed by a rules question:\n> " if en
                else f"\n轮到你发言（{data.get('phase', '')}）。直接输入发言；输入 ?规则问题 可问主持人：\n> ")
    if kind == "table_reply":
        return (f"\n{data.get('from', 'Someone')} interrupted: {data.get('text', '')}\nReply briefly, or press Enter to pass:\n> " if en
                else f"\n{data.get('from', '有人')} 打断你：{data.get('text', '')}\n简短回应，或直接回车暂不回应：\n> ")
    if kind == "election_up":
        return "\nRun for sheriff? Type yes or no:\n> " if en else "\n是否上警？输入 上警 / 不上警：\n> "
    candidates = ", ".join(item["name"] if item["pos"] == 0 else (f"#{item['pos']} {item['name']}" if en else f"{item['pos']}号{item['name']}")
                           for item in data.get("candidates", []))
    if kind == "vote":
        return f"\nVote now ({candidates}). Example: vote 3:\n> " if en else f"\n请投票（{candidates}）。例如：投 3 号：\n> "
    if data.get("role_key") == "witch" or data.get("role") == "女巫":
        save_targets = ", ".join(str(c["pos"]) for c in data.get("save_candidates", [])) or ("none" if en else "无")
        poison_available = data.get("poison", True)
        use = ("Use save N AND/OR poison M, or pass" if data.get("dual_potions") else "Use save N OR poison N, or pass") if en else (
            "可输入 救 N 毒 M，也可只救、只毒或不救不毒" if data.get("dual_potions") else "输入 救 N 或 毒 N，不能同夜用两药；也可输入 不救不毒")
        return (f"\nWitch: {data.get('desc', '')}\nSave targets: {save_targets}. Poison available: {poison_available}.\n"
                f"Poison candidates: {candidates}. {use}:\n> " if en else
                f"\n女巫：{data.get('desc', '')}\n可救：{save_targets}；毒药可用：{'是' if poison_available else '否'}。\n"
                f"可毒：{candidates}。{use}：\n> ")
    return f"\n{data.get('role', 'Action')}: {data.get('desc', '')}\nCandidates: {candidates}. Use choose N or pass:\n> " if en else f"\n{data.get('role', '角色')}：{data.get('desc', '')}\n行动目标（{candidates}）。例如：选 3 号，或 跳过：\n> "


async def play(board_id: str, seed: int | None, offline: bool, locale: str, names=None,
               personalities=None, conjecture=False, player_role=None):
    llm_options = {"enabled": False} if offline else None
    session = GameSession(board_id, llm_options, session_id="chat-" + secrets.token_urlsafe(12),
                          seed=seed, locale=locale, names=names,
                          personalities=personalities, conjecture=conjecture, player_role=player_role,
                          onboarding=True)
    print("Text only; voice and visual gameplay are not designed or implemented." if locale == "en" else
          "当前仅文字驱动；语音和视觉玩法尚无方案、尚未实现。")
    print("At any prompt: /seats, /history, votes, speeches, or ?question. These never submit an action." if locale == "en" else
          "任何等待行动时都可输入：座次、公开记录、上一轮票型、第2天发言记录、?规则问题。这些查询不消耗行动。")
    async for event in session.events():
        if event["type"] != "request":
            _render(event, session.engine.locale)
            continue
        kind, data = event["kind"], event.get("data", {})
        while True:
            raw = await asyncio.to_thread(input, _request_prompt(kind, data, locale))
            record_command = re.fullmatch(r"/history|history|公开记录|历史|(?:第\d+天)?(?:发言记录|完整发言|票型|投票记录)|(?:上一轮|最近)(?:的)?票型|(?:day \d+ )?(?:votes|ballots|speeches)|(?:last|latest) (?:votes|ballots)", raw.strip().casefold())
            if raw.startswith("?") or raw.strip().casefold() in ("/seats", "seats", "座次", "座次表") or record_command:
                print("🎙️ " + session.answer_question(raw[1:] if raw.startswith("?") else raw))
                continue
            if kind == "conjecture" and edit_conjecture(data, raw):
                continue
            action = parse_action(kind, data, raw)
            if action is not None and session.submit(action):
                break
            print("🎙️ I did not understand that action. Use a clear seat number or ? for rules." if locale == "en"
                  else "🎙️ 我没听懂这个行动。可以换成明确的座位号，或输入 ? 加规则问题。")


def main():
    parser = argparse.ArgumentParser(description="对话式狼人杀")
    parser.add_argument("--board", default="classic", help="板子 ID")
    parser.add_argument("--role", default="random", help="Your role ID, or random (default); see --list-roles")
    parser.add_argument("--list-roles", action="store_true", help="List roles available on the selected board")
    parser.add_argument("--seed", type=int, help="可复现随机种子")
    parser.add_argument("--offline", action="store_true", help="只使用本地表达")
    parser.add_argument("--lang", default="zh-CN", choices=("zh-CN", "en"), help="game language")
    parser.add_argument("--name", help="Your display name; omitted means random")
    parser.add_argument("--rename", action="append", default=[], metavar="PLAYER_ID=NAME",
                        help="Rename any cast member before play; repeatable (IDs from --list-cast)")
    parser.add_argument("--list-cast", action="store_true", help="List stable cast IDs and exit")
    parser.add_argument("--conjecture", action="store_true", help="Enable dual-table beta (off by default)")
    parser.add_argument("--personality", action="append", default=[], metavar="NPC_ID=PRESET_ID",
                        help="Fixed personality per NPC, or random; repeatable")
    parser.add_argument("--list-personalities", action="store_true")
    args = parser.parse_args()
    from .game.engine import BOARD_MAP, ROLE_META
    from .i18n import board_role_name
    if args.board not in BOARD_MAP:
        parser.error("Unknown board ID")
    available_roles = list(dict.fromkeys(BOARD_MAP[args.board]["roles"]))
    if args.list_roles:
        print("random\n" + "\n".join(f"{r}: {board_role_name(args.lang, BOARD_MAP[args.board], r, ROLE_META[r]['cn'])}"
                                    for r in available_roles))
        return
    if args.role not in ("random", *available_roles):
        parser.error("Role unavailable on this board; use --list-roles")
    from .casting import CAST_IDS, PLAYER_ID, validate_names
    if args.list_personalities:
        from .casting import persona_options
        print(json.dumps(persona_options(args.lang), ensure_ascii=False, indent=2))
        return
    if args.list_cast:
        print("\n".join(key + (" (you)" if key == PLAYER_ID else "") for key in CAST_IDS))
        return
    names = {}
    for item in args.rename:
        key, sep, value = item.partition("=")
        if not sep or key in names:
            parser.error("Use each --rename PLAYER_ID=NAME only once")
        names[key] = value
    if args.name is not None:
        names[PLAYER_ID] = args.name
    try:
        names = validate_names(names)
    except ValueError as error:
        parser.error(str(error))
    personalities = {}
    for item in args.personality:
        key, sep, value = item.partition("=")
        if not sep or key in personalities:
            parser.error("Use each --personality NPC_ID=PRESET_ID only once")
        personalities[key] = value
    from .casting import assign_personas
    try:
        assign_personas(args.seed, personalities)
    except ValueError as error:
        parser.error(str(error))
    asyncio.run(play(args.board, args.seed, args.offline, args.lang, names, personalities, args.conjecture, args.role))


if __name__ == "__main__":
    main()
