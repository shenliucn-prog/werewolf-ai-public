"""Locale packs for stable player identities and display-facing game text."""
from __future__ import annotations

SUPPORTED_LOCALES = ("zh-CN", "en")
DEFAULT_LOCALE = "zh-CN"

_CAST = {
    "zh-CN": [
        ("dashan", "大山"), ("amo", "阿墨"), ("alan", "阿岚"), ("xiaoman", "小满"),
        ("yexiao", "夜枭"), ("xiaolu", "小鹿"), ("aman", "阿蛮"), ("tiandou", "甜豆"),
        ("xicao", "细草"), ("laomai", "老麦"), ("aji", "阿吉"), ("acheng", "阿承"),
    ],
    "en": [
        ("dashan", "Miles"), ("amo", "Adrian"), ("alan", "Nora"), ("xiaoman", "Maya"),
        ("yexiao", "Owen"), ("xiaolu", "Chloe"), ("aman", "Victor"), ("tiandou", "Tessa"),
        ("xicao", "Felix"), ("laomai", "Leo"), ("aji", "Gavin"), ("acheng", "Alex"),
    ],
}

_EN_PERSONAS = {
    "dashan": ("loud, warm-hearted, instinct-first", ["Trust your gut."]),
    "amo": ("reflective, theatrical, sees both sides", ["Let us look at both sides."]),
    "alan": ("calm, gentle, methodical", ["Let's slow down and check the facts."]),
    "xiaoman": ("outgoing, resilient, occasionally hesitant", ["Give me a second to think."]),
    "yexiao": ("earnest, nervous under pressure", ["I mean what I say."]),
    "xiaolu": ("playful, intuitive, volatile", ["My instinct is talking."]),
    "aman": ("analytical, direct, composed", ["The logic matters here."]),
    "tiandou": ("cheerful, social, easily distracted", ["No hard feelings—keep talking."]),
    "xicao": ("precise, probing, demanding evidence", ["Which exact point proves that?"]),
    "laomai": ("patient, elegant, unhurried", ["Easy now. Let the table breathe."]),
    "aji": ("plainspoken, disciplined, challenging", ["Say it clearly and own it."]),
    "acheng": ("the human player's public table identity", ["Let's hear everyone out."]),
}

ROLE_NAMES_EN = {
    "seer": "Seer", "witch": "Witch", "hunter": "Hunter", "guard": "Guard",
    "knight": "Knight", "crow": "Crow", "gravekeeper": "Gravekeeper", "bomber": "Bomber",
    "wolf_king": "Wolf King", "white_wolf_king": "White Wolf King", "wolf_beauty": "Wolf Beauty",
    "hidden_wolf": "Hidden Wolf", "stone_ghost": "Stone Ghost", "evil_knight": "Evil Knight",
    "werewolf": "Werewolf", "civilian": "Villager",
    "grave": "Gravekeeper",
}

def role_name(locale: str | None, key: str, fallback: str) -> str:
    return ROLE_NAMES_EN.get(key, fallback) if normalize_locale(locale) == "en" else fallback


def normalize_locale(locale: str | None) -> str:
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def cast(locale: str | None) -> list[dict]:
    return [{"id": player_id, "name": name} for player_id, name in _CAST[normalize_locale(locale)]]


def persona(locale: str | None, player_id: str, display_name: str) -> dict | None:
    if normalize_locale(locale) != "en":
        return None
    traits, catchphrases = _EN_PERSONAS[player_id]
    return {"name": display_name, "traits": traits, "profile": traits,
            "catchphrases": catchphrases, "role_habits": {}, "relations": ""}


# ---------------------------------------------------------------------------
# Role abilities (English).  Structural role data stays in boards.json; these
# are only the display-facing descriptions for English sessions.
# ---------------------------------------------------------------------------
ROLE_DESC_EN = {
    "seer": "Each night, check one player and learn whether they are good or a werewolf.",
    "witch": "Holds an antidote (save one) and a poison (kill one), not both in one night; may self-save on night one.",
    "hunter": "When eliminated (not by poison or duel), may shoot one player.",
    "guard": "Each night, guard one player; cannot guard the same player two nights in a row. If both guarded and saved by the Witch, the attacked player still dies.",
    "knight": "Once per game, before your daytime statement, duel a player: a wolf dies and day ends; otherwise you die and day continues.",
    "crow": "Before each exile vote, may slander one other living player, adding one vote against them that round.",
    "gravekeeper": "Each night, learn whether the previously exiled player was good or a wolf; blind on night one.",
    "bomber": "When exiled, explodes and randomly kills one player.",
    "grave": "Gravekeeper",
    "wolf_king": "When exiled or shot by the Hunter, may shoot one player; cannot shoot if poisoned or defeated in a duel.",
    "white_wolf_king": "Before your daytime statement, may self-destruct and take one other living player down; day ends after death abilities resolve.",
    "wolf_beauty": "Each night, charm one player; when the Wolf Beauty is eliminated, the charmed player leaves too.",
    "hidden_wolf": "Belongs to the wolf faction but reads as good to the Seer.",
    "stone_ghost": "Each night, check one player's exact role; isolated from ordinary wolves. Gains the kill once the pack is gone.",
    "evil_knight": "One passive reflection: checked by Seer → Seer dies; poisoned by Witch → Witch dies; shot by Hunter → Hunter cannot shoot.",
    "werewolf": "Each night, kill one player together with the pack.",
    "civilian": "No ability; find the wolves through speech and votes.",
}


# ---------------------------------------------------------------------------
# Board metadata (English).  The `roles` list and rule resolution stay in
# boards.json; only the human-facing name / difficulty / description differ.
# ---------------------------------------------------------------------------
BOARDS_EN = {
    "divine_witch": {
        "name": "Divine Witch · Unlimited, one potion/night", "difficulty": "🧪 Experimental",
        "desc": "Classic roster, unlimited potions, one type per night. Self-save only on night one; guard plus save on the same target is fatal. Balance unproven.",
    },
    "divine_witch_dual": {
        "name": "Divine Witch · Unlimited, both potions/night", "difficulty": "🧪 Extreme experiment",
        "desc": "Classic roster, unlimited potions, at most one of each per night. Self-save only on night one; guard plus save on the same target is fatal. Balance unproven.",
    },
    "classic": {
        "name": "Seer · Witch · Hunter · Guard",
        "difficulty": "⭐ Beginner",
        "desc": "Classic balanced board: 4 wolves vs 4 gods (Seer/Witch/Hunter/Guard) vs 4 villagers, pure logic.",
    },
    "wolf_king": {
        "name": "Wolf King · Guard",
        "difficulty": "⭐⭐ Advanced",
        "desc": "The Wolf King can shoot when exiled or taken by the Hunter; the village must weigh who to push.",
    },
    "white_wolf_knight": {
        "name": "White Wolf King · Knight",
        "difficulty": "⭐⭐ Advanced",
        "desc": "White Wolf King self-destructs to trade; the Knight duels to break boards; fast, explosive tempo.",
    },
    "wolf_beauty_knight": {
        "name": "Wolf Beauty · Knight",
        "difficulty": "⭐⭐ Advanced",
        "desc": "Wolf Beauty charms and binds votes; the Knight duels to break stalemates; a defensive wolf fight.",
    },
    "hidden_wolf_crow": {
        "name": "Hidden Wolf · Crow",
        "difficulty": "⭐⭐ Advanced",
        "desc": "Hidden Wolf reads good to the Seer; the Crow slanders to distort votes; an information war.",
    },
    "bomber": {
        "name": "Bomber",
        "difficulty": "⭐⭐ Party",
        "desc": "The Bomber explodes when exiled and randomly kills someone; no one dares push carelessly.",
    },
    "stone_ghost": {
        "name": "Stone Ghost · Gravekeeper",
        "difficulty": "⭐⭐⭐ Expert",
        "desc": "Stone Ghost checks exact roles; the Gravekeeper re-checks exiles; an intelligence peak.",
    },
    "evil_knight": {
        "name": "Evil Knight · Guard",
        "difficulty": "⭐⭐⭐ Expert",
        "desc": "The Evil Knight has one passive reflection; gods must tread carefully; a nightmarish ability.",
    },
}


def board_role_name(locale, board, key, fallback):
    if key == "witch" and board.get("witch_rules", {}).get("unlimited"):
        return "Divine Witch" if normalize_locale(locale) == "en" else "神女巫"
    return role_name(locale, key, fallback)


def witch_rule_text(locale, board):
    rules = board.get("witch_rules", {})
    if not rules.get("unlimited"):
        return ("One antidote and one poison for the entire game; only one type per night. Self-save only on night one."
                if normalize_locale(locale) == "en" else "整局一瓶解药、一瓶毒药；同夜只能用一种，只有首夜可自救。")
    if normalize_locale(locale) == "en":
        timing = "You may save AND poison, at most once each per night." if rules.get("dual") else "Choose save OR poison each night."
        return ("Divine Witch: unlimited antidotes and poisons across nights. " + timing +
                " Only a living Witch may act. Antidote saves tonight's knife victim, not previously dead players; self-save only on night one. "
                "Poison cannot target yourself. Poison still kills a saved target; guarding and saving the same knife victim is fatal. "
                "After 20 full night/day cycles without a winner, the experiment ends in a draw. Balance unproven.")
    timing = "同夜可救又可毒，两种各最多一次。" if rules.get("dual") else "每夜只能救或毒，二选一。"
    return ("神女巫：解药和毒药跨夜不限总次数。" + timing +
            "只有存活女巫可行动；解药只救今晚刀口，不能复活往夜死者；仅首夜可自救。不能自毒；被救者仍可被毒死；守救同一刀口仍会奶穿。20个完整昼夜仍无胜者则实验平局。平衡尚未验证。")


# ---------------------------------------------------------------------------
# Display-only system event text.  The ledger always stores structured facts
# (pos / name / role / cause); these templates only change what a player sees.
# ---------------------------------------------------------------------------
_STRINGS = {
    "zh-CN": {
        "night_start": "第{n}夜",
        "knight_desc": "整局一次：决斗一人。对方是狼则其出局并结束白天；否则你出局、白天继续。不选目标可跳过。",
        "white_wolf_king_desc": "自爆并带走一人，结算死亡技能后结束白天。不选目标可跳过。",
        "crow_desc": "诽谤一人，为其增加一票放逐票，仅本轮有效。不选目标可跳过。",
        "knight_duel": "{pos}号骑士向{target}号发动决斗。",
        "white_explode": "{pos}号白狼王自爆，带走{target}号。",
        "crow_mark": "{target}号被乌鸦诽谤，本轮增加一票放逐票。",
        "skill_ends_day": "技能结算完毕，白天结束，直接进入夜晚。",
        "sg_kill_desc": "普通狼队已全灭。选择今晚的刀人目标（查验仍可使用）。",
        "grave_result": "你（守墓人）第{n}夜得知：上一轮被放逐的{target}号（{name}）是{result}。",
        "day_start": "第{d}天 天亮",
        "death": "{pos}号（{name}）死亡。",
        "flip": "{pos}号（{name}）翻牌——{role}。",
        "exile": "{pos}号（{name}）被放逐出局。",
        "seer_reflect": "预言家查验恶灵骑士，触发反弹——预言家死亡！",
        "witch_reflect": "女巫毒到恶灵骑士，触发反弹——女巫死亡！",
        "hunter_reflect": "猎人试图带走恶灵骑士，触发反弹——猎人无法开枪！",
        "charm": "狼美人魅惑了{n}号。",
        "hunter_shot": "{pos}号（{name}·猎人）开枪带走了{target}号（{tname}）。",
        "wolf_king_shot": "{pos}号（狼王）开枪带走了{target}号。",
        "vote_header": "第{d}天投票：{votes}",
        "vote_none": "无人投票",
        "vote_arrow": "{v}号→{t}号",
        "vote_tie": "平票，无人被放逐，平安日。",
        "sheriff_elected": "{pos}号（{name}）当选警长（1.5 票权）。",
        "sheriff_nobody": "无人上警，本局无警长。",
        "sheriff_tie": "警长投票流局，本局无警长。",
        "win_god": "所有狼人出局，好人阵营胜利！",
        "win_wolf": "狼人屠边成功，狼人阵营胜利！",
        "phase_day": "第{n}天",
        "election_phase": "警长竞选",
        "seer_check": "验人",
        "wolf_tactic": ("狼队统一刀人。可刀任意存活玩家，也可自刀：悍跳预言家骗女巫解药、"
                        "自刀做金水洗白，或引女巫盲毒好人。常规规则优先秒神职/强好人。"),
        "witch_knife": "今晚被刀的是 {pos}号。是否救人/毒人？",
        "guard_desc": "保护一人（不可连守同一人）",
        "beauty_desc": "魅惑一名玩家（你出局时其一同出局）",
        "sg_desc": "查验一名玩家的具体身份",
        "gun_desc": "开枪带走一名玩家",
        "note_self": "（你自己·自刀）",
        "note_mate": "（狼队友·自刀）",
        "seer_result": "你（预言家）第{n}夜验了{target}号（{name}），结果：{result}。",
        "sg_result": "你（石像鬼）第{n}夜查验了{target}号（{name}），身份是：{role}。",
        "result_wolf": "狼人",
        "result_good": "好人",
        "default_reply": "这个问题我先记下，投票前再说明。",
        "note_hunt": "查杀",
        "note_safe": "金水",
    },
    "en": {
        "night_start": "Night {n}",
        "knight_desc": "Once per game: duel a player. A wolf dies and day ends; otherwise you die and day continues. Leave the target empty to pass.",
        "white_wolf_king_desc": "Self-destruct and take one player down. Day ends after death abilities resolve. Leave the target empty to pass.",
        "crow_desc": "Slander a player, adding one exile vote against them this round only. Leave the target empty to pass.",
        "knight_duel": "#{pos}, the Knight, challenges #{target} to a duel.",
        "white_explode": "#{pos}, the White Wolf King, self-destructs and takes #{target} down.",
        "crow_mark": "#{target} is slandered by the Crow and receives one extra exile vote this round.",
        "skill_ends_day": "The ability has resolved. Day ends and night begins immediately.",
        "sg_kill_desc": "The ordinary pack is gone. Pick tonight's kill (your role check remains available).",
        "grave_result": "You (Gravekeeper) learn on night {n}: the last exiled player, #{target} ({name}), was {result}.",
        "day_start": "Day {d} — dawn",
        "death": "#{pos} ({name}) is dead.",
        "flip": "#{pos} ({name}) flips — {role}.",
        "exile": "#{pos} ({name}) is exiled.",
        "seer_reflect": "The Seer checked the Evil Knight and was reflected back — the Seer dies!",
        "witch_reflect": "The Witch poisoned the Evil Knight and was reflected back — the Witch dies!",
        "hunter_reflect": "The Hunter tried to shoot the Evil Knight and was reflected — the Hunter cannot shoot!",
        "charm": "The Wolf Beauty charmed #{n}.",
        "hunter_shot": "#{pos} ({name}, Hunter) shot and took #{target} ({tname}).",
        "wolf_king_shot": "#{pos} (Wolf King) shot and took #{target}.",
        "vote_header": "Day {d} vote: {votes}",
        "vote_none": "no votes",
        "vote_arrow": "#{v}→#{t}",
        "vote_tie": "Tie — no one is exiled. Peaceful day.",
        "sheriff_elected": "#{pos} ({name}) is elected sheriff (1.5 votes).",
        "sheriff_nobody": "No one ran; there is no sheriff this game.",
        "sheriff_tie": "Sheriff election tied off; there is no sheriff this game.",
        "win_god": "All werewolves are out — the village wins!",
        "win_wolf": "The werewolves have overrun the village — the werewolves win!",
        "phase_day": "Day {n}",
        "election_phase": "Sheriff election",
        "seer_check": "Check a player",
        "wolf_tactic": ("The pack picks one kill. You may knife any living player, even yourselves: "
                       "bluff the Seer to bait the Witch's save, knife a mate to play as a clean "
                       "body, or lure the Witch into poisoning an innocent. Normally target the "
                       "strongest gods or most valuable villagers."),
        "witch_knife": "The knife tonight is #{pos}. Will you save or poison?",
        "guard_desc": "Guard one player (not the same target on consecutive nights)",
        "beauty_desc": "Charm one player (when you leave, they leave too)",
        "sg_desc": "Check one player's exact role",
        "gun_desc": "Shoot and take one player down",
        "note_self": "(you — self knife)",
        "note_mate": "(wolf mate — self knife)",
        "seer_result": "You (Seer) checked #{target} ({name}) on night {n}: {result}.",
        "sg_result": "You (Stone Ghost) checked #{target} ({name}) on night {n}: {role}.",
        "result_wolf": "werewolf",
        "result_good": "good",
        "default_reply": "I'll note that question and address it before the vote.",
        "note_hunt": "hunt",
        "note_safe": "clean",
    },
}


def t(locale: str | None, key: str, **fmt) -> str:
    """Render a display-only system template for the given locale."""
    loc = normalize_locale(locale)
    pack = _STRINGS.get(loc, _STRINGS[DEFAULT_LOCALE])
    tmpl = pack.get(key) or _STRINGS[DEFAULT_LOCALE].get(key, key)
    return tmpl.format(**fmt) if fmt else tmpl


def list_sep(locale: str | None) -> str:
    return ", " if normalize_locale(locale) == "en" else "，"


def board_display(locale: str | None, board: dict) -> dict:
    """Locale-facing board name / difficulty / description."""
    if normalize_locale(locale) != "en":
        return {"name": board.get("name"), "difficulty": board.get("difficulty"),
                "desc": board.get("desc")}
    en = BOARDS_EN.get(board.get("id"), {})
    return {"name": en.get("name", board.get("name")),
            "difficulty": en.get("difficulty", board.get("difficulty")),
            "desc": en.get("desc", board.get("desc"))}


def role_desc(locale: str | None, key: str, role_meta: dict) -> str:
    if normalize_locale(locale) == "en":
        return ROLE_DESC_EN.get(key, role_meta.get("desc", ""))
    return role_meta.get("desc", "")
