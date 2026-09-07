# Conjecture mode research kernel

Status: independent, opt-in research infrastructure. This kernel is not itself
a playable mode or evidence that debate performance has improved. There is now
a separate [playable dual-table beta](GAME_MODES.md) for the browser/chat game,
and a [complete seven-seat extreme-profile experiment](EXTREME_EXPERIMENT.md).
Neither establishes ideal rationality. An isolated [model-driven shadow day protocol](CONJECTURE_SHADOW_DAY.md)
is implemented. Actual experiment records are local-only; protocol completion
does not establish better reasoning or game balance.

## Implemented

- `PublicTable` and `PrivateTable`: distinct immutable snapshot types. Every
  snapshot covers the entire fixed roster, including the actor. Unknown,
  alternative, and withheld public judgments are supported.
- `PublicArchive`: append-only public statements, events and table versions,
  exact historical lookup, and neutral row differences between versions.
- Atomic full-roster publication against one public-information cutoff. Drafts
  are validated before any table is published; citations to the same pending
  batch are rejected. Draft collection itself belongs to a future coordinator.
- `PrivateNotebook`: separately held lawful observations, private snapshots and
  records identifying which existing snapshot a decision reportedly used.
- Explicit public-only export. Private observations, private snapshot versions
  and their timing are not part of that export.
- A hand-authored seven-seat example in Chinese and English: a wolf claims to be
  the seer, a prior statement is challenged, an explanation is offered, and an
  ally subsequently cites that claim without becoming independent evidence.
- An offline debate coordinator: sealed dual-table submission, simultaneous
  release, targeted challenges/responses, explicit public revisions, host closure
  and one recorded action per seat.
- Per-observer, **hand-labelled** assessments with independent suspicion and
  credibility updates. No labels are published as an authoritative host verdict.
- Historical player/research replays. Player replays exclude other actors'
  private updates, including their frame counts; research replay is explicitly
  all-owner and must remain isolated.

Stable player, role and event identifiers do not change with display language.
Role/faction strings describe hypotheses, not verified game identities. Confidence
labels are qualitative, not calibrated probabilities.

## Run without models or network

From the repository root, using Python 3.10 or newer:

```sh
python -m unittest discover -s tests -p test_conjecture.py -v
python -m werewolf_web.research.fixtures --locale en
python -m werewolf_web.research.fixtures --locale zh-CN
python -m unittest discover -s tests -p test_debate.py -v
python -m werewolf_web.research.debate_fixtures --locale en --actor A
python -m werewolf_web.research.debate_fixtures --case reasonable_revision --locale zh-CN --actor C
```

The original `fixtures` example prints **only public records**. The new
`debate_fixtures` command prints a selected player's public history and own
private state; `--research` explicitly requests all private views. Do not share
that export with players. Neither command makes API requests or starts a server.
Outputs and classifications are scripted fixtures, not agent-generated
reasoning. The surrounding project suite may require its normal dependencies.

## Controlled debate pass

The coordinator enforces these states:

`collecting -> debating -> closed -> complete`

All seats must submit validated owner-matched drafts before release. Debate
allows one pending targeted response at a time and bounded challenges (default:
two total, one per actor). The host must explicitly force closure to end an
unanswered exchange. It does not punish that unanswered exchange automatically.
Only closed discussions accept actions, and each actor acts once. This is a
single static-roster research round, not a full Werewolf phase engine.

Five hand-authored classification cases run in both languages:

| Case | Intended observer interpretation |
| --- | --- |
| `reasonable_revision` | New public testimony explains a changed assessment |
| `different_conditions` | Statements use different conditional premises |
| `strategic_concealment` | Prior wording may have been deliberate cover |
| `unresolved_contradiction` | The response denies an archived earlier statement |
| `insufficient_evidence` | The observer reserves judgment |

The caller supplies each observer's classification separately, based on lawful
evidence. No semantic classifier verifies those labels yet. The fixtures include
observers disagreeing about the same exchange; this demonstrates state isolation,
not naturally emerging model disagreement.

In this pass, an unresolved contradiction adds `0.35 * sensitivity` to an
unknown target's suspicion and subtracts `0.30 * sensitivity` from credibility,
clamped to `[0, 1]`. These are **experimental scores, not probabilities**. Other
categories incur no penalty. Known good/wolf identities remain fixed even if
credibility decreases. Private snapshots retain the evidence and reason for each
assessment. Repeated challenges on the same target/row/evidence set do not stack.
This exact-reference deduplication does not detect semantic duplicate sources
disguised through different citations. Later reassessment/credibility recovery is
not implemented in this one-assessment-per-dispute pass.

The small fixture policy selects the highest private suspicion (stable seat
order breaks ties; a known wolf's teammates are excluded). Actors can explicitly
choose another public action. In the denial fixture, A's provisional target
changes from D to B, while F can continue publicly targeting D despite its private
knowledge of B. This checks data-to-action wiring, **not strategic optimality**.

Research replay captures before/after private table versions, per-observer score
changes, public revision history, structured challenge targets/evidence/responses,
and actions linked to existing private snapshots. Exported frames are detached
copies. Replays currently use full in-memory snapshots, so they are intended for
small fixtures, not long production games.

## Information boundaries

The archive does not hold ground truth or a registry of notebooks. A trusted
research coordinator must provision each notebook with only that actor's lawful
observations, and must never hand it to another actor. `export_for_owner()` is
intentionally private output; it must not be attached to a public response.

This is an in-process data layer, **not authentication, a sandbox, or an endpoint
authorization mechanism**. Arbitrary Python code holding all objects can read
them. A future transport needs actor authentication and explicit view construction.

Evidence IDs in public tables must exist in the public archive at the snapshot's
cutoff. A fabricated private-check claim is still a legal public claim: the
archive must not use hidden truth to decide whether a player is lying. Public
judgments cannot use the private `known` status; even a confident public account
is a player's account, not an authoritative certificate.

Reference checks do not prevent free text from revealing secrets or inventing
stories, nor do they establish that cited evidence proves a conclusion. Semantic
validation, public-expression consistency and role-specific disclosure policy
remain future work. A private `known` entry must cite available evidence, but this
layer does not independently verify the evidence's logical sufficiency.

## Deliberate limitations

- No natural-language contradiction detection. `changes()` reports a changed
  entry, not a lie. Suspicion updates require explicit observer annotations.
- No model calls, natural-language parsing, argument generation, or paid tests.
- Exact history availability is tested; actual agent recall and use are not.
- Decision records prevent references to nonexistent/old snapshots, but do not
  prove a planner actually used a snapshot. That requires integration tests.
- Fixed roster only. Alive/dead eligibility, multiple game rounds, asynchronous
  timeouts and real transport authentication remain future integration work.
  The offline coordinator now provides draft sealing, challenge budgets and
  explicit host closure. It assumes exclusive ownership of archive mutations;
  out-of-band public changes cause subsequent operations to fail closed.
- No durable disk persistence or replay importer yet. Export is a detached
  public snapshot; in-memory immutability is not tamper-proof external storage.
- No automatic changes to normal mode, no voice/avatar implementation, no new
  roles or victory conditions, and no UI work.

## Next decision boundary

The offline judgment interface and reserved evaluation set are now available;
see [Offline judgment evaluation](CONJECTURE_JUDGMENT_EVAL.md). They do not call
models or change suspicion themselves. Live research exports are local-only.
Experimental gameplay hypotheses (staged disclosure,
conditional commitments, limited formal challenges) should each be compared
against the same conjecture baseline rather than all enabled together.
