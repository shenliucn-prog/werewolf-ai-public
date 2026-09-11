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
