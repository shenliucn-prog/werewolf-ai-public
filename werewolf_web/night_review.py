"""Private resolved-night audit; release only after a normal game over."""
from copy import deepcopy


def validate(rows):
    if not isinstance(rows, list):
        raise ValueError("Invalid night audit")
    previous = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"night", "actions", "deaths"}:
            raise ValueError("Invalid night audit row")
        night = row["night"]
        if type(night) is not int or night <= previous:
            raise ValueError("Invalid night audit order")
        previous = night
        if not isinstance(row["actions"], dict) or not isinstance(row["deaths"], list):
            raise ValueError("Invalid night audit data")
        for action in row["actions"].values():
            if not isinstance(action, dict):
                raise ValueError("Invalid night action")
            for key, target in action.items():
                if key not in ("target", "save", "poison") or (target is not None and
                        (type(target) is not int or not 1 <= target <= 12)):
                    raise ValueError("Invalid night target")
        for death in row["deaths"]:
            if (not isinstance(death, dict) or set(death) != {"seat", "cause"}
                    or type(death["seat"]) is not int or not 1 <= death["seat"] <= 12
                    or not isinstance(death["cause"], str)):
                raise ValueError("Invalid night death")
    return deepcopy(rows)


def capture(night, actions, events):
    # Never persist model rationale, credentials or arbitrary action metadata.
    row = {"night": night,
           "actions": {kind: {k: v for k, v in action.items()
                              if k in ("target", "save", "poison")}
                       for kind, action in actions.items() if isinstance(action, dict)},
           "deaths": [{"seat": ev.seat, "cause": ev.data["cause"]}
                      for ev in events if ev.type == "death"]}
    return validate([row])[0]


def render(session):
    if not session.finished or not session.engine.winner:
        return ""
    en = session.engine.locale == "en"
    rows = session.night_audit
    lines = ["Night actions · post-game only" if en else "夜间行动与死因 · 仅赛后公开"]
    if not rows:
        lines.append("This older save has no night-action audit; missing actions are unknown."
                     if en else "此旧存档没有夜间行动记录；缺失行动无法还原，不作推测。")
    labels = {"wolves": "狼刀", "guard": "守卫", "seer": "预言家查验",
              "witch": "女巫", "stone_ghost": "石像鬼查验",
              "stone_ghost_kill": "石像鬼刀", "wolf_beauty": "狼美人魅惑"}
    causes = {"knife": "刀杀", "poison": "女巫毒杀", "reflect": "技能反弹",
              "charm": "魅惑殉情", "hunter_gun": "猎人开枪"}
    for row in rows:
        lines.append(f"Night {row['night']}" if en else f"第{row['night']}夜")
        for kind, action in row["actions"].items():
            for key, target in action.items():
                label = kind if en else labels.get(kind, kind)
                verb = key if en else {"target": "目标", "save": "解药", "poison": "毒药"}[key]
                value = f"#{target}" if target is not None else ("not used" if en else "未使用")
                lines.append(f"  {label} · {verb}: {value}")
        for death in row["deaths"]:
            cause = death["cause"] if en else causes.get(death["cause"], death["cause"])
            lines.append(f"  #{death['seat']} — {cause}")
        if not row["deaths"]:
            lines.append("  No deaths" if en else "  结算：平安夜，无人死亡")
    return "\n".join(lines)
