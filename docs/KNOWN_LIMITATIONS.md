# Current limitations

This describes the playable `GameSession` implementation. All ten configured
boards (eight original and two Divine Witch variants) have paths for their listed abilities, but this does not establish
complete rule coverage or balance. See the explicit [rule variant](RULE_VARIANT.md).

## Rule coverage

### Model-player boundary

All normal interfaces share provider-neutral model decisions (normal mode
only), with real preflight and no silent fallback. API, local model servers and
trusted Agent protocol adapters are supported; Codex is optional. Only explicit
legacy/offline selections use local rule decisions. Model conjecture tables and
cross-game learning are not yet integrated. Model requests use bounded context rather than full verbatim history;
older details may be omitted, while full records remain in local saves. Long
games can still be slow or exhaust call budgets. Failure pauses for explicit
retry/stop. Checkpoint recovery and browser reconnect are implemented. Structural
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

Live sessions run in one process, with local checkpoints for restart recovery
and browser reconnect. Campaign progress is stored separately and reconciled by
game id. Missing or corrupt saves may prevent recovery. There is no account
system, production deployment configuration, database service, or automatic
memory retention/cleanup policy. Use the server locally; see [SECURITY.md](../SECURITY.md).

## What the tests establish

The suite includes a 40-game matrix across ten boards, two languages and two modes,
plus targeted selected-role and regression games. It verifies selected behavior
and termination, not exhaustive legality, competitive balance, production
security or compatibility with every external provider. See the dated
[release audit](RELEASE_AUDIT.md) for a reusable verification checklist.

## Dialogue quality / 对话质量

Offline reactions avoid exact recent cross-speaker echoes and clarification
replies state an existing position or admit insufficient evidence instead of
opening another question. This is bounded template deduplication, not semantic
understanding. Model replies receive an answer/decline contract; prompt tests
do not prove real-model compliance or playing strength.
Offline contextual responses retain explicit reports by publicly flipped Seers,
including dead speakers. These remain attributed reports, not certified checks.

离线回应避免近期跨人物的模板重复，澄清回答重申立场或承认依据不足，
不另起追问。这不是语义理解，也不代表模型实测质量或玩法平衡已获证明。
已翻牌预言家即便死亡，其标准查验声明仍可供情境回应引用，不自动认证查验。
