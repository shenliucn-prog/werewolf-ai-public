# Play inside your own Agent / 在自己的 Agent 里玩

## English

The recommended player experience is conversation with your own Agent. The player should not need to type terminal commands: the Agent relays the real game and submits the player's choices. The browser is optional.

### What exists today

- `werewolf_web.chat_game` is an interactive stdin/stdout adapter over the same `GameSession` used by the browser.
- A local Agent with command execution and a persistent interactive process can act as its relay. Start it unbuffered with `python -u -m werewolf_web.chat_game --board classic --lang en --offline` after following the README setup. Use a PTY/session handle when the Agent's tools require one for ongoing input.
- This repository does **not** yet ship a universal Agent plugin, MCP server, installable host-specific integration or a resumable session protocol. Compatibility with arbitrary Agent hosts has not been established. A chat-only Agent without local tools cannot run the game this way.
- `--offline` disables the game's optional model service, not the hosting Agent's own model usage, subscription requirements or charges.

### Relay contract

During play use `/seats`, `/history`, `latest votes` or `day 2 speeches` to
retrieve public records without advancing the pending action. Natural queries
go through the host (`?Show the last ballots`). Always render the returned
statements verbatim. Exile voting accepts `peaceful day`; the post-speech
election window accepts `withdraw` or `stay`. These are explicit decisions,
never inferred from a rules question. A declined table reply is silent.

First-time users should fork/clone locally and run `python -m werewolf_web.setup --lang en`.
Use `--check` for an environment-only check. The wizard explains the
Agent/browser choices, costs and settings, then launches the selected interface.
When the user's choices are already known, the direct chat command remains valid.
Both player interfaces now pause before night one: show the complete host rules
and seats, answer questions, and submit `ready` only after the player confirms.
Do not claim to restore a terminated process: only an already live session can
continue. Read the repository's `AGENTS.md` for the complete relay obligations.

1. Read the README, prepare only this project's local environment and launch one real game process. Keep that process and its input session alive across user turns; do not launch a new game for every message.
2. Relay the public statements and only the private prompts actually emitted for this player. Preserve seat numbers, claims, timing and uncertainty. Do not inspect engine memory, hidden role allocations, private NPC state or developer-observer output to gain extra information.
3. When the game requests a decision, wait for the player. Convert their explicit choice into the supported input vocabulary. Ask if ambiguous; do not silently choose targets, alter a statement or autoplay.
4. Send rules questions with `?` at an action prompt. Relay the host's answer and keep waiting for the same decision. Conjecture private/public tables must remain separate; edits to a public table require the player's intent.
5. The local game engine decides legality and outcomes. Do not invent events, simulate the rest of a stalled game or present an Agent-written story as an actual engine result.
6. If the host cannot maintain the interactive process, say so. If it loses that process, there is no supported resume or browser transfer. Offer a new game or the optional browser, clearly describing the limitation.

The terminal parser recognizes a limited action vocabulary; the Agent supplies the conversational relay. Native integrations can be built around the shared session later, but must preserve the same information boundaries and be tested independently.

## 中文

推荐的是**玩家在自己的 Agent 对话里游玩**，不是要求玩家在终端敲命令。Agent 负责连接游戏、转述发言与提示、提交玩家决定；网页版只是可选界面。

目前的 `chat_game` 是和网页共用 `GameSession` 的终端桥接入口。有本地命令执行能力、能持续保留交互进程的 Agent 可以转接它：按 README 安装后，运行 `python -u -m werewolf_web.chat_game --board classic --lang zh-CN --offline`，跨对话轮次保留同一个输入会话。宿主工具需要时使用 PTY。

**尚无通用 Agent 插件、MCP 服务、各宿主的一键安装适配或断线续局协议；未验证所有 Agent 产品。** 没有本地工具的纯聊天 Agent 无法按此方式运行。`--offline` 只关闭游戏自身的模型调用，不免除宿主 Agent 的使用成本。

转接时必须：

- 局中可查 `座次`、`上一轮票型`、`第2天发言记录`、`公开记录`；自然语言查询
  用 `?把上一轮的票型拿出来`。查询不推进当前行动，记录逐条原样展示。
- 放逐可投 `平安日`；警上发言结束后可选 `退警` 或 `不退警`。必须由玩家
  明确决定，不能把询问规则当成提交行动。玩家暂不回应时保持沉默。

- 首次使用先 fork/clone 到本地，运行 `python -m werewolf_web.setup --lang zh-CN`；
  `--check` 仅检查环境。引导解释入口、费用和设置，然后启动所选界面。
- 文字与网页均在首夜前等待确认。完整展示主持人介绍、座次和规则；回答问题后，
  只有玩家明确准备好才提交“开始”。已知配置可直接运行原有 chat 命令。
- 逐条原样展示公开发言，带座位和名字。摘要不能代替原话；不得编造 NPC 准备回应，
  不得把含糊的“昨晚验过”解释成已经确认的重复查验。参见仓库 `AGENTS.md`。

- 只展示实际进程输出的公开信息和属于该玩家的私密信息；不查看隐藏身份、NPC 私有状态、引擎内存或全知观察器输出来作弊。
- 等待玩家明确决定；不代打、不擅自选目标或改发言。有歧义就问清楚。
- 用 `?问题` 询问游戏主持人，不消耗当前行动。猜想模式的私有表和公开表分开，公开内容须符合玩家意图。
- 让规则引擎判定结果，不编造进程没有产生的事件。保持同一交互进程；进程丢失时明确说明不能续局，不用模拟故事冒充恢复。

下一步原生接入应围绕共用会话实现，并单独验证宿主兼容性、跨轮次状态和信息边界；本文说明的是当前可用桥接方式及其限制，不代表这些原生适配已经完成。
