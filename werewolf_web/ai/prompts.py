"""提示词模板：构建 NPC / 主持人 的 LLM 输入。"""

ROLE_CN = {
    "seer": "预言家", "witch": "女巫", "hunter": "猎人", "guard": "守卫",
    "knight": "骑士", "crow": "乌鸦", "gravekeeper": "守墓人", "bomber": "炸弹人",
    "wolf_king": "狼王", "white_wolf_king": "白狼王", "wolf_beauty": "狼美人",
    "hidden_wolf": "隐狼", "stone_ghost": "石像鬼", "evil_knight": "恶灵骑士",
    "werewolf": "狼人", "civilian": "平民",
}

SYSTEM_NPC = """你正在参与一局12人狼人杀，你扮演其中一名玩家。
请用该角色的口吻、性格、口头禅发言，保持人设一致性。
你的发言要服务于你的游戏目标（好人找出狼人 / 狼人隐藏并带节奏）。
只输出该角色当轮的发言内容（1-4句话），不要输出任何解释、括号备注或OOC内容。
如果是狼人，可以适度欺骗但不能暴露你是AI或跳出游戏。
"""

SYSTEM_HOST = """你是狼人杀的上帝（主持人），负责推进游戏、播报流程、控制节奏。
你的播报要简洁有氛围，带一点戏剧感，但绝不泄露任何未翻牌玩家的身份。
只在规则允许的范围内描述事件。不编造不存在的信息。
"""

SYSTEM_REVIEW = """你是一名狼人杀复盘教练，擅长从对局中提取可执行的改进点。
请用结构化中文输出，聚焦具体、可落地的建议。
"""


def build_speech_prompt(persona: dict, role_cn: str, is_wolf: bool,
                        context: str, player_last_speech: str = "", locale: str = "zh-CN") -> str:
    if locale == "en":
        return (f"Name: {persona['name']}\nRole: {role_cn}\n"
                f"Faction: {'werewolves' if is_wolf else 'village'}\n"
                f"Personality: {persona.get('traits', '')}\n"
                f"Catchphrases: {', '.join(persona.get('catchphrases', []))}\n"
                f"Context and locked intent:\n{context}\n"
                f"Human player's previous statement: {player_last_speech}\n"
                "Speak naturally in English. Preserve the locked claim, accusation and defence; "
                "never invent check results or reveal private facts absent from the base statement.")
    catch = "、".join(persona.get("catchphrases", [])[:3])
    habit = persona.get("role_habits", {}).get(role_cn, "")
    rel = persona.get("relations", "")
    prompt = f"""【你的角色】
姓名：{persona['name']}
身份：{role_cn}（{'狼人阵营' if is_wolf else '好人阵营'}）
性格：{persona.get('traits','')}
口头禅：{catch}
作为{role_cn}的习惯：{habit}
人际关系：{rel}

【当前局势】
{context}

【你的任务】
请以上述人设发言。"""
    if player_last_speech:
        prompt += f"\n\n注意：玩家（阿承）上一轮说了：『{player_last_speech}』，请在发言中自然回应他。"
    return prompt


def build_vote_prompt(persona: dict, role_cn: str, is_wolf: bool,
                      context: str, candidates: list) -> str:
    cand_str = "、".join(candidates)
    prompt = f"""【你的角色】{persona['name']}（{role_cn}，{'狼人阵营' if is_wolf else '好人阵营'}）
性格：{persona.get('traits','')}

【当前局势】
{context}

【投票】
可投目标（含当前票数/疑点）：{cand_str}
请基于你的身份与目标，选择你要投的人。只返回一个JSON：{{"target": 座位号 或 null}}。
"""
    return prompt


def build_night_prompt(persona: dict, role_cn: str, action_desc: str,
                       context: str, candidates: list) -> str:
    cand_str = "、".join(str(c) for c in candidates)
    prompt = f"""【你的角色】{persona['name']}（{role_cn}）
性格：{persona.get('traits','')}

【当前局势】
{context}

【你的夜间行动】
{action_desc}
可取目标：[{cand_str}]
请返回JSON：{action_desc}对应的目标字段。例如 {{"target": 3}} 或 {{"save": 3, "poison": null}}。
"""
    return prompt


def build_review_prompt(board: str, winner: str, events_log: str,
                        npc_performances: str, locale: str = "zh-CN") -> str:
    if locale == "en":
        return (f"Board: {board}\nWinner: {winner}\nEvents:\n{events_log}\n"
                f"NPC performance:\n{npc_performances}\n"
                "Review the key turning points, specific improvements for both factions, "
                "and the host's pacing. Use only the recorded evidence. Write in English.")
    return f"""【本局板子】{board}
【胜利方】{winner}

【对局事件】
{events_log}

【各角色表现】
{npc_performances}

请输出复盘：
1. 胜负关键转折
2. 每个阵营本局的可改进点（具体到某人的某次发言/投票）
3. 主持人节奏控制的评价
4. 一句话总评
"""


def system_npc(locale: str) -> str:
    if locale == "en":
        return ("You are one player in a 12-player Werewolf game. Speak only in English, "
                "in character, in 1–4 sentences. Express the supplied strategic intent without "
                "changing its claim, accusation or defence. Do not add facts or out-of-character commentary.")
    return SYSTEM_NPC


def system_review(locale: str) -> str:
    return ("You are a Werewolf post-game coach. Write an evidence-based review in English "
            "with specific, actionable improvements." if locale == "en" else SYSTEM_REVIEW)
