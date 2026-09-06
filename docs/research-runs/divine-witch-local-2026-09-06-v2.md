# Divine Witch frozen-extreme screen — v2

Recorded: 2026-09-06 03:00:32 UTC (2026-09-05 in Los Angeles).
Decision: does the proposed unlimited Witch have playable counterpressure
under extreme local-AI profiles, and what interactions deserve playtesting?

**Assessment: share with caveats as engineering/qualitative screening, not as
a competitive balance or human-enjoyment verdict.**

## Evidence and design

[Full compressed record](divine-witch-local-2026-09-06-v2.json.gz) contains
96 attempts, source hashes, complete public events, night actions, all private
and public conjecture tables, role assignments and Witch-proxy inputs/outputs.
This is a researcher artifact with hidden identities, **not a live player view**.
Decompress to inspect JSON; no live opponent receives this aggregate record.

- All attempts used the normal twelve-seat GameSession, with conjecture beta
  on, a local Brain for each NPC and a local Brain proxy at the human Witch seat.
  There were **zero external model calls**. No model strength claim is made.
- Seeds 0–7, four layouts, three boards. Conditions 0/1 alternate all-high and
  all-low profiles across sorted stable player IDs and then complement them.
  Conditions 2/3 use complementary mixed profiles from `extreme_profiles.py`.
  Profiles are matched across boards for each seed/condition; identities are
  shuffled by seed, while the human proxy is deliberately always Witch.
- The 21 bounded numeric inputs are endpoints: six style, seven cognition,
  two depth values and six state values. Categorical argument style is logic/gut;
  experience is fixed at zero; learning, state reactions and carry are disabled.
  Base persona text/catchphrases remain seed-matched, not endpoint variables.
- Ordinary wolf self-kill, first-night-only Witch self-save, Guard collision,
  sheriff and death-role reveals remain in force. These are not the no-reveal,
  no-self-kill seven-seat Codex research rules.
- Per-board denominator: 32 attempted games. All completed; no failures or
  draws. The 20-cycle experiment cap was never reached. Replay is verification
  of the same observations, not additional independent experimental games.

## Independently recomputed totals

| Metric | Classic | Unlimited single | Unlimited dual |
| --- | ---: | ---: | ---: |
| Attempts / complete | 32 / 32 | 32 / 32 | 32 / 32 |
| Good wins | 11 | 16 | 16 |
| Wolf wins | 21 | 16 | 16 |
| Rescue attempts | 32 | 78 | 71 |
| Poison attempts | 28 | 35 | 45 |
| Poison attempts on wolves | 19 | 22 | 30 |
| Poison attempts on good players | 9 | 13 | 15 |
| Both-potion nights | 0 | 0 | 19 |
| Guard/save collisions | 4 | 13 | 10 |
| Nights Witch alive at action collection | 105 | 116 | 100 |
| Witch alive at game end | 8 | 12 | 13 |
| Maximum nights reached | 7 | 10 | 7 |

Rescues are attempts, not successful survival: poison or Guard overlap can
still kill the target. Poison counts classify the selected target's true
faction only during researcher analysis. Extra potions also extend or shorten
exposure, so raw counts are not matched per-night causal rates.

Good wins by layout, each out of eight seeds:

| Layout | Classic | Single | Dual |
| --- | ---: | ---: | ---: |
| 0: alternating high/low | 3 | 4 | 4 |
| 1: complementary low/high | 4 | 4 | 4 |
| 2: mixed X/Y | 3 | 7 | 7 |
| 3: complementary Y/X | 1 | 1 | 1 |

## Traceable case observations

Locate each case by `games[board, seed, condition]`, then its `nights` array.

### More powers did not guarantee a better result

Seed 3, layout 0, Witch at seat 6: single-mode good wins; dual-mode wolves win.
Both modes poison innocent seat 11 on night 2. Single mode later poisons wolf
seat 10 on night 3. Dual mode instead rescues seat 1 while poisoning innocent
seat 3 on night 3. These are diverging local-policy trajectories, not proof
that the second potion itself causes a loss in all otherwise-equal situations.

### Poisoning three wolves can still lose

Seed 5, layout 1, Witch at seat 3: both unlimited modes poison wolves at seats
4, 12 and 6 over nights 3–5, but wolves still win after night 7. Night 3 the
Guard saves the Witch from the knife; night 5 she is attacked again without
that protection and cannot self-save. The Witch's ability remains powerful
but temporary, dependent on survival and the wider board's win conditions.

### Repeated rescue creates a coordination problem

Seed 6, layout 2, single mode: on night 5 the knife, Guard and Witch rescue
all select seat 6, triggering the existing fatal overlap rule. In this
particular game good still wins; the collision is a cost, not a loss label.
Across the screen such overlaps rise from 4 to 13/10. This suggests studying
credible public Guard/Witch commitments and wolf deception around them.

## Reproducibility correction and retained precheck

The earlier [v1 precheck](divine-witch-local-2026-09-06-v1.json.gz) is retained,
compressed losslessly. Its figures are **superseded**, not pooled into v2.
Cross-process replay exposed unordered set traversal in suspicion aggregation.
Because evaluating a new speaker can consume that actor's private RNG for a
gut prior, iteration order could change later decisions. The engine now sorts
unique accusers, defenders and voters before processing; check-result name
formatting is also stable. This can change earlier seeded trajectories without
changing the potion rules. The complete 96-game matrix was rerun after the fix.

The main audit verifies recorded source hashes, all 32 matched role/profile
blocks, aggregate counts using a separate computation, and an exact rerun of
every game. Unit coverage also compares games under different Python hash seeds.

```sh
python tests/audit_divine_witch.py docs/research-runs/divine-witch-local-2026-09-06-v2.json.gz
python -m unittest discover -s tests -p 'test_divine_witch.py'
```

## Interpretation limits and next decision

The 16–16 split does not establish fairness. There are only eight initial seeds,
related profiles, fixed local policies, an AI proxy instead of a human, and
matched—not independent—conditions. Full public tables do not guarantee ideal
reasoning. NPC poison thresholds and public-claim wolf priorities are hand-coded;
neither side is an adaptive LLM searching for an optimal exploit.

Useful hypothesis: infinite supply shifts difficulty from rationing to
**coordination, accuracy and protecting the decision-maker**. Keep the strong
dual board available for single-player playtesting and retain single mode as
a nightly-choice comparison. Next examine explicit Guard/Witch agreements and
wolf fake agreements. Do not rebalance simply to reproduce the observed 50%.
