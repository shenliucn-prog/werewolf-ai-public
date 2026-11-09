# Multi-agent collaboration: Claude + ChatGPT / 多 Agent 协作

This file adds a **sync-first** operating agreement for two coding agents
(Claude and ChatGPT) that share this one working directory and one branch.
All existing rules in [AGENTS.md](../AGENTS.md), [CONTRIBUTING.md](../CONTRIBUTING.md)
and [AGENT_DEVELOPMENT.md](AGENT_DEVELOPMENT.md) still apply; this file only
adds the shared-folder discipline.

本文件为共享同一目录与分支的两个编码 Agent（Claude 与 ChatGPT）补充「先同步后开工」
的协作约定。AGENTS.md、CONTRIBUTING.md、AGENT_DEVELOPMENT.md 的既有规则全部继续生效，
本文件只补充共享目录下的纪律。

## One repo, one folder / 一个仓库、一个目录

- Canonical working directory: the single repository root opened by both
  agents (no second clone).
- Canonical remote: `origin` (the public repo). `origin/master` is the source of truth.
- Both agents open this same folder. There is no second clone and no per-agent branch.

共享目录固定为同一个仓库根目录，两个 Agent 都直接打开它，不另建克隆，也不各开分支；
远端为 `origin`，以 `origin/master` 为准。

## Branch and PR are mandatory / 必须走分支与 PR

`master` is protected: direct pushes are rejected and required checks must pass.
Never push to `master`. Every task gets a short-lived branch:

```bash
git fetch origin
git switch master && git merge --ff-only origin/master
git switch -c feat/<topic>        # or fix/<topic>, docs/<topic>
# work, commit...
git push -u origin feat/<topic>
```

Then open a pull request and let CI run. Merge only after the required checks
pass, with the user's authority. After merging, return to `master` and
fast-forward again.

`master` 是受保护分支：直接推送会被拒绝，且必须通过必需检查。任何任务都先开短分支，
推送分支后开 PR，检查通过并由用户授权后再合并；合并后回到 `master` 再次快进。

## Sync-first protocol / 先同步后开工

**Before starting any work** — run these and read the output:

```bash
git fetch origin
git status -sb          # must be clean; must not show "ahead/behind" divergence
git merge --ff-only origin/master   # if behind, fast-forward; never a merge commit
```

If `git status` shows uncommitted changes, or the branch has *diverged*
(`ahead N, behind M`), **stop and coordinate with the other agent first**.
Never force or reset over another agent's state.

**开工前** 依次执行并确认：`git fetch origin`、`git status -sb`（必须干净、无分叉）、
必要时 `git merge --ff-only origin/master`。若存在未提交改动或分支已分叉，先与对方
沟通，不要强推或重置。

**Do the work**, then run the standard gates from `AGENT_DEVELOPMENT.md`
(`python -m unittest discover -s tests -q`, `npm test`, `npm run check`,
`check_release.py`, `check_delivery.py --base HEAD`, `git diff --check`).

**Before finishing / committing:**

```bash
git fetch origin
git merge --ff-only origin/master   # re-sync if the other agent pushed meanwhile
# commit (with a new .changes/<name>.json per the delivery gate), then:
git push
```

完成修改后，提交前再次 `git fetch origin` 并 `--ff-only` 快进，避免覆盖对方刚推送的
提交；按交付门槛新增 `.changes` 记录后再 `git push`。

## Turn-taking / 轮流作业

Sharing one folder means the two agents **take turns editing files**, not work
simultaneously in the same checkout:

1. Agent A syncs master → creates a task branch → works → commits → pushes the
   branch → opens a PR.
2. Agent B syncs master (fast-forward) → creates its own task branch → works →
   commits → pushes → opens a PR.
3. Each PR merges independently once its checks pass.

Do not leave uncommitted changes sitting in the shared folder — they block the
other agent's fast-forward and will produce conflicts. Do not have both agents
on the same task branch at the same time.

同一目录意味着两个 Agent **轮流编辑同一工作区**，不要同时开工：一方同步 master、
开任务分支、修改、提交、推送分支并开 PR；另一方快进 master 后开自己的分支。不要在工作
目录里留未提交改动，也不要两人同时操作同一个任务分支。

If genuinely parallel work is needed, use separate branches (and ideally separate
clones) and follow the handoff rules in `AGENT_DEVELOPMENT.md`; the shared folder
still forces turn-taking at the file level.

若确实需要并行，使用各自的分支（最好各自克隆），并按 AGENT_DEVELOPMENT.md 的交接
要求记录分支、基线/头提交、PR、改动与检查结果；共享目录仍要求文件层面的轮流作业。

## Never do / 禁止项

- Push directly to `master` — it is protected and requires a pull request with
  passing required checks.
- `git reset --hard` — only when explicitly re-syncing a known-stale checkout to
  `origin/master` (fetch first, then reset, so nothing is invented).
- Force-push, or amend/rewrite already-pushed commits (this created the earlier
  divergence).
- `git pull` (merge) that can create a merge commit on a diverged history — use
  `git merge --ff-only` so history stays linear.
- Start work without `git fetch` + `git status` first.
- Work on a dirty tree, or commit over another agent's uncommitted changes.

禁止：直接向 `master` 推送（受保护分支，必须走 PR 并通过必需检查）；随意
`git reset --hard`（仅当明确要把已过期的本地副本重新同步到 origin/master 时才用，且先
fetch）；强推或改写已推送提交；用可能产生合并提交的 `git pull`（改用 `--ff-only` 保持
线性历史）；不先 fetch/status 就开工；在脏工作区上作业或覆盖对方未提交的改动。

## Handoff / 交接

When passing work, record repo, branch, base/head commit, PR (if any), changed
files, check results and outstanding work — as `AGENT_DEVELOPMENT.md` requires.
Never pass secrets, local paths, private saves or match transcripts.

交接时按 AGENT_DEVELOPMENT.md 写清仓库、分支、基线与当前提交、PR、修改文件、检查结果
与待办；不传密钥、本地路径、私有存档或对局记录。
