# Shared faction hypotheses: first prototype

This increment supports both local choice agents and model agents. It is not
a claim of improved win rate, calibrated probabilities, or a reproduced AIWolf
competition agent.

## Research and adaptation

We inspected `Assignment.py` and `RolePredictor.py` in the official
[2023 ddhb source archive](https://aiwolf.org/en/archives/2954), alongside its
[algorithm description](https://aiwolf.org/control-panel/wp-content/uploads/2023/09/ddhb.pdf).
ddhb enumerates role assignments in small games, searches a bounded set in
larger games, scores assignments, and aggregates their relative weights.
Its assignment evaluator also rejects states where wolves have reached parity.
That rejection must NOT be copied into our game: our wolf victory is elimination
of either all civilians or all gods, not numerical parity. Our public death
reveals and special-role check rules differ too. No external source code was
copied or executed.

The first implementation deliberately models only **wolf/good faction sets**,
not full roles or pairwise claim likelihoods. It conditions heuristic per-person
weights on the public initial wolf count, own role, public flips, known pack
members, and recognized private seer results. Dead seats remain in the roster,
so their revealed factions consume the original count. A human check does not
establish good faction on a board containing the hidden wolf.

## Two consumers, separate authority

- Local good-side voting and choice speech use the faction marginals. Wolf
  public-pressure tactics remain separate: knowing someone is good does not
  explain how to persuade the table to exile them.
- Model requests receive an optional private `joint_hypotheses` section, clearly
  labelled heuristic and uncalibrated. The model still selects every action.
  Under context pressure this aid is removed before original source evidence.
  API, command, and Codex adapters share the same observation assembly.
- The aid is not a public event, conjecture table, or spectator response.
  It neither makes another model request nor replaces a failed model decision.

## Reproducibility and limits

The solver takes plain observations, not an engine. Its trusted adapter reads
the public roster/role multiset and the existing per-seat information policy.
It does not read opponents' dealt role fields for inference. Results are
recomputed without RNG consumption or snapshot changes, including on restore.
Up to 15 seats are supported; only three highest-weight hypotheses are displayed,
but marginal weights use all feasible faction combinations. Ties are ordered
deterministically and are not evidence that the first displayed set is true.

## Increment 2: attributed opinion relations

Accuse/defend metadata now contributes a weak pairwise factor per candidate
world. An accusation favors opposite factions, so a truthful good accuser and
a deceptive wolf accuser remain distinct alternatives. Defense weakly favors
the same faction. These are hand-authored assumptions, not fitted likelihoods;
mistakes, bussing, and cross-faction support retain nonzero weight.

Repeated opinions are deduplicated and total influence is normalized per
speaker. Only the latest recorded day for a speaker/target pair participates;
opposing opinions on that same day cancel instead of inventing intra-day order.
Once a target flips, the pair factor is removed because the existing suspicion
memory already incorporates that flip. This avoids adding the same relationship
again in the new layer; it does not certify all old suspicion updates as calibrated.

Tests compare the same synthetic situation with and without the factor: a known
good accuser increases target weight; a known good target increases accuser
weight; repetitions/order do not matter; hard facts survive contrary opinions;
restore preserves inference. This is a mechanism test, not a strength benchmark.

Local smoke comparison (2026-09-10): classic board, seeds 0..19, automatic
OfflineSession player, same v1 solver with pair factors disabled versus enabled.
All 40 games finished; public speech/ballot trajectories differed in all 20
pairs. Good/wolf results were 16/4 without factors and 18/2 with factors.
Both sides changed policy at once, so this is neither an individual-agent
strength test nor evidence of better balance. The good-side skew is a warning
to investigate with larger, mixed-policy and seat-balanced experiments before
making a playing-strength or balance claim. No real model games were run.

### Mixed-policy pilot

Reproduce with `python -m scripts.compare_joint_policies --seeds 24`.
For each seed 0..23, run one all-v1 baseline and twelve variants, each with only
one seat receiving v2 relations. Initial dealt roles are asserted equal between
each pair. The automatic human-seat proxy participates under the same policy
selection. Total: 312 completed games and 288 correlated seat comparisons.

| Upgraded seat faction/role | Pairs | Baseline wins | Upgraded wins |
| --- | ---: | ---: | ---: |
| Good (all roles) | 192 | 144 | 150 |
| Wolf | 96 | 24 | 24 |
| Civilian | 96 | 72 | 71 |
| Seer | 24 | 18 | 20 |
| Guard | 24 | 18 | 19 |
| Witch | 24 | 18 | 20 |
| Hunter | 24 | 18 | 20 |

Role rows decompose the faction rows; do not add them together. Good seats
improved in 17 pairs and regressed in 11. Wolf seats changed no win/loss outcomes.
At the seed level, summed focal-seat win deltas were positive in 6 seeds,
negative in 5, zero in 13. These are not 288 independent samples; each seed's
baseline is reused. Subsequent RNG use can diverge after policy changes.

Conclusion: no broad improvement claim. Civilian performance needs investigation;
wolf deception/persuasion is not upgraded by this faction-inference change.
No gameplay weights were tuned to these seeds. Model use remains validated by
request-contract tests, not by this offline pilot or real-model win rates.

### Follow-up diagnosis and corrections

Audited all eight civilian win-to-loss pairs from the pilot. Their first public
divergence was a sheriff ballot in five pairs, exile ballots in two, and an
election speech in one. This locates divergence, not a proof of the full causal
chain to losing.

Two independent correctness issues were reproduced and corrected:

- The local planner used the same suspicion-maximizing utility for sheriff
  and exile, and removed wolf teammates even in a sheriff election. It now
  treats the badge as support: good players prefer good-faction estimates;
  wolves may support known teammates. Self-support is allowed only when self
  is in the supplied sheriff candidate list. Exile exclusion is unchanged.
- A player's own accusation was fed back into that player's inferred beliefs.
  Own opinions are now excluded from the pair factors. They remain in public
  memory for commitment checking and may affect other players. Model guidance
  explicitly makes the same distinction. This correction is independent of
  whether it improves the sampled win rate.

New comparison runs include the sheriff correction in **both** baseline and
upgraded arms. Do not directly attribute their changed totals versus the older
pilot to the relation factor alone.

Rerun on the same 24 seeds (312 games): good focal-seat wins 128/192 to
133/192; civilian 64/96 to 68/96; seer 16/24 to 16/24; guard 16/24 to 16/24;
witch 16/24 to 15/24; hunter 16/24 to 18/24; wolf 32/96 to 32/96.
Seven seed-level deltas were positive, seven negative, ten zero. These are
reused diagnostic seeds, not a held-out confirmation. The relation feature
still does not justify a broad playing-strength claim.

Wolf-policy direction (partially implemented below): separate private faction
knowledge from the public story; compare legal speech options using public
commitments and visible audience votes/opinions, never other brains' private
beliefs. Preserve fabricated check continuity, price contradictions, and allow
defense/abstention rather than mechanically inventing another black check.
Local agents would score these options; model agents would receive the same
public evidence and commitments without a forced answer. Test on held-out
seeds and mixed opponents before describing it as an improvement.

### Public-story v1 prototype

`ai/public_story.py` derives a bounded, read-only aid from public accusations,
defenses, exile ballots, and the actor's own public role commitments. It never
reads other agents' brains, private checks or unrevealed roles. Each living
speaker/target pair contributes at most its latest dated stance; contradictory
stances on the same day cancel rather than inventing within-day ordering.
Only the latest exile ballot per living voter contributes; sheriff votes do not.
Own accusations add no audience support. Reversing an earlier defense incurs
a soft cost, not an absolute ban. Old opinions decay with day distance.

Offline wolves use a small public-pressure adjustment in exile votes and
ordinary speech targeting, and use it to select new fabricated check targets.
Ties use the existing private RNG. Already recorded fabricated checks do not
change when the audience changes. Automatic bluffing no longer switches from
an already claimed non-seer role into seer. The subsequent v2 increment below
adds defense, explained reconsideration and varied fabricated reports; it is
still not a full dialogue planner or learned opponent model.

Models receive the same optional `public_story` data and retain the final choice.
It is dropped before source evidence when the request budget is exceeded. No
additional model calls or snapshot fields are introduced. Numeric weights are
explicit uncalibrated heuristics, not learned audience response probabilities.

`python -m scripts.compare_public_story` ran 48 classic offline auto-play games,
24 paired seeds 100–123 not used in the earlier diagnosis. Both arms retain
claim-continuity safeguards and joint inference; only public-pressure scores are
zeroed in control. Wolf wins: **5/24 control, 6/24 scorer**, with three improved,
two regressed, nineteen unchanged pairs. Subsequent random draws can diverge.
This small single-opponent-family ablation does not establish stronger overall
play, calibrated beliefs, model benefit, or better human experience.

### Dialogue v2: support, reconsideration and stable disguise

`ai/wolf_dialogue.py` adds choice-driven offline behavior. Non-bluff wolves can
claim civilian or hunter according to personality and the public board roster,
without acquiring that role's skills. A loyal character can support an otherwise
unchallenged target backed by public defenders; this is not automatic pack
protection. Repeated identical statements fall back to the ordinary choice path.

New fabricated reports can be good or wolf, based on public pressure, rather
than always issuing a black check. Unchecked targets are preferred. Re-checking
a target retains the old claimed result; legacy contradictory reports are not
silently repaired. No report is created before night one. Ordinary speech does
not suddenly accuse a previously fabricated-good target or support a fabricated-
wolf target. These are scripted continuity constraints, not restrictions on a
human's or model's legal ability to bluff.

Public-story v2 supplies the day of the actor's earlier stance and attributed
accusations from strictly later days. Offline reversals cite a real speaker and
day and explicitly say the accusation is not proof. Without that material the
script asks a question instead of silently reversing. Same-day ordering is not
invented from legacy day-only logs. Models receive this optional source summary
and discussion options, but do not run the offline dialogue selector.

Nine new tests cover actual support/reversal speech paths, both languages,
identity claims without changing real roles, mixed fabricated results, repeat-
target continuity, JSON snapshot/RNG continuation, public-source isolation and
the pre-night boundary. Full suite: 672 tests passing, plus browser DOM/syntax,
release and whitespace gates.

Paired ablation commands (no tuning between batches):

```sh
python -m scripts.compare_wolf_dialogue --seed-start 200 --seeds 24
python -m scripts.compare_wolf_dialogue --seed-start 300 --seeds 24
```

| Seeds | Control wolf wins | Dialogue wolf wins | Improved / regressed / unchanged |
|---|---:|---:|---:|
| 200–223 | 5/24 | 15/24 | 11 / 1 / 12 |
| 300–323 | 2/24 | 17/24 | 15 / 0 / 9 |

All 96 games finished. Control disables the new dialogue helpers while keeping
shared inference and pressure scoring; this is not a frozen release comparison.
Treatment produced 201 supportive utterances (including good-check reports),
86 civilian claims and 40 hunter claims across both batches. Raw counts are
game-length dependent, not quality scores. No natural explained reversal occurred
in either batch: that path has targeted test evidence only.

The large win-rate shift replicates against this one deterministic opponent
family, but may reflect susceptibility to role claims or fabricated good checks.
It is not evidence of balance, human-facing quality or real-model improvement.
Next evaluation should separate the effects of role claims, check polarity and
support, and test opponents that resist unverified claims. No real model calls,
user games or private local records were used or published.

### Factor separation before changing good-side inference

`python -m scripts.compare_dialogue_factors` uses fresh seeds 400–423 with
control, claims-only, reports-only, support-only, reversal-only and all-enabled
variants. The public-move mask bypasses the claim branch without accidentally
disabling support. Empty factors reproduce the control; invalid factors fail.
The reports factor bundles polarity, target selection and continuity, so it
does not isolate fake gold checks alone. The shared baseline correlates pairs;
later random draws and game length may differ. Results go to stdout, not user
saves or repository data files.

The initial diagnostic indicated contributions from claims and reports and a
larger combined effect; support alone was not a clear improvement. This is a
reason to inspect how good-side agents evaluate claims, not proof of a single
bug or permission to tune belief weights to force equal win rates. Models
still choose their actions, and no real-model calls were used in this audit.

中文：新增六组独立开关实验，先查收益来源，再审查好人如何评估声明。
查验组同时包含报告正反、选人、连贯性，不能把收益全部归于假金水；共享对照和
随机轨迹差异也限制结论。本步未修改好人判断权重，不以五五开为调参目标。

### Resolved-evidence accounting correction

Targeted reproductions found that repeating the same support or accusation
multiplied the observer's score update when its target flipped. The legacy
on-demand suspicion path also accumulated the same resolved relationship once
per repeated utterance. Both now count a speaker/target/stance relationship
once, retaining distinct speakers and different targets. No coefficients were
retuned. Repetition remains in the public transcript, not independent evidence.

Exile accounting now uses unique voters from that day's exile ballot only;
older votes and sheriff votes do not become extra votes in a later settlement.
Existing flip/exile deduplication still prevents repeated settlement on restore.
Model prompts explicitly distinguish resolved target identities from the
speaker's credibility: a wolf can make a correct claim or fabricated good check.
Models also receive the corrected shared inference aid, without forced actions.

Six focused tests cover repeated support/accusations, shared inference and
legacy-score invariance, current-day unique voters, separate speakers, restore
idempotence and preserving old accumulated scores. No checkpoint fields changed.
Old saves remain readable but already accumulated score bias is not silently
recomputed; use fresh games for full corrected-accounting evaluation.

The six-arm synthetic experiment was rerun after correction without retuning.
The combined wolf-policy advantage persisted. This closes accounting bugs, not
a claim of balance or proof that those bugs caused the prior win-rate change.
The report/role-claim effects still need stronger-opponent and diverse-board
testing; no real-model improvement was measured.

中文：修复翻牌后重复踩保被成倍记账，以及放逐结算混入往日/重复投票。
保留原权重，不为胜率调整参数；模型得到正确去重的辅助推断与证据边界提醒。
旧档可恢复但不追溯重算累计偏差。重跑实验后狼人优势仍在，本轮只关闭计数错误，
不宣称完成平衡或验证了真实模型收益。

### Cross-board and observation-path validation

`python -m scripts.compare_policy_matrix` runs 96 synthetic games: classic,
hidden-wolf/crow and stone-ghost boards, two good-side inference policies, eight
fresh paired seeds 500–507 per combination. The unary opponent keeps original
roster constraints and lawful private facts but omits pairwise opinion factors;
the joint opponent retains them. These are ablations of one offline family,
not independently developed or proven stronger opponents. Wolf dialogue is
enabled/disabled in each pair, with initial roster equality checked. All games
completed; benefits varied by board and opponent, with no net improvement in
some combinations. The tiny samples and differing later random draws do not
certify balance or real-model performance.

The real-session evidence test exposed a localization mismatch: observer flips
store display labels (`预言家`/`Seer`) while the dedicated model-context section
only recognized `seer`. Both language paths lost old public Seer statements
from that section. Public flip events now retain the stable role and name from
the engine's already-public event; the context builder also accepts old localized
flip labels. No hidden role query or private check is used. Statements remain
attributed, bounded and removable by the overall request budget, not certified
check results. Tests traverse actual speech observation, engine death/flip,
session publication and final model request; the fake runtime can still abstain.

Changed-role tests preserve both source-linked claims rather than overwriting
the earlier statement. Unrevealed claimants and publicly revealed wolves are
not promoted into the publicly-flipped-Seer section. This is evidence delivery,
not proof that every policy correctly interprets contradictions. Full structured
per-night claimed-check auditing and cross-role consistency remain unimplemented;
free-text statements are not silently converted into authoritative check records.

中文：三板子、两种同源推断策略的配对验证已完成，但不同组合收益不同。
真实会话测试发现并修复中英文翻牌标签导致的证据遗漏。已验证来源保留与身份
边界，尚未实现完整的逐夜查验声明对账，也不宣称模型一定能正确识破所有谎言。

This does not yet model exact role uniqueness, structured check-report relationships,
stone-ghost private role deductions, opponent learning, or lookahead search.
The soft inputs still come from existing suspicion memory. Improved playing
strength must be evaluated separately with paired games and diverse opponents;
passing rule-flow and privacy tests is not evidence of stronger play.

中文摘要：首批是两种模式共用的狼队组合辅助推断，不是完整角色推理。
离线玩家使用结果；模型可参考但仍自主决策。它不增加模型调用、不公开
私有假设、不改变存档格式。下一阶段才评估声明关联、完整角色约束及实战收益。
