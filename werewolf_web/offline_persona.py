"""Authored conversational priorities, separate from hidden-role inference."""

# Every library character has a deliberate conversational weakness/strength.
GROUPS = {
    "mediator": ("acheng", "xiaolu", "suming", "bailu", "xuning"),
    "challenger": ("xiaoman", "aman", "heya", "weilan", "jiyan"),
    "observer": ("yexiao", "xicao", "shenyan", "moran", "luming"),
    "connector": ("tiandou", "laomai", "qiaoxi", "tangye", "yunsu"),
    "explorer": ("alan", "amo", "luobai", "nanzhi", "yuejian"),
    "instigator": ("dashan", "aji", "linque", "guyan", "cangmo"),
}
PROFILE = {name: group for group, names in GROUPS.items() for name in names}
REPLIES = {
    "mediator": ("explain_stance", "reserve_judgment", "request_basis"),
    "challenger": ("request_basis", "explain_stance", "reserve_judgment"),
    "observer": ("reserve_judgment", "request_basis", "explain_stance"),
    "connector": ("explain_stance", "reserve_judgment", "request_basis"),
    "explorer": ("reserve_judgment", "explain_stance", "request_basis"),
    "instigator": ("request_basis", "reserve_judgment", "explain_stance"),
}


def reply_order(character_id):
    return REPLIES[PROFILE[character_id]]


def reaction_bias(character_id, option):
    """Small tie-break, never stronger than a revealed contradiction."""
    group = PROFILE[character_id]
    ident, topic = option["id"], option.get("topic")
    if group in {"mediator", "connector"}:
        return .4 if ":thanks:" in ident else 0
    if group in {"observer", "explorer"}:
        return .4 if ":probe:" in ident else 0
    return .4 if topic in {"counterclaim", "hear_target"} else 0
