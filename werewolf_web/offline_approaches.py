"""Human-facing strategy navigation, derived from authored speech semantics.

This is not a recommendation, probability or extra score. The existing brain
observes accuse/defend/claim/question fields; consequences describe that contract.
No hidden state is read and metadata never enters a speech or checkpoint schema.
"""

NOTES = {
    "pressure": (
        "公开踩人，影响他人判断；有多大说服力取决于他们对你的信任。翻牌后也会回看你这次站队。",
        "Publicly accuse a target. Others weigh your credibility; later flips can put your own stance under scrutiny."),
    "protect": (
        "公开保人，争取他暂不出局；如果他后来翻狼，你这次保护也会被怀疑。",
        "Publicly defend a target. If they later flip wolf, defending them can make you look suspicious."),
    "probe": (
        "点名要解释，不等于投他出局；主持人按追问额度安排回应。",
        "Ask for an explanation, without an exile commitment. The host schedules replies within the question limit."),
    "reveal": (
        "主动暴露或伪装身份；声明会被记住，对跳与前后矛盾会影响可信度。不是主持人认证。",
        "Reveal or bluff a role. Counterclaims and contradictions affect credibility; a claim is not host confirmation."),
    "discuss": (
        "对照桌上的具体说法回应；引用不算新的独立证据，也不自动等于踩人或保人。",
        "Respond to a specific statement. A quotation is not independent evidence or automatically an accusation or defense."),
    "hold": (
        "暂不推动出人，也不提供新线索。不同人格会对认错、拒答和观望有不同反应。",
        "Do not push a target or add evidence. Personalities react differently to admitting doubt, refusing and waiting."),
}


def describe(choice, locale):
    speech = choice.get("speech", {})
    kind = (speech.get("social_action") or {}).get("kind")
    # Claims/reports may also contain an accusation: identity exposure is primary.
    if speech.get("claim"):
        approach = "reveal"
    elif speech.get("question_to"):
        approach = "probe"
    elif speech.get("accuse"):
        approach = "pressure"
    elif speech.get("defend"):
        approach = "protect"
    elif kind in {"listen", "admit", "refuse", "reserve_judgment", "defer"}:
        approach = "hold"
    else:
        approach = "discuss"
    return {**choice, "approach": approach, "consequence": NOTES[approach][locale == "en"]}
