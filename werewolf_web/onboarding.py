"""Public, deterministic introductions for human-played games."""
from collections import Counter
import unicodedata

from .game.engine import ROLE_META
from .i18n import board_display, board_role_name, role_desc, witch_rule_text


def introduction(engine, conjecture=False, *, offline_choices=False):
    en = engine.locale == "en"
    board = board_display(engine.locale, engine.board)
    roles = Counter(engine.board["roles"])
    roster = ", ".join(f"{board_role_name(engine.locale, engine.board, key, ROLE_META[key]['cn'])} × {count}"
                       for key, count in roles.items())
    lines = ([f"Host Raven: Welcome to the Night Teahouse. Tonight: {board['name']}.", roster,
              "One human and eleven NPCs play locally. Voices and visual gameplay are not implemented.",
              "Good wins by eliminating every wolf. Wolves win by eliminating all special good roles OR all villagers.",
              "Night actions are private. Dawn announces deaths and reveals roles. Daytime has ordered statements, short host-moderated interruptions, then exile voting.",
              "On day one, declare sheriff candidacy once before speeches. A withdrawal window follows speeches. All living players, including candidates, vote. A tied election elects nobody.",
              "The sheriff has 1.5 exile votes. Speaking order is automatic, starting at the living sheriff; the sheriff cannot choose direction. Vote for a player or Peaceful Day: a Peaceful Day lead or any tie for highest votes eliminates nobody. This is an experimental rule."] if en else
             [f"主持人夜鸦：欢迎来到暗夜茶馆。今晚的板子是：{board['name']}。", roster,
              "你和十一名 NPC 在本机游玩。目前仅文字驱动，语音与视觉玩法尚未实现。",
              "全部狼人出局，好人获胜；全部神职或全部平民出局，狼人获胜。",
              "夜间按私密提示行动；天亮公布死亡并翻牌。白天顺序发言，主持人允许短暂公开插话，最后投票放逐。",
              "首日发言前统一报名上警，之后不能加入；警上发言结束后可退警。所有存活玩家（含候选人）参与警长投票，平票则无警长。",
              "警长放逐票重 1.5 票；发言顺序自动从存活警长开始，不能选择方向。可以投玩家或平安日；平安日最高票或最高票并列时无人出局。这是实验性规则。"])
    lines.append("Clarifications: each addressed player receives one combined reply per election/day window. The host closes follow-ups before the final statement and ballot. Guns resolve first, then a dead sheriff transfers/destroys the badge. First-night victims and daytime exiles have last words; other deaths do not." if en else
                 "澄清：警上与白天分开，每位被问者合并回答一次；主持人收口后进行最后陈述及投票。死亡先结算开枪，再交接或撕毁警徽；首夜死者与白天被放逐者有遗言，其他死亡无遗言。")
    for key in roles:
        label = board_role_name(engine.locale, engine.board, key, ROLE_META[key]["cn"])
        desc = witch_rule_text(engine.locale, engine.board) if key == "witch" else role_desc(engine.locale, key, ROLE_META[key])
        lines.append(f"{label}: {desc}")
    if offline_choices:
        lines.append("Offline discussion: choose a contextual response, listen, or open other responses. Free text is not interpreted; personalities are fixed." if en else
                     "离线讨论：可接话、先听听，或展开其他说法。不解析任意自由文本；本模式目前使用固定人格。")
    else:
        lines.append(("Conjecture ON: private beliefs and a separate public debate table; public table history is retained." if conjecture else
                  "Conjecture OFF: debate in natural language.") if en else
                 ("猜想模式已开：私有判断与公开辩论两张表分开，保留公开表历史。" if conjecture else "猜想模式已关：使用自然语言辩论。"))
    lines.append("Any rules questions? Ask the Host; the first night waits for your Ready confirmation." if en else
                 "大家有没有不懂的规则？可以先问主持人，只有你确认准备好后才进入第一夜。")
    return "\n".join(lines)


def seating_text(state):
    """Clockwise seat order, without private identities."""
    seats = sorted(state["seats"], key=lambda s: s["pos"])
    en = state.get("locale") == "en"
    labels = [f"#{s['pos']} {s['name']}" + ((" (you)" if en else "（你）") if s.get("is_player") else "") +
              ((" [out]" if en else "[出局]") if not s.get("alive", True) else "") for s in seats]
    heading = "Clockwise seats (last connects to first):\n" if en else "顺时针座次（末位与首位相邻）：\n"
    if len(labels) != 12:
        return heading + " → ".join(labels)
    width = max(sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in label) for label in labels) + 4
    def pad(label):
        size = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in label)
        return label + " " * (width - size)
    rows = [" " * width + labels[11]]
    for left, right in ((10, 0), (9, 1), (8, 2), (7, 3), (6, 4)):
        rows.append(pad(labels[left]) + " " * width + labels[right])
    rows.append(" " * width + labels[5])
    return heading + "\n".join(rows)
