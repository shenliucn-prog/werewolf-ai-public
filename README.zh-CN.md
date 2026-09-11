# Werewolf AI

[English](README.md) | 简体中文

<!-- version: 0.1.0-dev -->

离线与模型玩家共用[查验声明对账](docs/CHECK_CLAIMS.md)：将预言家声明的矛盾
关联到公开记录，不认证任何人的身份；自由文本不会被自动判定为查验声明。
当前开发版本：**0.1.0-dev**（尚非正式发布）。
参见[更新日志](CHANGELOG.md)与[版本发布流程](docs/RELEASING.md)。

当前开发版加入两种模式共用的实验性阵营推断、公开立场辅助。离线狼人可维持
伪装、使用不同的假查验、保人，并引用归属明确的声明解释重新考虑。模型只接收
可选辅助，仍自主决策。这些启发式不是已验证身份，也不保证平衡或真实模型收益。
参见[范围与限制](docs/JOINT_BELIEF_PROTOTYPE.md)。
重复发言不再成倍增加翻牌后的奖励或惩罚；放逐记账只计当日不重复的投票人。
旧存档恢复保留已有累计分，不追溯修正；完整评估此项变化应新开一局。
中英文对局中，公开翻牌的预言家发言会进入有上限的模型上下文保留区；
角色翻牌并不代表其每条查验声明都自动得到证实。

本机运行的单人狼人杀：你占一个座位，与 11 个 AI 对手对局。
**正式游玩必须连接模型 API，或通过受支持的适配器连接自己的 Agent。**
模型负责 NPC 发言和行动，Python 后端负责规则、结算与存档；网页只是可选界面，不是纯前端游戏。

推荐在自己的 Agent 对话里玩。Agent 需要能运行并保持本地交互进程。
**Agent 帮你转述，不等于它的模型已经接入 NPC**，仍需完成模型连接配置。
目前没有通用 Agent 插件，也没有单独的原生 App。

## 选择玩法

| 入口 | 功能 |
| --- | --- |
| 开始闯关 | 从平民开始，在固定板子的 16 个角色关卡中逐关获胜解锁。阵营获胜即可，不要求本人存活。 |
| 自由对局 | 选择板子、自己的身份或随机身份、NPC 名字，以及固定／随机人格。 |
| 继续游戏 | 从存档恢复中断的对局，不必重新开局。 |

输局可重试；平局计尝试但不解锁；主动放弃已开始的局计一次未胜。
模型故障会暂停，不会静默改用程序策略代打。角色教学和失败后的短复盘由模型生成，失败可重试。

**离线模拟必须主动选择，仅用于体验流程和测试，不调用模型、不计正式闯关成绩。**

另有独立的**离线选项局**：`python -m werewolf_web.offline_game`。
提供 12 个固定人格、替代角色、公共旁观与本地续存；不理解自由输入、不计闯关成绩。
使用方法及限制见[离线玩法](docs/OFFLINE_GAME.md)。

**对局驱动。** NPC 决策使用三种驱动之一：`api`（模型 API，含无密钥本地服务）、
`agent`（你自己的 Agent，其中 `command`／`codex` 是第二层适配器）或 `offline`。
配置按 请求 > 本地已存设置 > 环境 的顺序解析；没有任何可用配置时，会明确报告
“未配置”，而不是静默切到离线或退回一个不可用的 API 连接。

## 快速开始

需要 Python 3.10 或更新版本。想修改游戏，建议先 fork 再克隆自己的仓库；
只想试玩，也可直接克隆上游。以下命令均在仓库根目录运行。

```bash
git clone https://github.com/shenliucn-prog/werewolf-ai-public.git
cd werewolf-ai-public
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r werewolf_web/requirements.txt
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活环境。

### 1. 连接模型

任选一种：

- **API／本地模型服务**：复制 `werewolf_web/.env.example` 为
  `werewolf_web/.env`，设置 `LLM_BASE_URL`、`LLM_MODEL` 和服务要求的
  `LLM_API_KEY`。接口须兼容 OpenAI Chat Completions，支持无密钥的本地服务。
- **自己的 Agent**：配置符合[决策协议](docs/MODEL_CONNECTIONS.md)的本地桥接程序，
  选择 `--backend command`。任意 Agent 命令并不会自动兼容协议。
- **可选 Codex 适配器**：已有本地 Codex 登录时，可选 `--backend codex`。
  Codex 不是项目依赖。

发牌前会验证一次真实模型响应。默认调用预算为 240 次，API 用户可设置
`LLM_GAME_MAX_CALLS`。实际请求模型的重试、教学和短复盘也耗调用额度，教学缓存命中不耗调用。
调用上限不等于费用上限，实际收费由服务方决定。推理强度参数仅在服务支持时配置。
完整设置见[模型连接指南](docs/MODEL_CONNECTIONS.md)。

需要环境引导可运行 `python -m werewolf_web.setup --lang zh-CN`；
加 `--check` 则只检查环境。

### 2. 开局或续玩

让自己的 Agent 阅读 [Agent 游玩说明](docs/AGENT_PLAY.md)，运行游戏并转述真实对局，
不要替你决策。也可以自己操作终端：

```bash
# 闯关：当前解锁的角色
python -u -m werewolf_web.chat_game --campaign --lang zh-CN

# 自由对局：先选板子
python -u -m werewolf_web.chat_game --lang zh-CN

# 自由对局：指定板子和身份
python -u -m werewolf_web.chat_game --board classic --role seer --lang zh-CN

# 恢复：将 GAME_ID 替换为存档对局编号
python -u -m werewolf_web.chat_game --resume GAME_ID --lang zh-CN
```

闯关默认档案是 `default`，可用 `--profile NAME` 指定其他本地档案。
完成一关后再次进入闯关入口。闯关开局可复用保存的非敏感模型设置；
恢复时仍需在可信本地配置中提供凭据。

想用网页则运行：

```bash
python -m uvicorn werewolf_web.run:app --host 127.0.0.1 --port 8000
```

打开 [localhost:8000](http://127.0.0.1:8000)，选择语言、配置模型，
再选“开始闯关／自由对局／继续游戏”。
网页填写的密钥传给本机 Python 后端用于连接模型，不写入设置文件。

### 3. 发言、行动和问规则

主持人先介绍规则与座次。询问不懂的地方，确认“开始”后再进入第一夜。

| 终端等待行动时 | 输入 |
| --- | --- |
| 发言 | 直接输入发言内容 |
| 查看座次／公开历史 | `座次`／`公开记录` |
| 问规则，不消耗行动 | `?女巫怎么用药？` |
| 投票／选择目标 | `vote 3`／`choose 3` |
| 跳过可选行动 | `pass` |
| 重试闯关角色教学 | `/teaching` 或 `教学` |
| 赛后提示中重试短复盘 | `/review` 或 `复盘` |

合法选项以当时提示为准。终端解析的是明确指令，不是通用自然语言；
Agent 可以转译你的选择，但不能编造事件、偷看 NPC 隐藏状态。
完整操作见[玩家指南](docs/PLAYER_GUIDE.md)。

## 模式与限制

- **当前仅文字驱动**：支持中英文名字、对话和提示。语音与视觉玩法尚无方案或实现，头像只是装饰。
- **默认自然语言辩论**：模型玩家猜想表尚未接通；猜想模式仅用于明确选择的旧后端／离线研究玩法。
- **共十种板子**：建议从 classic 开始。神女巫和极端人格属于实验，不宣称已经平衡。
- **本地实验原型**：自动化测试不等于所有服务商和 Agent 都已验证。真实 API／Agent 完整闯关实测仍是发布验收待办；不承诺公平排行榜或防作弊。

详见[游戏模式](docs/GAME_MODES.md)、[神女巫](docs/DIVINE_WITCH.md)、
[项目规则](docs/RULE_VARIANT.md)和[已知限制](docs/KNOWN_LIMITATIONS.md)。

## 存档与隐私

检查点、闯关档案、本地设置、教学缓存和运行记忆保存在 `werewolf_web/data/`，
由 Git 忽略并从发布导出中排除。
**对局检查点含隐藏身份和 NPC 私有状态，请勿公开或用于作弊。**
设置和检查点不保存密钥；恢复模型对局时需重新验证可信连接。
存档缺失或损坏时不保证能恢复。

网页重连与终端 `--resume GAME_ID` 使用已保存会话，不要同时用两个界面操控同一局。
新正式对局不会自动继承上一局 NPC 的记忆。

模型服务会收到行动 NPC 有权使用的上下文，包括你的发言及该 NPC 的私密信息；
不要在游戏聊天中输入真实敏感资料。后端没有用户账号体系，也不是加固后的公网多人服务，
请只在本机运行。参见[安全说明](SECURITY.md)。

## 给修改项目的人

| 位置 | 职责 |
| --- | --- |
| `werewolf_web/session.py` | 共用会话、事件流程与恢复 |
| `werewolf_web/run.py`、`chat_game.py` | 网页和终端适配 |
| `werewolf_web/game/` | 确定性规则与胜负 |
| `werewolf_web/ai/model_player.py`、`ai/decision_runtime.py` | 模型决策与 API／Agent 适配 |
| `werewolf_web/ai/model_context.py` | 有界模型请求；完整记录仍留在存档 |
| `werewolf_web/campaign*.py` | 关卡、成绩、教学和短复盘 |
| `werewolf_web/static/`、`i18n.py` | 网页呈现与本地化 |

旧 Brain／研究工具与正式模型决策路径分开。`cli_game.py` 是可看全身份的开发观察工具，
**不是玩家入口**。人格文件的中文标题参与解析，不要直接当普通文档翻译。

```bash
python -m unittest discover -s tests -q
npm ci
npm test
node --check werewolf_web/static/js/app.js
node --check werewolf_web/static/js/i18n.js
python scripts/check_release.py
```

Node.js 24.15+（24.x）只用于开发测试；玩游戏不需要 npm 构建。
修改前请读[贡献指南](CONTRIBUTING.md)和[架构与扩展方法](docs/ARCHITECTURE.md)。
研究方案和设计草案不代表所有设想都已实现。

## 许可

代码采用 [MIT](LICENSE)。AI 生成头像已获授权用于本项目和仓库分发，
但**不属于 MIT 许可范围**，其他用途需单独获得许可。参见[素材说明](docs/ASSETS.md)。
