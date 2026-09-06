# Publication preparation — 2026-09-06 UTC

**Historical preparation record.** The maintainer subsequently authorized open-source publication. The selected destination is the separate `shenliucn-prog/werewolf-ai-public` repository, using a clean root commit and a GitHub noreply identity. The original development repository remains private and its history is not imported. See [public launch scope](PUBLIC_LAUNCH.md); the preparation-stage statuses and gates below describe the earlier audit, not live GitHub state.

Status: local preparation only. No remote repository was created or made public;
no existing Git history, original portraits or research artifacts were changed.
The candidate builder now creates separate metadata-redacted portrait copies.

Follow-up validation: 198 Python tests pass, including metadata-inventory and
candidate-export regression tests; release hygiene checks pass across 152 candidate files and 119 historical
blobs. The publication inventory still requires manual review, as intended.

## Findings confirmed after the release audit

- The older persona version contains two pre-cleanup nicknames. They were replaced
  in the current files, but remain reachable in Git history. Names and email
  values are intentionally not repeated here.
- All twelve portrait PNGs contain EXIF. A read-only inspection found AIGC
  provenance fields, service-user/time/content identifiers and signature-related
  structures. These are **not merely disposable editor metadata**. Wholesale
  deletion or rewriting could remove provenance or invalidate signatures.
- Git author and committer identities are a separate publication surface from
  file contents. A credential scan does not clear either those identities or EXIF.
- The maintainer already authorized publication of their own locally AI-generated
  portraits. They separately confirmed that they personally wrote the persona
  descriptions and catchphrases. The text-authorship question is closed; neither
  declaration requires repeat confirmation. Historical identifiers remain a
  separate privacy decision.

## Release route: local preparation implemented, publication pending

The **local history-free candidate preparation** is now implemented. Remote
repository creation and the final publication route have not been executed.

Keep the existing private repository as the development/research archive. Prepare
a separate public snapshot from an explicitly reviewed release commit, without
copying `.git`, runtime memories/reviews, local environment files or credentials.
Use a chosen public/noreply commit identity when initializing its public history.
Preserve the original MIT notice and the separate artwork scope.

This avoids copying old nicknames/commit identities without rewriting the
existing history. Candidate portraits redact the three independent description
fields identified below; the original files and separate provenance envelope stay
untouched. Do not disguise this metadata edit as a verified original signature.
If a public snapshot is selected,
record how future development changes will be synchronized before creating the
new remote. There is no standing authorization here to create that remote.

Publishing the existing repository as-is instead keeps its URLs and history,
but also publishes the old objects and author/committer metadata. A current-file
cleanup commit alone cannot make those earlier objects private. History rewriting
would be a separate, explicitly chosen operation, not routine release cleanup.

## Next gates, in order

1. **Resolved: persona text authorship.** The maintainer confirmed personal
   authorship of the descriptions and catchphrases; recorded in ASSETS.md.
2. **Implemented for local candidates:** remove only independent description
   fields `ServiceUser`, `Time`, `ContentId`; preserve pixels, ServiceProvider and
   the separate AIGC provenance/signature envelope. Its trace IDs/timestamps remain;
   signature validity is not asserted. Original portraits are untouched.
3. Choose existing-history publication versus a separate history-free snapshot.
4. Stage only reviewed candidate files, create a release-candidate commit and
   test that exact version. Run Python, DOM, replay and dependency checks.
5. Push only to the intended destination; verify that version's GitHub checks,
   license recognition, vulnerability reporting and branch protection before
   the visibility change. Earlier green checks do not clear this version.

## Repeatable read-only checks

```sh
python scripts/check_release.py --history
python scripts/audit_publication.py
```

The first checks limited credential patterns, links and rosters. The second
reports PNG metadata chunk types/sizes and counts of Git email identities,
without printing embedded values. It intentionally reports
`manual_review_required`; it does not certify legal rights or publication consent.

## Build a local candidate

```sh
python scripts/prepare_release.py --output /absolute/path/to/new-candidate --archive
```

Use a new directory outside this repository. Existing directories/archives and
unreviewed portrait layouts are rejected. No `.git`, local credentials, runtime
memories/reviews, virtual environments or installed node packages are copied.
The generated archive contains only manifest-listed release files and normalized
archive ownership/timestamps. It does not acquire an origin remote or commit author.

The candidate's manifest includes source/candidate file hashes and the exact
redacted field names, never their values. Both check scripts also work directly
in a history-free candidate: they report that Git history is unavailable rather
than claiming it was scanned. The credential/link check verifies manifest hashes.
Tests and research replay should run on the candidate itself before handoff.

Development stays in the existing private repository until publication is decided.
For a later candidate, rerun the exporter into a new directory; do not manually
develop in exported copies or import their runtime files back into the source.
If a separate public repository is chosen, publish reviewed snapshot diffs from
this workline without merging the private `.git` history. The public repository's
URL and commit identity must be established before that first remote push.

See [the release audit](RELEASE_AUDIT.md) for verified gameplay/architecture results
and [asset declarations](ASSETS.md) for the existing authorization and its scope.
