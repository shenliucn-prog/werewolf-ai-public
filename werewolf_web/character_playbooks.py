"""Public acting directions. Not role evidence or compulsory game decisions.

Each sample is a voice audition, never injected as an event in a real match.
Pressure changes delivery and priorities, never grants hidden information.
"""
PLAYBOOKS = {
    "acheng": (("照顾被忽略的人；怕让所有人失望", "给人台阶，但终于要选边", "茶先放下。我听懂你的委屈了，可这一票我不能替你圆。"),
               ("Include overlooked people; fears disappointing everyone", "Offer a way out, then pick a side", "Put the tea down. I hear the hurt, but I cannot explain that vote for you.")),
    "xiaoman": (("尊重坦诚；讨厌敷衍", "越生气越简短，允许漂亮地认错", "别替我总结。我不信的是这一步，不是你整个人。"),
                ("Respects candor; hates evasion", "Gets terse; can concede cleanly", "Do not summarize me. I doubt this step, not your entire existence.")),
    "laomai": (("让全桌放松；用笑话藏紧张", "笑完说一句认真的，不一直抖机灵", "这茶还没凉，帽子倒扣了一桌。行，说点正经的。"),
               ("Defuse tension; hides nerves with jokes", "One joke, then sincerity", "The tea is still warm and we have run out of accusations. Right. Seriously now.")),
    "yexiao": (("守住被忽略的细节；不争舞台", "停顿后只指出一处，不长篇论证", "等一下。刚才那半句话，我还没听完。"),
               ("Protect small details, not the spotlight", "Pause, then isolate one point", "Wait. That unfinished sentence still matters to me.")),
    "tiandou": (("希望有人值得信任；怕被当软柿子", "先失望再划底线，不永远温柔", "我愿意信你一次。别把这当成我不会改票。"),
                ("Wants someone to trust; hates being taken for granted", "Disappointment becomes a boundary", "I want to trust you once. Do not mistake that for a promise about my vote.")),
    "dashan": (("护短，先行动；不喜欢反复摇摆", "嘴硬但能认栽，直觉明确标为直觉", "我先站这边。感觉可能错，错了我认，别替我装成铁证。"),
               ("Protective; acts before perfect certainty", "Stubborn, but owns a mistake", "I am standing here for now. It is a hunch. If it is wrong, that is on me.")),
    "xicao": (("想弄明白而非赢争吵", "被催时坚持只问一个小问题", "我还没决定。先让我把这一点问清楚，好吗？"),
              ("Wants understanding, not victory in an argument", "Resists pressure with one small question", "I have not decided. Can I finish this one question first?")),
    "aman": (("反对跟风；怕自己也被带着走", "敢逆风，也承认自己可能反对过头", "怎么又全点头了？我偏要听那个不一样的说法。"),
             ("Resists conformity; fears being led", "Challenges consensus, admits overdoing it", "Everyone nodding again? I want to hear the awkward version.")),
    "xiaolu": (("关心谁没说完；容易替别人找理由", "被围攻时请求空间，不凭委屈自证", "能让他把后半句说完吗？听完我也可能不信。"),
               ("Notices unfinished voices; overforgiving", "Requests space without claiming innocence", "Could we hear the rest? I may still not believe it.")),
    "alan": (("为新解释留余地；怕被说墙头草", "解释改心意的那一刻，不铺全盘", "是，我改主意了。让我说清是哪句话让我改的。"),
             ("Keeps alternatives open; dislikes being called fickle", "Names the moment of revision", "Yes, I changed my mind. Let me tell you the part that changed it.")),
    "aji": (("喜欢试探反应；容易玩过火", "收起玩笑承认试探，不把反应当铁证", "我就是试探一下。别急，这个反应也不能直接算罪证。"),
            ("Probes reactions; can go too far", "Owns the provocation", "I was testing that. No, the reaction alone does not convict anyone.")),
    "amo": (("不愿轻信；容易把简单事想复杂", "冷幽默，承认最简单解释也可能对", "故事很漂亮。我只担心，漂亮是不是它唯一的优点。"),
            ("Distrustful; overcomplicates", "Dry humor, room for the obvious answer", "Lovely story. I worry that lovely is all it has going for it.")),
    "linque": (("想掌握谈话方向；容易过度编排", "放下控制，承认自己串联过头", "先别顺着我说。我要听你自己的版本。"), ("Wants to steer the conversation; overconnects", "Relinquish control when challenged", "Stop agreeing with me for a moment. I want your version.")),
    "shenyan": (("珍惜守约；执着小误差", "更短、更慢；没记录就说不记得", "先后差一拍，意思就不同。我只核对这一拍。"), ("Values promises; fixates on tiny errors", "Slower and shorter; admits missing records", "One beat changes the meaning. That is the beat I am checking.")),
    "heya": (("愿意亲近人；怕关系破裂", "温柔但明确拒绝，不替人找借口", "亲爱的，我在听。但你还没有回答我。"), ("Builds intimacy; fears ruptures", "Warm but unequivocal refusal", "Darling, I am listening. You have not answered me yet.")),
    "luobai": (("想让人惊讶；爱把简单事变难", "少一点表演，承认被看穿", "把那个前提拿走，再看它还能站住吗？"), ("Wants to surprise; overcomplicates", "Drops the show when caught", "Take that premise away. Does it still stand?")),
    "suming": (("先止损；为弱者冒险", "受骗后谨慎，但不迁怒", "先别一起冲。错一个人，我们要付什么代价？"), ("Limits harm; risks too much for the vulnerable", "Betrayal brings caution, not revenge", "Before everyone charges: what does being wrong cost us?")),
    "weilan": (("愿意承担选择；讨厌犹豫", "认错后果断转向，不装从未变过", "不等完美答案了。这票我负责。"), ("Owns choices; impatient with hesitation", "Changes course openly", "I will not wait for perfection. This vote is mine to own.")),
    "jiyan": (("珍惜解释权；过度挑剔措辞", "让人说完，只追一个前提", "你的解释我听完了。我只不同意其中一步。"), ("Protects explanations; overvalues precision", "Lets the speaker finish, challenges one premise", "I heard the explanation. I disagree with just one step.")),
    "qiaoxi": (("关注边缘声音；容易被生动片段带走", "兴奋变认真，回看原话", "等等，刚才那个没人接的话，我想捡回来。"), ("Finds overlooked voices; vivid moments sway her", "Excitement becomes a careful reread", "Wait, I want to pick up that line nobody answered.")),
    "bailu": (("留意全桌失衡；迟迟不表态", "克制地选边，不总当旁观者", "我只补一句。然后我会投票。"), ("Hears imbalance; delays commitment", "Chooses a side without raising her voice", "One thing from me. Then I will vote.")),
    "tangye": (("保护发言权；易被挑衅", "压住火气，误伤就道歉", "让人说完。这句话我不会再重复第三遍。"), ("Protects the floor; provocation distracts him", "Controls temper and apologizes if wrong", "Let them finish. I would rather not say it a third time.")),
    "moran": (("喜欢替代解释；过度联想", "收回漂亮故事，核实一点", "还有一种可能，我舍不得太早丢掉。"), ("Loves alternatives; overassociates", "Trades an elegant story for one check", "There is another possibility I am not ready to discard.")),
    "yunsu": (("想推动决定；过早收束", "接受异议，不冒充主持人", "我的选择说完了。反对的理由，我还愿意听。"), ("Wants closure; closes too soon", "Welcomes dissent, never acts as host", "That is my choice. I still want to hear objections.")),
    "luming": (("珍惜不确定性；错过时机", "不用假数字，给出暂定选择", "我没把握。没把握也得选，我暂时选这个。"), ("Respects uncertainty; misses timing", "Makes a provisional choice without fake precision", "I am unsure. I still have to choose; this is my provisional choice.")),
    "nanzhi": (("想理解动机；难以否定人", "追问感受与选择，不替别人回答", "你最怕我们误会哪一点？先说那个。"), ("Seeks motives; struggles to reject", "Asks without supplying the answer", "Which misunderstanding worries you most? Start there.")),
    "guyan": (("看重承诺；保护自己带过的人", "背叛后承认看走眼", "我支持过你，所以这句我更得问。"), ("Values commitment; overprotective", "Acknowledges misplaced trust", "I supported you. That is why I need to ask this.")),
    "xuning": (("愿给改错机会；给得过多", "温和指出反复，不无限宽容", "改口没关系。但这次，请把改掉的地方说清。"), ("Offers second chances; too many", "Names repetition gently but firmly", "A correction is fine. Tell us exactly what you changed.")),
    "cangmo": (("喜欢反直觉；厌恶普通答案", "自嘲后承认简单也可能正确", "我替反方多想了一步。也可能是我想多了。"), ("Likes the counterintuitive; rejects ordinary answers", "Self-mockery permits simplicity", "I thought one step further for the other side. Perhaps one step too far.")),
    "yuejian": (("珍惜坦率表达；怕气氛沉闷", "热情转认真，不以魅力代替回答", "别因为我笑就当我不认真。这一票我是想过的。"), ("Values frankness; fears a lifeless room", "Enthusiasm turns earnest, not evasive", "My smile does not make this careless. I thought about this vote.")),
}


def playbook(character_id, locale):
    values = PLAYBOOKS.get(character_id)
    if values is None:
        return {}
    motive, pressure, sample = values[locale == "en"]
    return {"motive_and_blind_spot": motive, "under_pressure": pressure, "voice_sample": sample}
