# Offline conjecture judgment evaluation

Status: a read-only request/report interface and a **hand-authored** benchmark.
A local Codex-account development smoke test was completed on 2026-09-05; see
the result below. No provider SDK, API key, network call, game action, or suspicion
update is part of the shipped interface itself.

The subsequent frozen reserved-set run passed 16/16 for classification, valid
reports and complete required evidence coverage, with no retries or in-run
changes. See [the acceptance report](research-runs/codex-heldout-2026-09-05.md)
for raw evidence, version fingerprints and limitations. No automatic suspicion
bridge was enabled.

## First real smoke result (2026-09-05)

Using the existing ChatGPT login through Codex CLI 0.153.3, requested model
`gpt-5.6-terra`, reasoning effort `medium`:

- Initial dev pass: 16/16 reports valid and classifications matching authored
  labels; 0 false-positive contradictions and 0 missed contradictions.
- All supplied quotations matched their sources. Complete required-evidence-ID
  coverage was only **14/16**: q01-en and q03-en omitted one relied-on source.
- The general prompt was strengthened to cite every material premise and prefer
  original sources. No gold label or scoring rule was changed.
- A targeted follow-up of those two cases plus q04-zh-CN and q06-en passed **4/4**
  for validity, classification and required evidence coverage.
- This follow-up was not a full-set rerun or held-out validation. The reserved
  acceptance set was not queried, and no automatic suspicion bridge was enabled.

The runs used independent ephemeral sessions, a read-only sandbox, an empty
working directory, disabled tools and ignored user config. Inputs were piped
through stdin; labels and repository contents were not supplied. No tool execution
events were observed. This follows the official
[Codex non-interactive workflow](https://learn.chatgpt.com/docs/non-interactive-mode).

[Raw reports, scores and usage](research-runs/codex-dev-smoke-2026-09-05.json)
retain the initial shortcoming and targeted follow-up separately. Account token
usage includes Codex's own context; it is not a direct API cost estimate. This
small development smoke validates the path, not general reasoning performance.

## Dataset and reserved split

`judgment_cases.py` contains 16 scenario families, each in Chinese and English:

- Development: 8 families / 16 language-specific requests.
- Reserved acceptance: 8 separate families / 16 requests.

Both translations of a family always stay in the same partition. The acceptance
set is reserved from prompt examples, not a cryptographically hidden or external
test set. It is authored and inspected in this repository. Once used to tune a
prompt, it is no longer a clean acceptance set; create new reserved cases before
claiming generalization. The small, synthetic corpus is not statistically
representative of real debate and its labels need independent review.

Coverage includes new evidence, corrected records, conditional/counterfactual
reasoning, deliberate withholding, denying earlier words, hearsay, negation,
fabricated quotations, conflicting role assignments, chronology, missing
context, and instructions embedded in untrusted testimony.

Labels are provisional research annotations, not facts about a speaker's real
intent or role. `strategic_concealment` means the explanation could be coherent,
not that the speaker has been proven honest. Exact-category disagreements should
be reviewed separately from the more consequential false accusation of an
unresolved contradiction.

## Read-only interface

1. Supply trusted owner-tagged `Evidence` records to `visible_input()`.
2. Only public records and that observer's own private records survive filtering.
3. `build_request()` accepts only the resulting immutable `JudgmentInput`, never
   a labelled case. Gold labels, split names and annotation notes are excluded.
4. A future caller may provide a raw JSON response to `parse_report()`.
5. Receive a detached `JudgmentReport`: verdict, confidence, explanation and exact
   quotations. The report contains no action recommendation or suspicion score.

There is deliberately no live-session adapter yet. Visibility relies on the
trusted caller correctly assigning ownership and recording only lawful evidence.
It does not authenticate callers, sanitize secrets embedded in arbitrary public
text, or prove that private evidence is legally obtained. Stable evidence IDs
must not themselves encode secrets.

The output categories are:

- `reasonable_revision`
- `different_conditions`
- `strategic_concealment`
- `unresolved_contradiction`
- `insufficient_evidence`
- `no_contradiction`

The most specific supported category is preferred. Abstention is explicitly
allowed. This schema is not wired to `DebateSession.assess()`; in particular,
`no_contradiction` is an evaluation category, not an automatically mapped score
update in the earlier hand-labelled coordinator.

## Validation boundaries

The parser rejects missing/extra/duplicate fields, wrong request or actor IDs,
unknown categories, non-finite/out-of-range confidence, empty explanations,
missing required citations, unavailable evidence, duplicate citations and quotes
which do not occur verbatim in the cited record. Non-abstaining reports need at
least one citation. Responses are size bounded and cannot include actions or
score updates as extra fields.

Exact quote matching validates provenance, **not semantic sufficiency**. A model
can still quote a real but irrelevant sentence or misinterpret an accurate quote.
Likewise, the benchmark's required-evidence-ID coverage is only a coarse rubric.
These limitations require review of explanations before any score-update bridge
is authorized. Declared confidence is saved for analysis, not treated as a
calibrated probability or a decision threshold.

The request explicitly treats testimony as data, including embedded instructions.
This is a prompt boundary, not proof that a future model resists prompt injection.

## Run locally, without API calls

From the repository root with Python 3.10 or newer:

```sh
python -m unittest discover -s tests -p test_judgment.py -v
python -m werewolf_web.research.judgment_eval requests --split dev
python -m werewolf_web.research.judgment_eval requests --split heldout
python -m werewolf_web.research.judgment_eval score --split dev --responses responses.json
```

Request export prints prompts without gold annotations. Reserved requests should
only be sent after freezing the prompt and model configuration. The scoring file
must be a JSON object mapping each request ID to its raw response **string**, not
a parsed report. The scorer rejects IDs from outside the selected split and
duplicate JSON keys. Missing responses remain counted; they are not dropped.

## Metrics

- Overall accuracy includes invalid and missing responses as failures.
- Valid-only accuracy is separately labelled and unavailable if none are valid.
- False-positive contradiction rate: incorrect contradiction verdicts divided
  by all labelled non-contradiction cases. Invalid negatives are separately
  reported, not silently classified as correct negatives.
- Miss rate: all labelled contradictions not successfully identified, including
  abstentions and invalid/missing reports, divided by labelled contradictions.
- Abstentions, validation errors, required-evidence-ID coverage, confusion counts
  and language-specific results are reported separately.
- Confidence is recorded per valid report, without claiming calibration.

Tests use synthetic responses constructed from known labels to check the parser
and scorer. A perfect synthetic test score is **not model accuracy**. Both language
versions are correlated items; 32 requests do not mean 32 independent scenarios.

## Next gate

Review the development rubric and reserve the acceptance set. A later, separately
approved experiment can freeze provider/model/version, reasoning effort, prompt,
repetitions and budget, then collect real responses. Calls, latency, cost and
provider errors need to be recorded by that future runner. No additional budget, provider or
paid experiment is implicitly authorized by this offline infrastructure.

Do not feed judgment reports into live suspicion or actions until false-positive
behavior and evidence interpretation have been reviewed on held-out examples.
