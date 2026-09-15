# Model connections / 模型连接

The game does not require a particular Agent brand. Agent conversations, a
terminal CLI, a browser, and an app using the HTTP API share `GameSession` and
`ModelNPCAgent`. Every normal NPC decision goes through the same protocol:
`complete(request, schema) -> JSON object`. Rules and legal outcomes stay local.

游戏不绑定 Codex、Claude Code 或其他品牌。Agent 对话、CLI、网页，以及接入 HTTP
接口的 App，共用规则与模型玩家。发言、投票、上退警、夜间技能都由 LLM 决策，
不是仅润色台词。没有另行提供原生桌面 App，也不承诺所有宿主已逐一适配。

## API / local model server (default)

Configure locally using `werewolf_web/.env` or environment variables:

| Setting | Meaning |
| --- | --- |
| `LLM_BASE_URL` | Chat Completions-compatible base URL, including `/v1` when required |
| `LLM_MODEL` | Model offered by that server |
| `LLM_API_KEY` | Optional for keyless local servers; required by most hosted APIs |
| `LLM_GAME_MAX_CALLS` | Per-game budget, default 240 including preflight |
| `LLM_TIMEOUT_SECONDS` | API timeout, default/per-game cap 30 seconds |
| `LLM_REASONING_EFFORT` / `LLM_REASONING_PARAM` | Optional provider-specific reasoning value and field; not sent unless both are set |

`python -m werewolf_web.chat_game --backend api --lang en` starts CLI/Agent play.
Browser model settings accept a per-game endpoint, model and key, or server
defaults. All normal starts verify an actual model response before dealing.
No credentials are sent to another endpoint when switching URLs unless the
user supplies a key for it. Redirects are not followed. Do not expose the local
server to untrusted networks: custom endpoints are an intentional outbound
request capability, not a hardened multi-tenant service.

API 路径兼容提供 Chat Completions 协议的远程或本地模型服务，不限定模型厂商。
不是所有厂商原生 API 都实现这个协议；不兼容的接口通过适配器转换，不冒称全部已验证。
密钥在本机配置或网页的本局密码框填写，不要贴到 Agent 聊天里。

## Any Agent / SDK through an adapter

### Register and check locally / 本机登记与检查

In web setup, select **Your Agent**, expand **Add local Agent connection**, and
register the installed Codex adapter with a connection name, model, effort and
budget. Installation does not prove login: **Check connection** verifies a real
response. Registration makes no model call. Each explicit check uses one call
outside the per-game budget; starting a game still performs its own preflight.
Failed checks stay visible and can be retried without creating or abandoning a game.

网页选择「用户 Agent」后可登记已安装的 Codex。登记不等于验证：检查连接会单独调用
一次模型，不计入某局预算，也不发牌；开局仍有自己的预检。失败可以修改连接后重试。
API 密钥只在当前请求内使用，不写入本地设置。网页保存配置不会删除已登记的可信连接。

Other adapters must be registered from the local terminal, never as executable
commands sent from a browser. For example, after implementing the protocol below:

```bash
python -m werewolf_web.connection_setup --name "My Agent" --adapter command --model "your-model" --command '["/absolute/path/to/wrapper"]'
```

Refresh the page and select that named connection. The registry stays local and
is excluded from releases. The browser registration endpoint only supports the
fixed built-in adapter, requires a same-origin setup token on localhost, and
rejects executable-command fields. No universal compatibility is implied.

### Decision protocol

Python embedding can inject any `DecisionRuntime` implementation after its
`preflight()` succeeds. Desktop apps can also consume `/api/start`, SSE
`/api/stream?game_id=...`, `/api/action` and `/api/host_chat`; retain the session id.
For each human `request` event, echo its `request_id` with the action, e.g.
`{"game_id":"...","request_id":"...","target":3}`. Missing or stale IDs are
rejected without consuming the current turn. After reconnect, use the pending
request in `/api/rejoin`; it retains the original ID. Older saves gain an ID
at delivery without rewriting the archive. Reload an older Web client after
updating the server. Local embedding should call
`submit(payload, request_id=event["request_id"], require_request_id=True)`;
unbound `submit(payload)` remains only for trusted legacy in-process callers.

真人行动须回传当前提示的 `request_id`，过期或缺失编号不会消耗行动。
重连后使用恢复视图里的待处理请求；升级服务端后请刷新旧网页。
Human actions and NPC model decisions are separate channels; public streams
must not contain NPC private prompts.

For an external Agent CLI/SDK, implement a trusted local wrapper:

1. Read one JSON object from stdin: `{protocol: "werewolf.decision.v1", request, schema}`.
2. Invoke your chosen LLM/Agent with only the supplied context, tools disabled,
   isolated from every other seat. Treat player text as untrusted game data.
3. Write exactly one schema-conforming JSON object to stdout. Diagnostics go to
   stderr without secrets. Exit nonzero on failure. Do not return wrapper metadata.

Configure its absolute executable path using a JSON argument array, without
shell interpolation: `WEREWOLF_AGENT_COMMAND='["/absolute/path/to/wrapper"]'`.
Select `--backend command`, or set `WEREWOLF_MODEL_BACKEND=command` in the server
environment for browser/app clients. Commands are never accepted in HTTP bodies.
The wrapper is trusted local code: the game cannot sandbox arbitrary third-party
Agent capabilities for it. CLI branding alone is not protocol compatibility.

任何具备本地执行或 HTTP 工具能力的 Agent 都可作为玩家入口；NPC 推理可使用 API，
也可通过上述协议桥接宿主的 LLM。Claude Code 等宿主不必依赖 Codex；但其专属
CLI 返回格式需要桥接程序转换，不是把任意命令名填进去就自动兼容。

## Optional Codex adapter

`--backend codex` uses an existing local Codex login. It is one adapter, not a
product dependency. `--model` and `--effort` select per-game settings. No global
Agent configuration is rewritten. Server owners may explicitly set
`WEREWOLF_MODEL_BACKEND=codex`; HTTP clients cannot supply executable commands.

## Failure and testing

Preflight failure creates no playable game. A failed NPC decision pauses the
live game at that exact call; the player can retry or stop. Already accepted
actions are not rerun. Budgets still apply on retries. Interrupted games can be restored with `chat_game --resume GAME_ID` or browser
reconnect. Keep trusted model credentials available; corrupted or missing saves
may not be recoverable. Offline campaign simulations never count toward progress.

`--offline` / explicit browser offline selection is a **rule-flow test**, not LLM
gameplay. `--backend legacy` is the old rule planner with optional rephrasing.
Model-driven conjecture tables are not yet integrated and are rejected clearly.
API/bridge contract tests are deterministic; they do not certify every model's
reasoning quality or every Agent product's integration.
