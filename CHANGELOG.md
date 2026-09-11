# Changelog / 更新日志

## Unreleased

- Added a public-only, source-linked audit of explicitly formatted Seer reports
  for offline menus and model context. Ambiguous prose remains unaudited.
- 新增离线选项与模型上下文共用的查验声明对账，仅核对标准格式的公开声明；
  不读他人私密查验，不将矛盾等同狼人身份。旧存档不迁移、不推测旧文本含义。

- Fixed public Seer evidence retention when real session flips use localized
  display labels rather than the stable role ID; public flip events now also
  carry optional stable role/name fields. Legacy localized records remain supported.
- 修复真实会话使用中英文展示标签翻牌时预言家发言漏保留；公开翻牌事件新增
  可选稳定角色/姓名字段，同时兼容旧本地化记录。新增跨板子、跨推断策略测试。

- Fixed repeated support/accusations multiplying flip evidence, and historic
  or duplicate votes entering a later exile's accounting. Both shared inference
  and legacy scoring deduplicate the resolved statement relationship.
- 修复重复保人/指控放大翻牌证据、历史或重复投票混入后续放逐记账；共用推断
  与旧策略评分均对已结算的发言关系去重。
- Existing saves remain readable, but old accumulated evidence scores are not
  retroactively repaired. / 旧存档仍可读取，但已有累计证据偏差不会被追溯重算。

- Added separate synthetic dialogue ablations (claims/reports/support/reversal)
  to distinguish policy effects before modifying good-side inference.
- 新增身份声明、查验报告、保人、转向的独立虚构对局实验，先区分策略影响，
  再决定是否修改好人推断；不据单一实验宣布平衡或真实模型收益。

- Shared faction inference and public-story aids for offline and model players;
  model decisions remain autonomous. Offline wolves gain consistent claims,
  varied fabricated checks, support and attributed reconsideration.
- 离线与模型玩家共用阵营推断、公开立场辅助；模型仍自主决策。离线狼人新增
  连贯伪装、多样假查验、保人与有来源的转向解释。
- Introduce version and bilingual documentation-impact checks. No numbered
  release is created by this change; `0.1.0-dev` identifies development only.
- 建立版本与双语文档影响检查；本次不创建正式发布，`0.1.0-dev` 仅标记开发状态。

Compatibility / 兼容性: These derived aids add no checkpoint schema fields.
Existing checkpoint validation still applies. / 派生辅助信息不新增存档字段，原有校验仍有效。

Limits / 限制: Heuristics are experimental, not calibrated probabilities or a
balance guarantee. No real-model improvement has been established.
启发式仍属实验，并非校准概率或平衡保证；尚无真实模型收益验证。
