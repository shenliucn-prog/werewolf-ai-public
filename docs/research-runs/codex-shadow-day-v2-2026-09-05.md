# Shadow day v2: role/faction split works; unknown-state encoding still fails

**Incomplete episode.** The authorized fresh attempt made seven initial model
calls, then stopped before atomic table publication. No debate, revision, ballot
or shadow verdict was produced. No retries, raw-answer normalization or repairs
were applied. [Raw researcher-only artifact](codex-shadow-day-v2-2026-09-05.json).
The original v1 failed artifact remains unchanged.

## Protocol changes

- `roles` contains exact-role hypotheses only (seer, villager, werewolf).
- `faction` separately contains good/wolf or empty, with its own `faction_status`.
  A player can know a faction while the specific role remains unknown/inferred.
- A deterministic constraint helper enumerates feasible assignments for the
  **fixed** 2-wolf/1-seer/4-villager board from the actor's own supplied facts and
  public configuration only. It receives no research ground-truth map.
- All-world conclusions preserve known roles/factions; source references include
  the public configuration and that actor's private facts. Candidate private
  roles cannot violate these lawful constraints. Public claims may still deceive.
- Ordinary-game random names/personalities are not part of this experiment.

The new fields are optional in the older research record API for compatibility;
the v2 experiment explicitly requires them. The semantic judge prompt is unchanged.

## Observed outcome

All seven calls returned strict JSON and separated role from faction. The v1
`["villager", "good"]` issue did not recur. With the deterministic helper's
lawful constraints supplied, A describes C as a villager from its sole-seer
identity and good-faction check; this is not independent model discovery.
Both wolves preserve the other five players' good factions without claiming to
know which one is the seer.

However, A and D put candidate roles in `roles` while setting `status: "unknown"`.
For example, A's B row contains `["villager", "werewolf"]` with unknown status.
The existing contract says unknown rows must have an empty role assertion list.
This happened in both their private and public drafts: **4 of 14 tables fail**;
the other ten pass individual offline validation. All fourteen cover seven seats.

This is an encoding failure, not evidence of a changed identity or a contradiction
between the candidates themselves. The response schema describes role alternatives
while the status rule treats the same list as an assertion. Even an explicit prose
instruction about empty unknown lists did not make the boundary reliable.

A's private strategy prose also refers to four unchecked seats although five
remain outside A/C. The structured closure does not check arbitrary natural-language
arithmetic or rationales. It is not proof of ideal rationality.

## Audit

- Model `gpt-5.6-terra`, medium reasoning; Codex CLI `0.153.3`.
- UTC 2026-09-06 01:18:56–01:21:19, September 5 in Los Angeles.
- Seven calls, 143.626 summed seconds, no reported tool events.
- Usage: 74,602 input tokens (62,720 cached); 6,864 output tokens;
  separately reported reasoning-output field: 751. No currency cost inferred.
- All saved requests match freshly reconstructed owner-only requests exactly.
- All five recorded source hashes match the files after execution.
- No table was partially published or saved; all votes and shadow results remain
  empty. The episode stopped at the first invalid draft, not after losing a game.

## Next proposed change — not run

Give **candidate sets** and **asserted judgments** explicitly distinct fields (or
use a tagged schema with an unambiguous unknown variant), and constrain model
output structurally before running an entire seven-seat batch. Keep supplied and
lawfully derived facts immutable and keep unmodified raw responses in the audit.
Do not convert failed unknown-state outputs into successful gameplay after the fact.
There is still no evidence from this attempt about debate quality or judge accuracy.
