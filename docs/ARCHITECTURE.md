# Architecture and extension guide

## Supported execution paths

Browser (`static/`) and terminal (`chat_game.py`) consume **the same
`GameSession`**, defined in `session.py`. `run.py` is the FastAPI adapter and
re-exports `GameSession` (and its `GameRunner` alias) for compatibility.
`GameSession.events()` starts one game, emits dictionaries and accepts validated
action dictionaries via `submit()`. It has one consumer and cannot be resumed.
The browser converts these events to views; it never decides legal actions.

All normal entry points inject `ModelNPCAgent` through a preflight-verified
`DecisionRuntime`. API/local model servers, trusted Agent wrappers and optional
Codex all implement `complete(request, schema) -> dict`. See [the connection
protocol](MODEL_CONNECTIONS.md). HTTP bodies cannot supply executable commands;
server owners select non-API adapters only through local environment configuration.

The LLM owns speech, candidacy/withdrawal, votes and skills; the engine validates
and resolves rules. Requests contain the actor's lawful `InformationSet`, full
public history and only that seat's prior decisions. Model calls run off the
event loop so HTTP/SSE and retry controls remain responsive. Failure pauses at
the exact failed call for explicit retry/stop; completed actions are not replayed.
Public history is memory, not proof the model understood it. The local Brain
still supplies personality and interruption-interest scoring, not model targets.

Only explicit legacy/offline tests retain the rule planner. Conjecture tables
remain legacy-only and are rejected in model mode rather than silently replaced.
The optional Codex adapter follows [non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode).
Other Agent wrappers must enforce their own tool isolation and role boundaries.

| Component | Owns | Must not own |
| --- | --- | --- |
| `game/engine.py`, `models.py` | Authoritative roles, legal resolution, deaths, victory, event ledger | Model wording or UI state |
| `ai/brain.py`, `strategy.py` | One NPC's lawful observations, beliefs and local decisions | Another NPC's private belief or unrevealed good role |
| `ai/strategic_agent.py` | Playable adapter, observations, optional expression, scoped memory | Replacement rule adjudication |
| `ai/model_player.py` | Provider-independent lawful prompt context, private decision memory, validated actions | Hidden opponent knowledge or rule adjudication |
| `ai/decision_runtime.py` | API and Agent-wrapper protocol, preflight, timeouts and call budgets | Rule decisions, public secrets or silent fallback |
| `ai/codex_player.py` | Optional Codex protocol adapter (backward-compatible class alias) | Global Agent settings or product-wide vendor dependency |
| `ai/host.py` | Public rules help, narration, bounded interruptions; separate postgame review | Live private-identity tutoring or inventing unimplemented rules |
| `game/conjecture.py` | Playable private/public drafts and public revision history | Host-certified claims or automatic proof of rationality |
| `ai/llm.py` | Optional OpenAI-compatible expression, budgets and fallback | Playable votes/night decisions |
| `casting.py`, `i18n.py` | Stable IDs, random/fixed presets, names and localization | Hidden-role allocation based on a display name |
| `research/` | Versioned research protocols and recorded experiments | Silent changes to the normal game's rules |

The information boundary is a coding contract with regression tests, **not an
enforced capability sandbox**: adapters hold the engine, which knows all roles.
Review every new read of `seat.role`, `is_wolf`, engine history and private results.
The legacy `NPCAgent` in `ai/npc.py` is not the playable decision path; persona
parsing still lives there. `cli_game.py` is an older omniscient observer, not proof
of browser/chat parity. Avoid building new human-play features only in that loop.

## Extension recipes

### Add a board using existing roles

1. Add a unique stable ID and exactly twelve role entries to `data/boards.json`.
   Unknown roles are not plugins: they need the implementation work below.
2. Add English board metadata in `i18n.py`; keep Chinese descriptions aligned.
3. State the rules explicitly in `docs/RULE_VARIANT.md` and the player guide if
   they alter basic actions. Public descriptions must match engine behavior.
4. Extend the full-session matrix expectations in `tests/test_game_options.py`;
   test both locales, both modes and selected human roles. Do not infer balance
   from successful termination.

### Add or change an ability

Update role metadata and wolf classification (`models.py`), legal targets and
atomic resolution (`engine.py`), player/NPC prompts and death-chain scheduling
(`GameSession`), local Brain strategy, and public rules/translation. Add a new
frontend/chat action only if the existing target or potion contracts cannot
represent it. Keep old boards' behavior unchanged unless explicitly versioned.

Test illegal/dead/self targets, timing, simultaneous deaths, winner timing,
private-event leaks, and complete web/chat sessions. Useful examples:
`tests/test_special_roles.py`, `test_divine_witch.py`, `test_role_selection.py`.

### Change personality or presentation

Use [cast customization](CAST_CUSTOMIZATION.md) and [parameter ranges](PERSONALITIES.md).
Canonical Chinese persona headings are parsed by code; do not translate or rename
them as prose-only cleanup. English display text is separate in `i18n.py`.
Slot ID, chosen preset, display name, seat and hidden role are distinct concepts.
Preserve separate random streams: changing a name must not change the role deal.

### Add a language or interface

Update Python `i18n.py`, frontend `static/js/i18n.js`, action help and tests together.
Claims and accusations have language-specific heuristics, not just translated UI.
A new transport should consume `events()` and submit actions; it should not copy
the phase loop. Voice/visual input needs its own design and evidence boundaries
before implementation. There is currently no voice/avatar behavior protocol.

### Add a model service or research rule

Playable online expression uses Chat Completions-compatible endpoints; native
vendor APIs need a separate adapter. Preserve timeouts, budgets, local fallback,
intent checks and key redaction. Changing endpoints must not forward a server key.
Test with stubs, not a maintainer's subscription. Codex research decisions are a
**different** path; see [mechanics lab](MECHANICS_LAB.md).

For new experiments, record the rules version, source hashes, seed/deal,
intervention, legal information sent per actor, failures, calls and complete
outputs. Preserve old artifacts and their source; never relabel a changed run
as the old result. Synthetic private tables are research data, not player-visible
game events. Never commit real users' private game logs or credentials.

## HTTP contract (local single-user prototype)

- `GET /api/boards?locale=en`, `/api/cast?locale=en`: public setup options.
- `POST /api/start`: settings object; returns an opaque `game_id`, not public roles.
- `GET /api/stream?game_id=...`: one SSE consumer. Missing game: 404; second
  connection: 409. Closing it cancels the game and removes its registry entry.
- `POST /api/action`: `game_id` plus the current action payload. Rejected actions
  keep the pending turn. Speech is limited to 4,000 characters.
- `POST /api/host_chat`: `game_id`, `question` (1–320 characters); does not consume
  a turn. Malformed JSON/non-object bodies and invalid ID types return 422.

The game ID acts as a bearer capability: anyone holding it can act in that game.
There is no authentication, multi-worker coordination, reconnect or public hosting
hardening. Never put a public proxy in front of this server unchanged.

## Known architectural debt

`GameSession` has been extracted to `session.py`; `run.py` is now a thin FastAPI
adapter that re-exports `GameSession`/`GameRunner` so existing importers keep
working. Startup directory creation (`config.ensure_dirs()`) still lives at
`run.py` import time, so a direct `session` importer that writes memory should
call it itself. Do not introduce a plugin framework before there is a second
genuine implementation. Other debts: synchronous model calls, unbounded
unopened sessions, runtime retention, an older separate observer loop and a large
Chinese-source persona/strategy layer. These limit hosting and onboarding, not
the ability to modify the local game with tests.

## Contributor verification

From the root, with the README Python environment and Node 24.15+ (24.x):

```sh
python -m unittest discover -s tests -q
npm ci
npm test
npm run check
python scripts/check_release.py
```

Use `python scripts/check_release.py --history` before publication. This scans
local reachable Git text blobs, not remote-only branches, binaries' metadata or
every possible credential format. Test both languages in an actual browser after
visual changes; jsdom cannot verify layout, contrast, focus or real SSE transport.
