# Extreme-personality experiment

## Preregistered scope (2026-09-06 UTC)

Four complete **seven-seat research games**, not one-day debate fragments and
not the normal twelve-seat ruleset. A=seer, B/F=wolves, C/D/E/G=villagers remain
fixed across conditions. Night precedes day. Kill/check decisions are sealed
and resolve simultaneously. Dead identities are not revealed. Wolves win at
parity; good wins when no wolves remain. Tied votes exile nobody. The first
living wolf alphabetically chooses the pack kill; this is not team negotiation.

Living actors submit private/public seven-row tables, two host-assigned living
actors may challenge, targets respond, tables are revised, and each actor makes
a separate vote call using its latest private table. Publication is batched.
Dead players remain in historical tables but receive no further calls. Full
public history and only the acting player's private notebook are supplied.
Known facts are constrained by lawful information, not researcher ground truth.
No model judge feeds a verdict or suspicion score back into gameplay.

## Endpoint interventions

All 21 bounded independent numeric settings are frozen at an endpoint:

- Six style fields and seven cognitive fields: 0.05 or 0.95.
- Preferred/max reasoning depth: 1 or 5, with preferred <= max. Explicit
  experimental depth overrides the ordinary derived initialization formula.
- Form: -0.85/+0.85; valence: -1/+1; arousal: .10/.90;
  confidence: .18/.88; stress: .08/.82; momentum: -.75/+.75.

Experience has no upper bound, so is excluded and held at zero. Argument style
is categorical (logic/gut in this batch), not a numeric maximum/minimum.
Computed noise/condition/mood are not independent parameters. No random state
perturbation, learning or intergame carry is applied, so learning_rate is recorded
but **inactive**. This is a prompt-conditioned intervention, not a demonstrated
change to the underlying model's intelligence or actual reasoning depth.

| Condition | A/C/E/G | B/D/F |
| --- | --- | --- |
| 0 | All numeric maxima, logic argument | All minima, gut argument |
| 1 | All minima, gut argument | All maxima, logic argument |
| 2 | Mixed endpoint profile X | Complement Y |
| 3 | Complement Y | Mixed endpoint profile X |

X sets logic, caution, evidence_processing, recursive_reasoning, calibration,
learning_rate, form, confidence, momentum and both depths high; all other
numeric fields low; logic argument. Y reverses every numeric setting and uses
gut argument. Both wolves share a profile in each condition; this is a major
design constraint, not a balanced factorial study.

## Runtime and audit

All calls use the existing Codex login, gpt-5.6-terra / medium. No API keys are
read or created. Ephemeral isolated working directories; user config ignored;
tools, file/shell access, apps, memory and web disabled in the task runner.
Structural JSON schemas plus local semantic/evidence validation are required.
No automatic retries, output repair or reuse. A failure stops the batch and
persists raw answers and partial state as a failed artifact, not a finished game.

User approved up to 440 calls across four games (110 safety cap each); games
stop earlier at victory. Results record requests, answers, usage, timestamps,
source hashes, profiles, full private/public archives, actions and winners.
These are **all-private research exports**, never player-facing resources.

```sh
python -m unittest discover -s tests -p test_game_options.py -v
python -m werewolf_web.research.extreme_run --run-codex --output-dir docs/research-runs/NEW_DIRECTORY
```

The first command is deterministic wiring/privacy validation, not model evidence.
The second needs explicit external-processing approval and consumes account usage.
It refuses to overwrite any selected result file.

Codex CLI invocation follows the official [non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode),
with additional local validation and experiment-specific isolation flags.

Batch records and observations: [2026-09-06 pilot report](research-runs/extreme-2026-09-06-v1/REPORT.md).

## Analysis limits

Only one realization per combination; no neutral baseline or repeated seeds.
Profiles, argument style and state change together, so differences cannot be
attributed to a single dimension. Fixed seats and deterministic speaking/pack
leadership can cause positional bias. Early deaths censor personality exposure.
Perfect archived memory is not proof of perfect model recall. Look for concrete
table/claim/revision/vote trajectories, not a four-game win-rate conclusion.
Record failures as findings about the protocol, not about player skill.
