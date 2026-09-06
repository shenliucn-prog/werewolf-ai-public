# Shadow day: first live attempt stopped at initial-table validation

**Outcome: incomplete, not a successful debate.** Seven model calls returned
initial dual tables, but three private tables failed the frozen representation
contract. The atomic publication guard stopped the episode before any debate,
revision, ballot or shadow judgment. No response was repaired, replaced or retried.

[Raw research artifact](codex-shadow-day-2026-09-05.json) contains synthetic
owner-private game information. Never supply the whole artifact to a player.

## Execution

- Protocol: `shadow-day-v1`, Chinese, fixed seven-seat assignment.
- Model: `gpt-5.6-terra`, medium reasoning; Codex CLI `0.153.3`, existing login.
- User explicitly authorized sending synthetic role information and visible game
  conversations to Codex after an earlier attempt was blocked before execution.
- UTC: 2026-09-06 01:09:56 through 01:11:43 (September 5 in Los Angeles).
- Calls: **7 of at most 27**; all seven returned exit code 0 and strict JSON.
- Summed call time: 106.592 seconds.
- Reported usage: 70,741 input tokens, including 62,720 cached input tokens;
  4,716 output tokens; 201 in the separate reported reasoning-output field.
  No monetary cost is inferred from account-backed usage.
- All calls reported zero tool events. Each included the expected disabled-Code-
  Mode warning, but completed its text response. The failure was in the local
  table validator, not model transport or the warning.

## Failure and interpretation

| Seat | Private table | Public table | Initial declared strategy |
| --- | --- | --- | --- |
| A | Accepted in offline validation | Accepted | Reveal seer claim and C's good-faction check |
| B | Accepted | Accepted | Claim villager and hide the link to F |
| C | Rejected | Accepted | Withhold public identity pending testimony |
| D | Accepted | Accepted | Claim villager and retain uncertainty |
| E | Rejected | Accepted | Withhold public identity pending testimony |
| F | Accepted | Accepted | Claim villager with low commitment |
| G | Rejected | Accepted | Claim villager and retain uncertainty |

The validator first stopped on C. A separate, read-only audit checked all seven
responses and found the same issue in E and G. Each wrote its own private role
as `roles: ["villager", "good"]`, with `status: "known"` and the correct owner
evidence. The locked input was `villager`, and the validator requires exactly
`["villager"]`.

This is **not evidence that those seats forgot their identity or learned someone
else's secret**. Villagers are good-aligned. The prompt/schema permits a list
containing role or faction words but does not unambiguously explain whether the
list means alternatives, combined attributes, or one canonical fact. Its generic
instruction to preserve the locked role did not prevent the redundant faction
annotation. The strict validator rejected that representation as specified.

All fourteen returned tables contain seven rows. Eleven pass the existing table
checks individually; three fail. None were saved or published, because the
protocol requires the complete batch to validate first. It would be misleading
to count the seven valid public drafts as a completed first public round.

## Additional observations, not debate outcomes

The drafts do show strategic separation between private and public tables: B/F
retain their own and teammate's wolf identity privately but publicly claim
villager. This is only an initial expression, not demonstrated persuasive skill.

Two reasoning gaps deserve explicit follow-up:

1. A lists “seer or villager” as C's private alternative, despite knowing A is
   the sole seer. A preserved the narrow faction-only check correctly, but its
   free-text alternative ignored another lawful constraint.
2. B/F mark every non-wolf seat wholly unknown. They lack those seats' exact
   good roles, but the two-wolf configuration plus known teammate exhausts all
   wolves, so the remaining faction is derivable. The protocol currently has
   no separate field for “exact role unknown, faction determined” or policy for
   promoting logically derived facts to knowledge.

The source text alone also illustrates why an existing evidence ID is not proof
of support: some identity claims cite E000001, which describes configuration and
procedure but does not certify anyone's individual role.

These are reasons to clarify representation and lawful inference before using
the mode as an ideal-rationality baseline. They do not justify automatically
penalizing players or feeding research ground truth into their private tables.

## Read-only audit and local verification

All of the following checks passed:

- Every saved request exactly matches a freshly reconstructed owner-scoped
  initial request, with only the common public event and that owner's notebook.
- No request contains another player's private evidence identifiers.
- All seven raw responses pass strict JSON decoding.
- All four recorded source hashes match the source files after the run.
- Public state still contains only the host setup event; no partial table
  release, saved private table, challenge, vote or shadow result exists.
- The full local suite passes: **139 tests**. Whitespace checks pass.

These checks establish the inspected local request boundary, not a general
information-flow proof or correctness of free-form reasoning. There are **zero
emergent judge verdicts**, so no judge accuracy or gameplay success rate can be
reported from this attempt.

## Recommended next step — not executed

Version a revised representation contract that separates exact-role hypotheses
from faction knowledge and clearly defines alternatives. Keep lawful supplied
facts immutable; allow constraint-derived conclusions only from each actor's
visible facts and the public rules, with provenance. Add regression cases for
redundant role/faction labels, unique-role exclusions and exhausted wolf counts.
Then run a fresh, separately labeled episode. Preserve this failed attempt;
do not silently normalize its raw answers or merge a rerun into this result.
