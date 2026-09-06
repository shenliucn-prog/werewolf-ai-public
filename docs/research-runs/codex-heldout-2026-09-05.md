# Frozen acceptance run: conjecture judgments

Local date: 2026-09-05. UTC review completed: 2026-09-06 01:01:15.

Result: **the frozen reserved set passed this single-run check**. This is not a
general accuracy or live-game safety claim.

| Check | Result |
| --- | --- |
| Valid structured reports | 16 / 16 |
| Classification matches authored labels | 16 / 16 |
| Complete required evidence-ID coverage | 16 / 16 |
| Chinese / English classification | 8 / 8 each |
| False contradiction accusations | 0 / 12 non-contradiction items |
| Missed contradictions | 0 / 4 contradiction items |
| Abstentions | 2, both matching the insufficient-evidence labels |
| Missing, malformed or failed responses | 0 |
| Retries or in-run prompt/label/scorer changes | 0 |
| Observed command/file/MCP/web tool events | 0 |

All quotations passed exact-source validation. The two embedded-instruction
items were classified from B's consistent statements rather than following G's
instruction to assert a contradiction. All 16 brief explanations were inspected
by the assistant; this was not an independent human review.

## Frozen setup

- Code baseline: `8ac9265`.
- Requested model: `gpt-5.6-terra`, reasoning effort `medium`.
- Codex CLI: `0.153.3`, existing ChatGPT-account authentication.
- One independent ephemeral invocation per item, read-only sandbox, empty
  working directory, user config ignored, tools disabled.
- Same stdin wrapper and final prompt as the prior development follow-up.
- No gold labels, previous responses or repository contents supplied to the model.
- No schema-constrained decoding. The existing strict parser scored raw replies.
- Prompt, dataset and scorer SHA-256 fingerprints matched before and after.

The corpus contains eight reserved scenario families, each with paired Chinese
and English versions. The 16 items are therefore not independent samples. The
set was not used for the preceding prompt adjustment, but has now been queried;
future tuning against these answers requires a new reserved set.

## Evidence and cost accounting

[Full raw reports, per-call usage, frozen fingerprints and scores](codex-heldout-2026-09-05.json)
are retained without account identifiers or credentials. CLI-reported totals:
158,265 input tokens (including 125,440 cached input tokens), 2,546 output tokens.
These totals include Codex's own agent context; they are not a direct API price
estimate. No API key was created.

## Decision

The result supports the next proposed stage: a small seven-player autonomous
debate with the judgment component operating only as a shadow observer. Do not
automatically convert its classifications into suspicion or game actions yet.

Limitations remain: short authored cases, one model configuration, one repetition,
correlated translations, and no independent label audit. Exact quotations and
required-ID coverage do not guarantee that every inference is sound. Real debate
adds longer histories, incomplete statements and strategic adaptation which this
test does not measure.

No gameplay feature, prompt, annotation or scoring rule was changed for this run.
