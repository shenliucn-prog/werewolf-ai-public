# Mechanics lab v2 — prepared, not live-tested

## Purpose and boundaries

Invent text-native interactions that create meaningful choices, not just more
dialogue. This is a **research-only seven-seat conjecture game**, not a new
default rule for normal twelve-seat games. Voice and visual gameplay remain
undesignated and unimplemented. Extreme personality values remain frozen at
their original endpoints; they are prompt interventions, not measured human
intelligence or guaranteed control of model reasoning.

Implementation: `werewolf_web/research/mechanics_lab.py`. It composes the v1
engine without modifying v1 research sources. The prior [four attempts](research-runs/extreme-2026-09-06-v1/REPORT.md)
remain immutable: two completed games, two protocol failures, 91 model calls.
The failures are not losses and unused calls from that approval are not a new
experiment authorization. **This stage performs zero new model calls.**

## Corrected baseline

- A challenge points to a `target_record` and, for a table, `row_player`.
  Its separate `evidence` list contains supporting OR disputed sources and
  need not repeat that target. Historical tables, public statements and
  public ballots can be questioned. Only living actors can challenge/respond.
- Every target/source reference must already exist in the public archive.
  Private and future references are rejected. The host checks record ownership
  and structure, not whether a natural-language argument is persuasive or true.
- Requests explicitly list each public table's version and sealed information
  cutoff. Same-batch publication order does not grant earlier knowledge.
  This exposes chronology for argument; it is not a semantic lie detector.
- No wolf self-kill or teammate kill is permitted in this particular ruleset.
  Public night deaths therefore imply good faction, not a specific role.
  Lawful candidate closure now includes that deduction for every actor without
  consulting hidden truth. **Do not generalize it to boards allowing self-kill.**
- Researcher-controlled role rotations 0–6 move identities across all seats;
  each owner sees only their role, lawful teammates/checks and public history.
  Rotation values/full assignments are absent from player requests.

## Two implemented candidate mechanics

| Arm | Changed rule | New decision | What could go wrong |
| --- | --- | --- | --- |
| Baseline | Corrected protocol, two host-assigned challenge slots/day | Which argument to challenge | Early role claims dominate |
| Tickets | Each actor has one challenge ticket for the entire game; pass keeps it, a real question spends it, responses are free | Spend now or save for a later host slot | Hoarding or denied opportunity suppresses useful discussion |
| Receipts | Every changed public identity/faction/candidate/confidence row gets a public category, explanation and optional public sources | Correct openly, explain new evidence, or acknowledge strategic change | Extra form-filling; strategic false explanations |

Receipt categories are `new_evidence`, `correction`, and `strategy`.
`new_evidence` requires a public source; the other categories may have none.
These labels are the **speaker's claims**, not host certifications. Players can
conceal private information or lie publicly. The host never automatically
punishes a correction, awards truth points or discloses private evidence.
Text-only rationale edits do not require a receipt; changed judgment fields do.
Every full roster remains in the tables, including dead subjects.

Tickets do not grant extra turns: the host still chooses at most two initiators
per day, closes each question after one answer, then orders revision and voting.
This first implementation tests scarcity within that schedule, **not** free
interruption, auctions, unlimited questioning or player-selected turn order.
Do not combine the two mechanics until each has been examined separately.

## Proposed next screening — approval still required

Prepare **12 games**: 3 arms × 2 role rotations (0, 3) × 2 complementary extreme
personality layouts (conditions 2, 3). Within each four-condition comparison
block the three arms share identities, personalities and host scheduling rules.
Models are stochastic and decisions can diverge; these are not identical
counterfactual trajectories. Two rotations are partial counterbalancing, not a
complete balance study. The alphabetical wolf selector and first-candidate
bias remain known confounds; later work should vary initiative/candidate order.

Inspect the proposal without running a model:

```sh
python -m werewolf_web.research.mechanics_lab
```

Its status is `draft_requires_approval`, with `provider_calls_allowed: 0`.
There is deliberately **no live runner for v2 yet**: the v1 runner must not be
reused unchanged because schemas and audit reconstruction differ. Before a
live pilot, wire a bounded v2 runner, save source hashes and exact requests,
add exact replay verification, choose the model/runtime, and obtain explicit
approval for game count, maximum calls and transmitted information. Keep the
six-night safety stop, stop on protocol failure without hidden repair/retry,
and record incomplete attempts separately. Do not automatically expand.

## How we look for a new game

For each attempted condition keep an evidence card with event IDs and quotes:

1. **Opportunity and choice:** who had a host slot; ticket offered/spent/passed;
   why they chose that move, and the alternatives described in their own words.
2. **Information use:** target claim, disputed source, reply, later public
   revision and the actor's owner-private table/vote. Full private state belongs
   only in the post-game researcher export, never an opponent's request.
3. **Novel interaction:** a saved question used later, a source dispute that
   forces clarification, a credible correction, a strategic fake correction,
   or a coalition formed around a verifiable commitment. Log counterexamples
   and dull/non-events as well as interesting successes.
4. **Costs:** extra response length/calls, abandoned opportunities, protocol
   failures, repetitive receipts, and host interventions. More text is not
   automatically more useful information or better play.
5. **Outcome:** completed/stopped, winner if completed, day reached. Denominator
   for completion is all attempts; ticket-use denominator is eligible slots
   with a ticket, not all players. Changing-mind counts are not lie counts.

After screening, select at most one promising mechanic and state one concrete
new hypothesis; rotate all seven identity assignments and repeat before any
comparative strength claim. Preserve unsuccessful branches. A useful candidate
must create a distinct choice and observable response without needing hidden
truth from the host. Fun and usability require later human playtesting.

## Validation assessment

**Share with caveats as preparation, not evidence of better gameplay.** Local
tests cover all 3 arms × 7 rotations × 4 extreme layouts (84 simulated full
games), separate target/source references, chronology metadata, public-only
closure, ticket accounting, receipts and atomic invalid-batch rejection.
The full-game fixtures use deterministic mock decisions, usually passing
questions; targeted tests exercise real challenge/receipt transitions.
These tests establish protocol operation, not model behavior or enjoyment.
Schema checks cover top-level compiler/engine agreement; provider acceptance
and real model adherence remain unverified. No new live results are claimed.

Reproduce with:

```sh
python -m unittest discover -s tests -p 'test_mechanics_lab.py'
python tests/audit_extreme.py docs/research-runs/extreme-2026-09-06-v1/condition-0.json docs/research-runs/extreme-2026-09-06-v1/condition-1.json docs/research-runs/extreme-2026-09-06-v1/condition-2.json docs/research-runs/extreme-2026-09-06-v1/condition-3.json
```
