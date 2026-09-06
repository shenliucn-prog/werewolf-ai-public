# Playable rule variant

These are this prototype's explicit rules, not a claim that all Werewolf tables
use the same variant. Browser and terminal chat use the same `GameSession`.

## Public and private information

- Eliminated players publicly reveal their role in the current variant. Living
  players' roles remain hidden except for communicating wolf teammates and
  explicitly revealed abilities. The isolated Stone Ghost does not know the pack.
- Seer checks return only **good / werewolf**. Hidden Wolf returns **good**, not
  its exact role. Stone Ghost checks return exact roles privately.
- Wolf Beauty's nightly charm target is not announced. A skipped charm leaves
  no active target that night. On the Beauty's death, the active target dies too.
- At the start of each night, a living Gravekeeper privately receives the last
  exiled player's faction. There is no result on the first night or after a day
  without exile. With public death reveals, this is redundant confirmation;
  a future no-reveal variant would make the role strategically distinct.

## Daytime abilities

| Role | Action window | Effect |
| --- | --- | --- |
| Knight | Before their own regular daytime statement; once per game | Duel another living player. A wolf target dies and day ends. Against a good target, the Knight dies and day continues. Passing does not consume the ability. |
| White Wolf King | Before their own regular daytime statement | Self-destruct and take another living player down. Day ends after death abilities resolve. |
| Crow | After statements, before the exile vote | Mark another living player for one extra exile vote that round. The mark's target is public, not the Crow's identity. |

Abilities cannot be activated during sheriff election, another player's speech,
or a table interruption. After an ability ends the day, remaining statements
and the exile vote are skipped. Win checks run after death chains resolve.
Both interfaces offer an optional target; use `choose N` or `pass` in chat.

The Crow's extra vote is exactly one, separate from the sheriff's 1.5 voting
weight. It expires at the next day and cannot apply to sheriff elections or
to a dead target. A tied highest exile tally eliminates nobody.

## Night actions and death chains

- The Stone Ghost gains a separate kill starting the night after the ordinary
  pack is gone. It retains its private role check. It cannot kill itself, and
  this does not reveal the pack's identities or allow pack communication.
- On original boards the Witch has one antidote and one poison for the entire
  game and can use at most one per night. `divine_witch` removes the total stock
  limit; `divine_witch_dual` also allows one of each in the same night. In all
  cases she saves only tonight's attacked player, self-saves only on night one,
  cannot self-poison or resurrect earlier deaths. See [Divine Witch](DIVINE_WITCH.md).
- The Guard can protect themselves but cannot guard the same target on consecutive
  nights. Guard plus antidote on the attacked player still causes death.
- Poison takes precedence over a knife when both hit the same target; a poisoned
  Hunter cannot shoot. In this variant a Hunter otherwise shoots except when
  killed by a Knight duel. A Wolf King shoots only after exile or a Hunter shot.
- Newly triggered deaths are drained before play resumes, regardless of seat order.

The engine rejects illegal night action batches before applying any part of them.
See [known limitations](KNOWN_LIMITATIONS.md) for remaining audit boundaries.
