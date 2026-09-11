# Public check-claim audit / 公开查验声明对账

This is a bounded reasoning aid, not a lie detector or a role oracle. Both
offline and model players use the same public records. It makes no model calls.

Append a standalone line to the end of your public speech:

    Seer report: night 1, seat 3, good.
    预言家查验声明：第1夜，3号，好人。

Use one language; replace the night, seat and result as needed. Results are
`good/wolf` or `好人/狼人`. Multiple reports must be consecutive final lines.
These lines declare **your own** report, including a deliberate bluff. Do not
use the declaration format to quote another player. Ordinary prose, wrapped
quotations and historical text without this format are not inferred as reports.

The audit links conflicting same-night targets/results, changed results for
one target, future nights, invalid seats and public flips to event numbers.
Hidden wolves read good under the current rules. Agreement with a flip does
not establish a real check; disagreement does not establish the speaker's
faction. No suspicion score is automatically changed by this aid.

Offline report options append the format automatically. Players can select
public challenge options; good-side NPCs can ask about a recorded discrepancy.
Models receive a bounded optional audit and choose their own response.
The public-record query `/checks` (or `查验声明` / `查验对账`) displays it.
Only 16 recent reports/findings are shown; the complete original public speech
remains in history. The model aid may be omitted to fit the request budget.

No save schema changes: the audit is rebuilt from persisted public speech.
Old unstructured reports remain readable but are not retroactively interpreted.
Automated tests cover this protocol, not real-model strength or game balance.

## 中文说明

在公开发言末尾单独加一行上面的标准声明，表示**本人声称**在哪一夜验了谁、
结果为何；也可以故意假报。多条声明须连续放在末尾，不用该格式引用别人。
离线报告选项自动附加，模型收到同一说明，但不会强制修改模型的决定。

对账只用公开发言与翻牌，标出来源编号：同夜目标/结果变化、同目标结果变化、
未来夜晚、非法座位、与公开翻牌不符或相容。隐狼按好人查验结果处理。
相容不证明真验，矛盾不证明发言者是狼，也不自动增加嫌疑分数。

可查询“查验声明”或“查验对账”，离线还可选择对账追问。最多展示最近16条
声明与发现，原始记录保留；模型请求空间不足时可省略该辅助信息。
旧存档无需迁移，自由文本不追溯推断。此功能不是全语义谎言检测器。
