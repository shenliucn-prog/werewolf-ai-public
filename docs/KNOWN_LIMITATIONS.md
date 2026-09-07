# Current limitations

This describes the playable `GameSession` implementation. All ten configured
boards (eight original and two Divine Witch variants) have paths for their listed abilities, but this does not establish
complete rule coverage or balance. See the explicit [rule variant](RULE_VARIANT.md).

## Rule coverage

### Model-player boundary

Agent chat defaults to local Codex decision players (normal mode only), with a
real preflight before dealing and no silent fallback. Browser and `--backend
legacy` remain rule-driven decisions with optional API rephrasing; `--offline`
is explicitly a rule-flow test. These modes are not equivalent playability
evidence. Codex conjecture tables and cross-game model learning are not yet
integrated. Full public history is included every turn without truncation;
long games can be slow or exceed context/account budgets. Failure stops the
process's game; resume and in-place retry are not implemented. Structural
validation does not prove semantic consistency, truthfulness or balance.

The common flow includes night actions, dawn/death announcements, first-day sheriff voting, statements, bounded table interruptions, exile voting, and victory checks. Seer checks, Witch potions, guarding, ordinary wolf kills, Hunter/Wolf King shots, Wolf Beauty charm, Bomber exile explosions, Hidden Wolf checks, and Evil Knight reflection have implementation paths, with remaining edge cases below.

| Area | Current gap |
| --- | --- |
| Knight / White Wolf King | Actions are offered before the actor's own regular statement, not arbitrary out-of-turn interrupts or during sheriff election |
| Crow | Extra-vote action is implemented; strategic quality and balance need playtesting |
| Gravekeeper | Private faction result is delivered; public death reveals make it redundant in the current variant |
| Stone Ghost | Separate inherited kill and private check are implemented; strategic quality needs playtesting |
| Witch and Guard | Night action batches reject invalid targets, unavailable potions, disallowed double potions and consecutive guarding. Divine Witch variants explicitly override supply and optionally allow double potions; balance is experimental, not certified |
| Death chains | Reverse-seat shooting chains are covered; all possible simultaneous special-role interactions are not exhaustively proven |
| Hidden information | Some event payloads and local strategy paths still need a deeper information-boundary review; this is not a formally audited secrecy model |

Wolf Beauty's nightly target is no longer broadcast, and Seer results no longer
contain exact-role metadata. Regression tests cover both boundaries. This is not
a complete noninterference audit of every local strategy path or model utterance.

The Classic board is the simplest starting point. Other boards remain experimental.
Host role descriptions include the implemented action windows. The older AI-only
observer CLI is a separate developer tool; it does not provide the new playable
day-ability flow and must not be used as evidence of browser/chat rule parity.

## Conversation and models

- Text only: voice and visual gameplay have no agreed design or implementation. Portraits are decorative.
- Playable conjecture mode is a dual-table beta, not ideal rationality or complete semantic contradiction detection. See [mode boundaries](GAME_MODES.md).
- Fixed/random preset choice is per NPC; there is no general personality-dimension editor in the game UI.

- Chat action parsing is deliberately limited to explicit commands and seat numbers.
- Natural-language claims/accusations are recognized heuristically, not through complete language understanding.
- Local English statements are template based and may repeat.
- Online expression has only heuristic intent checks; a model can still produce wording inconsistent with an intended claim or target.
- Provider calls are synchronous. Timeouts and call budgets bound individual waits, but do not provide fair scheduling between concurrent games.

## Hosting and persistence

Games are in-memory, single-process sessions. A restart or closed event stream ends the session; reconnect/resume is not implemented. There is no account system, production deployment configuration, durable database, or automatic memory retention/cleanup policy. Use the server locally; see [SECURITY.md](../SECURITY.md).

## What the tests establish

The suite includes a 40-game matrix across ten boards, two languages and two modes,
plus targeted selected-role and regression games. It verifies selected behavior
and termination, not exhaustive legality, competitive balance, production
security or compatibility with every external provider. See the dated
[release audit](RELEASE_AUDIT.md) for a reusable verification checklist.
