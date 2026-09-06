# V3: initial format gate passed, challenge response rejected

The new candidate/assertion distinction and table JSON Schema passed the three
representative initial seats (A/B/D) and then all seven initial submissions.
All seven public tables were atomically published. This is the first run to
reach the debate stage, but **not a completed debate**.

The eighth call, A's challenge, returned the requested target, row, evidence and
text **plus** unsolicited `private_table` and `public_table` fields. The general
instruction still told the model to submit dual tables even in a challenge task,
while that task expected only four challenge fields. Table-only structural output
constraints did not cover the challenge phase.

The strict parser rejected the whole response before public mutation. Neither
unsolicited table was published or saved; no challenge, vote or shadow result
was accepted. [Raw artifact](codex-shadow-day-v3-2026-09-05.json) is retained with
the original response. No fields were silently dropped to make it pass.

Execution: eight calls, 96,984 input tokens (24,832 cached), 9,429 output tokens,
and 1,386 in the separately reported reasoning-output field. Finished at
2026-09-06 01:32:56 UTC (September 5 local). These are account usage figures, not
a monetary cost estimate.

## Recovery boundary

V3.1 separates action-phase instructions from table-writing instructions and
supplies structural output schemas for challenges, responses, votes and shadow
judgments as well as tables. It reuses only the seven accepted initial raw
responses, after checking that their saved input requests exactly match current
initial requests and revalidating each draft. It does **not** reuse, repair or
publish the rejected eighth response.

The continuation is recorded as a separate artifact with parent-file hash and
explicit `reused` records. It is the same initial episode under a repaired phase
adapter, not a fresh independent sample. Reused calls are not billed or counted
as new model usage again.
