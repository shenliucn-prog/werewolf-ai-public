"""主持人（上帝）系统。

能力：
1. 叙事推进 —— 昼夜/死亡/投票的播报，带个性化风格。
2. 每局结束自动复盘 —— LLM 分析双方表现，写入 data/reviews/。
3. 主持风格进化 —— 持久化 host_style.json，逐步发展个性化话术与节奏。
4. 动态发明新规则 —— 基于对局情况生成规则变体，增加可玩性。
"""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime

from .. import config
from ..conversation import FloorPolicy
from . import prompts
from .llm import LLMClient
from ..i18n import normalize_locale, role_name, role_desc, board_display, witch_rule_text

REVIEW_DIR = config.REVIEW_DIR
STYLE_PATH = config.HOST_STYLE_PATH

DEFAULT_STYLE = {
    "games": 0,
    "tone": "沉稳带戏剧感",
    "catchphrases": ["天黑请闭眼。", "天亮了。", "真相，往往在最后一刻揭晓。"],
    "pacing": "标准",
    "personality": {
        "authority": 0.82,
        "drama": 0.55,
        "warmth": 0.48,
        "strictness": 0.90,
    },
    "skills": {
        "rules_accuracy": 0.70,
        "pacing_control": 0.55,
        "review_quality": 0.45,
    },
    "growth": {"xp": 0, "lessons": []},
    "invented_rules": [],
    "evolution_log": [],
}

ROLE_CONTRACTS = {
    "referee": "只执行既定规则和校验合法性，不改变规则，不提供策略建议。",
    "director": "只接触公开状态，负责节奏、轮次和清晰播报。",
    "coach": "仅在赛后读取完整状态，复盘决策质量，不干预进行中的对局。",
}


class RuleGuide:
    """Deterministic, public-only rules help for the live host chat."""

    def __init__(self):
        with open(config.BOARDS_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        self.roles = data["roles"]

    def answer(self, question: str, engine) -> str:
        question = " ".join((question or "").split())[:320]
        if engine.locale == "en":
            return self._answer_english(question, engine)
        if not question:
            return "当然可以问我规则。比如：『白天流程是什么？』『女巫怎么用药？』『这一局有哪些身份？』"

        # The host is a rules tutor, never a second player or a source of
        # private state.  Seat-specific questions are treated as strategy.
        names = [seat.name for seat in engine.seats.values()]
        strategy_words = ("谁是狼", "谁像狼", "投谁", "验谁", "守谁", "毒谁", "刀谁",
                          "该投", "该验", "该守", "该毒", "帮我选", "告诉我身份")
        if (re.search(r"\d+\s*号", question) or any(name in question for name in names) or
                any(word in question for word in strategy_words)):
            return "我可以解释规则和公开流程，但不能判断某位玩家的身份、提供投票或夜间行动建议。请根据公开发言、票型和你自己的合法私密信息决定。"

        if any(word in question for word in ("上警", "退警", "竞选")):
            return "仅首日发言前统一报名上警，之后不能加入。玩家界面在警上发言结束后可退警；所有存活玩家（含候选人）投票选警长，平票则无警长。"
        if any(word in question for word in ("平安日", "弃票")):
            return "放逐时可以投平安日，公开主张今天不放逐。平安日单独最高票或与最高票打平时无人出局；任意最高票并列也无人出局。平安日不是不表态的弃票，警长票权同样适用。"
        if engine.witch_unlimited and any(word in question for word in ("女巫", "药", "自救", "复活")):
            return witch_rule_text(engine.locale, engine.board)
        board_roles = [self.roles[role] for role in engine.board["roles"]]
        for role in sorted(board_roles, key=lambda role: -len(role["cn"])):
            if role["cn"] in question:
                return f"{role['emoji']} {role['cn']}：{role['desc']}"
        if any(word in question for word in ("胜利", "赢", "屠边", "结束")):
            return "胜利条件：所有狼人出局时好人阵营获胜；狼人让神职或平民任一边全部出局时，狼人阵营获胜（屠边）。"
        if any(word in question for word in ("白天", "流程", "顺序", "怎么玩", "规则")):
            role_names = "、".join(dict.fromkeys(role["cn"] for role in board_roles))
            return (f"本局是「{engine.board['name']}」。基本流程是：夜晚按身份行动 → 天亮公布死亡/翻牌 → "
                    "首日进行警长选举 → 存活玩家依次发言 → 全体投票放逐。平票时无人被放逐。"
                    f"本局身份包括：{role_names}。你可以继续问某个身份怎么行动。")
        if any(word in question for word in ("投票", "放逐", "平票", "警长")):
            return "白天所有存活玩家投票放逐一人；最高票唯一者出局并翻牌，平票则无人出局。首日可选警长，警长在投票中算 1.5 票。"
        if any(word in question for word in ("夜晚", "晚上", "夜里", "天亮")):
            return "夜晚只有仍存活且拥有行动的身份会收到操作提示；操作结果会依规则在天亮结算。主持人不会在夜间透露其他人的行动或结果。"

        return (f"我能解释本局「{engine.board['name']}」的流程、胜利条件、投票和身份技能。"
                "可以换一种问法，例如『守卫能连续守同一人吗？』")

    def _answer_english(self, question: str, engine) -> str:
        q = question.casefold()
        names = [seat.name.casefold() for seat in engine.seats.values()]
        if (re.search(r"#\s*\d+|\b(?:seat|player)\s*\d+", q)
                or any(re.search(rf"\b{re.escape(name)}\b", q) for name in names)
                or re.search(r"\bwho\b|\bshould i\b|recommend|choose for me|reveal.*identit", q)):
            return "I can explain rules, but I cannot identify players or recommend a vote or night target."
        if re.search(r"\b(candidacy|candidate|withdraw|withdrawal|election|run for sheriff)\b", q):
            return "Declare candidacy once before speeches on day one. Player interfaces offer withdrawal after speeches; no late entry. All living players, including candidates, vote; a tied election elects nobody."
        if re.search(r"\b(abstain|abstention|peaceful day)\b", q):
            return "Vote Peaceful Day to publicly support no exile. A Peaceful Day lead or any tie for highest votes eliminates nobody. Sheriff weighting applies. This is a vote for no exile, not an abstention."
        if engine.witch_unlimited and re.search(r"\b(witch|potion|potions|antidote|poison|revive|resurrect|self-save)\b", q):
            return witch_rule_text(engine.locale, engine.board)
        # Match specific compound roles before generic ones (Wolf King before
        # King, Evil Knight before Knight), using public board metadata only.
        roles = sorted(set(engine.board["roles"]),
                       key=lambda key: -len(role_name("en", key, key)))
        for key in roles:
            name = role_name("en", key, key)
            if re.search(rf"\b{re.escape(name.casefold())}\b", q):
                return f"{self.roles[key]['emoji']} {name}: {role_desc('en', key, self.roles[key])}"
        if re.search(r"\b(win|wins|victory|end)\b", q):
            return "The village wins when every werewolf is out. Werewolves win by eliminating either all special roles or all villagers."
        if re.search(r"\b(vote|voting|tie|exile|sheriff|mayor)\b", q):
            return "Living players vote to exile one player. A unique top vote is exiled and revealed; a tie exiles no one. The sheriff's vote counts as 1.5."
        if re.search(r"\b(night|dawn)\b", q):
            return "Living roles with night actions receive private prompts. Results resolve at dawn; I never reveal another player's private actions or results."
        board = board_display("en", engine.board)["name"]
        roster = ", ".join(role_name("en", key, key) for key in dict.fromkeys(engine.board["roles"]))
        return (f"Board: {board}. Night actions → dawn and revealed deaths → first-day sheriff election "
                f"→ living players speak → exile vote. Roles: {roster}. "
                "You can keep asking about abilities, voting or victory without using your action.")


class HostAgent:
    def __init__(self, llm: LLMClient, locale: str = "zh-CN"):
        self.llm = llm
        self.locale = normalize_locale(locale)
        self.style = self._load_style()
        self.role_contracts = dict(ROLE_CONTRACTS)
        self.rule_guide = RuleGuide()

    def _load_style(self) -> dict:
        self.style_path = STYLE_PATH if self.locale == "zh-CN" else STYLE_PATH.replace(".json", ".en.json")
        if os.path.exists(self.style_path):
            try:
                with open(self.style_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                merged = deepcopy(DEFAULT_STYLE)
                for key, value in saved.items():
                    if isinstance(value, dict) and isinstance(merged.get(key), dict):
                        merged[key].update(value)
                    else:
                        merged[key] = value
                return merged
            except Exception:
                pass
        return deepcopy(DEFAULT_STYLE)

    def save_style(self):
        with open(self.style_path, "w", encoding="utf-8") as f:
            json.dump(self.style, f, ensure_ascii=False, indent=2)

    # ---------- 叙事 ----------
    def narrate(self, event_type: str, text: str) -> str:
        """给引擎产生的事件加一点主持风格外衣。"""
        if self.locale == "en":
            prefixes = {"night_start": "Night falls. Everyone, close your eyes.",
                        "day_start": "☀️ Dawn breaks.", "death": "💀", "flip": "🂠",
                        "exile": "⚖️", "win": "🏆", "system": "📣"}
            return prefixes.get(event_type, "") + (" " + text if event_type != "night_start" else "")
        tone = self.style.get("tone", "沉稳")
        cp = self.style.get("catchphrases", [])
        if event_type == "night_start":
            lead = cp[0] if cp else "天黑请闭眼。"
            return f"{lead}"
        if event_type == "day_start":
            return f"☀️ {text}"
        if event_type == "death":
            return f"💀 {text}"
        if event_type == "flip":
            return f"🂠 {text}"
        if event_type == "exile":
            return f"⚖️ {text}"
        if event_type == "win":
            return f"🏆 {text}"
        if event_type == "system":
            return f"📣 {text}"
        return text

    def intro(self, board_name: str, seats_desc: str) -> str:
        if self.locale == "en":
            return (f"Welcome to Werewolf Night. Board: {board_name}.\n"
                    f"Twelve players take their seats. The table is set.\n{seats_desc}\n"
                    "Truth rarely arrives quietly.")
        cp = self.style.get("catchphrases", [])
        tail = cp[-1] if cp else ""
        return (f"欢迎来到狼人杀之夜。本局板子：{board_name}。\n"
                f"十二位玩家围坐桌前，命运即将揭晓。\n{seats_desc}\n"
                f"{tail}")

    def answer_rule_question(self, question: str, engine) -> str:
        """Private, non-blocking rules tutoring with no hidden-state access."""
        if isinstance(question, str) and any(w in question.lower() for w in ("猜想", "双表", "conjecture", "private table", "public table")):
            return ("Conjecture beta: private tables are your own beliefs; public tables are strategic claims, not certified facts. "
                    "Cover every player, including the dead; unknown is allowed. Submit before discussion and revise before voting. "
                    "All public versions remain visible; private tables are never broadcast. A changed opinion is not automatically a lie."
                    if self.locale == "en" else
                    "猜想测试模式：私有表记录你自己的判断；公开表是你用来辩论的立场，不是系统认证的事实。"
                    "两张表覆盖所有人（包括死者），允许未知。讨论前提交，投票前可修订。"
                    "历轮公开表保留，私有表不广播。改口不自动等于撒谎。")
        return self.rule_guide.answer(question, engine)

    def moderate_table_talk(self, *, topic_turns: int, extra_turns: int,
                            speaker_extra_turns: int, repeated_pair: bool) -> str | None:
        """Public-only conversational floor control.

        Returning text means the host has closed the current thread.  It never
        selects a side or evaluates hidden roles.
        """
        reason = FloorPolicy.close_reason(topic_turns=topic_turns, extra_turns=extra_turns,
            speaker_extra_turns=speaker_extra_turns, repeated_pair=repeated_pair)
        if self.locale == "en":
            if reason == "space":
                return "💬 Host: Let's make room for players who have not spoken."
            if reason == "pair":
                return "💬 Host: Log the point; this cannot become a two-person debate. Next speaker."
            if reason == "speaker":
                return "💬 Host: That is enough added detail. Let's hear another voice."
            return None
        if reason == "space":
            return "💬 主持人：大家先收一收，留一点空间给还没说话的人。"
        if reason == "pair":
            return "💬 主持人：这个点先记下，不要变成两个人的拉扯，换下一位。"
        if reason == "speaker":
            return "💬 主持人：这位玩家已经补充得够充分了，我们听听其他人的看法。"
        return None

    # ---------- 复盘 ----------
    def review(self, engine, npc_performances: str) -> str:
        events_log = "\n".join(
            f"[{e.type}] {e.text}" for e in engine.history
            if e.type in ("speech", "vote", "death", "flip", "exile", "win", "system"))
        text = None
        if self.llm.online:
            text = self.llm.generate(
                prompts.system_review(self.locale),
                prompts.build_review_prompt(board_display(self.locale, engine.board)["name"], engine.winner or "unknown",
                                            events_log, npc_performances, locale=self.locale),
                max_tokens=800)
        if not text or (self.locale == "en" and re.search(r"[\u4e00-\u9fff]", text)):
            text = self._heuristic_review(engine)
        # 落盘。目录要自己兜底：data/reviews/ 是运行时产物、已被 .gitignore
        # 排除，全新克隆的仓库里根本不存在，而 ensure_dirs() 只有 Web 入口
        # 会调用——CLI 直接跑就会在写复盘时 FileNotFoundError。
        os.makedirs(REVIEW_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(REVIEW_DIR, f"review_{engine.board_id}_{ts}.md")
        with open(path, "w", encoding="utf-8") as f:
            title = "Review" if self.locale == "en" else "复盘"
            f.write(f"# {title} {board_display(self.locale, engine.board)['name']} ({ts})\n\n{text}\n")
        # NPC 学习
        return text

    def _heuristic_review(self, engine) -> str:
        speeches = sum(event.type == "speech" for event in engine.history)
        votes = sum(event.type == "vote" for event in engine.history)
        if self.locale == "en":
            winner = "Draw" if engine.winner == "draw" else "Werewolves" if engine.winner == "wolf" else "Village"
            return (f"Winner: {winner}\nReason: {engine.end_reason}\n"
                    f"Recorded evidence: {speeches} statements and {votes} vote rounds.\n"
                    "Review prompts:\n- Wolves: compare your claimed checks with earlier statements.\n"
                    "- Village: compare accusations and defences with revealed roles before following a vote.\n"
                    "- Host: keep time for each player and close repeated two-person debates.")
        lines = [f"胜利方：{engine.winner}", f"原因：{engine.end_reason}"]
        lines.append(f"可复盘证据：{speeches}段发言，{votes}轮完整票型。")
        lines.append("可改进点：")
        lines.append("- 狼人：悍跳预言家时注意心路历程合理性")
        lines.append("- 好人：对查杀/金水的反应要更果断")
        lines.append("- 主持人：保持节奏，确保每个玩家都被点到")
        return "\n".join(lines)

    # ---------- 风格进化 ----------
    def evolve(self, engine, review_text: str):
        self.style["games"] = self.style.get("games", 0) + 1
        growth = self.style.setdefault("growth", {"xp": 0, "lessons": []})
        growth["xp"] = growth.get("xp", 0) + 1
        skills = self.style.setdefault("skills", {})
        has_speeches = any(event.type == "speech" for event in engine.history)
        has_votes = any(event.type == "vote" for event in engine.history)
        if has_speeches and has_votes:
            skills["review_quality"] = min(
                0.95, skills.get("review_quality", 0.45) + 0.01)
            lesson = "用完整发言与票型复盘，而不是只根据胜负评价。"
        else:
            skills["rules_accuracy"] = min(
                0.95, skills.get("rules_accuracy", 0.70) + 0.005)
            lesson = "事件记录不完整，下一局优先保证裁判账本。"
        lessons = growth.setdefault("lessons", [])
        lessons.append(lesson)
        growth["lessons"] = lessons[-20:]
        if self.llm.online and self.style["games"] % 1 == 0:
            prompt = (f"你已主持了{self.style['games']}局。当前风格：{self.style['tone']}，"
                f"口头禅：{self.style['catchphrases']}。\n最近一局复盘：{review_text[:500]}\n"
                f"请微调你的主持风格：返回JSON {{'tone':'...','catchphrases':['..','..','..'],"
                f"'pacing':'...'}}，让风格更鲜明有趣。")
            if self.locale == "en":
                prompt = (f"Games hosted: {self.style['games']}. Latest review: {review_text[:500]}\n"
                          'Suggest a small style adjustment in English as JSON with keys "tone", '
                          '"catchphrases" (three strings), and "pacing". Do not change game rules.')
            evo = self.llm.generate(
                "You are a Werewolf host. Write in English." if self.locale == "en" else prompts.SYSTEM_HOST,
                prompt, max_tokens=200)
            try:
                j = json.loads(evo)
                self.style.update({k: j[k] for k in ("tone", "catchphrases", "pacing") if k in j})
                self.style["evolution_log"].append(
                    f"第{self.style['games']}局后调整：{j.get('tone')}")
            except Exception:
                pass
        self.save_style()

    # ---------- 动态发明规则 ----------
    def maybe_invent_rule(self, engine) -> str | None:
        """A live referee must never invent an unenforced rule mid-game."""
        return None
