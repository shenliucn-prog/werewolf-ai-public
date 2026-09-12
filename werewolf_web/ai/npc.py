"""NPC AI 决策系统：双层角色扮演（人格层 + 身份层）。

每个 NPC 有独立人格（来自 personas/*.md）、信念(信任值)、情绪、记忆。
决策流：感知 state → LLM 推理 → 输出发言/投票/夜间行动。
玩家发言会被纳入上下文，NPC 必须回应。
"""
from __future__ import annotations

import json
import os
import re
import random
from typing import Optional

from .. import config
from . import prompts
from .llm import LLMClient

PERSONA_DIR = config.PERSONA_DIR
MEMORY_DIR = os.path.join(config.DATA_DIR, "npc_memory")
os.makedirs(MEMORY_DIR, exist_ok=True)

# 人设文件名用的是拼音 slug（player-dashan.md），而引擎里的名字是中文（大山）。
# 没有这张表，中文名一律匹配失败、静默退化成默认人设——12 个人说得一模一样。
NAME_SLUG = {
    "大山": "dashan", "阿墨": "amo", "阿岚": "alan", "小满": "xiaoman",
    "夜枭": "yexiao", "小鹿": "xiaolu", "阿蛮": "aman", "甜豆": "tiandou",
    "细草": "xicao", "老麦": "laomai", "阿吉": "aji", "阿承": "acheng",
}


def parse_persona(path: str) -> dict:
    """解析 player-xxx.md 为人设字典。兼容散文与 Markdown 表格两种格式。"""
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    d = {"name": os.path.basename(path).replace("player-", "").replace(".md", ""),
         "traits": "", "catchphrases": [], "role_habits": {}, "relations": ""}

    def section(title):
        m = re.search(rf"##\s*.*?{re.escape(title)}(.*?)(?=\n##\s|$)", txt, re.S)
        return m.group(1) if m else ""

    def table_cell(sec_txt: str, header_kw: str) -> str:
        """从 Markdown 表格里取某行某单元格：| 关键字 | 内容 |。"""
        # 匹配行首含关键字的表格行
        m = re.search(rf"^\s*\|[^\n]*?{re.escape(header_kw)}[^\n]*?\|([^\n]*)\|", sec_txt, re.M)
        if m:
            return m.group(1).strip()
        # 退而求其次：散文 "关键字：内容"
        m2 = re.search(rf"{re.escape(header_kw)}\s*[：:]\s*(.+)", sec_txt)
        return m2.group(1).strip() if m2 else ""

    # 一句话人设
    d["traits"] = table_cell(section("性格画像"), "一句话人设")
    # 完整性格画像（游戏风格/水平/短板/情绪曲线等整段）。
    # 只取"一句话人设"会丢掉关键判据——大山的"全凭直觉和气势"就写在
    # 「游戏水平」行里，丢了这行他就提取不出"凭直觉"的论证风格。
    d["profile"] = re.sub(r"[|\-*#]", " ", section("性格画像")).strip()
    # 口头禅
    line = table_cell(section("发言特征"), "标志性口头禅")
    if line:
        line = line.replace("<br>", "/")
        d["catchphrases"] = [c.strip().strip('"').strip("'").strip("「」")
                             for c in re.split(r"[/／]", line) if c.strip()]
    # 游戏习惯（按角色，表格行 | 角色 | 习惯 |）
    hab = section("游戏习惯")
    for role_key, role_cn in prompts.ROLE_CN.items():
        m = re.search(rf"^\s*\|[^\n]*?\b{re.escape(role_cn)}\b\s*\|([^\n]*)\|", hab, re.M)
        if m:
            d["role_habits"][role_cn] = m.group(1).strip()
    # 人际关系
    d["relations"] = section("人际关系").strip().replace("\n", " ")
    return d


def load_seat_persona(seat, engine):
    """Preset lookup uses trusted IDs, not a user-controlled name or path."""
    from ..casting import CAST_IDS
    from ..i18n import cast, persona as localized_persona
    slug = seat.persona_id or seat.player_id
    if getattr(engine, "character_cast", False):
        from ..characters import catalog
        character = next((c for c in catalog(engine.locale) if c["id"] == slug), None)
        if character is None:
            raise ValueError("unknown character")
        return {"name": seat.name, "traits": character["description"],
                "profile": character["story"], "speech_style": character["voice"],
                "catchphrase": character["phrase"], "catchphrases": [character["phrase"]],
                "role_habits": {}, "relations": "", "style_weights": character["weights"]}
    if slug not in CAST_IDS:
        raise ValueError("unknown persona")
    canonical = parse_persona(os.path.join(PERSONA_DIR, f"player-{slug}.md"))
    # Rebind any named references in preset prose to this match's cast.
    names = {entry["name"]: next((s.name for s in engine.seats.values()
             if (s.persona_id or s.player_id) == entry["id"]), entry["name"])
             for entry in cast("zh-CN")}
    # Duplicate fixed presets still refer to themselves by their own display name.
    original_name = next(entry["name"] for entry in cast("zh-CN") if entry["id"] == slug)
    names[original_name] = seat.name
    pattern = re.compile("|".join(map(re.escape, names)))
    def rebind(value):
        if isinstance(value, str):
            return pattern.sub(lambda m: names[m.group()], value)
        if isinstance(value, list):
            return [rebind(v) for v in value]
        if isinstance(value, dict):
            return {k: rebind(v) for k, v in value.items()}
        return value
    # Behavior extraction uses canonical Chinese descriptions in both locales.
    result = rebind(canonical)
    result["name"] = seat.name
    result["behavior_persona"] = canonical
    localized = localized_persona(engine.locale, slug, seat.name)
    if localized:
        localized["behavior_persona"] = canonical
        result = localized
    return result


class NPCAgent:
    def __init__(self, name: str, engine, llm: LLMClient):
        self.name = name
        self.engine = engine
        self.llm = llm
        self.seat = engine.seat_by_name(name)
        self.persona = load_seat_persona(self.seat, engine)
        self.role_cn = self.seat.role_cn
        self.is_wolf = self.seat.is_wolf
        # 局内记忆
        self.trust: dict[str, float] = {}
        self.emotion = "neutral"
        self.reasoning: list[str] = []
        self.memory = self._load_memory()

    def _load_persona(self, name: str) -> dict:
        return load_seat_persona(self.engine.seat_by_name(name), self.engine)

    def _load_memory(self) -> dict:
        path = os.path.join(MEMORY_DIR, f"{self.seat.persona_id or self.seat.player_id}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"games": 0, "wins": 0, "learnings": []}

    def save_memory(self):
        self.memory["games"] = self.memory.get("games", 0) + 1
        path = os.path.join(MEMORY_DIR, f"{self.seat.persona_id or self.seat.player_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, ensure_ascii=False, indent=2)

    def learn(self, text: str):
        if text and text not in self.memory["learnings"]:
            self.memory["learnings"].append(text)
            if len(self.memory["learnings"]) > 12:
                self.memory["learnings"].pop(0)

    # ---------- 上下文 ----------
    def build_context(self, speeches: list[str]) -> str:
        e = self.engine
        lines = []
        lines.append(f"第{e.day_count}天，白天发言阶段。")
        if e.sheriff:
            lines.append(f"当前警长是 {e.sheriff}号（{e.seat_at(e.sheriff).name}）。")
        lines.append("存活玩家：" + "、".join(
            f"{s.pos}号{s.name}" for s in e.alive_seats()))
        # 翻牌记录
        flips = [f"{s.pos}号{s.name}={s.role_cn}" for s in e.seats.values() if not s.alive]
        if flips:
            lines.append("已翻牌出局：" + "，".join(flips))
        # 自身私密信息
        if self.seat.role == "seer":
            res = "；".join(f"夜{n['night']}验{n['target']}号{n['name']}={('狼' if n['result']=='wolf' else '好人')}"
                            for n in e.seer_results)
            if res:
                lines.append("【你的验人】" + res)
        if self.is_wolf:
            mates = [f"{s.pos}号{s.name}" for s in e.seats.values()
                     if s.is_wolf and s.name != self.name]
            lines.append(f"【你的狼队友】{('、'.join(mates)) if mates else '无（你是孤狼/特殊狼）'}")
        lines.append("本回合发言记录：")
        if speeches:
            for sp in speeches:
                lines.append("  " + sp)
        else:
            lines.append("  （暂无）")
        return "\n".join(lines)

    # ---------- 发言 ----------
    def speak(self, speeches: list[str], player_last_speech: str = "") -> str:
        ctx = self.build_context(speeches)
        if self.llm.online:
            text = self.llm.chat(
                prompts.SYSTEM_NPC,
                prompts.build_speech_prompt(self.persona, self.role_cn, self.is_wolf,
                                            ctx, player_last_speech),
                max_tokens=300)
        else:
            text = self._heuristic_speech(ctx)
        self.reasoning.append(f"[D{self.engine.day_count}] {self.name}: {text[:60]}")
        return text.strip()

    def _heuristic_speech(self, ctx: str) -> str:
        cp = self.persona.get("catchphrases", [""])
        pre = cp[0] + "，" if cp else ""
        if self.seat.role == "seer":
            res = self.engine.seer_results
            if res:
                r = res[-1]
                if r["result"] == "wolf":
                    return f"{pre}我是预言家，昨晚验了{r['target']}号（{r['name']}）是查杀！大家跟我出他！"
                return f"{pre}我是预言家，验了{r['target']}号（{r['name']}）金水。"
            return f"{pre}我是预言家，目前还没验出明确信息，先听大家。"
        if self.is_wolf:
            return f"{pre}我是好人，先听听预言家怎么说，别乱分票。"
        return f"{pre}我是平民，信息不多，先站预言家/警长这边。"

    # ---------- 投票 ----------
    def vote(self, candidates: list[dict]) -> Optional[int]:
        cand_str = "、".join(
            f"{c['pos']}号{c['name']}({c.get('note','')})" for c in candidates)
        ctx = self.build_context([])
        if self.llm.online:
            raw = self.llm.chat(prompts.SYSTEM_NPC,
                                prompts.build_vote_prompt(self.persona, self.role_cn,
                                                         self.is_wolf, ctx, cand_str),
                                max_tokens=120)
            try:
                j = json.loads(raw)
                return j.get("target")
            except Exception:
                m = re.search(r"(\d+)", raw)
                return int(m.group(1)) if m else None
        return self._heuristic_vote(candidates)

    def _heuristic_vote(self, candidates: list[dict]) -> Optional[int]:
        e = self.engine
        # 预言家：直接投出已知查杀
        if self.seat.role == "seer":
            for r in e.seer_results:
                if r["result"] == "wolf" and r["target"] in {c["pos"] for c in candidates}:
                    return r["target"]
        # 狼人：投已知好人，绝不投狼队友（优先带神/预言家）
        if self.is_wolf:
            wolf_names = {s.name for s in e.seats.values() if s.is_wolf}
            goods = [c["pos"] for c in candidates
                     if c["name"] not in wolf_names and c["pos"] != self.seat.pos]
            return random.choice(goods) if goods else None
        # 普通好人：相信查杀标记；否则随机投一个非自己
        for c in candidates:
            if c.get("note") == "查杀":
                return c["pos"]
        pool = [c["pos"] for c in candidates if c["pos"] != self.seat.pos]
        return random.choice(pool) if pool else None

    # ---------- 夜间行动 ----------
    def night_action(self, action_desc: str, candidates: list,
                     keys: list[str]) -> dict:
        ctx = self.build_context([])
        e = self.engine
        wolf_names = {s.name for s in e.seats.values() if s.is_wolf}

        def _pos(c):
            return c["pos"] if isinstance(c, dict) else c

        # 狼人刀人的战术决策
        if self.is_wolf and "刀" in action_desc:
            mates = [_pos(c) for c in candidates if e.seat_at(_pos(c)).name in wolf_names]
            goods = [_pos(c) for c in candidates if e.seat_at(_pos(c)).name not in wolf_names]
            if self.llm.online:
                # 在线：把队友/自刀选项显式标注给 LLM，让它按局势决定是否自刀
                marked = []
                for c in candidates:
                    p = _pos(c)
                    nm = e.seat_at(p).name
                    tag = "（狼队友,自刀）" if nm in wolf_names else ""
                    marked.append(f"{p}号{nm}{tag}")
                raw = self.llm.chat(prompts.SYSTEM_NPC,
                                    prompts.build_night_prompt(self.persona, self.role_cn,
                                                              action_desc, ctx, marked),
                                    max_tokens=120)
                try:
                    j = json.loads(raw)
                    if j.get("target") is not None:
                        return {"target": int(j["target"])}
                except Exception:
                    pass
                # LLM 解析失败：兜底刀好人
                return {"target": random.choice(goods) if goods else (mates[0] if mates else None)}
            # 离线：公平启发式（不开天眼看身份）——默认刀好人；小概率自刀做战术
            if goods and mates and random.random() < 0.12:
                return {"target": random.choice(mates)}   # 12% 自刀，制造悍跳/骗药空间
            if goods:
                return {"target": random.choice(goods)}
            return {"target": random.choice(mates) if mates else None}

        cand_str = [str(c) for c in candidates]
        if self.llm.online:
            raw = self.llm.chat(prompts.SYSTEM_NPC,
                                prompts.build_night_prompt(self.persona, self.role_cn,
                                                          action_desc, ctx, candidates),
                                max_tokens=120)
        else:
            raw = self.llm._fallback_action(
                f"{action_desc}\n可取目标：[{', '.join(cand_str)}]")
        try:
            return json.loads(raw)
        except Exception:
            return {k: None for k in keys}
