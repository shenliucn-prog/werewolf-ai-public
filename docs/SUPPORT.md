# Support and evidence / 支持与证据

This is an experimental, local-first personal project, without a response-time
SLA, competitive fairness certification or a commitment to backport fixes.
Report the exact release/commit: main and downloadable releases can differ.

| Area | Scope |
| --- | --- |
| Python | 3.10+ required; Linux CI runs 3.10, 3.12 and 3.13. |
| macOS / Windows | Local execution is intended; consult the exact commit's CI for platform smoke results. Do not infer every Agent adapter is certified. |
| Browser | Local Python backend required; not a static website. Check the CI workflow for the browser paths actually exercised. |
| API | OpenAI-compatible Chat Completions; provider behavior varies. |
| User Agent | Trusted command wrapper implementing the documented protocol; optional Codex adapter. Opening this repo in an Agent is not NPC connectivity. |
| Offline | Explicit rule-based choice play; no model, no campaign score. |
| Models | Mock/contract tests are not evidence of a complete real-model game. |

Before reporting: reproduce on a new disposable game if safe, retain your old
save privately, and provide a minimal public-event excerpt rather than the save.
For security issues use [private reporting](../SECURITY.md).

这是个人维护的本地实验项目，没有响应时限承诺或竞技公平认证。反馈请注明准确
版本，区分主分支和下载版。支持方向不等于所有平台、浏览器、模型适配器均已实测；
以对应提交 CI 的具体测试范围为准。排查时使用新测试局，旧存档请私下备份，勿公开。
