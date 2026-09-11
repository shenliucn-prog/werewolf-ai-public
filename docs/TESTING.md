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

CI adds macOS/Windows smoke tests to Linux verification. A green platform job
is evidence for those tests, not certification of every adapter on that OS.
The already-required `dependencies` check runs even after upstream failures and
explicitly requires both new jobs to succeed; skipped jobs cannot silently
bypass the new gates. This avoids requiring a separate branch-protection edit.
Never attach real saves, credentials or private transcripts to CI artifacts.

安装运行与测试依赖后，可测量分支覆盖率；暂不设虚假的全覆盖指标。
真实浏览器测试连接本地后端，验证离线旁观、准备确认、刷新续局和结算；
它不替代闯关与真实模型验收。跨平台任务仅证明其覆盖的路径。
