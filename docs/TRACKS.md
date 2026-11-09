# Workstreams / 工作流

This project is one repository with several distinct workstreams. A **track** is a
scope boundary for planning and review — not a separate repository, branch or
Cowork project. One Cowork project, one working folder and one memory remain the
source of truth.

本项目是一个仓库、多条工作流。**Track（工作流）** 是规划与评审的范围边界，不是独立
仓库、长期分支或新的 Cowork 项目；仍然只有一个 Cowork 项目、一个工作目录、一份记忆。

## Principles / 原则

- One Cowork project; one named chat session per track for dive-in.
- A track owns **modules**, not files exclusively. Shared contract files require a
  contract note in the PR (see below).
- Every task is a short-lived branch off `master` and one pull request. No
  long-lived track branches.
- Because both agents share one folder, they **serialize**. True parallel work
  needs a second clone, never a second Cowork project.
- CI, the delivery gate and the PR review are the coordination mechanism. There
  is no orchestrator agent.

一个 Cowork 项目；每个 track 一个命名会话便于随时进入。Track 拥有的是模块而非排他文件。
任务一律从 `master` 开短分支、一个 PR；不设长期 track 分支。共享目录意味着两个 Agent
轮流作业；要真并行就另开克隆，而不是另开 Cowork 项目。协调靠 CI、交付门禁与 PR 评审，
不设编排 Agent。

## Tracks / 工作流

| Track | Scope | Main modules | Validation | Branch prefix |
| --- | --- | --- | --- | --- |
| **Offline intelligence** | authored dialogue, social actions, personas, reply menus | `offline_*.py`, `social_actions.py`, `speech_targets.py` | `test_offline_*`, `test_social_actions`, `test_dialogue_ablation` | `feat/offline-` |
| **Onboarding** | first-run, connection setup, entry paths | `onboarding.py`, `connection_setup.py`, `setup.py`, `chat_game.py`, `cli_game.py` | `test_onboarding`, `test_chat_game`, `test_chat_persistence`, `test_api_contract` | `feat/onboarding-` |
| **Design / UX** | web desk, roundtable, i18n copy, portraits | `static/*.js`, `i18n.py`, `static/js/i18n.js`, character assets | `test_roundtable_flow`, `test_ux_closure`, `test_playable_locales`, `test_i18n` | `feat/design-` |
| **Model / conversation** | prompts, context budget, stance continuity, night audit, claim evidence | `ai/*`, `conversation.py`, `observations.py`, `night_review.py`, `check_claims.py` | `test_model_*`, `test_table_*`, `test_dialogue_*`, `test_night_review` | `feat/model-` |
| **Campaign / rules** | boards, roles, progression, settlement | `game/`, `casting.py`, `characters.py`, `character_*.py`, `campaign*.py`, `actions.py`, `participants.py` | `test_engine`, `test_special_roles`, `test_campaign_*`, `test_casting`, `test_role_selection` | `feat/rules-` |
| **Platform / delivery** | CI, release, recovery, drivers, perf | `scripts/`, `.github/`, `checkpoint.py`, `recovery.py`, `restore_coordinator.py`, `session_codec.py`, `driver.py`, `perf.py`, `lifecycle.py` | `test_delivery`, `test_release_*`, `test_checkpoint`, `test_recovery*`, `test_driver`, `test_perf` | `chore/platform-` |

### Non-goals / 非目标

- **Offline intelligence**: model-provider behavior, campaign scoring.
- **Onboarding**: web-desk visual design (Design track), game rules.
- **Design / UX**: rules and settlement, driver internals.
- **Model / conversation**: provider adapters (Platform), UI layout.
- **Campaign / rules**: teaching copy and entry flow (Onboarding), prompt wording.
- **Platform / delivery**: gameplay behavior and balance.

## Contract files / 契约文件

These are shared by most tracks. A PR that changes them must state the affected
tracks and why the change is safe for each:

- `werewolf_web/session.py` — session orchestration, step machine, event order.
- `werewolf_web/game/engine.py` — rules and settlement.
- `werewolf_web/i18n.py` and `werewolf_web/static/js/i18n.js` — shared strings.
- `werewolf_web/public_record.py` — public observation format.

以下文件由多条工作流共享。改动它们时，PR 必须写明影响哪些 track，以及为何对每条 track
安全：`session.py`、`game/engine.py`、`i18n.py`/`static/js/i18n.py`、`public_record.py`。

## Operating model / 运作方式

1. **One agent per track at a time.** Claude and ChatGPT are assigned tracks, but
   the shared folder serializes edits. Do not work simultaneously.
2. **Dive-in:** each track has a named chat session (e.g. “offline intelligence”,
   “onboarding”). Its transcript, branch and PR are the audit trail.
3. **Integration:** one PR per task; merge after required checks. A weekly
   15-minute integration pass rebases open PRs and merges them in dependency
   order (Platform → Rules → Model → Offline/Onboarding/Design).
4. **Progress view:** the COS status artifact (open PRs, checks, track labels)
   plus GitHub labels/milestones. No separate Cowork projects.

1. **同一时间一个 Agent 一条 track**；共享目录决定必须轮流。2. **随时进入**：每条 track
一个命名会话，会话记录、分支和 PR 就是审计轨迹。3. **集成**：一任务一 PR，检查通过再
合并；每周一次集成检查按依赖顺序（平台 → 规则 → 模型 → 离线/接入/设计）合并。4. **进度**
看 COS 状态页、PR 与标签/里程碑，不另开 Cowork 项目。

## COS duties / 主控职责

The COS is a role, not an extra agent:

- own `docs/TRACKS.md`, labels and milestones;
- triage open PRs (including dependency PRs) and flag blockers;
- review contract-file changes for cross-track impact;
- keep the status artifact and weekly brief current;
- do not implement code unless explicitly asked.

COS 是角色而非额外 Agent：维护本文件、标签与里程碑；分诊 PR 与依赖更新、标记阻塞；审查
契约文件改动；维护状态页与周报；除非明确要求，不直接写代码。

## Definition of done / 完成标准

A task is done when: relevant tests pass, `npm test` and the delivery gates pass,
the `.changes` record and affected docs are updated, the PR is merged, and any
real-model claim is backed by recorded evidence (mock tests are not evidence).

任务完成的标准：相关测试通过，`npm test` 与交付门禁通过，`.changes` 记录和受影响文档
已更新，PR 已合并；任何真实模型结论都必须有可核对的证据，模拟测试不算证据。
