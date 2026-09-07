"""First-run local onboarding; dependency checks use only the standard library."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def choose(prompt, choices, default):
    while True:
        value = input(f"{prompt} [{'/'.join(choices)}] ({default}): ").strip() or default
        if value in choices:
            return value
        print(" / ".join(choices))


def main():
    parser = argparse.ArgumentParser(description="Local Werewolf onboarding / 本地狼人杀引导")
    parser.add_argument("--lang", choices=("en", "zh-CN"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    locale = args.lang or ("en" if args.check else choose("Language / 语言", ("en", "zh-CN"), "en"))
    say = lambda en, zh: print(en if locale == "en" else zh)
    os.chdir(Path(__file__).resolve().parent.parent)
    say("Welcome. Your local fork hosts one player, eleven NPCs and a host.",
        "欢迎。你 fork 的本地仓库将运行一位玩家、十一位 NPC 和主持人的对局。")
    missing = [name for name in ("fastapi", "uvicorn", "httpx", "openai") if importlib.util.find_spec(name) is None]
    if sys.version_info < (3, 10) or missing:
        say("Use Python 3.10+, install dependencies, then run setup again:", "请使用 Python 3.10+，安装依赖后再次运行引导：")
        print("python3 -m venv .venv")
        python = ".venv\\Scripts\\python" if os.name == "nt" else ".venv/bin/python"
        print(f"{python} -m pip install -r werewolf_web/requirements.txt")
        print(f"{python} -m werewolf_web.setup")
        return 1
    say("Environment ready.", "运行环境已就绪。")
    if args.check:
        return 0
    say("Recommended: play in your Agent conversation, keeping one interactive process alive. You can also play directly here or in the browser.",
        "推荐在自己的 Agent 对话里玩，由 Agent 保留同一个交互进程；也可以直接在当前终端或网页玩。")
    say("Existing game? Return to its original live session/tab. Disk resume and interface transfer are not implemented; closing the process loses the game.",
        "已有对局？回到原来仍运行的会话或标签页继续。目前没有断线续局或跨界面迁移，关闭进程会丢失对局。")
    entry = choose("Entry / 入口", ("agent", "web", "exit"), "agent")
    if entry == "exit":
        return 0
    say("Agent play uses Codex model decisions by default and requires a working local Codex login. It consumes account usage. Offline mode is only a rule-flow test; the legacy API path only rephrases local decisions.",
        "Agent 对局默认由 Codex 模型决策，需要本机 Codex 已登录，会消耗账户用量。离线模式仅供规则流程测试；旧 API 路径只润色本地决策。")
    if entry == "web":
        say("Browser currently uses legacy rule-driven NPCs, not Codex decision players. For model gameplay choose the Agent entry. Open http://127.0.0.1:8000, choose settings and read rules before Ready. Keep this server running.",
            "网页版当前仍使用旧规则驱动 NPC，不是 Codex 决策玩家。体验模型对局请选择 Agent 入口。打开 http://127.0.0.1:8000，选择设置、阅读规则后再准备。保持此服务运行。")
        return subprocess.call([sys.executable, "-m", "uvicorn", "werewolf_web.run:app", "--host", "127.0.0.1", "--port", "8000"])
    from .game.engine import BOARD_MAP, ROLE_META
    from .i18n import board_display, board_role_name
    from .casting import CAST_IDS, PLAYER_ID, persona_options
    for key, board in BOARD_MAP.items():
        print(f"{key}: {board_display(locale, board)['name']}")
    board = choose("Board / 板子", tuple(BOARD_MAP), "classic")
    roles = tuple(dict.fromkeys(BOARD_MAP[board]["roles"]))
    for key in roles:
        print(f"{key}: {board_role_name(locale, BOARD_MAP[board], key, ROLE_META[key]['cn'])}")
    role = choose("Your role / 你的身份", ("random", *roles), "random")
    say("Conjecture beta uses separate private and public tables. Leave off for your first game.",
        "猜想模式测试版使用私有和公开两张表，第一局建议关闭。")
    conjecture = choose("Conjecture / 猜想模式", ("off", "on"), "off")
    personality = choose("NPC personalities / NPC 人格", ("random", "fixed"), "random")
    command = [sys.executable, "-u", "-m", "werewolf_web.chat_game", "--board", board, "--role", role, "--lang", locale]
    if conjecture == "on":
        command.append("--conjecture")
    if personality == "fixed":
        options = persona_options(locale)
        for item in options:
            print(f"{item['id']}: {item['label']}")
        for npc in CAST_IDS:
            if npc != PLAYER_ID:
                preset = choose(npc, tuple(item["id"] for item in options), npc)
                command.extend(("--personality", f"{npc}={preset}"))
    name = input("Your name (blank = random) / 你的名字（留空随机）: ").strip()
    if name:
        command.extend(("--name", name))
    say("Codex checks a real model response before dealing roles. Failure stops the game; no silent fallback. Local is a test, not model gameplay. Codex conjecture tables are not yet integrated.",
        "Codex 在发身份前验证真实模型响应，失败会停止，不静默降级。local 是测试，不是模型对局。Codex 猜想表暂未接入。")
    backend = choose("NPC decisions / NPC 决策", ("codex", "local", "legacy"), "codex")
    if backend == "local":
        command.append("--offline")
    elif backend == "legacy":
        command.extend(("--backend", "legacy"))
    say("Setup complete. Next: meet the host, check seats/rules, ask questions, then confirm Ready. Night one has not started.",
        "设置完成。接下来认识主持人、查看座次和规则、提问，再确认开始。第一夜尚未开始。")
    return subprocess.call(command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print("\nSetup closed / 引导已关闭")
