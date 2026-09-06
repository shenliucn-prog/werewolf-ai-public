"""狼人杀 · 无 UI 命令行对局。

和 Web 版的区别
--------------
* 不要浏览器、不要 SSE，纯文本一局跑到底，直接读终端。
* **12 个座位全部由 AI 驾驶**（含阿承），旁观者是上帝视角。
* **每个角色一个 Brain 实例**：私有信念、私有随机数、私有推理链。
  同一个局面下不同角色会给出不同判断，狼队刀人也是各自提案再收敛。
* 每次决策先打印「思考」（该角色此刻的内心推理），再打印他实际做的事。

用法
----
    python -m werewolf_web.cli_game                    # 经典板，随机种子
    python -m werewolf_web.cli_game --board wolf_king  # 换板子
    python -m werewolf_web.cli_game --seed 42          # 复现同一局
    python -m werewolf_web.cli_game --delay 0.4        # 逐条慢慢看
    python -m werewolf_web.cli_game --no-think         # 只看发言，不看思考
    python -m werewolf_web.cli_game --log game.md      # 同时落盘
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

from . import config
from .game import engine as eng_mod
from .game.models import WOLF_ROLES
from .ai import brain as brain_mod
from .ai.npc import load_seat_persona
from .ai.host import HostAgent
from .ai.llm import LLMClient

BAR = "═" * 66
SUB = "─" * 66
NIGHT_ORDER = {"seer": 0, "wolves": 1, "witch": 2, "guard": 3,
               "wolf_beauty": 4, "stone_ghost": 5}


class CLIGame:
    def __init__(self, board_id="classic", seed=None, delay=0.0,
                 show_think=True, log_path=None, quiet=False):
        self.engine = eng_mod.GameEngine(board_id, seed=seed)
        self.seed = seed if seed is not None else random.randrange(1, 10 ** 6)
        self.engine.rng = random.Random(self.seed)
        self.delay = delay
        self.show_think = show_think
        self.quiet = quiet
        self.log_path = log_path
        self._log_lines: list[str] = []
        self.brains: dict[str, brain_mod.Brain] = {}
        self._triggered: set[int] = set()
        self.llm = LLMClient()
        self.host = HostAgent(self.llm)

    # ---------------------------------------------------------- 输出
    def out(self, s: str = ""):
        print(s)
        self._log_lines.append(s)

    def think(self, who: str, text: str):
        """打印某个角色的私密推理。"""
        if not self.show_think:
            return
        for i, line in enumerate(_wrap(text, 58)):
            tag = "思考" if i == 0 else "    "
            if i == 0:
                self.out(f"   {tag}· {line}")
            else:
                self.out(f"     {line}")

    def pause(self, mult=1.0):
        if self.delay:
            time.sleep(self.delay * mult)

    # ---------------------------------------------------------- 初始化
    def _init_brains(self):
        e = self.engine
        for pos, s in sorted(e.seats.items()):
            persona = self._persona(s.name)
            # 每人一个独立随机源 —— 思想是各自跑的，不是共享一个 RNG
            rng = random.Random(self.seed * 7919 + pos * 104729)
            self.brains[s.name] = brain_mod.Brain(
                seat=s, engine=e, persona=persona, rng=rng,
                llm=self.llm if self.llm.online else None)

        # 狼队打法分配：最能演的去悍跳，其余划水/深水
        wolves = sorted(e.wolves(),
                        key=lambda w: -(self.brains[w.name].style.bluff * 0.6
                                        + self.brains[w.name].style.aggression * 0.4))
        for rank, w in enumerate(wolves):
            self.brains[w.name].assign_wolf_strategy(rank, len(wolves))

    def _persona(self, name: str) -> dict:
        return load_seat_persona(self.engine.seat_by_name(name), self.engine)

    def _print_seats(self):
        e = self.engine
        self.out(BAR)
        self.out(f"  狼人杀 · {e.board['name']}   种子 #{self.seed}"
                 f"   {'（LLM 在线：每角色独立推理）' if self.llm.online else '（离线推理引擎）'}")
        self.out(BAR)
        self.out("  座位表（上帝视角）：")
        for pos, s in sorted(e.seats.items()):
            mark = "👤你" if s.is_player else "   "
            state = self.brains[s.name].match_state
            self.out(f"   {mark} {pos:2d}号 {s.name:<5s} {s.emoji}{s.role_cn:<6s}"
                     f" [{s.faction}]  状态:{state.condition_label}/{state.mood}")
        wolf_names = "、".join(f"{s.pos}号{s.name}({s.role_cn})"
                               for s in e.seats.values() if s.is_wolf)
        self.out(f"\n  狼阵营：{wolf_names}")
        self.out(BAR)
        self.out()

    # ---------------------------------------------------------- 主流程
    def run(self):
        e = self.engine
        e.setup()
        self._init_brains()
        self._print_seats()

        guard = 0
        while not e.winner and guard < 20:
            guard += 1
            self._night()
            if e.check_win():
                break
            self._day()
            if e.check_win():
                break

        e.check_round_limit()
        self._finish()
        if self.log_path:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._log_lines))
            self.out(f"\n（本局已落盘：{self.log_path}）")

    # ---------------------------------------------------------- 夜晚
    def _night(self):
        e = self.engine
        requests = e.start_night()
        self.out(BAR)
        self.out(f"  🌙 第 {e.night_count} 夜")
        self.out(BAR)
        requests = sorted(requests, key=lambda r: NIGHT_ORDER.get(r[0], 9))
        actions: dict = {}
        knife = None

        for actor, _pos in requests:
            if actor == "seer":
                d = self._act("seer", "🔮 预言家", "验人", actions, knife)
            elif actor == "wolves":
                knife = self._wolves(actions)
            elif actor == "witch":
                d = self._act("witch", "🧪 女巫", "用药", actions, knife)
            elif actor == "guard":
                d = self._act("guard", "🛡️ 守卫", "守护", actions, knife)
            elif actor == "wolf_beauty":
                d = self._act("wolf_beauty", "💋 狼美人", "魅惑", actions, knife)
            elif actor == "stone_ghost":
                d = self._act("stone_ghost", "🗿 石像鬼", "查验", actions, knife)

        self.out(SUB)
        events = e.resolve_night(actions)
        if not events:
            self.out("  🌅 天亮了，昨夜无人死亡——平安夜。")
        for ev in events:
            self._print_event(ev)
        self._broadcast(events)
        # 上帝视角补一句验人结果（玩家自己知道，桌上其他人不知道）
        for r in e.seer_results:
            if r["night"] == e.night_count:
                self.out(f"  🔮 上帝视角：预言家验 {r['target']}号{r['name']} → "
                         f"{'狼人' if r['result'] == 'wolf' else '好人'}")
        for r in e.sg_results:
            if r["night"] == e.night_count:
                self.out(f"  🗿 上帝视角：石像鬼查 {r['target']}号{r['name']} → {r['role_cn']}")
        self._triggers()
        self.out()
        self.pause()

    def _act(self, kind: str, icon: str, verb: str, actions: dict,
             knife) -> brain_mod.Decision:
        e = self.engine
        seat = e._seat_of_role(kind) if kind != "wolves" else None
        b = self.brains[seat.name]
        cands = [s.pos for s in e.alive_seats()]
        if kind == "guard":
            cands = [p for p in cands if p != seat.pos and p != e.guard_last] \
                or [p for p in cands if p != seat.pos]
        elif kind in ("seer", "wolf_beauty", "stone_ghost"):
            cands = [p for p in cands if p != seat.pos]
        elif kind == "witch":
            cands = [p for p in cands if p != seat.pos]

        self.out(f"  {icon} {seat.pos}号{seat.name} · {seat.role_cn}")
        d = b.night(kind, cands, knife=knife,
                    antidote=e.witch_antidote, poison=e.witch_poison)
        self.think(seat.name, d.reason)
        if kind == "witch":
            bits = []
            if d.save is not None:
                bits.append(f"救 {d.save}号{e.seat_at(d.save).name}")
            if d.poison is not None:
                bits.append(f"毒 {d.poison}号{e.seat_at(d.poison).name}")
            self.out(f"     行动：{'；'.join(bits) if bits else '不用药'}")
            actions["witch"] = {"save": d.save, "poison": d.poison}
        else:
            if d.target is not None:
                self.out(f"     行动：{verb} {d.target}号{e.seat_at(d.target).name}")
            actions[kind] = {"target": d.target}
        self.pause()
        return d

    def _wolves(self, actions: dict):
        """每只狼独立提案，再收敛成统一刀口。"""
        e = self.engine
        wolves = e.wolves()
        cands = [s.pos for s in e.alive_seats()]
        self.out(f"  🐺 狼队刀人 —— {len(wolves)} 只狼各自提案")
        proposals = []
        for w in wolves:
            b = self.brains[w.name]
            d = b.night("wolves", cands)
            self.out(f"     {w.pos}号{w.name}（{w.role_cn}·{b.wolf_strategy}）")
            self.think(w.name, d.reason)
            if d.target is not None:
                self.out(f"       → 提议刀 {d.target}号{e.seat_at(d.target).name}")
            proposals.append((w, d.target))

        tally: dict[int, int] = {}
        for _w, t in proposals:
            if t is not None:
                tally[t] = tally.get(t, 0) + 1
        if not tally:
            self.out("     ⚖️ 无人提出有效目标，今晚空刀。")
            actions["wolves"] = {"target": None}
            return None
        ranked = sorted(tally.items(), key=lambda kv: -kv[1])
        top_v = ranked[0][1]
        tied = [p for p, v in ranked if v == top_v]
        # 平票时听最激进的那只狼
        knife = tied[0] if len(tied) == 1 else max(
            tied, key=lambda p: max(self.brains[w.name].style.aggression
                                    for w, t in proposals if t == p))
        if len(ranked) > 1:
            detail = "，".join(f"{p}号×{v}" for p, v in ranked)
            self.out(f"     ⚖️ 收敛：{detail} → 统一刀 {knife}号{e.seat_at(knife).name}")
        else:
            self.out(f"     ⚖️ 一致同意：刀 {knife}号{e.seat_at(knife).name}")
        actions["wolves"] = {"target": knife}
        self.pause()
        return knife

    # ---------------------------------------------------------- 白天
    def _day(self):
        e = self.engine
        e.start_day()
        self.out(BAR)
        self.out(f"  ☀️ 第 {e.day_count} 天 · 天亮了")
        self.out(BAR)
        alive_now = "、".join(f"{s.pos}号{s.name}" for s in e.alive_seats())
        self.out(f"  存活：{alive_now}")
        if e.sheriff:
            self.out(f"  警长：{e.sheriff}号{e.seat_at(e.sheriff).name}（1.5 票权）")
        self.out()

        if e.day_count == 1:
            self._election()

        self.out(SUB)
        self.out("  🗣️ 发言阶段")
        order = e.speech_order()
        today: list[tuple[str, brain_mod.Speech]] = []
        for pos in order:
            seat = e.seat_at(pos)
            if not seat.alive:
                continue
            b = self.brains[seat.name]
            sp = b.speak(e.day_count, today)
            self._speak_line(seat, sp, b)
            e.record_speech(
                seat.pos, sp.text, claim=sp.claim,
                accuse=sp.accuse, defend=sp.defend,
            )
            for other in self.brains.values():
                other.observe_speech(e.day_count, seat.name, sp, sp.text)
            today.append((seat.name, sp))
            self.pause()

        self.out(SUB)
        self._vote()

        self._triggers()
        self.out()
        self.pause()

    def _speak_line(self, seat, sp: brain_mod.Speech, b: brain_mod.Brain):
        self.out(f"  {seat.pos}号 {seat.name}：")
        # 思考：他此刻怎么判断场上形势
        ranked = sorted(((b.suspicion(n), n) for n in b.alive_names()
                         if n != seat.name), reverse=True)
        if ranked:
            top = "、".join(f"{n}({s:.2f})" for s, n in ranked[:3])
            self.think(seat.name, f"我眼中的可疑排序：{top}。"
                                  f"{'我是狼，队友是' + '、'.join(b.mates()) + '，我要保住他们。' if b.is_wolf else ''}")
        for i, line in enumerate(_wrap(sp.text, 56)):
            self.out(f"     {'「' if i == 0 else '  '}{line}{'」' if i == 0 and len(sp.text) < 56 else ''}")
        tags = []
        if sp.claim:
            tags.append(f"跳「{sp.claim}」")
        if sp.accuse:
            tags.append(f"踩 {sp.accuse}")
        if sp.defend:
            tags.append(f"保 {sp.defend}")
        if tags:
            self.out(f"     〔{' / '.join(tags)}〕")

    # ---- 警长竞选
    def _election(self):
        e = self.engine
        self.out("  ⚖️ 警长竞选")
        ups = []
        for s in e.alive_seats():
            b = self.brains[s.name]
            if s.role == "seer" and b.style.aggression > 0.35:
                ups.append(s)
            elif b.is_wolf and b.wolf_strategy == "bluff":
                ups.append(s)
            elif b.style.aggression > 0.80:
                ups.append(s)
        if not ups:
            self.out("     无人上警，本局无警长。")
            self.out()
            return
        for s in sorted(ups, key=lambda x: x.pos):
            b = self.brains[s.name]
            sp = b.speak(e.day_count, [])
            self.out(f"     {s.pos}号{s.name} 上警：")
            self.think(s.name, "我先抢警长，1.5 票权能带节奏，"
                               "而且拿了警徽明天不容易被投出去。")
            for line in _wrap(sp.text, 54):
                self.out(f"       {line}")
            e.record_speech(
                s.pos, sp.text, phase="election", claim=sp.claim,
                accuse=sp.accuse, defend=sp.defend,
            )
            for other in self.brains.values():
                other.observe_speech(0, s.name, sp, sp.text)

        votes: dict[int, int] = {}
        for s in e.alive_seats():
            b = self.brains[s.name]
            tgt, why = b.vote([u.pos for u in ups], sheriff=True)
            votes[s.pos] = tgt
        tally: dict[int, float] = {}
        for v in votes.values():
            if v:
                tally[v] = tally.get(v, 0) + 1
        if tally:
            mx = max(tally.values())
            top = [k for k, v in tally.items() if v == mx]
            if len(top) == 1:
                e.sheriff = top[0]
                self.out(f"     → {top[0]}号{e.seat_at(top[0]).name} "
                         f"以 {int(mx)} 票当选警长。")
            else:
                self.out("     → 平票，本局无警长。")
        else:
            self.out("     → 无人得票，本局无警长。")
        self.out()

    # ---- 投票
    def _vote(self):
        e = self.engine
        self.out("  🗳️ 投票阶段")
        alive = e.alive_seats()
        votes: dict[int, int] = {}
        for s in alive:
            b = self.brains[s.name]
            tgt, why = b.vote([x.pos for x in alive])
            votes[s.pos] = tgt
            if tgt:
                self.out(f"     {s.pos}号{s.name} → 投 {tgt}号{e.seat_at(tgt).name}")
                self.think(s.name, why)
            else:
                self.out(f"     {s.pos}号{s.name} → 弃票")

        tally: dict[int, float] = {}
        for voter, t in votes.items():
            if not t or t == voter:
                continue
            w = 1.5 if (e.sheriff and voter == e.sheriff) else 1.0
            tally[t] = tally.get(t, 0) + w
        self.out(f"     票型：" + "，".join(
            f"{p}号{e.seat_at(p).name} {v:g}票" for p, v in
            sorted(tally.items(), key=lambda kv: -kv[1])))
        exiled = None
        if tally:
            mx = max(tally.values())
            top = [k for k, v in tally.items() if v == mx]
            exiled = top[0] if len(top) == 1 else None
        for s in alive:
            self.brains[s.name].observe_vote(e.day_count, s.name,
                                             e.seat_at(votes[s.pos]).name
                                             if votes.get(s.pos) else None)
        events = e.resolve_vote(votes, exiled)
        if not events:
            self.out("     ⚖️ 平票，无人被放逐，平安日。")
        for ev in events:
            self._print_event(ev)
        if exiled:
            seat = e.seat_at(exiled)
            for b in self.brains.values():
                b.observe_flip(seat.name, seat.role_cn, seat.is_wolf)
                b.observe_exile(e.day_count, seat.name, seat.is_wolf)

    # ---------------------------------------------------------- 死亡触发
    def _triggers(self):
        e = self.engine
        for s in list(e.seats.values()):
            if s.alive or s.pos in self._triggered:
                continue
            if s.role == "hunter" and s.death_cause not in ("poison", "knight_duel"):
                self._gun(s, "🏹 猎人")
            elif s.role == "wolf_king" and s.death_cause in ("exile", "hunter_gun"):
                self._gun(s, "👑 狼王")

    def _gun(self, shooter, icon):
        e = self.engine
        b = self.brains[shooter.name]
        cands = [s.pos for s in e.alive_seats() if s.pos != shooter.pos]
        if not cands:
            self._triggered.add(shooter.pos)
            return
        tgt, why = b.vote(cands)
        self.out(f"  {icon} {shooter.pos}号{shooter.name} 死亡触发，可以开枪")
        self.think(shooter.name, why)
        if tgt:
            fired = e.trigger_hunter(shooter.pos, tgt, []) if shooter.role == "hunter" \
                else e.trigger_wolf_king(shooter.pos, tgt, [])
            if fired is not False:
                self.out(f"     → 带走 {tgt}号{e.seat_at(tgt).name}")
                victim = e.seat_at(tgt)
                self.out(f"     🂠 {tgt}号{victim.name} 翻牌——{victim.role_cn}")
                for other in self.brains.values():
                    other.observe_flip(victim.name, victim.role_cn, victim.is_wolf)
            else:
                self.out("     → 恶灵骑士反制，猎人无法开枪。")
        self._triggered.add(shooter.pos)

    # ---------------------------------------------------------- 事件播报
    def _print_event(self, ev):
        if ev.type == "death":
            self.out(f"  💀 {ev.text}")
        elif ev.type == "flip":
            self.out(f"  🂠 {ev.text}")
        elif ev.type == "exile":
            self.out(f"  ⚖️ {ev.text}")
        elif ev.type == "system":
            self.out(f"  📣 {ev.text}")

    def _broadcast(self, events):
        for ev in events:
            if ev.type == "flip":
                nm = ev.data.get("name")
                role = ev.data.get("role")
                is_wolf = role in WOLF_ROLES
                for b in self.brains.values():
                    b.observe_flip(nm, ev.data.get("role_cn", ""), is_wolf)

    # ---------------------------------------------------------- 收尾
    def _finish(self):
        e = self.engine
        for brain in self.brains.values():
            brain._state_event("match_complete")
        self.out(BAR)
        self.out(f"  🏆 {'平局' if e.winner == 'draw' else '好人阵营胜利' if e.winner == 'god' else '狼人阵营胜利' if e.winner == 'wolf' else '未完成'}"
                 f" —— {e.end_reason}")
        self.out(BAR)
        self.out("  全场身份：")
        for pos, s in sorted(e.seats.items()):
            state = "存活" if s.alive else "出局"
            self.out(f"   {pos:2d}号 {s.name:<5s} {s.role_cn:<6s} {state}")
        self.out()

        perf = "\n".join(
            f"- {name}（{b.me.role_cn}）：发言{sum(1 for d, w, _ in b.speeches if w == name)}次，"
            f"踩过{sum(1 for _, w, _ in b.accuse_log if w == name)}人，"
            f"状态 {b.starting_state['condition_label']}/{b.starting_state['mood']}→"
            f"{b.match_state.condition_label}/{b.match_state.mood}"
            for name, b in self.brains.items())
        self.out("  NPC状态复盘：")
        for line in perf.splitlines():
            self.out(f"     {line}")
        review = self.host.review(e, perf)
        self.host.evolve(e, review)
        self.out("  📋 主持人复盘：")
        for line in review.split("\n"):
            self.out(f"     {line}")
        self.out(BAR)


# ---------------------------------------------------------------- 工具
def _wrap(text: str, width: int) -> list[str]:
    """按显示宽度折行（中文按 2 列算）。"""
    lines, cur, w = [], "", 0
    for ch in text:
        cw = 2 if ord(ch) > 0x2E80 else 1
        if w + cw > width:
            lines.append(cur)
            cur, w = ch, cw
        else:
            cur += ch
            w += cw
    if cur:
        lines.append(cur)
    return lines or [""]


def main():
    ap = argparse.ArgumentParser(description="狼人杀 · 无 UI 命令行对局")
    ap.add_argument("--board", default="classic", help="板子 id，见 data/boards.json")
    ap.add_argument("--seed", type=int, default=None, help="随机种子，填了可复现")
    ap.add_argument("--delay", type=float, default=0.0, help="每条之间的秒数，默认 0")
    ap.add_argument("--no-think", action="store_true", help="不打印角色的内心推理")
    ap.add_argument("--log", default=None, help="把整局写入指定文件")
    args = ap.parse_args()

    if args.board not in eng_mod.BOARD_MAP:
        print(f"未知板子 {args.board}。可选：{', '.join(eng_mod.BOARD_MAP)}")
        sys.exit(1)

    CLIGame(board_id=args.board, seed=args.seed, delay=args.delay,
            show_think=not args.no_think, log_path=args.log).run()


if __name__ == "__main__":
    main()
