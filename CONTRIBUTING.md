# Contributing

Start with [architecture and extension recipes](docs/ARCHITECTURE.md) and the
[player guide](docs/PLAYER_GUIDE.md). Changes should preserve both playable
interfaces and both languages, not just one screenshot or one seeded match.

For browser interaction regressions, install Node.js 24.15+ (24.x), then run
`npm ci && npm test`. These development dependencies are locked in the repo;
no private tooling or temporary local installation is required.
Run `python scripts/check_release.py` for documentation links, board structure
and a limited credential-pattern scan. This is not a full security audit.

This project is an experimental local game. Before substantial feature work, open an issue describing the player experience and the rule variant you intend to support. English and Chinese reports are both welcome.

Source code is MIT licensed. Existing portraits are authorized by the maintainer for this project's use and publication, separately from MIT; see [asset provenance](docs/ASSETS.md). Confirm permission and license compatibility before submitting externally sourced code or assets.

## Set up

Follow the virtual-environment instructions in [README.md](README.md). No API key is needed for development or the test suite.

```bash
python -m unittest discover -s tests -q
node --check werewolf_web/static/js/app.js
node --check werewolf_web/static/js/i18n.js
git diff --check
```

## Changes that need particular care

- Keep rules and action selection in the local engine. Optional model output must not become an authority for game state.
- Keep public information, role-private information, and post-game analysis separate. A rules answer must never reveal a hidden role or choose a target for a player.
- Both human-playable interfaces use `GameSession`. Avoid adding browser-only game mechanics.
- Use stable player and role IDs for behavior, persistence, and actions. Display names and translations must not determine legality.
- Update English and Chinese user-facing text together. Chinese persona headings are parsed by code; changing them can alter NPC behavior.
- Add a focused regression test for a gameplay bug, state transition, or information-boundary change. Describe manual UI checks when the change affects presentation.
- Consult [known limitations](docs/KNOWN_LIMITATIONS.md) before claiming that a special ability is supported.

## Pull requests

### Tracking and review / 归类与审查

Maintainers triage every PR with a responsible assignee, a type label
(`bug`, `enhancement`, `documentation`, `refactor`, or `release`) and
relevant `area:*` labels. Contributors without permission can leave these
fields to the maintainer; missing metadata is not a reason to reject help.

Assign a version milestone when the target is agreed. Unscheduled work stays
without a milestone rather than inventing a release promise. Close a version
milestone after its published scope is complete. Tags and Releases remain the
source for downloadable versions; a milestone is not itself a release.

Link an issue when one exists; small standalone fixes may explain their scope
directly. Projects boards are optional and should track real ongoing work, not
duplicate milestones merely to populate a field.

Record actual review outcomes, outstanding findings and validation limits.
CI is not independent review. A single-maintainer self-check must be described
as such; never create approvals under another account to simulate a reviewer.
Historical metadata backfills must be described as retrospective, not as
evidence that a review or schedule existed at the time.

维护者为每个 PR 指定负责人、类型标签及相关 `area:*` 标签；外部贡献者没有权限
时由维护者补齐。版本确定后再关联里程碑，未排期不虚构版本承诺；发布范围完成后
关闭里程碑，标签和 Release 才是下载版本依据。已有 issue 则关联，小改动可独立说明。
Projects 看板可选，不为填满字段创建空看板。

审查记录必须反映实际情况：CI 不是独立审查，单维护者自查应如实说明，不借用其他
账号伪造批准。历史字段补录须标明为回溯归类，不暗示当时已有排期或审查。

Documentation is part of the same change, not deferred until requested.
Add a new bilingual `.changes/<unique-name>.json` record for each PR, declaring
documentation impact and save/config compatibility. Update affected guides;
update both READMEs for modes, setup, entry points or advertised capability
changes. Pure internal changes may explain `docs_impact: none`.
Run `python scripts/check_delivery.py --base HEAD` before committing (use the
PR base after committing). See [versioned delivery](docs/RELEASING.md).
CI checks declarations and file consistency; reviewers still verify meaning.

Submit issues and pull requests to [werewolf-ai-public](https://github.com/shenliucn-prog/werewolf-ai-public), targeting `master`. The public repository starts with a clean snapshot; do not merge private development history into it. Maintainer updates should be reviewed, sanitized file changes through the same pull-request checks. Required checks apply to the maintainer too; an additional person's approval is not mandatory for this single-maintainer project.

Explain the player-visible problem, the resulting behavior, and how you verified it. Keep unrelated refactors separate. Include the board, language, seed, and offline/online setting for reproducible gameplay reports.

Never include API keys, `.env` files, real-person profiles, or raw private match transcripts. New portraits and other assets must include their source and permission terms.
