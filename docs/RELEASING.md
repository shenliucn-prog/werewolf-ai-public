# Versioned delivery / 版本化交付

Code + tests + affected documentation form one deliverable. Users should not
need to request README updates separately. / 代码、测试、相关文档一起交付，
不需要用户额外提醒更新 README。

## Development and releases / 开发与发布

`VERSION` is the game version source, separate from the development-only npm
package version. `0.1.0-dev` bootstraps version tracking; it is not a claim that
a release already exists. README version markers must agree. Before choosing
a public number, inspect remote tags and Releases too; local tags alone are
not authoritative. / VERSION 是游戏版本来源；npm 版本只属于测试工具。
`0.1.0-dev` 仅开启版本管理，不代表已经发布。正式编号前须核查远端标签和发布记录。

Use `0.x.y` while experimental; new feature batches increment the middle
number, fixes the last. `-rc.1` marks a candidate. Compatibility-breaking
changes must be documented even before 1.0. / 实验阶段采用 0.x.y：功能批次升中位，
修复升末位，候选版加 -rc.1；1.0 前的不兼容变更同样必须说明。

Main-branch README describes that checkout, including explicitly marked
experimental features. A tagged release includes its own matching README;
do not document unreleased features as already available in an older release.
README 保持当前代码的说明；每个发布标签保留当时匹配的文档，不能宣称旧版已有新功能。

## Every PR / 每个 PR

Create a new `.changes/<unique-name>.json`; keep old records as history.
Use `.changes/shared-intelligence.json` as the initial example, with fresh text:

- `summary` and `compatibility`: nonempty `en` and `zh` strings.
- `docs_impact`: `readme` for product/entry/setup changes; `docs` for detailed
  guide changes; `none` only for genuinely internal work, with a reason.
- `docs`: paths actually changed in this PR; both READMEs for `readme` impact.
- `reason`: explain the classification; “none” is not an automatic exemption
  from reviewer scrutiny.

新增独立变更记录，写清双语摘要、兼容性、文档影响、实际修改的文档与理由。
纯内部重构可以不改 README，但不能省略判断。记录不等于审查通过。

Run `python scripts/check_delivery.py --base HEAD` before committing; after
committing, substitute the actual PR base commit. CI uses the PR base and
rejects missing/new-record reuse, missing declared docs, one-language README
updates and inconsistent version markers. Semantic accuracy and translation
quality are still human/Agent review responsibilities. Required GitHub checks
must be enabled in branch protection to prevent bypass; adding a workflow
alone does not change repository protection settings.

## Release checklist / 发布清单

1. With release authorization, inspect remote tags/releases, select a number,
   update VERSION and both README markers, and consolidate reviewed changes
   into `CHANGELOG.md` under `## <version>` (keep `## Unreleased`). Include
   bilingual changes, known limitations and save/config compatibility.
2. Test the exact candidate: Python suite, `npm test`, `npm run check`,
   `python scripts/check_release.py`, `git diff --check`, and
   `python scripts/check_delivery.py --release v<version>`.
3. Exercise documented entry commands and checkpoint continuation. State
   explicitly if real API/Agent play has not been verified. Mock tests are
   not real-model evidence. No provider calls without the intended configuration.
4. Review and merge the release PR. Create the tag on that reviewed commit,
   then a draft GitHub Release with matching bilingual notes. Review permitted
   sanitized assets before publishing. Never upload local settings, saves,
   transcripts or experiment output. See [publication safety](PUBLIC_RELEASE.md).
5. Publish only the approved candidate. Fix released bugs with a new version,
   not a moved tag. Roll back code via a new reviewed change; never promise
   older code can read newer saves without testing it.

发布顺序：授权 → 核查编号 → 版本/双语文档/兼容说明 → 完整验收 → 审核合入 →
对应提交打标签 → 草稿发布核对 → 正式发布。开发完成和合并不等于发布授权。
本流程当前不自动打标签、不自动发布；检查脚本本身只读。

## Automated candidate / 自动候选包

After this workflow is merged, run **Verified release candidate** on master
with an existing reviewed tag whose checkout contains the workflow's candidate
script. Default `draft=false` is a rehearsal: verification and downloadable
artifacts only. `draft=true` additionally creates a draft Release and provenance
attestation. It never creates/moves a tag, overwrites an existing Release or
publishes a draft. Publish manually only after reviewing the exact package.

The gate runs the full Python/DOM suite, dependency audit, release checks, then
builds and smoke-tests the actual archive. The checksum covers the delivered
bytes. The attestation identifies this workflow run; the package manifest
records the tagged source commit. Neither proves gameplay balance or real-model
quality. Old tags without `scripts/release_candidate.py` are unsupported.

合入后，从 master 手动选择已审核标签，默认只演练。显式选择 draft 才创建
草稿与来源证明，正式发布仍需人工确认。不覆盖旧版、不移动标签。
失败修复需新提交／新版本；保留旧下载，勿承诺未经验证的存档向后兼容。
