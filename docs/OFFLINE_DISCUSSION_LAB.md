# Offline choice-based discussion prototype

For complete rule games with twelve characters and saves, see
[Offline choice games](OFFLINE_GAME.md). This smaller fixture remains available
for comparing individual design choices.

This is an **opt-in design experiment, not a complete Werewolf game**. It does
not replace formal model play or the existing offline rule-flow mode. No API,
Agent connection, credentials, hidden roles, save files or campaign scores are
used. All records are synthetic public statements, not real playtest data.

Run from the repository root:

```sh
python -m werewolf_web.offline_lab --lang en
python -m werewolf_web.offline_lab --lang zh-CN
```

Select numbered options; `q` quits. Seat 1 is the player. Four experimental
NPC profiles occupy seats 2–5: Dashan (firm), Xicao (evidence-oriented), Aman
(skeptical of consensus), and Tiandou (responsive to admissions). These are
not the final twelve-character cast or their balanced gameplay parameters.

## What to try

The public fixture shows an initial expression of support, a subsequent
unverified seer claim, and then a changed exile ballot. Respond to a question
about that change, raise one topic, hear a response and one interruption, then
vote after the host closes the floor.

Compare the same scene with:

- a source-linked explanation versus declining to explain;
- admitting unsupported following versus citing the new claim;
- suspecting the reported target versus provisionally defending them.

NPC suspicion scores and ballots change with those actions. A request for
evidence alone does not count as an accusation. The earlier question closes
on an explicit response, including refusal, and is not asked repeatedly.
NPC ballots never use the player's unrevealed ballot. There is no elimination
or winner: without hidden roles, this fixture cannot establish correctness.

## Implementation boundary and known limitations

`offline_lab.py` contains a small deterministic policy, public source records,
stage-specific option IDs and a terminal renderer. Scores are heuristic policy
weights, **not calibrated probabilities**. Ties in NPC candidate scores favor
the lower seat number for reproducibility; this is not a balanced game policy.
Dialogue and options are authored for this one scene. This does not implement
general language understanding, lie planning, role skills, persistence, a Web
screen, character replacement or spectator mode. Those must not be advertised
as delivered by this prototype.

The automated tests cover every menu path, stale-action rejection without
mutation, source references, bounded interruptions, divergent ballots, and
both terminal languages. They do **not** establish that the prototype is fun.

Before integrating a full match, manually evaluate whether options offer
meaningful trade-offs, whether responses feel relevant, and whether characters
are recognizable beyond their names. Do not expand to twelve profiles or all
boards simply because tests pass. If the choices remain shallow, keep the
offline experience scoped to teaching and rule demonstrations.

## 中文试玩说明

这是独立的离线讨论样板，不是完整狼人杀，不调用模型、不计成绩、不保存。
你是1号，其他四人分别代表坚定、重证据、质疑共识、看重坦诚的试验人格。
输入编号完成「回应追问 → 提出议题 → 他人回应与打岔 → 主持人收束 → 投票」。

可以重新运行，对比「引用新报告」「承认跟票」「拒绝解释」的后果，再比较
「怀疑2号」「追问3号」「暂时保留2号」。报告仍是声明，不会自动变成事实。
当前无身份、夜晚、出局和胜负，不能用来判断狼人策略或板子平衡。
四人人格与固定台词都只是样板；是否扩展到12人，应先由实际试玩决定。
