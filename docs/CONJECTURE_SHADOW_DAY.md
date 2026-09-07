# Seven-seat shadow debate experiment

Status: bounded research protocol; live run artifacts are not distributed.

This is an isolated Chinese-language **single daytime slice**, not a full game,
a win-rate study, or a change to normal mode. It uses seven independent model
contexts, not seven persistent agents with tools. Their exact prior public and
owner-private records are supplied again at each call.

## Protocol lineage

Role and faction judgments are separate. Owner-lawful constraints must not be
derived from researcher ground truth.

`shadow-day-v3` adds a separate `candidate_roles` list. `roles` is now at most
one current assertion, empty for unknown/withheld status. Candidate sets can
remain multiple without asserting an identity. Both the output JSON Schema and
local validator enforce this distinction. Local validation still checks lawful
evidence, private constraints, complete roster coverage and shared cutoffs.

The first three sealed submissions (A, B, D: seer, wolf, villager) form an early
format gate. Each response is checked immediately; failure aborts before further
calls. On success the same drafts are retained and remaining seats continue;
this is a gate within one episode, not three extra calls or an independent test
set. Initial publication still waits for all seven. Revised submissions are also
validated individually before the complete batch is atomically released.

The current record API retains legacy defaults for older fixtures. V3 requires
the new candidate field explicitly. Neither structural output constraints nor
candidate sets certify the truth of public claims or natural-language reasoning.

V3.1 uses action-specific prompts and output schemas for every phase. An explicit
`--resume-initial-from PATH` can reuse seven accepted initial answers only when
their exact inputs match the current protocol; all are revalidated and lineage
is recorded. Rejected actions are never reused or silently stripped of fields.

## Shared seven-seat sequence

1. Seven living seats: two wolves, one seer, four villagers. A is the seer, B/F
   are wolves, and C/D/E/G are villagers. This fixed assignment is researcher-only.
   A lawfully knows C's good faction; wolves know their teammate; each seat knows
   its own role. No death event or complete prior night is simulated.
2. Each model submits seven-row private and public tables. All initial requests
   share one public cutoff, and the complete batch is validated before release.
3. The host grants A and then C one challenge slot each, with a pass option. The
   model chooses the target and table row. Each challenged target responds once.
   These speaking slots are fixed protocol choices, not evidence that the host
   can autonomously identify the most useful speaker.
4. The host closes debate without judging truth. All seven seats independently
   revise both tables against the same post-debate cutoff. Public revision
   explanations are separate from private strategy explanations.
5. A separate model call for each seat receives its saved version-2 private table
   plus every public table version, then chooses a secret ballot. Ballots are
   released together; voting reasons remain private. No elimination or winner is
   resolved. An input trace shows the table was supplied, not that it caused the
   action or reveals the model's internal reasoning.
6. Only after all votes, the unchanged shadow judge reviews each actual exchange
   using public evidence available at the time of its response. It sees neither
   ground truth nor later revisions/votes. Its result is recorded, never fed back
   to players, suspicion scores, the host, or action selection.

Known private facts are locked to their lawful role/faction and source. New
public testimony cannot overwrite them. This is an experimental constraint, not
a claim that all inferred identities are correct. Players may deliberately
reveal or fabricate public claims; reference validation cannot establish the
truth of their prose.

## Reproduce

Offline checks require no model or network:

```sh
python -m unittest discover -s tests -p test_shadow_debate.py -v
```

After approving external processing of the synthetic game inputs, with an
already authenticated Codex CLI:

```sh
python -m werewolf_web.research.codex_shadow_run --run-codex \
  --output outputs/shadow-day.json
```

The explicit opt-in flag permits **at most 27 calls**: 14 table submissions,
two challenges, up to two responses, seven votes, and up to two shadow judgments.
The model is `gpt-5.6-terra` with medium reasoning, set per invocation. No global
configuration is changed, no new API key is created, and account usage is consumed.
Each call has a 180-second limit; there are no retries or format repairs. Invalid
output aborts and retains a partial artifact. Existing output paths are refused.

The runner uses an empty temporary working directory, ephemeral sessions,
read-only sandboxing, no approvals, disabled web search, and disabled tools,
plugins, apps, memory and multi-agent capabilities. Runtime logs may still be
written by Codex in its own home. It does not read credentials itself.

## Audit boundary and next evidence

The JSON output contains requests, raw final responses, timings, usage, source
hashes, stage state, public history and **all private notebooks**. It is explicitly
a researcher artifact: never pass the whole file to a player or public replay.
Use `ShadowDay.public_export()` for public-only data. Local Python ownership is
not a security boundary against arbitrary code running in the same process.

Review whether identities stay lawfully separated, whether public claims differ
strategically from private beliefs, what the model says caused revisions, whether
ballots agree with the supplied beliefs or stated strategy, and whether the judge
cites the actual source text. There are no gold labels for emergent exchanges, so
parser-valid judge outputs must not be reported as measured classification accuracy.

One fixed Chinese episode with one model and two challenge slots cannot establish
debate quality, general reliability, optimal rationality, multi-round memory,
cross-model fairness, bilingual performance, or improved win rates. Multi-seed,
role-rotated, longer experiments and an ordinary-text control remain future work.
