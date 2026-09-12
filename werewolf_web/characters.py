"""Public authored characters: appearance and personality, never secret roles."""
import random
from .offline_cast import CHARACTERS, BY_ID, cast_settings
from .i18n import cast
from .character_expansion import EXPANSION_BY_ID
from .offline_cast import display_names

# Existing, project-owned portraits are reused as complete character identities.
PROFILES = {
    "acheng": ("茶馆的调停者", "The Peacemaker", "总替争执的人续上热茶；愿意听完，但有时太想让所有人满意。", "Keeps the tea warm through every argument; listens generously, sometimes at the cost of conviction."),
    "xiaoman": ("带刺的玫瑰", "The Thorned Rose", "说话利落，审美挑剔，记得每一次改口；欣赏坦诚的对手。", "Sharp words, exacting taste, a memory for every changed story; respects an honest opponent."),
    "laomai": ("夜场的说书人", "The Storyteller", "笑话总比怒气先到；轻松外表下藏着老练的观察。", "A joke arrives before his temper; an easy manner conceals a veteran's watchfulness."),
    "yexiao": ("月下的记录者", "The Moonlit Archivist", "习惯坐在灯影交界处，少言，却会为一个被忽略的细节开口。", "Sits where lamplight meets shadow; speaks rarely, but never lets a small detail disappear."),
    "tiandou": ("人群里的暖光", "The Warm Spark", "记得每个人喜欢喝什么；愿意相信别人，也正在学会说不。", "Remembers everyone's favorite drink; quick to trust, slowly learning to say no."),
    "dashan": ("不退的磐石", "The Steadfast", "一旦决定便站到最前面；保护同伴，也需要学会收回判断。", "Steps forward once his mind is made up; protective, but slow to admit a wrong turn."),
    "xicao": ("雨后的解谜者", "The Rain Reader", "声音轻，问题却很准；喜欢证据，不喜欢被催着站队。", "A gentle voice with precise questions; prefers evidence to pressure to pick a side."),
    "aman": ("逆风的火花", "The Contrarian Spark", "别人点头时她先问为什么；有勇气顶住多数，也可能为反对而反对。", "Asks why when everyone else nods; brave against a majority, sometimes contrary for its own sake."),
    "xiaolu": ("林间的倾听者", "The Woodland Listener", "留意没说完的话与被打断的人；善解人意，却容易替别人解释太多。", "Notices unfinished sentences and interrupted speakers; empathetic, occasionally too forgiving."),
    "alan": ("风向的旅人", "The Wayfarer", "喜欢留一扇窗给新的解释；会改变主意，但必须说清理由。", "Leaves a window open to another explanation; willing to change her mind and explain why."),
    "aji": ("冒险的试探者", "The Daring Scout", "先抛出一个大胆问题，再观察全桌；好奇心旺盛，也会玩火。", "Throws out a daring question and watches the table; curious enough to play with fire."),
    "amo": ("冷月的怀疑者", "The Dry Skeptic", "嘴角的笑意让人猜不透；总能找出另一种解释，也可能错过最简单的答案。", "An unreadable half-smile; finds another explanation, sometimes missing the simplest one."),
}


def catalog(locale):
    en = locale == "en"
    names = display_names(locale)
    result = []
    for c in CHARACTERS:
        extra = EXPANSION_BY_ID.get(c.id)
        result.append({"id": c.id, "name": names[c.id],
            "title": extra["titles"][en] if extra else PROFILES[c.id][en],
            "story": extra["stories"][en] if extra else PROFILES[c.id][2 + en],
            "description": c.description[en], "phrase": c.phrase[en],
            "voice": extra["voices"][en] if extra else c.description[en],
            "weights": dict(zip(("aggression", "logic", "bluff", "loyalty", "caution", "verbosity"), c.weights)),
            "portrait": f"/img/portraits/{c.id}.png"})
    return result


def bind_characters(engine, choice, seed=None):
    if not isinstance(choice, str) or choice not in (*BY_ID, "random"):
        raise ValueError("Choose a listed character or random.")
    if choice == "random":
        rng = random.Random(f"{seed}:character") if seed is not None else random.SystemRandom()
        choice = rng.choice(tuple(BY_ID))
    mapping, names = cast_settings(choice, engine.locale, seed=seed)
    engine.cast_names = names
    engine.cast_personas = mapping
    engine.character_cast = True
    return choice
