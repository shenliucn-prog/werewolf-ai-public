# Public-release readiness

**Publication update:** the maintainer authorized a separate history-free release at [werewolf-ai-public](https://github.com/shenliucn-prog/werewolf-ai-public). See [public launch scope](PUBLIC_LAUNCH.md). The private-repository status and pending decisions in the dated audit records below are historical; live checks are available in the public repository's Actions tab.

**Current audit: [2026-09-06 release-candidate review](RELEASE_AUDIT.md).**
Follow-up: [publication privacy and history plan](PUBLICATION_PLAN.md).
Persona-text follow-up: the maintainer confirmed personal authorship of the
descriptions and catchphrases. The historical text-source review item below is
resolved; see [ASSETS.md](ASSETS.md).
The older checklist below is historical evidence, not the current test result.
The current candidate adds playable conjecture, role selection, Divine Witch,
contributor tests and documentation; it has not been pushed or published by the
audit. Read the current report's publication gates before changing visibility.

Review date: 2026-09-04. Repository: `shenliucn-prog/werewolf-ai`.

The repository remains private. This document records preparation work; it is not an authorization to change visibility or a claim of a complete security audit.

## Completed in this preparation pass

- Pushed the playable bilingual baseline, `12df821`, to `origin/master`.
- Replaced the landing README with English and retained a linked Chinese version.
- Added contribution guidance, a security policy, issue/PR templates, test CI, and Dependabot update configuration.
- Added explicit implementation limitations instead of claiming every configured role is fully playable.
- Corrected leftover non-cast nicknames in the current persona text. Historical versions still contain the original text.
- Ignored localized host-state files and environment-file variants, while retaining `.env.example`.
- Changed the direct server entry point to bind to localhost.
- Fixed a custom model endpoint inheriting the server's API key when no caller key was supplied; added a regression test.
- Replaced old dependency pins with versions verified in a clean Python 3.12 environment and removed unused multipart/uvicorn-extra dependencies.

## Validation evidence

| Check | Result |
| --- | --- |
| Unit/integration suite on new dependencies | 48 tests passed, including 32 completed offline matches |
| Installation consistency | `pip check`: no broken requirements |
| Dependency audit | Original requirements: 16 known vulnerabilities in 4 resolved packages; updated requirements: none reported by `pip-audit` at review time |
| SDK compatibility | Real client construction and Chat Completions interface verified without sending a provider request |
| HTTP smoke check | Homepage, static language pack, and English board metadata returned successfully |
| Tracked text/history scan | Pattern scan of all 4 baseline commits and local refs found no matches for common API/GitHub/AWS key formats, private keys, credential URLs, or personal absolute paths |
| Image metadata | All 12 PNG portraits contain EXIF metadata. A sampled ImageDescription contains AIGC service-provider, service-user, time, and content-ID fields |

The history scan is a limited pattern scan, not a guarantee that arbitrary secrets, personal information, or copyrighted material are absent. It excludes binary pixel content. Git author/committer identities include a personal email domain and a local-tool identity; the owner should decide whether these are appropriate to publish.

Audit commands:

```bash
python -m unittest discover -s tests -q
python -m pip check
python -m pip install pip-audit
python -m pip_audit -r werewolf_web/requirements.txt --progress-spinner off
node --check werewolf_web/static/js/app.js
node --check werewolf_web/static/js/i18n.js
git diff --check
```

## Owner decisions required before making public

1. **License — decided:** on 2026-09-04 the maintainer approved MIT for source code; the full [LICENSE](../LICENSE) is now included. Portraits remain separate from MIT.
2. **Portrait publication — authorized by maintainer:** the maintainer confirmed that all 12 portraits were AI-generated locally, are their own, and are authorized for this project's use and publication with the repository. This records the maintainer's authorization, not an independent rights audit; the generation tool/model was not supplied. No general standalone artwork reuse license was granted. Persona provenance remains a separate review item. See [ASSETS.md](ASSETS.md).
3. **Privacy and historical content:** decide whether the old nicknames, author identities, and image generation identifiers are acceptable. If they identify real people/accounts, sanitize both the current files and reachable history before public release. History rewriting requires a separate decision and coordination with existing clones; no history rewrite was performed.
4. **Release positioning:** retain the experimental local-prototype label. The five missing role paths are now wired into shared browser/chat sessions and the two identified private-information leaks are fixed. Action windows, public death reveals, and remaining caveats are documented in [RULE_VARIANT.md](RULE_VARIANT.md) and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md); do not claim exhaustive rule coverage.

## 2026-09-04 implementation follow-up

- Added the approved MIT code license and a separate asset-provenance record.
- Added Knight, White Wolf King, Crow, Gravekeeper and inherited Stone Ghost
  kill paths to the shared playable session, with English/Chinese prompts.
- Removed the public nightly charm announcement and exact-role Seer metadata.
- Added atomic night-action validation, corrected poison-versus-knife precedence,
  enforced NPC Witch self-save limits and drained reverse-seat death chains.
- Validation: **66 tests passed**, including the original 32 complete matches
  plus 6 complete matches exercising each human daytime ability in both languages.
  Both browser JavaScript files passed syntax checks; `git diff --check` passed.
- The local homepage, controls, and board metadata loaded in the connected
  browser. Independent automated Chrome startup failed in this environment;
  actual browser clicks for the new daytime actions remain unverified. No paid
  provider calls were made for this verification.

## GitHub follow-up status

At initial inspection, the repository had a blank description, no license, no issue/PR templates, no project test workflow, no topics, and an unprotected `master` branch. It had no issues or releases. GitHub community health was 14%.

- Confirm the new test workflow passes on GitHub before creating a release.
- Enable Dependabot security alerts and private vulnerability reporting where available. The alert API reported that Dependabot alerts were disabled; the current credential also lacked the indicated administration scope. No credential scopes were expanded.
- The maintainer approved configuring `master` protection together with eventual publication: block force pushes/deletion and require successful tests without mandatory external approval. GitHub currently rejects branch protection on this private repository under its current plan. Do not change visibility or upgrade the plan automatically. Verified check names: `test (3.10)`, `test (3.12)`, `test (3.13)`, and `dependencies` (GitHub Actions app ID 15368).
- Add a short English description/topics and, later, a release tag and representative screenshot.
- Review public exposure of all commits and assets before changing visibility. GitHub explains the consequences in [repository visibility guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).
- After publishing, check the Security tab. GitHub's [secret scanning documentation](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning) describes automatic scanning for public repositories and its coverage of Git history.

Public source release and public application hosting are different milestones. The current application remains intended for local use; see [SECURITY.md](../SECURITY.md).
