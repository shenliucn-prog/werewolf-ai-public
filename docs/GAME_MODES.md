# Game setup and modes

For the separate terminal-first option-driven mode (twelve fixed characters,
public spectating and no model calls), see [Offline choice games](OFFLINE_GAME.md).

## Current medium

Both web and terminal conversation are **text-driven**. Voice and visual gameplay
have **no agreed design and no implementation** yet. Portraits and interface
graphics are decorative; the engine receives no voice, face, posture or camera
signals. These future media must be designed and evaluated separately.

## Before each game

1. Choose a board and language. Classic is the recommended starting board.
   Choose **Your role** or leave **Random role** selected. Only roles present
   on that board are offered; the full role counts stay unchanged. Other
   assignments remain hidden. Changing boards resets an unavailable choice.
2. Set names in **Names & personalities**, or randomize them.
3. For each NPC choose **Random each game** or a fixed personality preset.
   Fixed selections persist in the setup form until changed; they are not
   stored across page reloads. Duplicate fixed presets are allowed. Random
   slots draw without replacement from presets not already fixed. With no
   fixed slots, all eleven presets appear once as before.
4. Leave Conjecture mode off for ordinary natural-language play, or enable its
   beta dual-table workflow. Choose local expression or your model settings.
5. Start. Names, personalities, your role, mode, board and language are locked for that
   match. Starting over requires confirmation in the web interface.

The human is not assigned scripted AI behavior. Names and personality choices
do not alter the role/seat random stream. Host rules chat remains available
without spending an action. Closing a stream does not end the session;
saved games can be resumed. This remains a local, single-human-plus-NPC game, not an
online multiplayer account/lobby service.

## Playable conjecture beta

Living actors submit two full-roster tables before regular daytime discussion,
then revise before exile voting. Each row has a player, an identity judgment
(unknown, good/wolf faction, or an exact board role) and a reason. Dead players
remain as subjects of guesses but cannot act. Human private known facts are
prefilled; public claims may differ deliberately. Keep the private and public
tables distinct: a private belief is not automatically broadcast.

Public tables appear as expandable, versioned records; earlier versions remain
in the log and in each NPC's public-table history. Local NPCs generate drafts
from their existing strategy and lawful information. Public claims/accusations
enter their observations, and online expression receives the complete public
table archive. The NPC private table is a snapshot of its existing local belief
machinery; it is **not yet a replacement decision engine**.

This beta does **not** guarantee ideal rationality, exhaustive contradiction
detection, or that a model genuinely uses every history entry. It does not
automatically penalize opinion changes. Public table judgments are claims,
not host-certified identities. The separate research adapter below has richer
role/faction/candidate/evidence fields and distinct table-to-vote model calls.

## Terminal conversation

```sh
python -m werewolf_web.chat_game --list-personalities --lang en
python -m werewolf_web.chat_game --board classic --list-roles --lang en
python -m werewolf_web.chat_game --board classic --role seer --offline
python -m werewolf_web.chat_game --offline --conjecture --personality dashan=aman --personality amo=random
```

Repeat `--personality NPC_ID=PRESET_ID` for fixed choices. Omitted NPCs are random.
While editing tables, use `private 3 wolf reason` / `public 3 unknown reason`
(or `私有 3 wolf 理由` / `公开 3 unknown 理由`). Numbers refer to the displayed
table row, not seat numbers. `done` / `提交` submits both drafts; `keep` / `保留`
is also accepted. `?question` still asks the host privately. JSON import remains
an optional advanced input, not a requirement.

## API

`POST /api/start` accepts `conjecture: boolean` (default false) and
`personalities: {NPC_ID: "random" | PRESET_ID}`, plus
`player_role: "random" | ROLE_ID` (omitted/null means random). Role IDs must
belong to the selected board. This is the human's hidden identity, not a
personality preset. It is never added to public settings or NPC context.
Invalid values are rejected
before session registration. `/api/cast` includes localized preset choices,
but never hidden game roles. Every session, including terminal play, uses a
fresh memory scope. NPC memory keys include both slot and preset so duplicate
presets do not overwrite one another. Older files are untouched.

## Separate experiments

[Extreme personality experiments](EXTREME_EXPERIMENT.md) use a different,
explicit seven-seat ruleset and Codex as the decision maker. Do not equate
research results with balance or player experience on the normal board.
The [mechanics lab](MECHANICS_LAB.md) prepares corrected research protocols
and isolated candidate rules; no new external experiment is started by setup.

## Verification boundary

Automated tests cover 40 offline full matches (10 boards × 2 languages × 2 modes),
including duplicate fixed presets, and targeted setup/privacy/chat checks.
`tests/test_setup_ui.cjs` uses jsdom (`npm ci && npm test`) to test the real
frontend scripts against mocked transport. It is a DOM test, not a screenshot
or real-browser interaction test. Current actual-browser evidence and remaining
visual/accessibility gaps must be checked using the [release checklist](RELEASE_AUDIT.md).

## Divine Witch experiments

Two optional boards retain the Classic roster while changing potion supply.
`divine_witch` permits unlimited total potions but one type per night;
`divine_witch_dual` permits one antidote and one poison per night, every night.
Select Witch before starting to play her yourself. Both work with either mode
and both languages. Original boards retain finite potions. See
[Divine Witch rules and results](DIVINE_WITCH.md); these are not balance-certified.
