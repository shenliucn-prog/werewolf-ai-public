# Your first game / 第一次怎么玩

## English — two-minute guide

You are one of twelve players. The other eleven are local AI characters; the
host explains rules and keeps time. This is **one human per game**, not an
online lobby. Text is the evidence: portraits do not encode tells.

1. Start with **Classic** (Seer · Witch · Hunter · Guard), **Local AI only**,
   Conjecture **off**, and random NPC personalities. Pick **Seer** to learn an
   information role, or keep your role random. Read your private role card.
2. At night, only invited roles act. Choose from the offered targets and
   confirm. In chat use `choose 3`; Witch uses `save 3` or `poison 4`.
   `pass` skips an optional action. Ordinary villagers have no night action.
3. At dawn, deaths and roles are publicly revealed in this project's variant.
   The first day includes a sheriff election. You may decline to run; the
   sheriff's exile vote weighs 1.5. Tied exile tallies eliminate nobody.
4. During the day, compare claims, checks and votes. Speak when prompted:
   “I am the Seer. I checked #3: good. I suspect #7 because their claim changed.”
   Say whatever strategy you intend; recognition of claims is heuristic, not
   complete understanding. Other players may interrupt; the host limits exchanges.
5. Vote for an offered candidate (`vote 7`). Good wins when all wolves are
   eliminated. Wolves win when **either all special good roles or all ordinary
   villagers are eliminated**; parity alone is not this variant's win rule.
   Dead players stop acting, apart from eligible immediate death abilities,
   and can watch the rest of the game and review.

Use **Ask the Host** or `?How does the Guard work?` whenever waiting for an
action. This is private and does not spend that action. The host does not
identify wolves or select targets for you. Private messages marked 🔒 are
different from public statements. A player's claimed role is not a certified role.

### Which mode should I choose?

| Choice | What changes | Suitable for |
| --- | --- | --- |
| Normal (default) | Natural-language debate; no mandatory tables | First games and ordinary play |
| Conjecture beta | Private belief table + public debate table, revised before discussion and voting; public versions retained | Studying consistent claims; more input and reading |
| Divine Witch boards | Unlimited total potions; single variant uses one type/night, dual allows one of each/night | Experimental strong-role play, not proven balanced |
| Research runners | Separate protocols, including seven-seat Codex decisions or all-AI local screens | Developers; not an extra lobby mode |

Conjecture can be combined with any board. Your private table is not broadcast;
your public table may deliberately differ. Changes of mind are not automatically
punished. In terminal table editing, row numbers refer to the displayed table
rows, **not seat numbers**. Voice and behavioral visual signals are not implemented.

In all Witch boards, self-save works only on night one. Antidote cannot revive
earlier deaths, and Guard + save on the same knife victim is fatal. Only Divine
Witch **dual** accepts `save 3 poison 4` together. See [full rules](RULE_VARIANT.md).

If an action fails to send, the browser restores the action panel for retry.
A closed connection or server restart cannot resume a match; start a new one.
Keep the server on your own machine. Online wording is optional and sends game
context to your configured provider; do not include sensitive real-world details.

## 中文——两分钟上手

这是“一位真人 + 十一位 AI + 自动主持人”的十二人对局，不是多人联网大厅。
头像只是装饰，判断依据来自文字发言、行动、公开翻牌及你合法知道的私密信息。

1. 首局选经典「预女猎守」、只用本地 AI、关闭猜想模式，人格保持每局随机。
   想体验信息型身份可选预言家，也可随机身份；开局后先看自己的私密身份卡。
2. 夜晚收到提示才行动，网页选目标并确认；聊天输入「选 3」「救 3」「毒 4」。
   可选行动用 `pass` 跳过，平民无需夜间行动。
3. 天亮公开死讯并翻出死者身份；第一天有警长竞选，可以不上警。
   警长放逐票重 1.5 票，放逐最高票并列时无人出局。
4. 白天比较声明、查验和投票，再表达自己的判断。例如「我是预言家，昨晚验 3 号是好人，
   7 号改口没有解释，我怀疑他」。其他人可以打岔，主持人限制拉扯时长。
   自然语言识别是启发式的，不保证理解每一种表达。
5. 收到投票提示后选择候选人（如「投 7」）。全部狼人出局则好人胜；
   全部神职或全部平民任一组出局则狼人胜，不是简单按狼人数达到一半判胜。
   死亡后除合法的即时死亡技能外不再行动，可继续看完对局与复盘。

不懂就单聊主持人：网页「问主持人」，聊天 `?守卫怎么用？`，不会消耗当前行动。
主持人只解释规则，不泄露身份，不替你决定投谁。🔒 是自己的私密信息；
他人跳身份只是声明，不是主持人认证。

普通模式用自然语言辩论。猜想模式是研究取向的测试版：每次整理自己的私有判断表和
对外的公开辩论表，公开版本保留历史，不等于完美推理，也不会把改口一律判为说谎。
聊天编辑双表时，数字是显示的表格行号，不是座位号。

神女巫两板总药量无限：择一版每夜救或毒；双开版可「救 3 毒 4」，每种各一次。
两板都仅首夜能自救、不能复活旧死者、守救同一刀口会导致死亡，二十个完整昼夜无胜者平局。
这是平衡未定的实验板；猜想开关独立于板子，语音和视觉行为玩法尚未实现。

发送失败会恢复操作面板；断线或服务重启不能续局，需要重新开始。
详细设置见[游戏模式](GAME_MODES.md)，完整规则见[本项目规则版本](RULE_VARIANT.md)。
