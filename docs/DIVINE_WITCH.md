# Divine Witch — playable experimental boards

Status: implemented for browser and conversation play, with Chinese/English
rules, selectable player role, optional conjecture beta and NPC support.
**Experimental, not balance-certified.** Classic remains the default board.

## Play now

In the browser choose **Divine Witch · Unlimited, both potions/night**, then
choose **Divine Witch** under **Your role**. Leave Conjecture off for ordinary
conversation or enable it to retain versioned public conjectures.

```sh
python -m werewolf_web.chat_game --board divine_witch_dual --role witch --offline --conjecture
python -m werewolf_web.chat_game --board divine_witch --role witch --lang en --offline
```

Both boards retain the Classic composition: four wolves, a Seer, Witch,
Hunter, Guard and four villagers. `witch` stays the stable role ID;
“Divine Witch” is its board-specific name, not a second Witch in the roster.

| Rule | Classic | Unlimited single (`divine_witch`) | Unlimited dual (`divine_witch_dual`) |
| --- | --- | --- | --- |
| Total potion supply | One antidote and one poison/game | Unlimited across nights | Unlimited across nights |
| Nightly use | Save OR poison | Save OR poison | Save AND/OR poison, one target each |
| Self-save | Night one only | Night one only | Night one only |
| Other limits | Living actor/targets only | Same | Same |
| Long-game guardrail | No new limit | Draw after 20 complete cycles | Draw after 20 complete cycles |

Antidote saves tonight's knife victim, not previously dead players. A dead
Witch cannot act on later nights, but actions chosen alive resolve normally
on the night she is killed. Poison cannot target the Witch herself. Saving
does not cancel poison; guard plus antidote on the same knife victim remains
fatal under this project's existing “milk-through” rule. Wolves can self-kill
or kill teammates on these twelve-seat boards; a saved player is not certified
good. Winning conditions remain all wolves eliminated vs either all special
roles or all villagers eliminated. The round cap is public, not a hidden
balance intervention. Terminal dual input: `save 3 poison 7` / `救 3 毒 7`.

The dual version tests the proposed strong power directly. The single version
is a separate comparison, not an undisclosed nerf of the dual version.

## NPC adaptation and information boundaries

- All actors receive the public variant rules; opponent identities and the
  fact that the human chose a role are not revealed.
- Wolves assign greater night priority to someone publicly claiming Witch
  under unlimited rules. This is based on the claim, never the hidden role.
  Bluffing remains possible; claimed Witch is not certified Witch.
- An aggressive single-potion Witch may forgo rescue to poison a very strongly
  suspected wolf. A dual Witch may rescue and poison on the same night.
- Unlimited supply removes stock conservation, not the cost of killing an
  innocent. Local AI retains suspicion thresholds rather than blindly poisoning.
- Rules chat, own-role description, action prompts and setup labels describe
  the selected variant. Default and original boards keep finite potions.

## Frozen-extreme screening result

See the [validated v2 report](research-runs/divine-witch-local-2026-09-06-v2.md).
This is **local strategic AI**, not an LLM decision experiment or human study.
Every seat, including a Witch proxy for the normal human player, uses the
existing Brain; the playable conjecture beta is enabled. Personality traits,
bounded cognition and state are frozen at their documented endpoints.

96 games: 3 boards × 8 seeds × 4 complementary endpoint layouts. Each seed and
layout has the same role/seat/name assignments across boards. All 96 finished
with a winner. No draw limit was reached; no external model calls were made.

| Board | Good wins / 32 | Wolf wins / 32 | Poison attempts on good players | Guard/save collisions |
| --- | --- | --- | --- | --- |
| Classic | 11 | 21 | 9 | 4 |
| Unlimited single | 16 | 16 | 13 | 13 |
| Unlimited dual | 16 | 16 | 15 | 10 |

The observed 16–16 totals are **not proof of balance**. These are only eight
initial seeds, fixed local policies and four related personality layouts.
The same intervention can help one layout and hurt another. The two unlimited
variants have equal aggregate wins but do not win the same individual games.

## What this suggests for new play

1. **Coordination can replace scarcity.** Repeated rescue creates more chances
   for Guard/Witch collisions. Players could publicly agree on who covers
   which target, while wolves forge claims or disrupt those agreements.
   Public commitments are a strategy available through existing conversation,
   not a newly enforced or truth-certified mechanism.
2. **More powers amplify bad reads too.** Dual action increases both successful
   wolf poisoning and mistaken good-player poisoning. It is not merely a
   faster guaranteed victory. Single action adds a sharp rescue-vs-kill choice.
3. **Witch survival becomes a team resource.** After night one the Witch cannot
   self-save, so wolves can hunt her and allies can protect her. This preserves
   a counterplay window without secretly weakening her potion supply.

Keep both experimental boards available. Use the dual version for direct
single-player playtests of the proposed fantasy and single mode as the control
for nightly tradeoffs. Next test deliberate Guard/Witch coordination and wolf
fake commitments, rather than adding wolf numbers solely to force a 50% rate.
That proposed coordination study has not yet been implemented or run.

## Verification and limits

Tests cover repeated potions, both-night input through web/chat/API, first-night
self-save, death/resurrection limits, same-target rescue/poison, Guard conflict,
unchanged Classic supply, public-claim-only targeting and round-limit semantics.
Selected-Witch full sessions cover both variants, both languages and both modes.
DOM tests exercise actual frontend scripts against mocked transport; a new
real-browser walkthrough evidence is recorded separately in the [release audit](RELEASE_AUDIT.md).

The v2 source is preserved in `docs/research-runs/divine-witch-local-v2-source.tar.gz`
because later release fixes legitimately change source hashes. Extract it into an
empty temporary directory and set `WEREWOLF_REPLAY_SOURCE` to that directory when
running `tests/audit_divine_witch.py` on the v2 `.json.gz`. This checks original
hashes and exact trajectories. Alternatively, `--compare-current` explicitly tests
whether the current source reproduces those trajectories; it does **not** claim
the current source hashes are the recorded hashes. Neither operation calls a model.

The screen uses temporary memory, disables host evolution and NPC persistence,
and asserts all intervened parameters remain frozen after every game. Effective
abilities are still derived by the existing engine; “extreme” does not mean
every derived score must also equal an endpoint. True human enjoyment and
adaptive LLM gameplay remain unmeasured. No commit or publication is implied.
