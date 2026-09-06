# Extreme-personality pilot — results

**Final: four conditions attempted; two games completed and two stopped at
protocol validation. No rejected output was repaired or retried.**
Run window: 2026-09-06 01:58:11–02:23:49 UTC.

Question: which concrete behaviors or protocol weaknesses appear when every
bounded independent personality/ability/state parameter is set to an endpoint?
Audience: the game designer; purpose: generate testable mechanism ideas, not
rank models or estimate win rates. All timestamps use UTC.

Design, endpoint values, exclusions, rules and predeclared limits:
[experiment specification](../../EXTREME_EXPERIMENT.md).

## Results

| Condition | Outcome | Completed days | Model calls |
| --- | --- | ---: | ---: |
| 0: alternating all-high/all-low | Protocol stopped on D2, no winner | 1 | 32 |
| 1: complementary all-low/all-high | Wolves won after N2 | 1 | 25 |
| 2: mixed X/Y | Wolves won after N2 | 1 | 25 |
| 3: complementary Y/X | Protocol stopped on D1, no winner | 0 | 9 |

Source artifacts: [condition 0](condition-0.json), [condition 1](condition-1.json),
[condition 2](condition-2.json), [condition 3](condition-3.json).
Condition 0 was not retried or repaired. Following inspection, the remaining
pre-approved independent conditions continued; this is not a rerun of condition 0.

Total: **91 Codex calls**, below the approved 440-call ceiling. Reported usage:
1,532,787 input tokens (406,016 cached, already included in that input total),
65,994 output tokens, and a separately reported 13,931 reasoning-output tokens.
No monetary cost is inferred from these fields. There were no recorded tool
capability events. Neither complementary pair completed both arms; the two
finished wolf victories must not be interpreted as a comparative win rate.

## Verified observations (not causal claims)

### 1. A table-only challenge gate rejected an action-based challenge

Condition 0's last response, `D2-challenge-D`, targeted B and cited E000021
(ballots), E000022 (C's night death), and E000025 (D's own table):

> 你投C后C被刀，我还是觉得有点怪。

Those were real public records. The validator rejected the challenge because
none was **B's public table**; it did not reject fabricated evidence. This is a
protocol-compatibility failure, not proof that D's inference was irrational.
The failed response was never published; the partial game has no winner.

Condition 3 stopped under the same gate at `D1-challenge-B`. B targeted G's
high-confidence wolf judgment of B and cited E000001/E000002, the rules and
death announcement used by G. The actual G table was E000009. B's text clearly
asked why those sources supported G's claim, but the machine contract required
E000009 in the evidence array. B had maximum logic/evidence/calibration in this
mixed condition. The two failures therefore do not support attributing this
problem specifically to low ability.

G's unsupported guess happened to identify a real wolf. That does not make its
argument well-supported; conversely a wolf can make a legitimate evidence
challenge. Ground-truth correctness and argument quality must be assessed
separately.

Mechanism hypothesis: permit separate challenge types for a table assertion,
an action sequence, and a claimed source, each with appropriate evidence checks.
Separate the targeted table/row from supporting or disputed source references.
Do not require every legitimate question to cite the target's table in one
undifferentiated evidence array.

### 2. Retraction did not automatically repair credibility

In condition 0, F initially accused C without evidence. C challenged F; F
acknowledged it was a feeling and changed C's public row to unknown in revision
2, explicitly recording the withdrawal. D1 ballots
then exiled F, 4 votes to C's 2. C/E/G's recorded vote reasons specifically
mentioned F's unsupported accusation followed by withdrawal; D also distrusted
that sequence. B and F still voted C.

This is one trajectory, not evidence that retracting is generally bad. A
mechanism worth testing is a distinction between an evidence-driven revision,
an admitted unsupported guess, and an unexplained reversal. Treating all changes
as contradictions would punish honest correction.

### 3. Simultaneous drafts can be misrepresented as sequential responses

Condition 1 B's `D1-challenge-B` asserted that E's initial table had failed to
respond after B announced a Seer claim and a wolf check on E. Yet both initial
tables were sealed against the same public cutoff, before either saw the other.
The public archive's per-record order is publication order, not information
availability at drafting time. B is a wolf: this may be strategic misrepresentation
rather than a model reasoning mistake. The available record cannot distinguish
those intentions.

Mechanism hypothesis: show a table's information cutoff/batch prominently and
make chronology-based challenges refer to it. Full memory alone does not prevent
misuse of chronology.

### 4. Maximum numeric settings did not guarantee a correct vote

In condition 1 B claimed Seer and falsely accused E. E truthfully claimed
villager. B/C/D/F/G voted E (5–1); B killed D on N2, reaching wolf parity.
D's recorded vote reason treated E's lack of counterclaim and weak rebuttal as
evidence against E, despite D having maximum numeric style/cognition/state
settings. E was a villager and could not truthfully counterclaim Seer.

This does not isolate the effect of logic, stress, confidence or any one field:
they changed jointly. Nor does one wrong vote prove poor calibration; a rational
player can be misled under hidden information. Prompt values cannot be described
as measured intelligence or ideal rationality. Better evidence-source distinctions
and tests of burden-of-proof handling are candidate follow-ups, not proven fixes.

## Important data and protocol caveats

Condition 2 provides a second concrete false-check trajectory, not an independent
replication with the same treatment. F claimed Seer and accused C. C truthfully
claimed villager and challenged the cited source (a night-death event). F replied
that a check is private and maintained the accusation. B/D/E/F/G voted C, 5–1.
E/G, who had high logical/evidence/calibration settings in this mixed condition,
still cited the concrete check claim and lack of counterclaim. C knew the claim
was false but could not transfer that private certainty to the table. After B
killed D on N2, wolves reached parity. Full tables did not authenticate a claimed
private information source.

- All four conditions killed A on N1, before A could publish a table. The
  first-letter target bias and lost Seer information limit their comparability
  to games where the Seer participates in debate.
- The implemented night action excludes all wolves, including the killer. Thus
  a night victim must be good even without a role flip; the public rule should
  explicitly state the no-self-kill restriction as well as no teammate kills. The lawful
  constraint helper only closes supplied private facts plus the starting role
  counts; it does not automatically promote that public deduction to a locked
  `known` fact. Inferred good remains possible. This incomplete knowledge closure
  is a protocol limitation, not evidence of a player's inability to deduce it.
- Condition 1 F's response contained serialized JSON inside the `text` string.
  It passed the field/type contract but is poor display quality. Structural
  validation is not a guarantee of useful prose; no cleanup was applied.
- Frozen learning_rate is inactive. Categorical argument style has no numeric
  endpoints; experience has no maximum. Derived values are not independent
  interventions. See the specification rather than treating every serialized
  field as an experimentally varied parameter.
- No neutral baseline, no repeated trials per condition, fixed identities and
  speaking slots, both wolves sharing a profile, early-death censoring, and
  joint changes across 21 parameters preclude a causal or win-rate conclusion.

## Validation

Assessment: **share with caveats for qualitative observations; not fit for
comparative strength claims**. Exact requests, terminal game state, usage totals
and source hashes for all four conditions were independently replay-checked with
`tests/audit_extreme.py`, without external calls. Failed and completed games have
separate denominators; profile assignments match the registered combinations and
all 21 numeric endpoints validate. There are no charts requiring visual validation.

## Next design tests (not implemented or run in this batch)

1. Separate the target statement/table from its supporting/disputed evidence;
   accept action-based challenges. Keep immutable raw records rather than
   silently repairing references.
2. Make simultaneous submission batches and information cutoffs explicit in
   player-facing context, and distinguish a new-evidence revision from a prior
   unsupported guess or a contradiction. Do not treat all revisions as lies.
3. Clarify the night rules and complete lawful deduction of publicly inferable
   facts. Counterbalance identities and candidate order so the Seer is not
   systematically removed before the debate intervention.
4. Only after those protocol checks, repeat counterbalanced games to test
   narrower dimensions. Preserve the distinction between personality tendency,
   underlying model capability and temporary state.

Outstanding: two planned conditions have no game outcome; causal strength,
personality adherence and persuasion accuracy have not been established. No
additional model calls beyond the four approved condition attempts were made.
