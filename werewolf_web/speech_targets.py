"""Conservative Chinese current-stance extraction, not general text understanding."""
import re


def chinese_targets(text, seats):
    names = {seat.pos: seat.name for seat in seats if not seat.is_player}
    # Quoted/reported/historical statements are not the speaker's current stance.
    clean = re.sub(r'“[^”]*”|‘[^’]*’|"[^"]*"|「[^」]*」', '', text)
    attack = support = None
    prefix = r"(?:我)?(?:今天|现在|目前)?(?:仍然|仍|暂时|暂|会|先|更|也|决定|选择)*"
    target = r"(?P<seat>\d{1,2})号"
    for raw in re.split(r"[，,。；;！？!?\n]", clean):
        clause = re.sub(r"\s+", "", raw)
        if re.search(r"昨天|前天|昨晚|曾经|之前|说过|如果|假如|是否|吗|呢", clause):
            continue
        a = re.match(rf"^{prefix}(?:票投|投给|投|出|怀疑|踩|查杀|优先看|重点看){target}(?!\d)", clause)
        d = re.match(rf"^{prefix}(?:保|信任|相信|站|支持){target}(?!\d)", clause)
        d = d or re.match(rf"^{target}(?:先放|暂放|是好人|是金水)(?:$|[^不])", clause)
        a = a or re.match(rf"^{target}(?:是狼|有问题)(?:$|[^吗呢])", clause)
        if a and int(a['seat']) in names:
            attack = names[int(a['seat'])]
        if d and int(d['seat']) in names:
            support = names[int(d['seat'])]
    if attack == support:
        return None, None  # A contradictory/ambiguous statement stays unclassified.
    return attack, support
