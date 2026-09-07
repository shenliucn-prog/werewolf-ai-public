# Public source and local data

The public repository contains reusable code, bilingual rules, generic research
protocols, licensed assets and deliberately synthetic test fixtures only.

Do not commit actual play transcripts, model requests/responses, private notebooks,
experiment results, local screenshots, packaging manifests, machine paths,
credentials or personal configuration. Keep research output in ignored `outputs/`
or outside the checkout. Runtime reviews and NPC memory remain ignored.
“Public” inside a game means visible to its players, not approved for GitHub.

Before publishing, run `python scripts/check_release.py` and review the diff.
Use `--history` on a full clone to inspect reachable Git history too. These checks
are limited safeguards, not proof of privacy or permission to publish arbitrary data.
Synthetic fixtures must be authored for testing, never copied from play logs.

Deleting a file in a new commit does not remove previous versions. If data was
published, back it up privately, coordinate a history rewrite, and recheck every
remote branch and tag. Old PR refs, caches and third-party forks may retain copies;
contact the hosting provider when removal is needed. Rotate exposed credentials
rather than relying on history rewriting.
