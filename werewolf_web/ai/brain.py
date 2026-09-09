"""离线独立推理引擎（无 LLM Key 时的"大脑"）。

设计原则
--------
1. **一人一脑**：每个 NPC 持有且仅持有一个 Brain 实例。怀疑度、信任度、
   观察笔记全都是实例私有字段，任何两个 Brain 之间不共享状态。
   因此同一个局面下，不同角色会得出不同结论——这是"各自思考"的物质基础，
   不是给一个共享随机数取不同的台词模板。
2. **不开天眼**：好人只能依据公开信息（发言/投票/死亡翻牌）+ 自身私密信息
   （自己的身份、狼队友、验人结果）推理。狼人知道队友，但不知道好人身份。
3. **可解释**：每次决策都产出 reason（内心推理），供 CLI 展示，
   让旁观者看清"他为什么这么想"。
4. **可切换**：若配置了 LLM Key，Brain 会把同样的私有上下文交给 LLM，
   依旧是每人一次独立调用，不共享思路。

信念模型
--------
怀疑度 sus[name] ∈ [0,1]，先验 0.35，由以下证据增量更新：
  - 验人结果（仅预言家自己有）
  - 跳身份后被翻牌证伪
  - 踩了好人 / 保了狼（"踩保关系"是狼人杀推理的主干）
  - 投了好人 / 投了狼
  - 划水、沉默、跟风
"""
from __future__ import annotations

import math
import random
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from ..game.models import GameEvent, WOLF_ROLES
from ..recovery import (
    SCHEMA_VERSION, check_version, decode_rng, encode_rng,
    require_str, require_dict, require_list,
)
from .affect import MatchState
from .growth import CognitiveProfile
from .strategy import BeliefState, DecisionTrace, StrategicVotePlanner

PRIOR = 0.35          # 先验怀疑度
_TAIL_PUNCT = "，,。.！!？?…、；;：:～~"


def _clean_cp(s: str) -> str:
    """清洗口头禅：去引号、破折号前缀与尾部标点，避免拼出「——"…，"」这类脏拼接。"""
    s = (s or "").replace('"', "").replace("'", "")
    s = s.strip().lstrip("—-–· ").strip("「」《》").strip()
    return s.rstrip(_TAIL_PUNCT).strip()


# ---------------------------------------------------------------- 风格
@dataclass
class Style:
    """从人设档案提炼出的行为参数，决定这个角色"怎么打"。"""
    aggression: float = 0.5    # 带节奏 / 主动踩人的倾向
    logic: float = 0.5         # 推理严谨度（低=凭直觉）
    bluff: float = 0.4         # 悍跳 / 演戏的倾向
    loyalty: float = 0.6       # 保队友的意愿（狼用）
    caution: float = 0.5       # 藏身份的倾向
    verbosity: float = 0.5     # 话多程度
    argument: str = "plain"    # 论证风格：logic 摆证据 / gut 凭直觉 /
                               # both 两面看 / probe 追问 / plain 平铺

    @staticmethod
    def from_persona(persona: dict) -> "Style":
        # 口头禅也必须进语料：阿墨的"要从两面来看"就写在口头禅里，
        # 只取 traits/relations/habits 会漏掉他最鲜明的说话方式。
        blob = " ".join([
            str(persona.get("traits", "")),
            str(persona.get("profile", "")),
            str(persona.get("relations", "")),
            " ".join(f"{k}{v}" for k, v in (persona.get("role_habits") or {}).items()),
            " ".join(persona.get("catchphrases") or []),
        ])
        s = Style()
        # —— 攻击性：谁爱带节奏、谁话多 ——
        if re.search(r"冲锋|激情|上头|带节奏|嗓门|激进|火爆|豪爽|开心果|爱玩|组局", blob):
            s.aggression += 0.32
            s.caution -= 0.15
        if re.search(r"话多|话太多|长篇大论|追根问底|追问|认真", blob):
            s.aggression += 0.20
            s.caution -= 0.12
        if re.search(r"看谁不爽|邪气|浪子", blob):
            s.aggression += 0.25
            s.logic -= 0.20
        # —— 逻辑：谁能算得清 ——
        if re.search(r"冷静|理性|分析|逻辑|缜密|沉稳|追根问底|排除法|精准|预判", blob):
            s.logic += 0.32
            s.aggression -= 0.05
        if re.search(r"天才|智商|聪明|老练|高手|carry|经验", blob):
            s.logic += 0.22
            s.caution += 0.08
        if re.search(r"新手|菜|直觉|凭感觉|不太会|一般", blob):
            s.logic -= 0.25
        # —— 伪装：谁能演、谁藏不住 ——
        if re.search(r"悍跳|演|骗|忽悠|伪装|心机|老狐狸|戏精|深水", blob):
            s.bluff += 0.40
        if re.search(r"露馅|聊爆|不会藏|不太会藏|藏不住|太认真", blob):
            s.bluff -= 0.28
        # —— 谨慎：谁想藏着、谁想苟 ——
        if re.search(r"划水|低调|苟|安静|内向|害羞|怂|佛系|有点.?面", blob):
            s.aggression -= 0.28
            s.caution += 0.22
        if re.search(r"深水", blob):
            s.caution += 0.25
        # —— 话量 ——
        if re.search(r"话多|话太多|长篇大论|啰嗦|唠叨|嘴碎|嘴上不把门|爱聊|能说", blob):
            s.verbosity += 0.35
        if re.search(r"话少|惜字如金|简短|沉默|不爱说|闷|高冷|冷淡", blob):
            s.verbosity -= 0.30

        # —— 论证风格：这是"说话像不像这个人"的关键 ——
        # 顺序有意义：越具体的风格越优先匹配
        # 判定顺序有讲究：越鲜明的"说话方式"越优先。
        # 注意别绕道 logic 分数——"不太会玩"本该低分，却常被别的褒义词
        # 拉回 0.5 以上，于是憨厚的 夜枭 被判成了平铺直叙。
        if re.search(r"两面|两方面|都要看|一方面|另一面|辩证|客观|圆滑|和稀泥", blob):
            s.argument = "both"
        elif re.search(r"追问|反问|依据是什么|为什么|你刚才说|较真|追根|问到底", blob):
            s.argument = "probe"
        elif re.search(r"直觉|凭直觉|凭感觉|靠感觉|第六感|猜|看谁不爽|说不上来"
                       r"|莫名|第一印象|认定了|我就是觉得|感觉走", blob):
            s.argument = "gut"
        elif (re.search(r"推导|推导过程|排除法|逻辑链|论证|精准|预判|推演|分析", blob)
              and s.logic >= 0.70):
            # 排在前：有推导能力的人优先用推导，哪怕口头禅带点犹豫
            # （阿蛮的"我们来推一下啊……"就被省略号误伤过）
            s.argument = "logic"
        elif re.search(r"啊\？|吗\？|呃|嗯|我不太|不知道|说不上来|猜",
                       " ".join(persona.get("catchphrases") or [])):
            # 说话带犹豫/迷糊的人（"啊？轮到我了吗"）讲不出推导链
            s.argument = "gut"
        elif re.search(r"心不在焉|经常离线|懵懂|不太会玩|水平一般|逻辑一般|新手|菜", blob) \
                and s.logic < 0.62:
            # 水平信号只能当辅助：档案里常有转折语境（阿蛮"玩得不多，但脑子太好使"、
            # 阿岚"自称不太会，实际远高于自述"），必须和 logic 分数交叉验证
            s.argument = "gut"

        def clamp(x):
            return max(0.05, min(0.95, x))
        s.aggression = clamp(s.aggression)
        s.logic = clamp(s.logic)
        s.bluff = clamp(s.bluff)
        s.caution = clamp(s.caution)
        s.loyalty = clamp(s.loyalty)
        s.verbosity = clamp(s.verbosity)
        return s

    def to_dict(self) -> dict:
        return {
            "aggression": self.aggression,
            "logic": self.logic,
            "bluff": self.bluff,
            "loyalty": self.loyalty,
            "caution": self.caution,
            "verbosity": self.verbosity,
            "argument": self.argument,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Style":
        return cls(
            aggression=data["aggression"],
            logic=data["logic"],
            bluff=data["bluff"],
            loyalty=data["loyalty"],
            caution=data["caution"],
            verbosity=data["verbosity"],
            argument=data["argument"],
        )


# ---------------------------------------------------------------- 话语
@dataclass
class Speech:
    text: str = ""
    claim: Optional[str] = None     # 公开跳的身份
    accuse: Optional[str] = None    # 踩的人（名字）
    defend: Optional[str] = None    # 保的人（名字）
    question_to: Optional[str] = None
    protected_facts: tuple[str, ...] = ()


@dataclass
class Decision:
    """一次决策的完整产物：内心推理 + 实际行动。"""
    reason: str = ""
    target: Optional[int] = None
    save: Optional[int] = None
    poison: Optional[int] = None
    speech: Optional[Speech] = None


# ---------------------------------------------------------------- 大脑
class Brain:
    def __init__(self, seat, engine, persona: dict, rng: random.Random,
                 llm=None, cognitive_state: dict | None = None,
                 match_carry: dict | None = None, emit_start: bool = True):
        self.me = seat                 # 自己的座位（Seat）
        self.name = seat.name
        self.engine = engine
        self.persona = persona
        self.rng = rng
        self.llm = llm                 # 有 Key 时每脑一次独立调用
        behavior_persona = persona.get("behavior_persona", persona)
        self.style = Style.from_persona(behavior_persona)
        self.cognition = CognitiveProfile.from_persona(
            behavior_persona, self.style, cognitive_state)
        # Match form is deliberately fresh each game.  Only the small carry
        # value can cross a game boundary; cognition remains its own profile.
        self.match_state = MatchState.start(rng, match_carry)
        # Keep a fixed baseline for the post-game coach: current state is
        # useful only when it can be compared with how this match began.
        self.starting_state = self.match_state.snapshot()

        # —— 私有信念（每个 Brain 独一份）——
        self.sus: dict[str, float] = {}
        self.claims: dict[str, str] = {}          # 谁公开跳了什么
        self.claim_order: list[tuple[str, str]] = []   # 跳身份的先后顺序
        self.accuse_log: list[tuple[int, str, str]] = []   # (day, 谁, 踩谁)
        self.defend_log: list[tuple[int, str, str]] = []   # (day, 谁, 保谁)
        self.vote_log: list[tuple[int, str, str, str]] = []     # (day, 谁, 投谁, 票种)
        # Challenge events and named targets. A target is not an exact quote:
        # context resolves prior utterances as candidates, never certain links.
        self.disputed_event_nos: list[int] = []
        self.disputed_targets: list[tuple[int, str]] = []
        self.flips: list[tuple[str, str, bool]] = []       # (谁, 身份, 是否狼)
        self.resolved_exiles: set[tuple[int, str]] = set()
        self.speeches: list[tuple[int, str, str]] = []     # (day, 谁, 话)
        self.silent: set[str] = set()                      # 划水过的人
        self.my_claims: list[str] = []                     # 我自己公开说过的话
        self.wolf_strategy: Optional[str] = None           # 狼人本局打法
        self.notes: list[str] = []
        # 个人"直觉"：每人对同一批人有不同的观察偏好，且跨夜稳定。
        # 这是"各自思考"的直接来源——同样的公开信息，不同人读出不同结论。
        self.gut: dict[str, float] = {}
        self.decision_traces: list[DecisionTrace] = []
        if emit_start:
            self._state_event("match_start")

    def effective_ability(self, dimension: str) -> float:
        """Current ability for a decision, without mutating long-term cognition."""
        baseline = getattr(self.cognition, dimension)
        return self.match_state.effective(baseline, dimension)

    def effective_abilities(self) -> dict[str, float]:
        names = ("evidence_processing", "recursive_reasoning", "social_reading",
                 "deception", "calibration", "decisiveness")
        return {name: self.effective_ability(name) for name in names}

    def _state_event(self, event: str) -> None:
        """Private coach ledger; never emitted as a public game event."""
        self.engine.history.append(GameEvent(
            type="npc_state", seat=self.me.pos, text=event,
            data={"name": self.name, "event": event,
                  "start": self.starting_state,
                  "state": self.match_state.snapshot()},
        ))

    def _trace_night(self, kind: str, decision: Decision, candidates: list[int]) -> None:
        self.decision_traces.append(DecisionTrace(
            actor=self.name, phase=self.engine.phase, day=self.engine.day_count,
            night=self.engine.night_count, action=kind, target=decision.target,
            reasoning_depth=max(1, min(self.cognition.max_depth,
                                       self.cognition.preferred_depth + self.match_state.depth_adjustment())),
            rationale=decision.reason, beliefs=BeliefState.from_brain(self, candidates).faction_probabilities
            if candidates else {}, alternatives=[], confidence=self.match_state.confidence,
            state_snapshot=self.match_state.snapshot(),
        ))

    def gut_of(self, nm: str) -> float:
        if nm not in self.gut:
            self.gut[nm] = self.rng.random()
        return self.gut[nm]

    # ================================================== 基础查询
    @property
    def role(self) -> str:
        return self.me.role

    @property
    def is_wolf(self) -> bool:
        return self.me.is_wolf

    def mates(self) -> list[str]:
        if not self.is_wolf or self.role == "stone_ghost":
            return []
        return [s.name for s in self.engine.seats.values()
                if s.is_wolf and s.role != "stone_ghost" and s.name != self.name]

    def alive_names(self) -> list[str]:
        return [s.name for s in self.engine.alive_seats()]

    def sus_of(self, nm: str) -> float:
        return self.sus.get(nm, PRIOR)

    def ensured(self, nm: str):
        self.sus.setdefault(nm, PRIOR)

    # ================================================== 观察（公开信息）
    def observe_flip(self, nm: str, role_cn: str, is_wolf: bool):
        """有人出局翻牌——最硬的信息，用它回推所有踩保关系。

        幂等：同一个人只记一次。否则重复事件会把踩保权重叠加，推理失真。
        """
        if any(f[0] == nm for f in self.flips):
            return
        self.flips.append((nm, role_cn, is_wolf))
        # Wolves may grieve a teammate they already know privately.  This is
        # derived solely from their legal wolfmate set, and is never published.
        if nm in self.mates():
            self.match_state.react("ally_lost")
            self._state_event("ally_lost")
        sign = -1 if is_wolf else 1
        # 踩过他的人：踩对了→像好人；踩错了→像狼
        for day, who, tgt in self.accuse_log:
            if tgt == nm:
                self.ensured(who)
                self.sus[who] += sign * 0.18
        # 保过他的人：保了狼→像狼；保了好人→像好人
        for day, who, tgt in self.defend_log:
            if tgt == nm:
                self.ensured(who)
                self.sus[who] -= sign * 0.20
        if is_wolf:
            self.sus.pop(nm, None)

    def observe_speech(self, day: int, who: str, sp: Speech, text: str, event_no=None):
        self.speeches.append((day, who, text))
        if event_no is not None and (sp.accuse or sp.defend):
            self.disputed_event_nos.append(event_no)
            for target in dict.fromkeys(t for t in (sp.accuse, sp.defend) if t):
                self.disputed_targets.append((event_no, target))
        if sp.claim:
            self.claims[who] = sp.claim
            if not any(w == who and c == sp.claim for w, c in self.claim_order):
                self.claim_order.append((who, sp.claim))
        if sp.accuse:
            self.accuse_log.append((day, who, sp.accuse))
            if sp.accuse == self.name and who != self.name:
                self.match_state.react("accused")
                self._state_event("accused")
        if sp.defend:
            self.defend_log.append((day, who, sp.defend))
            if sp.defend == self.name and who != self.name:
                self.match_state.react("defended")
                self._state_event("defended")
        if len(text.strip()) < 12:
            self.silent.add(who)

    def observe_vote(self, day: int, who: str, tgt: Optional[str], sheriff: bool = False):
        if tgt:
            self.vote_log.append((day, who, tgt, "sheriff" if sheriff else "exile"))

    def observe_exile(self, day: int, nm: str, is_wolf: bool):
        """Public exile: update vote evidence and exactly one personal read."""
        key = (day, nm)
        if key in self.resolved_exiles:
            return
        self.resolved_exiles.add(key)
        # A public exile resolves a voter's own binary call once.  Do not use
        # speeches here: a player can accuse and later vote differently.
        my_vote = next((target for d, who, target, kind in reversed(self.vote_log)
                        if d == day and who == self.name and kind == "exile"), None)
        if my_vote == nm:
            reaction = "correct_read" if is_wolf else "wrong_read"
            self.match_state.react(reaction)
            self._state_event(reaction)
        for d, who, t, kind in self.vote_log:
            if t == nm and kind == "exile":
                self.ensured(who)
                self.sus[who] += (-0.15 if is_wolf else 0.12)

    # ================================================== 怀疑度计算
    @staticmethod
    def _llr(p: float) -> float:
        """对数似然比——用 logit 累加代替线性加分，天然饱和。

        线性加分的致命问题：被 7 个人踩就 +0.70 直接打满，于是狼只要
        集体带票就能把一个好人钉死，全场（包括真预言家）跟着跑。
        logit 累加则越接近 1 增益越小，需要压倒性的证据才能定死。
        """
        p = min(0.98, max(0.02, p))
        return math.log(p / (1 - p))

    def _flipped(self, nm: str):
        return next((f for f in self.flips if f[0] == nm), None)

    def _base_suspicion(self, nm: str) -> float:
        """不含舆论项的"基础可疑度"，用来评估某个指控者自己有多像狼。

        只看硬信息（我验/查过的）+ 已翻牌的事实回推，不看"谁踩了他"，
        避免 A 依赖 B、B 又依赖 A 的循环推导。
        """
        e = self.engine
        seat = e.seat_by_name(nm)
        if seat is None or not seat.alive:
            return 0.9
        if nm == self.name or seat.name in self.mates():
            return -1.0

        p = PRIOR
        if self.role == "seer":                      # 我自己验过的，铁证
            for r in e.seer_results:
                if r["name"] == nm:
                    p = 0.93 if r["result"] == "wolf" else 0.05
        if self.role == "stone_ghost":
            for r in e.sg_results:
                if r["name"] == nm:
                    p = 0.91 if seat.is_wolf else 0.05
        if self.claims.get(nm) == "seer" and self.role == "seer":
            p = 0.88                                  # 跟我抢预言家 = 悍跳

        for _d, who, tgt in self.accuse_log:          # 他踩过已翻牌的人
            if who == nm:
                f = self._flipped(tgt)
                if f:
                    p = 0.28 if f[2] else 0.66        # 踩中狼→像好人
        for _d, who, tgt in self.defend_log:          # 他保过已翻牌的人
            if who == nm:
                f = self._flipped(tgt)
                if f:
                    p = 0.72 if f[2] else 0.30        # 保了狼→像狼
            if tgt == nm:
                f = self._flipped(who)
                if f and f[2]:
                    p = max(p, 0.78)                  # 被已翻牌的狼保过
        # Evidence processing, not static persona logic, determines how much
        # current form lets gut noise dilute evidence.  Personality still owns
        # aggression and speaking style elsewhere.
        evidence = self.effective_ability("evidence_processing")
        p += (1 - evidence) * (self.gut_of(nm) - 0.5) * 0.35
        return max(0.02, min(0.95, p))

    def suspicion(self, nm: str) -> float:
        """综合所有私有 + 公开证据，得出我对这个人的怀疑度。"""
        e = self.engine
        seat = e.seat_by_name(nm)
        if seat is None or not seat.alive:
            return 9.0
        if nm == self.name or seat.name in self.mates():
            return -1.0

        # —— 硬信息优先：我亲手验/查过的，舆论动摇不了 ——
        if self.role == "seer":
            for r in e.seer_results:
                if r["name"] == nm:
                    return 0.93 if r["result"] == "wolf" else 0.05
        if self.role == "stone_ghost":
            for r in e.sg_results:
                if r["name"] == nm:
                    return 0.91 if seat.is_wolf else 0.05
        if self.claims.get(nm) == "seer" and self.role == "seer":
            return 0.88                       # 我才是预言家，他是悍跳

        logit = self._llr(PRIOR)

        # —— 直接证据：踩保关系被翻牌证实/证伪（硬事实）——
        for _d, who, tgt in self.accuse_log:
            if who == nm:
                f = self._flipped(tgt)
                if f:
                    logit += self._llr(0.26) if f[2] else self._llr(0.68)
        for _d, who, tgt in self.defend_log:
            if who == nm:
                f = self._flipped(tgt)
                if f:
                    logit += self._llr(0.73) if f[2] else self._llr(0.30)
            if tgt == nm:
                f = self._flipped(who)
                if f and f[2]:
                    logit += self._llr(0.80)          # 被已翻牌的狼保过

        # —— 舆论项：按指控者的可信度加权（反向推理的核心）——
        # 狼踩谁，谁反而更像好人。每个指控者贡献一份、按可信度折算后累加：
        # 一个可信的人咬是弱信号，三个可信的人咬是强信号；
        # 若咬他的人本身就像狼，这一票反过来给被咬的人洗白。
        # （只取"最强的一次"会废掉好人的合力——试过，好人胜率反而更低。）
        for w in sorted({w for _d, w, t in self.accuse_log if t == nm}):
            logit += (0.5 - self._base_suspicion(w)) * 0.80
        for w in sorted({w for _d, w, t in self.defend_log if t == nm}):
            logit -= (0.5 - self._base_suspicion(w)) * 0.65

        # 投票关系：同样按投票人的可信度加权累加（只看放逐票，警长票不算踩人）
        for w in sorted({w for _d, w, t, kind in self.vote_log if t == nm and kind == "exile"}):
            logit += (0.5 - self._base_suspicion(w)) * 0.30

        # —— 跳身份的行为学 ——
        claim = self.claims.get(nm)
        if claim == "seer":
            rivals = [o for o, c in self.claims.items()
                      if c == "seer" and o != nm
                      and e.seat_by_name(o) and e.seat_by_name(o).alive]
            if rivals:
                # 两个人都在跳预言家。可用的判据是"先后顺序"：悍跳通常是后手，
                # 等真预言家报完再针对性的对咬。所以后跳的那个略可疑。
                order = [w for w, c in self.claim_order if c == "seer"]
                if nm in order and len(order) > 1 and order.index(nm) > 0:
                    logit += self._llr(0.55) - self._llr(PRIOR)
            else:
                logit += self._llr(0.32)      # 目前唯一一个跳的，暂且信
            if any(a[1] == nm and a[2] == self.name for a in self.accuse_log):
                logit += self._llr(0.80)      # 他踩了我，我对他观感立刻变差
        if claim in ("witch", "hunter", "guard"):
            if self.is_wolf:
                logit += self._llr(0.42)      # 对狼来说，明神是高价值目标
            else:
                logit += self._llr(0.28)      # 对好人来说，跳神职略可信

        if nm in self.silent:                 # 划水
            logit += self._llr(0.42) - self._llr(PRIOR)

        return 1.0 / (1.0 + math.exp(-logit))

    # ================================================== 夜间决策
    def day_skill(self, candidates: list[int]) -> Decision:
        """Choose from public beliefs and lawful private knowledge, never roles."""
        if not candidates:
            return Decision(target=None, reason="没有合法目标。")
        e = self.engine
        if self.role == "white_wolf_king":
            pool = [p for p in candidates if e.seat_at(p).name not in self.mates()]
            threats = [p for p in pool if self.claims.get(e.seat_at(p).name)
                       in ("seer", "witch", "hunter", "guard", "knight")]
            pressured = any(target == self.name for _day, _who, target in self.accuse_log)
            if not threats and not pressured:
                return Decision(target=None, reason="暂不自爆，继续观察。")
            pick = max(threats or pool, key=lambda p: (
                e.sheriff == p, self.gut_of(e.seat_at(p).name))) if pool else None
        else:
            pick = max(candidates, key=lambda p: self.suspicion(e.seat_at(p).name))
            if self.role == "knight" and self.suspicion(e.seat_at(pick).name) < 0.65:
                pick = None
        return Decision(target=pick, reason="根据公开发言与自己的判断选择是否发动技能。")

    def night(self, kind: str, candidates: list[int], **kw) -> Decision:
        """kind: seer / wolves / witch / guard / wolf_beauty / stone_ghost"""
        fn = {
            "seer": self._seer,
            "wolves": self._wolves,
            "witch": self._witch,
            "guard": self._guard,
            "wolf_beauty": self._beauty,
            "stone_ghost": self._sg,
        }.get(kind)
        if fn is None:
            return Decision(reason="我今晚没有行动。")
        decision = fn(candidates, **kw)
        # Form affects only which legal option is selected when close; it does
        # not reveal, add, or bypass information.  The bounded perturbation is
        # intentionally much smaller than the strategic score differences.
        if decision.target in candidates and len(candidates) > 1:
            noise = self.match_state.decision_noise(
                self.effective_ability("evidence_processing"))
            if self.rng.random() < noise:
                done = {r["target"] for r in self.engine.seer_results} if kind == "seer" else set()
                alternatives = [pos for pos in candidates if pos != decision.target and pos not in done]
                if alternatives:
                    decision.target = self.rng.choice(alternatives)
                    decision.reason += " 当前状态让我保留一点不确定性，改选另一名合法目标。"
        self._trace_night(kind, decision, candidates)
        return decision

    # ---- 预言家验人
    def _seer(self, cands: list[int], **kw) -> Decision:
        e = self.engine
        done = {r["name"] for r in e.seer_results}
        pool = [p for p in cands if e.seat_at(p).name not in done]
        if not pool:
            pool = list(cands)
        scored = sorted(((self.suspicion(e.seat_at(p).name), p) for p in pool),
                        reverse=True)
        top = scored[0]
        # 逻辑型挑最可疑的；直觉型会飘
        evidence = self.effective_ability("evidence_processing")
        pick = top[1] if self.rng.random() < 0.55 + 0.3 * evidence \
            else self.rng.choice(pool)
        tgt = e.seat_at(pick)
        reason = (f"已验 {len(done)} 人（{'、'.join(sorted(done)) if done else '无'}）。"
                  f"当前我最怀疑的是 {top[1]}号{e.seat_at(top[1]).name}"
                  f"（怀疑度{top[0]:.2f}）。")
        if self.style.caution > 0.6 and e.night_count == 1:
            reason += "第一晚先验一个话多/带节奏的，信息量最大。"
        return Decision(reason=reason, target=pick)

    # ---- 狼人刀人（每只狼独立提议，由 runner 汇总）
    def _wolves(self, cands: list[int], **kw) -> Decision:
        e = self.engine
        mates = set(self.mates())
        goods = [p for p in cands if e.seat_at(p).name not in mates]
        mate_pos = [p for p in cands if e.seat_at(p).name in mates]

        def threat(p: int) -> float:
            # 自己和队友都不是"威胁"——自刀是另一套战术，走 self_knife 分支。
            # 之前没排除自己，悍跳位会把自己算成头号威胁，还给出
            # "他跳了预言家，不刀他明天全场跟着他走" 这种自相矛盾的理由。
            if p == self.me.pos:
                return -1.0
            nm = e.seat_at(p).name
            t = 0.2
            claim = self.claims.get(nm)
            if claim == "seer":
                t += 0.75                       # 真/假预言家都必须死
            elif claim in ("witch", "guard", "hunter"):
                t += 0.35
                if claim == "witch" and e.witch_unlimited:
                    t += 0.70  # Public claim only: never inspect the hidden role.
            if e.sheriff == p:
                t += 0.30                       # 警长 1.5 票权
            if any(a[1] == nm and a[2] in mates for a in self.accuse_log):
                t += 0.35                       # 踩过我队友的，优先刀
            if any(a[1] == nm and a[2] == self.name for a in self.accuse_log):
                t += 0.25                       # 踩过我的
            t += self.suspicion(nm) * 0.5       # 我自己的判断
            # 个人直觉权重放大：狼之间对"该刀谁"本就该有分歧，
            # 权重太低会被公共证据压成"一致同意"，失去各自思考的价值
            t += self.gut_of(nm) * 0.45
            return t

        # —— 战术：自刀 ——
        # 情形一：我正准备悍跳，自刀做金水骗女巫解药
        # 情形二：队友被踩得厉害，送他出局洗白另一个人
        self_knife_chance = 0.0
        if self.wolf_strategy == "bluff" and e.night_count <= 2:
            self_knife_chance = 0.35 * self.effective_ability("deception")
        if goods and self.rng.random() < self_knife_chance:
            me_pos = self.me.pos
            if me_pos in cands:
                return Decision(
                    reason=(f"我打算悍跳预言家，先自刀做金水——女巫大概率会救我，"
                            f"这样我明天跳预言家就是「被救的银水」，可信度直接拉满。"
                            f"风险是女巫不救，但收益够大。"),
                    target=me_pos)

        ranked = sorted(((threat(p), p) for p in goods), reverse=True)
        if not ranked:
            return Decision(reason="场上只剩狼了，随便刀一个。",
                            target=(mate_pos[0] if mate_pos else None))
        pick = ranked[0][1]
        if self.rng.random() > 0.6 + 0.25 * self.effective_ability("evidence_processing") and len(ranked) > 1:
            pick = ranked[1][1]
        nm = e.seat_at(pick).name
        why = []
        if self.claims.get(nm) == "seer":
            why.append("他跳了预言家，不刀他明天全场跟着他走")
        if e.sheriff == pick:
            why.append("他是警长，1.5票权太碍事")
        if any(a[1] == nm and a[2] in mates for a in self.accuse_log):
            why.append(f"他白天踩过我的队友，必须做掉")
        if not why:
            why.append("威胁度最高，先削好人战力")
        return Decision(reason=f"候选里威胁度排序："
                              f"{' > '.join(f'{p}号{e.seat_at(p).name}' for _, p in ranked[:3])}。"
                              f"刀 {pick}号{nm}——{'；'.join(why)}。",
                        target=pick)

    # ---- 女巫（只有她知道刀口是谁）
    def _witch(self, cands: list[int], knife: Optional[int] = None,
               antidote: bool = True, poison: bool = True, **kw) -> Decision:
        e = self.engine
        save = poison_t = None
        parts = []
        can_save = antidote and (knife != self.me.pos or e.night_count == 1)
        if knife is not None and can_save:
            nm = e.seat_at(knife).name
            s = self.suspicion(nm)
            claim = self.claims.get(nm)
            # 救不救：第一天倾向救；明确神职/低怀疑必救；高怀疑不救
            if e.night_count == 1 and s < 0.6:
                save = knife
                parts.append(f"第一晚刀的是 {knife}号{nm}，信息太少，先救下看看（银水还能帮我判断他是不是自刀）")
            elif claim in ("seer", "witch", "guard", "hunter") and s < 0.5:
                save = knife
                parts.append(f"{knife}号{nm} 明跳神职，是好人核心，必须救")
            elif s > 0.7:
                parts.append(f"被刀的 {knife}号{nm} 我本来就怀疑（{s:.2f}），不救，" +
                             ("不帮可能自刀的狼保轮次" if e.witch_unlimited else "省药"))
            else:
                save = knife
                parts.append(f"{knife}号{nm} 倒牌，怀疑度{s:.2f}不算高，救下来保轮次")
        elif knife is not None and not antidote:
            parts.append(f"{knife}号被刀，但我的解药已经用掉了，救不了")

        # Unlimited single-potion play creates an opportunity cost, not a stock
        # cost. An aggressive witch can give up a rescue for a very strong read.
        if e.witch_unlimited and not e.witch_dual and save is not None and knife != self.me.pos:
            suspects = [p for p in cands if p != knife]
            if suspects and self.style.aggression > 0.65 and max(self.suspicion(e.seat_at(p).name) for p in suspects) > 0.85:
                save = None
                parts.append("但有更强的狼嫌疑目标，同夜只能一种药，改为放弃救人争取毒狼")
        if poison and (save is None or e.witch_dual):
            # 毒：只在证据比较硬的时候出手
            pool = [(self.suspicion(e.seat_at(p).name), p) for p in cands]
            pool = [x for x in pool if x[1] != knife]
            if pool:
                pool.sort(reverse=True)
                s, p = pool[0]
                if s > 0.78 and self.style.aggression > 0.4:
                    poison_t = p
                    parts.append(f"{p}号{e.seat_at(p).name} 怀疑度{s:.2f}，证据够硬，直接毒掉")
                elif e.night_count >= 3 and s > 0.7:
                    poison_t = p
                    parts.append(f"已经第{e.night_count}夜，再不毒就没机会了，毒掉 {p}号（{s:.2f}）")
                else:
                    parts.append(f"最可疑的是 {p}号（{s:.2f}），但还没到必毒的程度，" +
                                 ("药虽无限，也不能盲毒好人" if e.witch_unlimited else "先留着毒药"))
        if not parts:
            parts.append("没有明确的用药必要，今晚空过")
        return Decision(reason="。".join(parts) + "。", save=save, poison=poison_t)

    # ---- 守卫
    def _guard(self, cands: list[int], **kw) -> Decision:
        e = self.engine
        pool = [p for p in cands if p != e.guard_last]
        if not pool:
            pool = list(cands)

        def worth(p: int) -> float:
            nm = e.seat_at(p).name
            w = 0.2
            if self.claims.get(nm) == "seer":
                w += 0.7
            elif self.claims.get(nm) in ("witch", "hunter"):
                w += 0.3
            if e.sheriff == p:
                w += 0.2
            if p == self.me.pos and self.style.caution > 0.6:
                w += 0.15
            return w + self.rng.uniform(0, 0.12)

        ranked = sorted(((worth(p), p) for p in pool), reverse=True)
        pick = ranked[0][1]
        nm = e.seat_at(pick).name
        why = "他跳了预言家，是狼队首要目标" if self.claims.get(nm) == "seer" \
            else "感觉他今晚最可能被刀"
        limit = "首夜没有连守限制" if e.guard_last is None \
            else f"不能连守（上一晚守的 {e.guard_last}号今晚不能再守）"
        return Decision(reason=f"{limit}。守 {pick}号{nm}——{why}。", target=pick)

    # ---- 狼美人魅惑
    def _beauty(self, cands: list[int], **kw) -> Decision:
        e = self.engine
        mates = set(self.mates())
        pool = [p for p in cands if e.seat_at(p).name not in mates] or list(cands)
        ranked = sorted(((self.suspicion(e.seat_at(p).name) * -1
                          + (0.6 if self.claims.get(e.seat_at(p).name) == "seer" else 0)
                          + (0.3 if e.sheriff == p else 0), p) for p in pool), reverse=True)
        pick = ranked[0][1]
        return Decision(reason=f"魅惑 {pick}号{e.seat_at(pick).name}——"
                              f"大概率是神职/警长核心，我若出局能拉他垫背。",
                        target=pick)

    # ---- 石像鬼查验
    def _sg(self, cands: list[int], **kw) -> Decision:
        e = self.engine
        done = {r["name"] for r in e.sg_results}
        pool = [p for p in cands if e.seat_at(p).name not in done] or list(cands)
        # 优先查跳了身份的人：确认真预言家/真神，方便狼队定点清除
        ranked = sorted(((
            (0.8 if self.claims.get(e.seat_at(p).name) else 0)
            + (0.3 if e.sheriff == p else 0)
            + self.rng.uniform(0, 0.2), p) for p in pool), reverse=True)
        pick = ranked[0][1]
        why = ("他公开跳了身份，先摸清底牌，狼队好定点清除"
               if self.claims.get(e.seat_at(pick).name) else "先摸一个人的底牌")
        return Decision(reason=f"查 {pick}号{e.seat_at(pick).name} 的具体身份——{why}。",
                        target=pick)

    # ================================================== 白天发言
    def speak(self, day: int, today: list[tuple[str, Speech]]) -> Speech:
        """today: 今天已经说过话的人 [(name, Speech)]，按发言顺序。"""
        e = self.engine
        alive = [s.name for s in e.alive_seats() if s.name != self.name]
        if not alive:
            return Speech(text="……")

        # 我当前的判断
        ranked = sorted(((self.suspicion(n), n) for n in alive), reverse=True)
        top_s, top_n = ranked[0]
        my_claim = self.claims.get(self.name)

        # 今天已经有人跳预言家了吗
        seer_claimants = [n for n, c in self.claims.items()
                          if c == "seer" and n != self.name
                          and e.seat_by_name(n) and e.seat_by_name(n).alive]
        accused_me = [w for _d, w, t in self.accuse_log if t == self.name]

        sp = Speech()
        # ---------- 狼人 ----------
        if self.is_wolf:
            sp = self._wolf_speak(day, ranked, seer_claimants, accused_me, today)
        # ---------- 预言家 ----------
        elif self.role == "seer":
            sp = self._seer_speak(day, ranked, seer_claimants, accused_me)
            if self.claims.get(self.name) == "seer" and sp.claim is None:
                sp = Speech(text="我仍然认预言家身份，下面报完整查验口径。", claim="seer")
        # ---------- 其他神职 ----------
        elif self.role in ("witch", "guard", "hunter", "knight", "gravekeeper", "crow"):
            sp = self._god_speak(day, ranked, seer_claimants, accused_me)
        # ---------- 平民 ----------
        else:
            sp = self._civ_speak(day, ranked, seer_claimants, accused_me)

        if not sp.text:
            sp.text = "我没什么信息，先过。"
        prefix = self.match_state.expression_prefix()
        if prefix and self.rng.random() < 0.42:
            sp.text = prefix + sp.text
        if self.engine.locale == "en":
            sp.text = self._english_line(sp)
        if sp.claim == "seer":
            account = self.check_account(sp.accuse)
            sp.text += "\n" + account
            sp.protected_facts = (account,)
        return sp

    def check_account(self, preferred=None):
        """A real Seer's own results, or this actor's stable invented account.

        Never read another role's check results to construct a bluff.
        """
        e = self.engine
        if self.role == "seer":
            records = list(e.seer_results)
        else:
            if not hasattr(self, "_bluff_checks"):
                self._bluff_checks = {}
            night = max(1, e.night_count)
            if night not in self._bluff_checks:
                prior = {r["target"] for r in self._bluff_checks.values()}
                pool = [s for s in e.alive_seats() if s.name != self.name and s.pos not in prior]
                if pool:
                    target = next((s for s in pool if s.name == preferred), pool[0])
                    self._bluff_checks[night] = {"night": night, "target": target.pos, "name": target.name, "result": "wolf"}
            records = list(self._bluff_checks.values())
        if e.locale == "en":
            return "My claimed checks: " + ("; ".join(f"night {r['night']}: #{r['target']} {r['name']} — {'werewolf' if r['result'] == 'wolf' else 'good'}" for r in records) or "none to report.")
        return "我的查验口径：" + ("；".join(f"第{r['night']}夜：{r['target']}号{r['name']}——{'查杀' if r['result'] == 'wolf' else '金水'}" for r in records) or "暂无查验结果。")

    def answer_check_question(self):
        if self.claims.get(self.name) != "seer":
            return Speech(text="I have not publicly claimed Seer; I have no claimed checks to give." if self.engine.locale == "en" else "我没有公开跳预言家，没有宣称过查验结果。")
        account = self.check_account()
        return Speech(text=account, claim="seer", protected_facts=(account,))

    def _english_line(self, speech: Speech) -> str:
        """Offline English realization preserves the already locked intent."""
        catch = (self.persona.get("catchphrases") or [""])[0]
        lead = (catch + " ") if catch else ""
        if speech.claim == "seer":
            if self.role == "seer":
                target = speech.accuse or speech.defend
                result = next((r for r in reversed(self.engine.seer_results)
                               if r["name"] == target), None)
                if result:
                    alignment = "a werewolf" if result["result"] == "wolf" else "good"
                    return lead + (f"I am the Seer. On night {result['night']}, I checked "
                                   f"#{result['target']} {target}: {alignment}.")
            if speech.accuse:
                return lead + f"I am the Seer. I accuse {speech.accuse}; their story conflicts with my claim."
            return lead + "I am the Seer. I have no confirmed wolf to report yet."
        if speech.accuse:
            evidence = self._english_evidence(speech.accuse)
            argument = {
                "logic": f"I suspect {speech.accuse}. {evidence or 'I want to compare their claims with the votes.'}",
                "gut": f"My gut says {speech.accuse}. {evidence or 'It is a read, not proof; hear them out.'}",
                "both": f"There may be another explanation, but I lean toward {speech.accuse}. {evidence}",
                "probe": f"{speech.accuse}, explain your reasoning. {evidence or 'Which public fact supports your claim?'}",
            }
            return lead + argument.get(self.style.argument, f"I suspect {speech.accuse}. {evidence}").strip()
        if speech.defend:
            return lead + f"I want to hold {speech.defend} for now. Do not lock the vote too early."
        return lead + "I am not ready to lock a vote. I want to hear the table first."

    def _english_evidence(self, name: str) -> str:
        for _day, who, target in self.accuse_log:
            flipped = self._flipped(target)
            if who == name and flipped and not flipped[2]:
                return f"They accused {target}, who later flipped good."
        for _day, who, target in self.defend_log:
            flipped = self._flipped(target)
            if who == name and flipped and flipped[2]:
                return f"They defended {target}, who later flipped wolf."
        if any(who == name and target == self.name for _day, who, target in self.accuse_log):
            return "They accused me; I want to hear the evidence."
        if name in self.silent:
            return "They have not committed to a clear position."
        return ""

    # ================================================== 桌面插话
    def interruption_interest(self, speaker: str, speech: Speech) -> float:
        """Whether this player has a public-discourse reason to cut in.

        The score uses only the utterance and this brain's lawful beliefs.  It
        never grants new information and is only a request to the host, which
        remains responsible for allowing or closing the exchange.
        """
        if speaker == self.name:
            return 0.0
        score = 0.08 + self.style.verbosity * 0.20 + self.style.aggression * 0.18
        score += self.effective_ability("social_reading") * 0.08
        if speech.accuse == self.name or speech.defend == self.name:
            score += 0.48
        elif speech.accuse:
            score += 0.20 + abs(self.suspicion(speech.accuse) - 0.5) * 0.18
        elif speech.claim:
            score += 0.17
        return min(0.88, score)

    def table_interjection(self, speaker: str, speech: Speech) -> Speech:
        """A deliberately short public interruption, never a new action."""
        target = speech.accuse or speech.defend
        if speech.defend == self.name and speech.accuse != self.name:
            text = (f"{speaker}, thanks for hearing me out. Please keep checking my claims against the public record."
                    if self.engine.locale == "en" else f"{speaker}，谢谢你愿意听我的说法，但大家仍要对照公开记录核实。")
            return Speech(text=text)
        if speech.accuse == self.name:
            text = self._say(f"{speaker}，你这个点我不同意，别只凭一句话就定我",
                             evidence=self._why_suspect(speaker), who=speaker)
            return self._english_table(Speech(text=text, accuse=speaker), speaker, target)
        if speech.accuse:
            belief = self.suspicion(speech.accuse)
            if belief >= 0.60:
                text = self._say(f"我补一句，{speech.accuse} 确实值得继续解释",
                                 evidence=self._why_suspect(speech.accuse), who=speech.accuse)
                return self._english_table(Speech(text=text, accuse=speech.accuse), speaker, speech.accuse)
            text = self._say(f"先别急着把 {speech.accuse} 定死，{speaker} 的依据还不够",
                             evidence=self._why_suspect(speaker), who=speaker)
            return self._english_table(Speech(text=text, accuse=speaker), speaker, speaker)
        if speech.claim:
            return self._english_table(Speech(text=self._say(f"{speaker} 既然跳了身份，把理由和前后逻辑说清楚")), speaker, None)
        social = self.rng.choice([
            "今天桌上火药味有点重，大家先把话说完整",
            "我听着有点绕，先别急着把谁按死",
            "我插一句，气氛归气氛，最后还是拿发言和票型说话",
        ])
        return self._english_table(Speech(text=self._say(social)), speaker, None)

    def table_reply(self, interrupter: str) -> Speech:
        """One concise reply after an interruption; the host closes it after."""
        reply = Speech(text=self._say(f"{interrupter} 的问题我听到了，我的理由已经摆出来，"
                                      "大家结合后面的发言再判断"))
        if self.engine.locale == "en":
            reply.text = f"I hear {interrupter}'s question. My reasoning is on the table; weigh it with the rest."
        return reply

    def _english_table(self, speech: Speech, speaker: str, target: str | None) -> Speech:
        if self.engine.locale != "en":
            return speech
        if target == self.name:
            speech.text = f"{speaker}, I disagree with that read on me. Do not decide this from one line."
        elif speech.accuse:
            speech.text = f"Let me cut in: {target} still needs to explain that point."
        else:
            speech.text = f"One quick point about {speaker}'s statement: keep the discussion grounded."
        return speech

    # ================================================== 个性化表达
    def _why_suspect(self, nm: str) -> str:
        """说出我怀疑这个人的具体理由——依据只能来自我自己的观察日志。

        这是"每个人说法不同"的根：同一个结论，细草会追问依据，
        阿墨先两面看再下结论，大山只凭直觉。
        """
        e = self.engine
        if self.role == "seer":                       # 我亲手验的
            for r in e.seer_results:
                if r["name"] == nm:
                    return f"我第{r['night']}夜验了 {nm}，结果是{'查杀' if r['result'] == 'wolf' else '金水'}"
        if self.role == "stone_ghost":
            for r in e.sg_results:
                if r["name"] == nm:
                    return f"我查过 {nm} 的底"
        for _d, who, tgt in self.accuse_log:          # 他踩过已翻牌的好人
            if who == nm:
                f = self._flipped(tgt)
                if f and not f[2]:
                    return f"{nm} 咬过 {tgt}，而 {tgt} 翻牌是好人"
        for _d, who, tgt in self.defend_log:          # 他保过已翻牌的狼
            if who == nm and self._flipped(tgt) and self._flipped(tgt)[2]:
                return f"{nm} 保过 {tgt}，{tgt} 已经翻牌是狼"
            if tgt == nm:
                f = self._flipped(who)
                if f and f[2]:
                    return f"{nm} 被 {who} 保过，而 {who} 是狼"
        if any(a[1] == nm and a[2] == self.name for a in self.accuse_log):
            return f"{nm} 上来就咬我"
        if self.claims.get(nm) == "seer" and self.role == "seer":
            return f"{nm} 也在跳预言家，而我才是真的"
        if nm in self.silent:
            return f"{nm} 一直在划水，什么都不说"
        return ""

    def _say(self, core: str, evidence: str = "", who: str = "") -> str:
        """按角色的论证风格把结论包装成"他自己的话"。"""
        st = self.style
        arg = st.argument
        if arg == "logic":
            body = f"{evidence}，所以{core}" if evidence else f"按现场信息推，{core}"
        elif arg == "gut":
            body = (f"我就觉得{core}，说不上来为什么，但这个感觉很强烈"
                    if st.verbosity > 0.55 and who else f"我就觉得{core}")
        elif arg == "both":
            body = (f"这个事情嘛，要从两面看……{evidence}。不过综合下来，还是{core}"
                    if evidence else f"这个事情嘛，两面都能说，但我倾向{core}")
        elif arg == "probe":
            body = (f"等一下，{evidence}——这个点你怎么解释？{core}"
                    if evidence else f"你先回答我，凭什么？{core}")
        else:
            body = f"{evidence}，{core}" if evidence else core

        # 话多的人再补一句，话少的人到此为止
        if st.verbosity > 0.62 and self.rng.random() < 0.45:
            body += self.rng.choice(["，这是我目前最确定的判断",
                                     "，大家可以参考一下",
                                     "，我先摆在这儿，你们自己看"])
        cp = [c for c in (self.persona.get("catchphrases") or []) if _clean_cp(c)]
        if cp and self.rng.random() < 0.30 + 0.35 * st.verbosity:
            pick = _clean_cp(self.rng.choice(cp))
            # 口头禅本身已经带论证味道时（阿墨的"要从两面来看"），
            # 再套一遍论证模板就成了"两面看……两面看……"的车轱辘话
            if re.search(r"两面|推导|为什么|凭什么|觉得|猜|准不准", pick):
                return f"{pick}，{core}"
            body = f"{pick}，{body}"
        return body

    def _accuse_speech(self, nm: str, lead: str = "我点一个") -> str:
        """生成一句有个人风格的踩人发言。"""
        return self._say(f"{lead} {nm}，他今天最不对劲",
                         evidence=self._why_suspect(nm), who=nm)

    # ---- 狼人发言
    def _wolf_speak(self, day, ranked, seer_claimants, accused_me, today) -> Speech:
        e = self.engine
        mates = self.mates()
        top_s, top_n = ranked[0]
        # 找一个"可以牺牲/不被怀疑"的好人当靶子
        target = top_n
        # 悍跳：我是本局的悍跳位
        if self.wolf_strategy == "bluff" and not seer_claimants:
            # 给一个假查杀：挑威胁最大的好人。演得再像也得有个人腔调
            victim = top_n
            self.claims[self.name] = "seer"
            return Speech(
                text=self._say(f"我是预言家，今天我先出 {victim}，下面报我的查验口径"),
                claim="seer", accuse=victim)
        # 场上已经有人跳预言家了
        if seer_claimants:
            mates_set = set(self.mates())
            rival = next((n for n in seer_claimants if n not in mates_set), None)
            mate_claim = next((n for n in seer_claimants if n in mates_set), None)
            if self.wolf_strategy == "bluff" and rival:
                # 我就是悍跳位 —— 咬死真预言家，绝不让他把节奏带走
                return Speech(
                    text=self._say(f"{rival} 是悍跳，我才是真预言家，"
                                   f"他那个报法不对，大家别跟，先出他"),
                    claim="seer", accuse=rival)
            if mate_claim:
                target = next((n for _score, n in ranked if n not in mates_set and n != mate_claim), top_n)
                # 队友在悍跳，我配合他，顺手把水搅浑
                return Speech(
                    text=self._say(f"我站 {mate_claim}，他报得比较实。"
                                   f"{target} 值得继续解释",
                                   evidence=self._why_suspect(target), who=target),
                    accuse=target, defend=mate_claim)
            lead = seer_claimants[0]
            if lead == top_n or lead in accused_me:
                return Speech(text=self._say(f"我不接受 {lead} 的说法，需要他解释查验和判断依据",
                                             evidence=self._why_suspect(lead), who=lead), accuse=lead)
            return Speech(
                text=self._say(f"我先听 {lead} 的，{top_n} 今天有点飘，别被带节奏",
                               evidence=self._why_suspect(top_n), who=top_n),
                accuse=top_n, defend=lead)
        # 划水 / 倒钩
        if self.style.aggression < 0.4:
            return Speech(text=self._say("我是平民，信息不多，先跟着大家走，听预言家的"))
        if accused_me:
            return Speech(
                text=self._say(f"{accused_me[0]} 你咬我没道理啊，我哪里像狼了，"
                               f"{top_n} 才更可疑",
                               evidence=self._why_suspect(top_n), who=top_n),
                accuse=top_n)
        return Speech(text=self._accuse_speech(top_n, lead="我比较怀疑"),
                      accuse=top_n)

    # ---- 预言家发言
    def _seer_speak(self, day, ranked, seer_claimants, accused_me) -> Speech:
        e = self.engine
        res = e.seer_results
        wolves_found = [r for r in res if r["result"] == "wolf"]
        goods_found = [r for r in res if r["result"] == "good"]

        def _still(name):
            s = e.seat_by_name(name)
            return s is not None and s.alive

        if seer_claimants:
            # 有人跟我抢 → 直接对跳。我手里有硬货，说话底气不同
            rival = seer_claimants[0]
            r = wolves_found[-1] if wolves_found else None
            if r and _still(r["name"]):
                core = (f"{rival} 是悍跳，我才是真预言家。我第{r['night']}夜验了 "
                        f"{r['target']}号{r['name']} 是查杀，大家别被他带偏")
            else:
                core = f"{rival} 是悍跳，我才是真预言家，大家别跟错人"
            return Speech(text=self._say(core), claim="seer",
                          accuse=(r["name"] if r and _still(r["name"]) else rival))
        if wolves_found:
            r = wolves_found[-1]
            if _still(r["name"]):
                return Speech(
                    text=self._say(f"我是预言家，第{r['night']}夜验了 {r['target']}号"
                                   f"{r['name']}，查杀，今天必出他"),
                    claim="seer", accuse=r["name"])
        if goods_found and (self.style.aggression > 0.45 or day >= 2):
            r = goods_found[-1]
            if _still(r["name"]):
                return Speech(
                    text=self._say(f"我是预言家，验了 {r['target']}号{r['name']} 是金水，"
                                   f"这个位置可以信"),
                    claim="seer", defend=r["name"])
        if self.style.caution > 0.6 and day == 1:
            return Speech(text=self._say("我是平民，第一天没什么信息，先听听大家"))
        return Speech(text=self._say("我是预言家，暂时还没验出明确的狼，"
                                     "先不报太多，我接着验"), claim="seer")

    # ---- 其他神职
    def _god_speak(self, day, ranked, seer_claimants, accused_me) -> Speech:
        top_s, top_n = ranked[0]
        if self.role == "witch" and self.style.aggression > 0.5 and day >= 2:
            return Speech(text=self._accuse_speech(top_n, lead="今天先出"),
                          accuse=top_n)
        if accused_me and self.style.aggression > 0.45:
            return Speech(
                text=self._say(f"咬我的都注意点，我不是狼。{top_n} 才更可疑",
                               evidence=self._why_suspect(top_n), who=top_n),
                accuse=top_n)
        if seer_claimants and self.style.logic > 0.5:
            lead = min(seer_claimants, key=self.suspicion)
            if lead in accused_me:
                return Speech(text=self._accuse_speech(lead, lead="我不接受"), accuse=lead)
            return Speech(
                text=self._say(f"我暂时站 {lead}，这是站边判断，还需要核对他的查验和票型"), defend=lead)
        return Speech(text=self._accuse_speech(top_n, lead="我比较怀疑"),
                      accuse=top_n)      # 话里点了名就得认账，否则推理链断了

    # ---- 平民
    def _civ_speak(self, day, ranked, seer_claimants, accused_me) -> Speech:
        top_s, top_n = ranked[0]
        if accused_me:
            return Speech(
                text=self._say(f"{accused_me[0]} 你咬我我认不了，{top_n} 反而更像狼",
                               evidence=self._why_suspect(top_n), who=top_n),
                accuse=top_n)
        if self.style.aggression > 0.6 and top_s > 0.5:
            return Speech(text=self._accuse_speech(top_n, lead="我点一个"),
                          accuse=top_n)
        if seer_claimants:
            lead = min(seer_claimants, key=self.suspicion)
            return Speech(
                text=self._say(f"我暂时站 {lead}，需要继续核对他的查验和票型"), defend=lead)
        if self.style.aggression < 0.4:
            return Speech(text=self._say("我是平民，没信息，先过，听后面"))
        return Speech(text=self._accuse_speech(top_n, lead="暂时看"),
                      accuse=top_n if top_s > 0.55 else None)

    # ================================================== 投票
    def vote(self, cands: list[int], sheriff: bool = False) -> tuple[Optional[int], str]:
        plan = StrategicVotePlanner(self).plan(cands, sheriff=sheriff)
        self.decision_traces.append(plan.trace)
        return plan.target, plan.rationale

    def grow(self, won: bool) -> str:
        """Learn from trace quality with bounded updates across games."""
        return self.cognition.learn(self.decision_traces, won)

    # ================================================== 狼队打法分配
    def assign_wolf_strategy(self, rank: int, total: int):
        """狼队按性格分工：最能演的那一只去悍跳，其余划水/深水。

        只允许一个悍跳位——两只狼同时跳预言家会互相拆台，那是送人头。
        分工是团队协同，但每个人对局势的判断仍然各自独立。
        """
        if self.wolf_strategy:
            return
        if rank == 0:
            self.wolf_strategy = "bluff"          # 队里最能演的那只
        elif self.style.aggression < 0.4:
            self.wolf_strategy = "quiet"          # 低调划水
        else:
            self.wolf_strategy = "undercover"     # 深水/倒钩

    # ================================================== 快照 / 恢复
    def snapshot(self) -> dict:
        """Whitelisted private-state snapshot; no engine/persona/llm references."""
        return deepcopy({
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "style": self.style.to_dict(),
            "cognition": self.cognition.snapshot(),
            "match_state": self.match_state.snapshot(),
            "starting_state": self.starting_state,
            "sus": self.sus,
            "claims": self.claims,
            "claim_order": self.claim_order,
            "accuse_log": self.accuse_log,
            "defend_log": self.defend_log,
            "vote_log": self.vote_log,
            "disputed_event_nos": self.disputed_event_nos,
            "disputed_targets": self.disputed_targets,
            "flips": self.flips,
            "resolved_exiles": sorted(self.resolved_exiles),
            "speeches": self.speeches,
            "silent": sorted(self.silent),
            "my_claims": self.my_claims,
            "wolf_strategy": self.wolf_strategy,
            "notes": self.notes,
            "gut": self.gut,
            "decision_traces": [trace.to_dict() for trace in self.decision_traces],
            "bluff_checks": {str(night): check for night, check in
                             getattr(self, "_bluff_checks", {}).items()},
            "rng": encode_rng(self.rng),
        })

    def restore(self, data: dict) -> None:
        """Restore private state in place; seat/engine/persona/llm stay wired.

        Validate-then-apply: every field is type/range checked and converted
        *before* any attribute is replaced, so a corrupt snapshot cannot leave
        a half-restored brain.
        """
        where = "Brain.snapshot"
        check_version(data, where)
        data = deepcopy(data)

        # ---- validate (no mutation) ----
        name = require_str(data, "name", where, allow_empty=False)
        style = Style.from_dict(require_dict(data, "style", where))
        cognition = CognitiveProfile.restore(require_dict(data, "cognition", where))
        match_state = MatchState.restore(require_dict(data, "match_state", where))
        starting_state = require_dict(data, "starting_state", where)
        sus = require_dict(data, "sus", where)
        claims = require_dict(data, "claims", where)
        gut = require_dict(data, "gut", where)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in sus.values()):
            raise ValueError(f"{where}: sus values must be numbers")
        if any(not isinstance(v, str) for v in claims.values()):
            raise ValueError(f"{where}: claims values must be strings")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in gut.values()):
            raise ValueError(f"{where}: gut values must be numbers")

        def tuples(items, label):
            out = []
            for item in items:
                if not isinstance(item, (list, tuple)):
                    raise ValueError(f"{where}: {label} entries must be arrays")
                out.append(tuple(item))
            return out

        claim_order = tuples(require_list(data, "claim_order", where), "claim_order")
        accuse_log = tuples(require_list(data, "accuse_log", where), "accuse_log")
        defend_log = tuples(require_list(data, "defend_log", where), "defend_log")
        vote_log = tuples(require_list(data, "vote_log", where), "vote_log")
        # Legacy 3-tuples (day, who, target) carry no vote kind; mark it unknown
        # rather than fabricating "exile" for an old record.
        vote_log = [v if len(v) == 4 else v + ("unknown",) for v in vote_log]
        flips = tuples(require_list(data, "flips", where), "flips")
        resolved_exiles = set()
        for item in require_list(data, "resolved_exiles", where):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(
                    f"{where}: resolved_exiles entries must be [int, str] pairs")
            seat, role = item
            if type(seat) is not int or isinstance(seat, bool):
                raise ValueError(f"{where}: resolved_exiles seat must be an integer")
            if not isinstance(role, str):
                raise ValueError(f"{where}: resolved_exiles role must be a string")
            resolved_exiles.add((seat, role))
        speeches = tuples(require_list(data, "speeches", where), "speeches")

        silent = require_list(data, "silent", where)
        my_claims = require_list(data, "my_claims", where)
        notes = require_list(data, "notes", where)
        for label, values in (("silent", silent), ("my_claims", my_claims),
                              ("notes", notes)):
            if any(not isinstance(x, str) for x in values):
                raise ValueError(f"{where}: {label} must be an array of strings")
        silent = set(silent)

        traces = [DecisionTrace.from_dict(trace)
                  for trace in require_list(data, "decision_traces", where)]
        wolf_strategy = data.get("wolf_strategy")
        if wolf_strategy is not None and not isinstance(wolf_strategy, str):
            raise ValueError(f"{where}: wolf_strategy must be a string or null")

        bluff_raw = data.get("bluff_checks", {})
        if not isinstance(bluff_raw, dict):
            raise ValueError(f"{where}: bluff_checks must be an object")
        bluff_checks = {}
        for night, check in bluff_raw.items():
            if not isinstance(night, str) or not night.lstrip("-").isdigit():
                raise ValueError(f"{where}: bluff_checks keys must be night numbers")
            if not isinstance(check, dict):
                raise ValueError(f"{where}: bluff_checks values must be objects")
            bluff_checks[int(night)] = check
        rng = decode_rng(data.get("rng"))
        disputed = require_list(data, "disputed_event_nos", where) if "disputed_event_nos" in data else []
        if any(type(x) is not int or x < 1 for x in disputed):
            raise ValueError(f"{where}: disputed_event_nos must be positive integers")
        targets = tuples(require_list(data, "disputed_targets", where), "disputed_targets") if "disputed_targets" in data else []
        if any(len(row) != 2 or type(row[0]) is not int or row[0] not in disputed
               or not isinstance(row[1], str) or not row[1] for row in targets):
            raise ValueError(f"{where}: invalid disputed_targets")

        # ---- apply ----
        self.name = name
        self.style = style
        self.cognition = cognition
        self.match_state = match_state
        self.starting_state = starting_state
        self.sus = sus
        self.claims = claims
        self.claim_order = claim_order
        self.accuse_log = accuse_log
        self.defend_log = defend_log
        self.vote_log = vote_log
        self.disputed_event_nos = disputed
        self.disputed_targets = targets
        self.flips = flips
        self.resolved_exiles = resolved_exiles
        self.speeches = speeches
        self.silent = silent
        self.my_claims = my_claims
        self.wolf_strategy = wolf_strategy
        self.notes = notes
        self.gut = gut
        self.decision_traces = traces
        self._bluff_checks = bluff_checks
        self.rng = rng
