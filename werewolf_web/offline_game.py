"""Explicit choice-driven offline games on the shared GameSession engine."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import random
import secrets

from .session import GameSession
from .ai.brain import Speech
from .ai.strategic_agent import StrategicNPCAgent
from .offline_cast import BY_ID, CHARACTERS, cast_settings
from .i18n import cast, role_name
from .game.engine import BOARD_MAP, ROLE_META
from . import checkpoint


def words(locale, zh, en):
    return en if locale == "en" else zh


def speech_choices(session, actor, reply=False):
    """Menus depend only on public state. A bluffing player has the same menu.

    Source-linked options quote actual public speech; no option labels certify
    someone's role or compute the correct answer for the player.
    """
    e = session.engine
    lang = e.locale
    choices = []

    def add(key, group, text, **fields):
        choices.append({"id": key, "group": group.split(" / ")[lang == "en"], "label": text,
                        "speech": asdict(Speech(text=text, **fields))})

    add("wait", "回应 / Respond", words(lang, "目前没有足够的新证据，我先保留判断。", "I have no sufficient new evidence; I reserve judgment."))
    add("admit", "回应 / Respond", words(lang, "我承认之前判断不够扎实，现在保留意见。", "I admit my earlier judgment was not well supported; I am reserving judgment."))
    add("refuse", "回应 / Respond", words(lang, "这次我选择不解释，但这本身不能证明身份。", "I decline to explain this time; that alone does not establish my role."))
    if not reply:
        for role in dict.fromkeys(e.board["roles"]):
            label = role_name(lang, role, ROLE_META[role]["cn"])
            add(f"claim:{role}", "声明 / Claim", words(lang, f"我声明自己是{label}。这是我的身份声明。", f"I claim to be {label}. This is my claim."), claim=role)
    for seat in e.alive_seats():
        if seat.pos == actor.pos:
            continue
        target = f"#{seat.pos} {seat.name}"
        add(f"suspect:{seat.pos}", "怀疑 / Suspect", words(lang, f"我暂时怀疑{target}，这是判断，不是查验。", f"I provisionally suspect {target}; this is a judgment, not a check."), accuse=seat.name)
        add(f"support:{seat.pos}", "支持 / Support", words(lang, f"我暂时支持{target}，但不把这个判断当作事实。", f"I provisionally support {target}, without treating that judgment as fact."), defend=seat.name)
        if not reply:
            add(f"ask:{seat.pos}", "追问 / Ask", words(lang, f"请{target}说明目前的判断依据。", f"Please, {target}, explain the basis of your current judgment."), question_to=seat.name)
            if e.night_count:
                for result in ("good", "wolf"):
                    label = words(lang, "好人" if result == "good" else "狼人", result)
                    add(f"report:{seat.pos}:{result}", "报告 / Report", words(lang,
                        f"我声明自己是预言家；第{e.night_count}夜查验{target}为{label}。这是我的报告，尚未公开验证。",
                        f"I claim seer; my night {e.night_count} report on {target} is {label}. This report is not publicly verified."),
                        claim="seer", **({"defend": seat.name} if result == "good" else {"accuse": seat.name}))
    # A bounded menu of exact recent public sources; any actor can cite one.
    sources = [event for event in session._events if event.get("type") in ("speech", "ballots", "flip", "exile")][-8:]
    for event in sources:
        quote = event["text"]
        # Do not quote truncated text as though it were the complete original.
        if len(quote) > 500:
            continue
        number = event["event_no"]
        for stance in ("agree", "challenge"):
            boundary = words(lang, "这是玩家声明，不代表已证实。", "This is a player statement, not proven truth.") if event["type"] == "speech" else words(lang, "这是公开事件；它不直接证明其他人的身份。", "This is a public event; it does not directly establish anyone else's role.")
            text = words(lang,
                f"我{'引用' if stance == 'agree' else '质疑对这条记录的推论'}记录{number}「{quote}」。{boundary}",
                f"I {'cite' if stance == 'agree' else 'question conclusions drawn from'} record {number}: “{quote}”. {boundary}")
            # Agreeing adopts the stated position; challenging a statement does
            # not automatically accuse its author of being a wolf.
            fields = {k: event.get(k) for k in ("accuse", "defend")} if stance == "agree" else {}
            add(f"cite:{number}:{stance}", "引用 / Cite", text, protected_facts=(quote,), **fields)
    return choices


def action_choices(session, kind, data):
    lang = session.engine.locale
    if kind in ("speech", "table_reply", "table_answer"):
        key = "answer" if kind == "table_answer" else "text"
        return [{**c, "payload": {key: c["label"], "offline_speech": c["speech"]}}
                for c in speech_choices(session, session.engine.player_seat(), kind != "speech")]
    def option(key, label, payload):
        return {"id": key, "group": words(lang, "行动", "Action"), "label": label, "payload": payload}
    if kind == "ready":
        return [option("ready", words(lang, "准备好了，开始第一夜", "Ready: start night one"), {"ready": True})]
    if kind in ("election_up", "election_withdraw"):
        field = "up" if kind == "election_up" else "withdraw"
        labels = (("上警", "Run for sheriff"), ("不上警", "Do not run")) if field == "up" else (("退警", "Withdraw"), ("继续竞选", "Stay in the election"))
        return [option(str(value), words(lang, *label), {field: value}) for value, label in zip((True, False), labels)]
    if kind not in ("night", "day_skill", "vote"):
        raise ValueError(f"Unsupported offline action: {kind}")
    if kind == "night" and data.get("role_key") == "witch":
        saves = [None] + ([c["pos"] for c in data.get("save_candidates", [])] if data.get("antidote") else [])
        poisons = [None] + ([c["pos"] for c in data.get("candidates", [])] if data.get("poison") else [])
        return [option(f"potion:{save}:{poison}", words(lang, f"救：{save or '不用'}；毒：{poison or '不用'}", f"Save: {save or 'none'}; poison: {poison or 'none'}"), {"save": save, "poison": poison})
                for save in saves for poison in poisons if not (save and poison) or data.get("dual_potions")]
    options = [option(str(c["pos"]), f"#{c['pos']} {c['name']}", {"target": c["pos"]}) for c in data.get("candidates", [])]
    if kind != "vote":
        options.append(option("pass", words(lang, "不发动技能", "Do not use the ability"), {"target": None}))
    return options


class ChoiceAgent(StrategicNPCAgent):
    """Same legal skill/ballot policy, with structured public dialogue choices."""
    def bind(self, session):
        self.session = session
        character = BY_ID[session.character_map[self.seat.player_id]]
        self.character = character
        self.brain.style = character.style()
        return self

    def observe_speech(self, day, who, speech, event_no=None):
        repeated = any(d == day and w == who and text == speech.text for d, w, text in self.brain.speeches)
        super().observe_speech(day, who, speech, event_no)
        if who == self.name or repeated:
            return
        # Exact authored actions only, not heuristic natural-language parsing.
        responses = {c["id"]: c["label"] for c in speech_choices(self.session, self.seat, True) if c["id"] in ("admit", "refuse")}
        self.brain.ensured(who)
        if speech.text == responses["admit"]:
            self.brain.sus[who] -= .06 * self.style.loyalty
        elif speech.text == responses["refuse"]:
            self.brain.sus[who] += .06 * self.style.aggression

    def speak(self, today=(), player_last_speech=""):
        options = speech_choices(self.session, self.seat)
        by_id = {c["id"]: c for c in options}
        own = [ev for ev in self.session._events if ev.get("type") == "speech" and ev.get("name") == self.name]
        chosen = None
        # Lawful private check results only for the actual seer; other roles
        # never read this list. Reports remain publicly attributed claims.
        if self.brain.role == "seer":
            records = [r for r in self.engine.seer_results if r["night"] == self.engine.night_count]
            if records:
                r = records[-1]
                chosen = by_id.get(f"report:{r['target']}:{r['result']}")
        elif self.brain.is_wolf and self.brain.wolf_strategy == "bluff":
            checks = getattr(self.brain, "_bluff_checks", {})
            n = self.engine.night_count
            if n not in checks:
                pool = [s for s in self.engine.alive_seats() if s.name != self.name and s.name not in self.brain.mates()]
                if pool:
                    target = self.brain.rng.choice(pool)
                    checks[n] = {"night": n, "target": target.pos, "name": target.name, "result": "wolf"}
                    self.brain._bluff_checks = checks
            if n in checks:
                r = checks[n]
                chosen = by_id.get(f"report:{r['target']}:{r['result']}")
        # Avoid repeating the same report in the same day/election sequence.
        if chosen and any(ev["text"].endswith(chosen["label"]) for ev in own[-2:]):
            chosen = None
        if chosen is None:
            candidates = [s for s in self.engine.alive_seats() if s.name != self.name
                          and (not self.is_wolf or s.name not in self.brain.mates())]
            if candidates:
                target = max(candidates, key=lambda s: (self.brain.suspicion(s.name), -s.pos))
                key = f"suspect:{target.pos}"
                # Cautious personalities prefer a question before a weak accusation.
                if self.brain.suspicion(target.name) < .55 and self.style.caution > .6:
                    key = f"ask:{target.pos}"
                chosen = by_id[key]
                if own and own[-1]["text"].endswith(chosen["label"]):
                    chosen = by_id["wait"]
            else:
                chosen = by_id["wait"]
        speech = Speech(**deepcopy(chosen["speech"]))
        # Occasional, stable phrasing; no catchphrase on every line.
        if not own:
            speech.text = self.character.phrase[self.engine.locale == "en"] + " " + speech.text
        return speech

    def table_reply(self, interrupter):
        own = [ev for ev in self.session._events if ev.get("type") == "speech" and ev.get("name") == self.name]
        if own:
            ev = own[-1]
            return Speech(text=words(self.engine.locale, f"回应{interrupter}：我的立场见记录{ev['event_no']}。这仍是判断或声明，不是新增查验；我没有更多公开证据。",
                f"To {interrupter}: my position is in record {ev['event_no']}. It remains a judgment or claim, not a new check; I have no further public evidence."))
        return Speech(text=words(self.engine.locale, "我暂时没有公开证据，不把猜测说成事实。", "I have no public evidence yet; my suspicion is not fact."))

    def table_interject(self, speaker, speech):
        return Speech(text=words(self.engine.locale, f"我想提醒{speaker}：身份声明和已经证实的事实要分开。", f"A reminder to {speaker}: distinguish role claims from established facts."))


class OfflineSession(GameSession):
    offline_choice_mode = True

    async def _pace(self, seconds):
        await asyncio.sleep(0)

    async def _question_reply(self, agent, asker):
        return await self._npc_call(agent.table_reply, asker)

    def __init__(self, board_id="classic", *, character="acheng", spectator=False,
                 player_name=None, **kwargs):
        if type(spectator) is not bool:
            raise ValueError("spectator must be boolean")
        locale = kwargs.get("locale", "zh-CN")
        self.character_map, names = cast_settings(character, locale, player_name)
        self.character = character
        self.spectator = spectator
        self.proxy = None
        super().__init__(board_id, {"enabled": False}, names=names, onboarding=True, **kwargs)
        self.campaign_counted = False

    def _install_agents(self):
        for name, old in list(self.agents.items()):
            new = ChoiceAgent.restore_agent(old.snapshot(), self.engine, self.llm, self.memory_dir)
            new.participant = old.participant
            self.agents[name] = new.bind(self)

    async def _step_setup(self):
        await super()._step_setup()
        self._install_agents()
        player = self.engine.player_seat()
        self.proxy = ChoiceAgent(player.name, self.engine, self.llm, self.memory_dir,
                                 private_rng=random.Random(self.engine.rng.randrange(1, 2**31))).bind(self)
        # The proxy is an observer for legal autonomous spectator choices, never
        # an extra seat or an extra participant in NPC floor selection.
        if player.is_wolf:
            self.proxy.assign_wolf_strategy(0, 1)

    def _delivery_event(self, event):
        event = super()._delivery_event(event)
        if event.get("type") == "request" and self.pending and event["request_id"] == self._human_request().request_id:
            # Derived menus are transport data, not duplicated into every save.
            event = {**event, "choices": action_choices(self, event["kind"], event["data"])}
        return event

    def submit(self, response, **kwargs):
        if not self.pending:
            return False
        valid = action_choices(self, self.pending["kind"], self.pending["data"])
        if not any(response == c["payload"] for c in valid):
            return False
        return super().submit(response, **kwargs)

    def _player_speech(self, text):
        for item in reversed(self.decision_log):
            result = item.get("result")
            if isinstance(result, dict) and result.get("text", result.get("answer")) == text and "offline_speech" in result:
                return Speech(**deepcopy(result["offline_speech"]))
        raise ValueError("Offline speech must come from an accepted structured option")

    def _broadcast_speech(self, seat, speech):
        super()._broadcast_speech(seat, speech)
        if self.proxy:
            self.proxy.observe_speech(self.engine.day_count, seat.name, speech, self._event_no + 1)

    def _broadcast_votes(self, votes, sheriff=False):
        super()._broadcast_votes(votes, sheriff)
        if self.proxy:
            for pos, target in votes.items():
                self.proxy.observe_vote(self.engine.day_count, self.engine.seat_at(pos).name,
                                        self.engine.seat_at(target).name if target else None, sheriff)

    async def _emit_event(self, event):
        await super()._emit_event(event)
        if self.proxy and event.type in ("flip", "exile"):
            seat = self.engine.seat_at(event.seat)
            if event.type == "flip":
                self.proxy.observe_flip(seat.name, seat.role_cn, seat.is_wolf)
            else:
                self.proxy.observe_exile(self.engine.day_count, seat.name, seat.is_wolf)

    def auto_choice(self, kind, data, options):
        """Autonomous replacement uses only its own Brain/allowed private data."""
        agent = self.proxy
        if kind == "ready":
            return options[0]
        if kind in ("speech", "table_reply", "table_answer"):
            speech = agent.speak() if kind == "speech" else None
            if speech:
                found = next((o for o in options if speech.text.endswith(o["label"])), None)
                if found:
                    return found
            return options[0]
        if kind in ("election_up", "election_withdraw"):
            yes = agent.brain.role == "seer" or agent.style.aggression > .65
            return options[0 if (yes if kind == "election_up" else not yes) else 1]
        if kind == "vote":
            result = {"target": agent.vote(data["candidates"], data.get("sheriff", False))}
        elif kind == "day_skill":
            result = {"target": agent.brain.day_skill([c["pos"] for c in data["candidates"]]).target}
        elif kind == "night" and data.get("role_key") == "witch":
            saves = data.get("save_candidates", [])
            result = agent.night_action("witch", data["candidates"], knife=saves[0]["pos"] if saves else None,
                                        antidote=data.get("antidote"), poison=data.get("poison"))
        elif kind == "night":
            role = data.get("role_key")
            if role in ("hunter", "wolf_king"):
                result = {"target": agent.vote(data["candidates"])} if data["candidates"] else {"target": None}
            else:
                result = agent.night_action(role, data.get("candidates", []))
        else:
            raise ValueError("Unknown auto action")
        return next((o for o in options if o["payload"] == result), options[-1])

    async def _write_review(self, reveal):
        # No account calls, cross-game growth or verbose full-history dump.
        self.emit({"type": "review", "text": words(self.engine.locale,
            f"离线局结束，共{self.engine.day_count}天。票型和公开发言保留在本局记录；人格不是阵营，声明不是事实。本局不计闯关成绩。",
            f"Offline game ended after {self.engine.day_count} days. Ballots and speeches remain in the record. Personality is not alignment; claims are not facts. No campaign score."), "winner": self.engine.winner})
        self._checkpoint()

    def snapshot(self):
        result = super().snapshot()
        result["offline_choices"] = {"version": 1, "character": self.character,
            "spectator": self.spectator, "proxy": self.proxy.snapshot() if self.proxy else None}
        return result

    def restore(self, data):
        extra = data.get("offline_choices")
        if (not isinstance(extra, dict) or type(extra.get("version")) is not int or extra["version"] != 1
                or extra.get("character") != self.character or extra.get("spectator") is not self.spectator
                or data.get("driver") != "offline" or data.get("campaign_counted") is not False
                or data.get("campaign_profile") is not None or data.get("planner") is not None
                or data.get("llm", {}).get("config", {}).get("enabled") is not False):
            raise ValueError("Wrong offline mode, character, view or version")
        # Validate the proxy on a throwaway engine before applying base state.
        probe = deepcopy(self.engine)
        probe.restore(data["engine"])
        if probe.seats:
            if not isinstance(extra.get("proxy"), dict) or extra["proxy"].get("name") != probe.player_seat().name:
                raise ValueError("Missing or mismatched offline proxy")
            ChoiceAgent.restore_agent(extra["proxy"], probe, self.llm, self.memory_dir)
        super().restore(data)
        self._install_agents()
        self.proxy = (ChoiceAgent.restore_agent(extra["proxy"], self.engine, self.llm, self.memory_dir).bind(self)
                      if extra.get("proxy") else None)


def public_event(event, spectator):
    """Public spectators never receive a player role, private result or menu."""
    if spectator and event["type"] in ("private", "request"):
        return None
    if spectator and event["type"] == "init":
        return {"type": "narration", "text": event["host_intro"] + "\n" +
                "\n".join(f"#{s['pos']} {s['name']}" for s in event["state"]["seats"])}
    return event


async def play(session, *, read=input, write=print, automatic=False):
    from .chat_game import _render
    async def answer():
        value = (await asyncio.to_thread(read, "> ")).strip()
        if value.startswith("?") or value in ("/history", "/seats", "座次", "公开记录"):
            write(session.answer_question(value[1:] if value.startswith("?") else value))
            return ""
        return value if len(value) <= 16 else ""
    try:
        # Re-arm a restored pending request before consuming its historic
        # event. Otherwise a reply can reach the queue before ask_player has
        # resumed, creating a second prompt and shifting every later answer.
        session.ensure_game_task()
        await asyncio.sleep(0)
        async for event in session.events():
            if event["type"] != "request":
                visible = public_event(event, session.spectator)
                if visible:
                    # Keep the standard renderer; tests can capture stdout.
                    _render(visible, session.engine.locale)
                continue
            if not session.pending or event["request_id"] != session._human_request().request_id:
                continue  # historical/replayed prompts are not new decisions
            options = action_choices(session, event["kind"], event["data"])
            if automatic or (session.spectator and event["kind"] != "ready"):
                selected = session.auto_choice(event["kind"], event["data"], options)
            else:
                write(event["data"].get("desc", ""))
                groups = list(dict.fromkeys(c["group"] for c in options))
                while True:
                    current = options
                    if len(groups) > 1:
                        write("\n".join(f"{i+1}. {g}" for i, g in enumerate(groups)))
                        value = await answer()
                        if value == "q":
                            return 0
                        if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= len(groups):
                            continue
                        current = [o for o in options if o["group"] == groups[int(value)-1]]
                    write("\n".join(f"{i+1}. {c['label']}" for i, c in enumerate(current)))
                    value = await answer()
                    if value == "q":
                        return 0
                    if value.isascii() and value.isdigit() and 1 <= int(value) <= len(current):
                        selected = current[int(value)-1]
                        break
            if not session.submit(selected["payload"], request_id=event["request_id"], require_request_id=True):
                raise ValueError("Stale or invalid offline choice")
        return 1 if session.faulted else 0
    except (EOFError, KeyboardInterrupt):
        return 0
    finally:
        task = session._game_task_ref
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", choices=tuple(BOARD_MAP), default="classic")
    parser.add_argument("--character", choices=tuple(BY_ID), default="acheng")
    parser.add_argument("--role", default="random")
    parser.add_argument("--name")
    parser.add_argument("--spectate", action="store_true")
    parser.add_argument("--lang", choices=("zh-CN", "en"), default="zh-CN")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--resume")
    parser.add_argument("--cast", action="store_true", help="List the twelve fixed characters")
    args = parser.parse_args(argv)
    if args.cast:
        names = {p["id"]: p["name"] for p in cast(args.lang)}
        for c in CHARACTERS:
            print(f"{c.id}: {names[c.id]} — {c.description[args.lang == 'en']}")
        return 0
    try:
        if args.resume:
            path = checkpoint.checkpoint_path(args.resume)
            data = checkpoint.load_checkpoint(path)
            extra = data["offline_choices"]
            session = OfflineSession(data["board_id"], character=extra["character"], spectator=extra["spectator"], locale=data["locale"], session_id=args.resume, checkpoint_path=path)
            session.restore(data)
        else:
            game_id = "offline-" + secrets.token_urlsafe(10)
            session = OfflineSession(args.board, character=args.character, spectator=args.spectate,
                player_name=args.name, player_role=args.role, seed=args.seed, locale=args.lang,
                session_id=game_id, checkpoint_path=checkpoint.checkpoint_path(game_id))
        print(words(session.engine.locale, "离线选项局 · 程序策略 · 不计闯关成绩 · q保存退出\n等待选项时：?规则问题、/seats 座次、/history 公开记录，不消耗行动。", "Offline choice game · rule-based NPCs · no campaign score · q saves and exits\nAt a menu: ?rules question, /seats, /history do not spend your action."))
        print(f"Resume: python -m werewolf_web.offline_game --resume {session.session_id}")
        return asyncio.run(play(session))
    except (ValueError, KeyError) as error:
        print(f"Offline game: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
