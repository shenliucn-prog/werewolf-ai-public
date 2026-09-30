# Next release candidate / 下次发布候选

Prepared 2026-09-30. Proposed version: **0.4.0** (feature release).
Latest published tag: **v0.3.0**. No new tag or Release is created by this document.
准备日期：2026-09-30；建议功能版 **0.4.0**，最新已发布标签仍为 **v0.3.0**。

## Scope / 范围

The reviewed feature baseline is main commit `42b9c13`, including PRs #43–#48.
See [Unreleased](../CHANGELOG.md#unreleased) for bilingual changes and compatibility.
The reverted PR #34 is not included as a delivered feature.

功能基线为 `42b9c13`，包含 #43–#48；双语改动和存档兼容见更新日志。
已撤回的 #34 不作为交付功能。

Dependency candidates are separate until merged and reverified:

| PR | Candidate | Scope |
| --- | --- | --- |
| [#49](https://github.com/shenliucn-prog/werewolf-ai-public/pull/49) | jsdom 30.1.1 | Development DOM tests / 开发测试 |
| [#50](https://github.com/shenliucn-prog/werewolf-ai-public/pull/50) | OpenAI SDK 3.19.2 | Model client / 模型客户端 |
| [#51](https://github.com/shenliucn-prog/werewolf-ai-public/pull/51) | Starlette 1.7.0 | Web runtime / 网页运行时 |

依赖升级需合入并复验后才算发布内容，不把待合并 PR 当作已交付。

## Evidence and remaining gates / 证据与待完成项

- Baseline CI on 2026-09-29 (Asia/Shanghai): 780 Python tests, 3 Chromium
  flows, Python 3.10/3.12/3.13, macOS/Windows smoke checks and dependency audit
  passed. Reported combined coverage: 82%. This evidence applies to `42b9c13`.
- 基线 CI 全绿，证据只对应该提交；不直接替代后续候选的检查。
- Before release, choose the exact merged candidate and rerun its normal gates,
  browser continuation and packaged-download smoke tests. Inspect permitted
  assets and checksums. CI fixtures use synthetic providers; record separately
  whether real API/Agent full-game validation was performed for that candidate.
- 发布前锁定实际合入提交，执行门禁、网页续局与下载包启动测试，核对素材及校验和；
  合成服务测试与真实 API/Agent 整局结果分开记录。
- With release authorization, update VERSION, both README markers and the
  changelog version section together; merge the release change, tag its reviewed
  commit, then follow [the release procedure](RELEASING.md).
- 获得发布指令后同步版本号、双语 README 与版本日志；审核合入后，在对应提交上打标签，
  按发布流程生成并核验候选包。

Offline balance remains a follow-up investigation. The small paired experiment
does not justify changing role rules or claiming improved winning strength.
离线平衡仍待后续研究，不能据小样本直接改角色规则或宣称实力提升。
