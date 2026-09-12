# Playable rule variant

These are this prototype's explicit rules, not a claim that all Werewolf tables
use the same variant. Browser and terminal chat use the same `GameSession`.

## Elections, Peaceful Day and public records

After daytime discussion and before exile ballots, a living human participant
gets one optional final reply, independently of the shared clarification limit.
Answer or skip closes discussion; NPCs do not start another interruption chain.
The reply/skip is checkpointed and is not repeated after recovery. Spectators
and dead players do not receive this turn. Offline play uses contextual choices.

白天讨论结束、放逐投票开始前，存活真人有一次独立于追问额度的完整回应机会。
回答或跳过后直接进入投票，不再打岔；恢复不会重复发言。旁观者与死亡玩家没有此行动。

Player-facing chat and browser games collect candidacy before first-day
speeches, announce all candidates, then offer one withdrawal window after the
speeches. No late entry or re-entry is allowed. All living players, including
remaining candidates and withdrawn candidates, vote. A tie elects nobody.
Unattended research callers with `onboarding=False` retain the earlier election
protocol without the human withdrawal prompt.

Exile ballots now offer **Peaceful Day** alongside living players. This is a
public vote for no exile, not a silent abstention. It has the same weight as a
player vote (including the sheriff's 1.5). If Peaceful Day leads, or any options
tie for highest votes, nobody is exiled. The Crow's extra vote still applies only
to its marked living player. This experimental option changes incentives;
balance is not yet established. Cautious NPCs can support it when none of their
suspicions reach the local decision threshold; personalities and beliefs remain
relevant. No independent abstention option is provided.

Both elections and exile votes publish each voter's target and weight, the
Crow's bonus when applicable, and totals. At a chat prompt use `votes`,
`latest votes`, `day 2 speeches`, `/history` or `/seats`. Chinese equivalents
include `上一轮票型`, `第2天发言记录`, `公开记录` and `座次`.
For natural-language requests, ask the host with `?` (for example
`?把上一轮的票型拿出来`); in the browser use the existing host chat field.
Queries never submit actions or reveal private night results. Speech records
are verbatim. Declining an interruption emits no player statement. Final review
includes all identities and the public timeline after the game ends. These
records belong to the live process; restarting does not restore a lost game.

## Claims, clarification and interruptions

Seer claims include a dated account of checks. A true Seer uses only their own
results; a bluffing NPC maintains its own invented account without consulting
the Seer's hidden results. Both are player claims, not host certifications. A
language-model rewrite must retain the account verbatim or local wording is used.
These safeguards improve consistency; they do not certify all NPC reasoning.

During your statement, directly asking a numbered player for their checks
(for example, “12号不说自己验了谁吗？” or “#12, who did you check?”) queues a public
clarification after ordered speeches and before voting. The host allows at most
two such replies per day. Someone who has not publicly claimed Seer does not
disclose private checks in this window. Duplicate questions to one player are
combined. This first version recognizes check questions, not arbitrary debate
questions. Rules questions sent with `?` remain private and never enter this queue.

Spontaneous exchanges have a three-extra-utterance budget and cannot follow two
consecutive main speeches. Main speeches always retain their order. The separate
clarification window may add up to two responses. Declining a reply is silent.

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
