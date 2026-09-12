# Changelog / 更新日志

## Unreleased

No additional changes yet. / 暂无后续变更。

## 0.3.0

### Player experience / 玩家体验

- Redesigned bilingual web game desk, grouped setup, character search and clearer
  connection guidance. Local Agent registration and connection checking are
  separate from starting a game; a connection check makes one model call.
- 重做中英文网页游戏桌面、分组开局、人物搜索与连接引导。本机 Agent 登记、
  连接检查与开局分离；连接检查单独消耗一次模型调用。
- Expand the library to 30 authored personalities with 18 new original portraits.
  Each game still seats 12 distinct characters. Character identity and secret
  game role remain independent; personality inputs affect both supported drivers.
- 人物库扩至三十人，新增十八张原创肖像；每局仍为十二位不同人物，人物与秘密
  身份独立，性格参数接入离线与模型模式。
- Give living human players an optional complete reply before daytime exile
  voting, even after repeated questions. Improve clarification closure, repeated
  dialogue handling, model reply validation and public flipped-Seer evidence.
- 存活真人在白天放逐投票前有一次可跳过的完整回应，不因连续追问耗尽机会。
  同时改进追问收尾、重复台词、模型回应校验与公开预言家翻牌证据保留。

### Delivery / 交付

- Add browser continuation/settlement tests, cross-platform smoke tests, coverage
  reporting, and verified tagged download archives with checksums. Refresh
  bilingual onboarding, support guidance and artwork provenance documentation.
- 新增浏览器续局/结算测试、跨平台检查、覆盖率报告，以及带校验和的标签候选包
  验证流程；同步双语开局、开源支持与素材来源文档。

Compatibility: saved cast mappings remain stable on resume, including original
twelve-character mappings. New character-cast games sample from thirty. Existing
driver/credential checks remain in force. Back up local saves before upgrading;
older versions are not guaranteed to read new character saves. No local settings,
credentials, saves or game transcripts are included in the release package.
兼容性：恢复保留存档人物映射，包含原十二人人物映射；新人物对局从三十人中抽取。
驱动与凭据校验保持。升级前备份本地存档，不保证旧版本读取新人物存档。
发布包不含本地设置、密钥、存档与对局记录。

Limits: experimental local single-player game, not a hosted multiplayer service.
Offline uses authored choices and does not understand arbitrary prose or count
toward campaign scores. Personality differences are not verified balance gains.
No real API/Agent full game was run for this release; browser model tests use
synthetic providers. Artwork licensing is separate from the source-code MIT license.
限制：仍为实验性本机单人游戏，不是托管多人服务。离线使用预设选项，不理解任意
自由文本、不计正式闯关成绩；人格差异不代表已验证的平衡收益。本版未跑真实
API/Agent 整局，浏览器模型测试使用模拟服务。肖像许可独立于代码 MIT 许可。

## 0.2.0

- Offline terminal/Web discussion now starts with contextual responses and
  neutral listening; the full menu remains available under Other responses.
- 离线终端/网页默认显示情境回应与中立过麦；完整菜单保留在“其他说法”。
- Public report/counterclaim reactions depend on personality, without reading
  hidden roles. Natural authored report lines remain auditable; legacy report
  lines remain supported. Existing saves regenerate menus on resume.
- 公开查验/对跳回应受人格影响，不读隐藏身份；自然的固定报告句仍可对账，
  兼容旧标准句。旧存档恢复后重新生成菜单，选项编号可能变化。
- Fixed offline onboarding claiming free-language debate and short Chinese
  listening text being treated as inactivity.
- 修复离线开场误称自然语言辩论，以及中文“先听听”被当作划水。
  随机人格和任意语言理解仍未实现。

Compatibility: no save schema migration. Resumed menus are regenerated and
option numbers may differ; existing mode/credential validation is unchanged.
Older versions do not interpret the new natural report grammar as audit data.
兼容性：无存档格式迁移；恢复时重新生成菜单，编号可能改变，模式/凭据校验不变。
旧版程序不会把新增的自然报告格式解析成对账数据。

Limits: authored offline dialogue, fixed personalities, no arbitrary prose
understanding, no verified balance gains. No real API/Agent full game was run
for this release. Offline remains explicit and excluded from campaign scores.
限制：离线仍为人工编写的对话与固定人格，不理解任意文本，不宣称平衡收益。
本次发布未跑真实 API/Agent 整局；离线需主动选择且不计正式闯关成绩。

## 0.1.0

First numbered experimental release: local single-player campaigns and free
games, model API/user Agent connections, explicit offline choice play, public
spectating, recovery and bilingual guidance. No hosted service is included.
首个编号实验版本：本机单人闯关与自由对局、模型 API/用户 Agent 接入、
显式离线选项玩法、公开旁观、存档恢复及双语引导；不包含托管服务。

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
- Introduce version and bilingual documentation-impact checks, now included
  in this first numbered release.
- 建立版本与双语文档影响检查，并纳入首个编号发布。

Compatibility / 兼容性: These derived aids add no checkpoint schema fields.
Existing checkpoint validation still applies. / 派生辅助信息不新增存档字段，原有校验仍有效。

Limits / 限制: Heuristics are experimental, not calibrated probabilities or a
balance guarantee. No real-model improvement has been established.
启发式仍属实验，并非校准概率或平衡保证；尚无真实模型收益验证。

Release validation uses automated entry/recovery tests and offline fixtures.
No real API/Agent full game was run for this release. Voice and visual gameplay
are not implemented. Existing validation can reject incompatible or damaged
saves; backward reading by older versions is not promised.
本次发布采用自动化入口/恢复测试及离线虚构样例，未执行真实 API/Agent 完整
对局验收。语音和视觉玩法未实现；存档仍接受原有兼容与损坏校验，不保证旧版
程序可读取新版存档。离线模拟不计正式闯关成绩。
