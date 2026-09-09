"""Only emitted public information is eligible for player history queries."""
import copy
import re


def target_label(target, locale):
    if target == 0:
        return "Peaceful Day" if locale == "en" else "平安日"
    if target is None:
        return "No ballot" if locale == "en" else "未投票"
    return f"#{target}"


class PublicRecord:
    def __init__(self, locale):
        self.locale = locale
        self.entries = []

    def observe(self, event, day, night=None, phase=None):
        # An explicit allowlist excludes role prompts, private results, init
        # payloads, research tables and internal NPC state.
        if event.get("type") not in {"speech", "narration", "ballots", "death", "flip", "exile"}:
            return
        self.entries.append({"day": day, "night": night, "phase": phase,
                             "event": copy.deepcopy(event)})

    def query(self, question):
        q = question.strip().casefold()
        votes = bool(re.search(r"票型|唱票|投票记录|votes|ballots", q))
        speeches = bool(re.search(r"发言记录|完整发言|speeches", q))
        history = q in ("/history", "history", "历史", "公开记录")
        if not (votes or speeches or history):
            return None
        rows = self.entries
        if votes:
            rows = [r for r in rows if r["event"]["type"] == "ballots"]
        elif speeches:
            rows = [r for r in rows if r["event"]["type"] == "speech"]
        day = re.search(r"(?:第\s*|day\s*)(\d+)", q)
        if day:
            rows = [r for r in rows if r["day"] == int(day.group(1))]
        elif votes and re.search(r"上一|最近|last|latest", q):
            rows = rows[-1:]
        en = self.locale == "en"
        lines = []
        for row in rows:
            ev = row["event"]
            phase = row.get("phase")
            night = row.get("night")
            # A night/dawn death or flip is labeled by the *night* it resolved in,
            # never the previous day's counter — the player-facing history must
            # not mislabel "night 3" as "day 2".
            if ev["type"] in ("death", "flip", "exile") and phase in ("night", "dawn") and night is not None:
                prefix = f"[Night {night}] " if en else f"[第{night}夜] "
            else:
                prefix = f"[Day {row['day']}] " if en else f"[第{row['day']}天] "
            text = (f"#{ev['seat']} {ev['name']}: {ev['text']}" if ev["type"] == "speech" else ev.get("text", ""))
            lines.append(prefix + text)
        return "\n".join(lines) or ("No matching public records yet." if en else "尚无对应公开记录。")


def ballot_event(engine, votes, tally, sheriff=False):
    en = engine.locale == "en"
    lines = ["Sheriff ballots" if sheriff and en else "警长票型" if sheriff else "Exile ballots" if en else "放逐票型"]
    ballots = []
    for voter, target in sorted(votes.items()):
        weight = 1 if sheriff else (1.5 if voter == engine.sheriff else 1)
        ballots.append({"voter": voter, "target": target, "weight": weight})
        lines.append(f"#{voter} {engine.seat_at(voter).name} → {target_label(target, engine.locale)} ({weight})")
    if not sheriff and engine.crow_target in {s.pos for s in engine.alive_seats()}:
        lines.append(f"{'Crow extra vote' if en else '乌鸦额外票'} → #{engine.crow_target} (+1)")
    lines.append(("Totals: " if en else "合计：") + ", ".join(
        f"{target_label(target, engine.locale)}: {count}" for target, count in tally.items()))
    return {"type": "ballots", "sheriff": sheriff, "day": engine.day_count,
            "ballots": ballots, "tally": dict(tally), "text": "\n".join(lines)}
