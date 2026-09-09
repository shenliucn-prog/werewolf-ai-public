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
from . import restore_coordinator


def _number(text: str, candidates: list[dict]) -> int | None:
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    target = int(match.group(1))
    return target if target in {item["pos"] for item in candidates} else None


def parse_action(kind: str, data: dict, text: str) -> dict | None:
    """Convert a deliberately small, unambiguous chat vocabulary to actions."""
    text = text.strip()
    if kind == "model_retry":
        if text.casefold() in ("retry", "重试"):
            return {"retry": True}
        if text.casefold() in ("stop", "结束", "停止"):
            return {"retry": False}
        return None
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
    if kind == "table_answer":
        if text.casefold() in ("skip", "pass", "跳过", "暂不回答", "不回答", "pass on"):
            return {"skip": True}
        return {"answer": text} if text.strip() else None

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
    elif kind == "teaching":
        if event.get("unavailable"):
            print("⚠️ " + event["text"])
        else:
            print(("\n📖 Role teaching\n" if en else "\n📖 角色教学\n") + event["text"])
    elif kind == "campaign_review":
        print(("\n📋 Campaign review\n" if en else "\n📋 闯关短复盘\n") + event["text"])
    elif kind == "error":
        print("⚠️ " + event["text"])


def _request_prompt(kind: str, data: dict, locale: str = "zh-CN") -> str:
    en = locale == "en"
    if kind == "model_retry":
        return "\nModel paused. retry / stop: " if en else "\n模型暂停。输入 重试 / 结束："
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
    if kind == "table_answer":
        return (f"\nAnswer {data.get('from', 'the questioner')}'s question, or type skip to pass:\n> " if en
                else f"\n请简短回答 {data.get('from', '提问者')} 的追问；输入 跳过 或直接回车暂不回答：\n> ")
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


async def _campaign_review_repl(session: GameSession) -> None:
    """Post-game campaign short-review handling (terminal entry).

    The review is generated once during the endgame step and rendered as a normal
    event; here a ``generate_review_once`` covers the narrow crash-between-settle-
    and-review case without re-charging a persisted result, then the player can
    explicitly retry a failed (or regenerate a stale) review with ``/review``
    (or ``复盘``) — charging budget — without leaving the REPL.
    """
    from . import campaign_flow
    locale = session.engine.locale
    if not campaign_flow.review_applies(session):
        return
    event = campaign_flow.generate_review_once(session)
    if event is not None:
        _render(event, locale)
    if session.campaign_review_state == "unavailable":
        print("⚠️ " + ("The short review failed. Type /review to retry, or press Enter to quit."
                       if locale == "en" else "短复盘生成失败。输入 /review 重试，或直接回车结束。"))
    while True:
        raw = (await asyncio.to_thread(
            input,
            ("\n/review to regenerate the short review, Enter to quit:\n> "
             if locale == "en" else "\n输入 /review 重新生成短复盘，回车结束：\n> "))).strip()
        if raw.casefold() in ("", "q", "quit", "exit", "退出", "结束"):
            return
        if raw in ("/review", "复盘"):
            event = campaign_flow.generate_campaign_review(session)
            if event is None:
                print("🎙️ " + ("No short review for this result." if locale == "en" else "本局结果无需短复盘。"))
            else:
                _render(event, locale)
            continue
        print("🎙️ " + ("Type /review to retry, or press Enter to quit." if locale == "en"
                        else "输入 /review 重试，或回车结束。"))


def _teaching_command(session: GameSession) -> bool:
    """Regenerate + print the role teaching (terminal ``/teaching`` command).

    Only a campaign game has a teaching role; a free-play or offline session
    returns False so the caller can show a fallback note.  A cache hit is free;
    a miss charges one budget unit (``cached_role_teaching`` already makes a hit
    free).  Rendered inline (``publish=False``) so the live REPL loop does not
    re-render the same event a second time when it drains the queue.
    """
    from . import campaign_flow
    from .campaign import LEVELS
    if not session.campaign_profile:
        return False
    role = session.engine.player_role
    if role not in {level["role"] for level in LEVELS}:
        return False
    model = getattr(session.planner, "model", "campaign")
    event = campaign_flow.generate_teaching(session, role, model, publish=False)
    _render(event, session.engine.locale)
    return True


async def _repl(session: GameSession) -> int:
    """Drive one live session through the terminal; returns a process exit code."""
    locale = session.engine.locale
    async for event in session.events():
        if event["type"] != "request":
            _render(event, session.engine.locale)
            if event["type"] == "error":
                return 1
            continue
        if event.get("event_no") != session._pending_event_no:
            # Historical prompts are not new turns after a restart.
            continue
        kind, data = event["kind"], event.get("data", {})
        while True:
            raw = await asyncio.to_thread(input, _request_prompt(kind, data, locale))
            record_command = re.fullmatch(r"/history|history|公开记录|历史|(?:第\d+天)?(?:发言记录|完整发言|票型|投票记录)|(?:上一轮|最近)(?:的)?票型|(?:day \d+ )?(?:votes|ballots|speeches)|(?:last|latest) (?:votes|ballots)", raw.strip().casefold())
            if raw.startswith("?") or raw.strip().casefold() in ("/seats", "seats", "座次", "座次表") or record_command:
                print("🎙️ " + session.answer_question(raw[1:] if raw.startswith("?") else raw))
                continue
            if raw.strip().casefold() in ("/teaching", "教学"):
                if _teaching_command(session):
                    continue
                print("🎙️ " + ("Teaching is only available in a campaign game." if locale == "en"
                                else "教学仅在闯关对局可用。"))
                continue
            if kind == "conjecture" and edit_conjecture(data, raw):
                continue
            action = parse_action(kind, data, raw)
            if action is not None and session.submit(action, request_id=event.get("request_id"),
                                                     require_request_id=True):
                break
            print("🎙️ I did not understand that action. Use a clear seat number or ? for rules." if locale == "en"
                  else "🎙️ 我没听懂这个行动。可以换成明确的座位号，或输入 ? 加规则问题。")
    if session.campaign_profile and session.finished and not session.faulted:
        await _campaign_review_repl(session)
    return 0


async def play(board_id: str, seed: int | None, offline: bool, locale: str, names=None,
               personalities=None, conjecture=False, player_role=None, backend=None,
               model=None, effort=None, max_calls=None, agent_command=None,
               resume_game_id=None):
    from . import driver as driver_mod
    from .ai.decision_runtime import create_runtime, ModelTurnError
    from . import checkpoint, campaign_flow, settings as user_settings
    if resume_game_id is not None:
        # Rehydrate an interrupted chat game from its checkpoint (§7).  Board,
        # roles and locale come from the save; only the trusted local model
        # runtime is re-derived and re-verified before play resumes.
        try:
            path = checkpoint.checkpoint_path(resume_game_id)
            payload = checkpoint.load_checkpoint(path)
        except (ValueError, OSError) as error:
            print(str(error))
            return 1
        if payload.get("session_id") != resume_game_id:
            print("Save does not match that game id." if locale == "en" else "存档与该对局编号不符。")
            return 1
        planner = None
        planner_snap = payload.get("planner")
        if planner_snap is not None:
            try:
                # Re-derive the runtime from trusted local config, matching the
                # save's driver/adapter lock; explicit CLI flags override it.
                kwargs = restore_coordinator.runtime_kwargs(
                    payload, user_settings.load_settings(), command=agent_command,
                    model=model, effort=effort, max_calls=max_calls)
                if kwargs is None:
                    print("Cannot resume: this game needs a locally configured agent command." if locale == "en"
                          else "无法续玩：本局需要本地已配置的 Agent 命令。")
                    return 1
                planner = create_runtime(**kwargs)
                print(json.dumps(planner.public_status(), ensure_ascii=False), flush=True)
            except (ModelTurnError, ValueError) as error:
                print(str(error))
                return 1
        session = GameSession(payload.get("board_id", "classic"),
                              {"enabled": False} if planner is None else None,
                              session_id=resume_game_id, planner=planner,
                              checkpoint_path=path, _defer_preflight=True)
        try:
            # Restore config + budget first, then persist the preflight
            # reservation, then run the liveness check — so a crash between the
            # reservation and the check still restores the consumed call, and
            # success leaves the runtime verified (not clobbered by restore).
            if not await restore_coordinator.restore_and_verify(
                    session, payload, resume_campaign=campaign_flow.resume):
                print("This game was abandoned and cannot be resumed." if locale == "en"
                      else "本局已放弃，无法续玩。")
                return 1
        except (ValueError, KeyError, TypeError, ModelTurnError) as error:
            print("Could not resume this game: " + str(error))
            return 1
        return await _repl(session)
    # Resolve the gameplay driver exactly as the web does (shared resolution).
    explicit = {}
    if offline:
        explicit["offline"] = True
    if backend is not None:
        explicit["backend"] = backend
    if model:
        explicit["model"] = model
    if effort:
        explicit["effort"] = effort
    if max_calls is not None:
        explicit["max_calls"] = max_calls
    resolved = driver_mod.resolve_driver(explicit=explicit,
                                         saved=user_settings.load_settings(),
                                         command=agent_command)
    if not resolved["configured"]:
        print(resolved["reason"] or
              ("No model or offline mode configured." if locale == "en" else
               "未配置模型或离线模式。"))
        return 1
    offline_mode = resolved["driver"] == "offline"
    planner = None
    if offline_mode:
        print("TEST MODE: local decisions, optional wording only. Not model-player gameplay." if locale == "en" else
              "测试模式：本地规则决策，模型至多润色台词。这不是大模型玩家对局。", flush=True)
    else:
        if conjecture:
            print("Model-player conjecture tables are not integrated yet / 模型玩家猜想表尚未接入；请选择普通模式。")
            return 1
        try:
            planner = create_runtime(**resolved["runtime_kwargs"])
            print(json.dumps(planner.public_status(), ensure_ascii=False), flush=True)
            print("Checking LLM before dealing roles… / 发身份前验证 LLM 连接……", flush=True)
            await asyncio.to_thread(planner.preflight)
        except (ModelTurnError, ValueError) as error:
            print(str(error))
            return 1
        print("Model connection verified. No silent offline fallback." if locale == "en" else
              "模型连接验证通过；本局不会静默切换离线玩家。", flush=True)
    llm_options = {"enabled": False} if offline_mode or planner is not None else None
    session_id = "chat-" + secrets.token_urlsafe(12)
    session = GameSession(board_id, llm_options, session_id=session_id,
                          seed=seed, locale=locale, names=names,
                          personalities=personalities, conjecture=conjecture, player_role=player_role,
                          onboarding=True, planner=planner,
                          checkpoint_path=checkpoint.checkpoint_path(session_id))
    session.driver, session.adapter = resolved["driver"], resolved["adapter"]
    print("Text only; voice and visual gameplay are not designed or implemented." if locale == "en" else
          "当前仅文字驱动；语音和视觉玩法尚无方案、尚未实现。")
    print("At any prompt: /seats, /history, votes, speeches, or ?question. These never submit an action." if locale == "en" else
          "任何等待行动时都可输入：座次、公开记录、上一轮票型、第2天发言记录、?规则问题。这些查询不消耗行动。")
    print(f"Game id: {session_id} — resume with --resume {session_id}" if locale == "en" else
          f"对局编号：{session_id}；中断后可用 --resume {session_id} 续局。")
    return await _repl(session)


async def campaign_play(profile_id: str, offline: bool, locale: str, seed: int | None,
                        backend=None, model=None, effort=None, max_calls=None,
                        agent_command=None):
    """Terminal campaign entry: play the current unlocked level, count and settle.

    Offline / legacy rule tests are an explicit choice and never count toward
    campaign progress (no archive registration, no hook).
    """
    from . import driver as driver_mod
    from .ai.decision_runtime import create_runtime, ModelTurnError
    from . import campaign_flow, checkpoint, settings as user_settings
    from .campaign import LEVELS

    profile = campaign_flow.load_profile(profile_id)
    level = LEVELS[min(profile["unlocked"], len(LEVELS) - 1)]
    role, board_id = level["role"], level["board"]
    game_id = "campaign-" + secrets.token_urlsafe(12)

    explicit = {}
    if offline:
        explicit["offline"] = True
    if backend is not None:
        explicit["backend"] = backend
    if model:
        explicit["model"] = model
    if effort:
        explicit["effort"] = effort
    if max_calls is not None:
        explicit["max_calls"] = max_calls
    saved = user_settings.load_settings()
    resolved = driver_mod.resolve_driver(explicit=explicit, saved=saved,
                                         command=agent_command)
    if not resolved["configured"]:
        print(resolved["reason"] or
              ("No model or offline mode configured." if locale == "en" else
               "未配置模型或离线模式。"))
        return 1

    if resolved["driver"] == "offline":
        print("Offline rule test — not counted toward campaign progress." if locale == "en"
              else "离线规则测试——不计入闯关成绩。")
        session = GameSession(board_id, {"enabled": False}, session_id=game_id,
                              seed=seed, locale=locale, player_role=role, onboarding=True)
        session.driver, session.adapter = resolved["driver"], resolved["adapter"]
        return await _repl(session)

    try:
        campaign_flow.begin_attempt(profile_id, game_id, role, board_id,
                                    config={"driver": resolved["driver"],
                                            "adapter": resolved["adapter"],
                                            "backend": resolved["backend"],
                                            "model": resolved["model"]})
    except ValueError as error:
        print(str(error))
        return 1

    planner = None
    try:
        planner = create_runtime(**resolved["runtime_kwargs"])
        print(json.dumps(planner.public_status(), ensure_ascii=False), flush=True)
        print("Checking LLM before dealing roles… / 发身份前验证 LLM 连接……", flush=True)
        await asyncio.to_thread(planner.preflight)
        # Persist the resolved config; only the trusted CLI may store the agent
        # command argv (the web's save path drops it).
        persist = dict(saved or {})
        for key in ("driver", "adapter", "backend", "model", "effort", "max_calls"):
            if resolved[key] is not None:
                persist[key] = resolved[key]
        if resolved["command"] is not None:
            persist["command"] = resolved["command"]
        user_settings.save_settings(persist, trusted=True)
    except (ModelTurnError, ValueError) as error:
        print(str(error))
        return 1

    session = GameSession(board_id, {"enabled": False}, session_id=game_id,
                          seed=seed, locale=locale, player_role=role, onboarding=True,
                          planner=planner,
                          checkpoint_path=checkpoint.checkpoint_path(game_id))
    session.driver, session.adapter = resolved["driver"], resolved["adapter"]
    session.campaign_profile = profile_id
    session._checkpoint()
    session.progress_hook = campaign_flow.progress_hook(profile_id, game_id)
    print((f"闯关关卡：{role}（{board_id}）—— 通关后解锁下一关。" if locale == "zh-CN" else
           f"Campaign level: {role} ({board_id}) — win to unlock the next."))
    # First-entry teaching: generated (and charged) once, retried on failure, and
    # rendered by the REPL as a normal event (no separate print here).
    campaign_flow.generate_teaching(session, role, getattr(planner, "model", "campaign"))
    return await _repl(session)


def main():
    parser = argparse.ArgumentParser(description="对话式狼人杀")
    parser.add_argument("--board", help="板子 ID；省略时先选择 / select before dealing")
    parser.add_argument("--role", default="random", help="Your role ID, or random (default); see --list-roles")
    parser.add_argument("--list-roles", action="store_true", help="List roles available on the selected board")
    parser.add_argument("--seed", type=int, help="可复现随机种子")
    parser.add_argument("--offline", action="store_true", help="只使用本地表达")
    parser.add_argument("--backend", choices=("api", "codex", "command", "legacy"),
                        help="api (default or local config), codex, command; legacy is a rule test")
    parser.add_argument("--agent-command", help="Trusted local wrapper as JSON argument array; stdin/stdout protocol")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--lang", default="zh-CN", choices=("zh-CN", "en"), help="game language")
    parser.add_argument("--name", help="Your display name; omitted means random")
    parser.add_argument("--rename", action="append", default=[], metavar="PLAYER_ID=NAME",
                        help="Rename any cast member before play; repeatable (IDs from --list-cast)")
    parser.add_argument("--list-cast", action="store_true", help="List stable cast IDs and exit")
    parser.add_argument("--conjecture", action="store_true", help="Enable dual-table beta (off by default)")
    parser.add_argument("--personality", action="append", default=[], metavar="NPC_ID=PRESET_ID",
                        help="Fixed personality per NPC, or random; repeatable")
    parser.add_argument("--list-personalities", action="store_true")
    parser.add_argument("--resume", metavar="GAME_ID",
                        help="Resume an interrupted game from its checkpoint (board/role come from the save)")
    parser.add_argument("--campaign", action="store_true",
                        help="Play the campaign (闯关): the current unlocked level, counted and settled")
    parser.add_argument("--profile", default="default",
                        help="Campaign profile id (default: 'default')")
    args = parser.parse_args()
    from .game.engine import BOARD_MAP, ROLE_META
    from .i18n import board_role_name
    if args.max_model_calls is not None and not 1 <= args.max_model_calls <= 1000:
        parser.error("--max-model-calls must be between 1 and 1000")
    if args.resume is not None:
        # Resume rehydrates board/roles/locale from the save; board selection,
        # renaming and personality flags do not apply to a resumed game.
        result = asyncio.run(play(None, None, args.offline, args.lang,
                                  resume_game_id=args.resume, backend=args.backend,
                                  model=args.model, effort=args.effort,
                                  max_calls=args.max_model_calls,
                                  agent_command=args.agent_command))
        if result == 1:
            raise SystemExit(1)
        return
    if args.campaign:
        result = asyncio.run(campaign_play(args.profile, args.offline, args.lang,
                                           args.seed, backend=args.backend,
                                           model=args.model, effort=args.effort,
                                           max_calls=args.max_model_calls,
                                           agent_command=args.agent_command))
        if result == 1:
            raise SystemExit(1)
        return
    if args.board is None:
        if args.list_roles or args.list_cast or args.list_personalities:
            args.board = "classic"
        else:
            from .setup import choose
            from .i18n import board_display
            for key, board in BOARD_MAP.items():
                print(f"{key}: {board_display(args.lang, board)['name']}")
            args.board = choose("Board / 板子", tuple(BOARD_MAP), "classic")
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
    result = asyncio.run(play(args.board, args.seed, args.offline, args.lang, names, personalities,
                              args.conjecture, args.role, args.backend, args.model, args.effort, args.max_model_calls,
                              args.agent_command))
    if result == 1:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
