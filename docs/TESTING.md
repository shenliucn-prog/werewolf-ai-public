# Verification / 验证

Install runtime requirements plus `requirements-test.txt` in a virtual environment.
Run `python -m coverage run -m unittest discover -s tests -q`, then
`python -m coverage report`. Branch coverage is a measured baseline, not a
100% completeness claim or a new blocking threshold.

For real Chromium + local HTTP/SSE: `python -m playwright install chromium`,
then `python tests/browser/player_entry.py`. This exercises offline player and spectator
creation, the ready gate, page reload/continuation and settlement. Persistence
is disposable. A further campaign scenario uses a synthetic Chat Completions
HTTP fixture, retries failed teaching, resumes and checks exactly-once scoring.
The test fixture is not a real model and exposes no routes in the product app.
These tests do not prove real API/Agent quality or all browser flows.
Existing jsdom tests remain fast UI contract tests, not browser E2E.

CI runs the macOS/Windows smoke tests, Chromium entry checks and coverage on
master and the weekly schedule; pull requests run the Linux Python matrix, the
JavaScript checks and the dependency audit. The already-required `dependencies`
check runs after the heavy jobs and requires both to succeed on full runs; on
pull requests they are intentionally skipped and the aggregate check passes.
This avoids requiring a separate branch-protection edit.
Never attach real saves, credentials or private transcripts to CI artifacts.

安装运行与测试依赖后，可测量分支覆盖率；暂不设虚假的全覆盖指标。
真实浏览器测试连接本地后端，验证离线旁观、准备确认、刷新续局和结算；
CI 在 master 与每周计划任务上运行跨平台、浏览器与覆盖率；PR 只跑 Linux 测试矩阵与
依赖审计。已必需的 `dependencies` 检查在完整运行中要求重任务成功；PR 中重任务按设计
跳过并通过，无需单独修改分支保护。测试环境不放真实密钥。
