# Agent-neutral development / 跨 Agent 开发

## One policy / 一份规则

Open the public repository root in your coding tool. [AGENTS.md](../AGENTS.md)
is the canonical policy. Codex and Cursor can read it directly. Claude Code
loads [CLAUDE.md](../CLAUDE.md), which imports it with `@AGENTS.md`.
The Cursor always-applied project rule points to the same policy. These are
repository files, not global preferences or model-routing changes. Other
agents should explicitly read AGENTS.md and [CONTRIBUTING.md](../CONTRIBUTING.md).

用 Cursor、Claude Code、Codex 或其他工具打开本仓库根目录，遵循同一份 AGENTS.md。
Claude Code 通过 CLAUDE.md 导入；Cursor 项目规则引用同一文件，不另存一套要求。
无需安装 Codex、修改全局设置或绑定特定模型；其他工具可显式读取上述文档。

These entry files follow the documented [Claude Code imports](https://code.claude.com/docs/en/memory)
and [Cursor rules](https://cursor.com/docs/context/rules). File wiring and
repository tests do not prove every installed editor version loads them:
check the host's active project instructions on first use.

首次使用请在宿主中确认项目规则已加载。文件配置与自动测试不等于已实测每个编辑器版本。

## Dependency PRs / 依赖维护

1. Inspect the actual diff and current base, not just the bot title. If two
   PRs change the same manifest to the same version, retain one, link the
   duplicate and close it only within the user's authorized scope. Root pip
   scanning excludes `werewolf_web/**`; that runtime has a dedicated entry.
2. Read failed *steps*. The delivery gate requires a **new** bilingual
   `.changes/<unique-name>.json` for each PR, including bot PRs. Do not weaken
   the gate or reuse an old record. See [the schema](RELEASING.md).
3. Write a factual summary and save/config compatibility statement. A pure
   dependency update may use `docs_impact: none`, `docs: []`, with a concrete
   reason after checking the affected guides. Changed behavior requires docs.
4. Follow the standard virtual-environment setup in the README. Install the
   exact candidate requirements, then run the commands below from the root.
5. Set the actual assignee, type and area labels. Leave the milestone empty
   for unscheduled maintenance. Record self-review and limits honestly; tests
   do not constitute another person's approval. Merge only with user authority
   and passing required checks on the current head. Release is a separate action.

先比对实际 diff 去重，再读具体失败步骤。机器人也要新增双语变更记录，说明存档、配置
与文档影响，不跳过交付门槛。只升级内部依赖可说明为何无需修改用户指南；行为变化则同步
改文档。补齐真实负责人和标签，不虚构排期或独立审查；用户授权且最新检查通过后才合并。

```bash
python -m pip install -r werewolf_web/requirements.txt -r requirements-test.txt
python -m unittest discover -s tests -q
npm ci
npm test
npm run check
python scripts/check_release.py
python scripts/check_delivery.py --base HEAD
git diff --check
```

Before committing, `--base HEAD` includes working changes. After committing,
use the actual PR base commit instead. CI tests Python 3.10, 3.12 and 3.13
without cancelling sibling versions on the first failure, plus macOS/Windows
smoke tests, Chromium entry checks, coverage and a dependency audit. CI does
not invoke a live model. Use an isolated environment with no real credentials.

提交前用 HEAD 检查工作区；提交后改用 PR 实际基线提交。CI 不再因一个 Python 版本失败
取消其他版本；另外保留跨平台、浏览器、覆盖率及依赖审计。测试环境不放真实密钥。

## Editor support versus NPC integration / 编辑器与 NPC 接入

The coding host can maintain or relay this game without being the NPC runtime.
API and trusted command adapters use the existing `werewolf.decision.v1`
contract. Cursor/Claude Code CLI output is **not** automatically this protocol;
a trusted wrapper must implement it, isolate each seat and disable tools.
See [model connections](MODEL_CONNECTIONS.md). No new vendor adapter is added
by these instruction files. Do not silently substitute offline NPCs.

兼容 Cursor、Claude Code 的开发协作，不代表它们的模型自动成为 NPC。现有 API／可信命令
适配器仍走同一协议；直接填写任意 CLI 名称不保证可用，须有包装器并通过预检。此次未新增
厂商专属运行时，不修改存档、配置格式、模型选择或失败暂停机制。

When handing work to another agent, record the repository, branch, base/head
commits, PR number, changed files, checks/results and outstanding work in the
PR description. Exclude keys, local paths, private saves and match transcripts.
Keep the existing game/session ID when relaying play; never start a replacement
game just because the host changes. Resume rules remain in AGENTS.md.

跨 Agent 交接写清仓库、分支、基线与当前提交、PR、修改、检查结果和待办，不传密钥或私有
存档。转述对局时保持原有会话，不因换工具重新开局；恢复流程仍遵循 AGENTS.md。
