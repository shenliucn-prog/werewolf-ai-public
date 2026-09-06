# V3.1: completed seven-seat shadow day, with explicit continuation lineage

**The bounded protocol completed.** Seven seats published dual tables, A and C
each challenged B, B responded twice, all seats revised their tables and cast a
ballot, and two shadow judgments were recorded after voting. This establishes
an end-to-end research trace, not optimal rationality, a full-game win rate, or
validated semantic-judge accuracy.

[Raw researcher-only artifact](codex-shadow-day-v3-1-2026-09-05.json) contains all
private states; never provide it wholesale to a player.

## Lineage and cost accounting

The parent [V3 attempt](codex-shadow-day-v3-2026-09-05.md) passed all seven initial
tables but failed at the challenge adapter. V3.1 retains those seven **unmodified
raw initial answers**, verifies their requests exactly match current initial
requests, and revalidates the drafts. The parent's rejected challenge is not used.
The artifact records the parent file hash and marks reused entries explicitly.

- Model: `gpt-5.6-terra`, medium reasoning, existing Codex login, CLI 0.153.3.
- Continuation: 2026-09-06 01:34:41–01:39:19 UTC (September 5 in Los Angeles).
- 27 logical steps: **7 reused initial answers and 20 new model calls**.
- The parent and continuation together made 28 actual calls, including the one
  rejected challenge. This is not two independent completed episodes.
- New calls: 277.288 summed seconds; 372,521 input tokens (23,808 cached),
  11,969 output tokens, 2,740 separately reported reasoning-output tokens.
- No new-call tool events were reported. Existing disabled-Code-Mode warnings
  did not prevent text responses. No monetary cost is inferred.

The adapter now separates table instructions from action instructions and supplies
a JSON output schema for every phase. Strict local validation remains in place;
it does not silently drop unsolicited fields or repair responses.

## Observed debate and votes

B privately knows B/F are wolves, but publicly claims seer and a wolf check on A.
A truly is the seer and publicly claims the good check on C. These initial drafts
were prepared against the same public cutoff, before either saw the other's table.

A challenges B's counterclaim and check. B repeats its claimed check on A. C then
questions the medium confidence and possible fake-check wording in B's first
table. B explains confidence as cautious public wording and says the fake-check
possibility refers to A's claimed check on C.

The revised beliefs diverge: C leans toward A while retaining B as a possibility;
D accepts B's explanation and prioritizes suspicion of A. Voting is consistent
with the supplied revised beliefs or the wolves' declared strategy in the
recorded explanations, but a trace is not proof of a model's internal cognition.

| Voter | Ballot | Recorded private rationale, summarized |
| --- | --- | --- |
| A | B | B's counterclaim conflicts with A's lawful knowledge |
| B | A | Maintain pressure on A and conceal F |
| C | B | A's C-good claim fits C's knowledge; B's wording remains suspect |
| D | A | More persuaded by B's check/wording explanation |
| E | B | B's confidence explanation is unconvincing |
| F | A | Maintain the public position supporting B |
| G | A | Revised private table favors B's explanation |

Tally: **A 4, B 3**. The protocol does not execute an exile or resolve a winner.
The result is not a causal estimate of persuasion: there is no counterfactual
control, role rotation, seed replication or ordinary-text comparison.

## Shadow judgments and limitations

After all ballots, the unchanged judge prompt receives only public evidence up
to each respective response, not roles, private beliefs or future vote outcomes.

- Exchange A→B: `no_contradiction`, self-reported confidence 0.98.
- Exchange C→B: `strategic_concealment`, self-reported confidence 0.90. The report
  explicitly treats concealment as a plausible explanation, not verified intent.

Both reports pass strict parsing and exact-quote provenance checks. There are no
gold labels for these emergent exchanges, so **2 valid reports is not 100% judge
accuracy**. Neither judgment changed a player's suspicion or action.

One issue warrants independent semantic review: B later attributes its earlier
ambiguous fake-check wording to A's check-on-C statement, although the initial
tables were sealed at the same pre-publication cutoff. The second judge accepts
the explanation without discussing that timing. This could be post-hoc attribution
or a later clarification of an earlier generic possibility; the present trace
does not justify declaring the judge certainly right or wrong.

Candidate sets also matter: B's public initial table rules out wolves for C/D/E/G
while claiming only to have checked A. Those exclusions need an explanation and
can constrain the remaining wolf locations. The two host-selected questions do
not exhaust all possible inconsistencies. The format is now executable, but this
is still far from proving an ideal-rationality ceiling.

## Verification

- Offline replay reconstructs all **27 requests** exactly, then reproduces the
  final research state exactly using the raw responses without model calls.
- All six recorded source hashes match the post-run source files.
- Fourteen public and fourteen private table snapshots are present (two per
  player), with original versions preserved and simultaneous batch cutoffs.
- Seven ballots reference saved private version 2; shadow judgments occur only
  after the ballots and are absent from all player inputs.
- All 154 local tests pass; whitespace and frontend syntax checks pass.

The separate ordinary-game name/personality UI still lacks full automated browser
interaction verification because browser-cache write permission was not granted.
That does not invalidate this provider-free replay, but the two workstreams should
not be reported as jointly ready for a fully verified release or silently committed.
