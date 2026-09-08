# Reliable Play and Recovery Design

Status: proposal (not yet implemented). Revised against `origin/master`
(`cfef85a`, the generic `ModelNPCAgent` / `DecisionRuntime` layer), not the older
Codex-only tree.

## 1. Goal

Let a game survive losing the browser connection, and survive a process restart,
without re-dealing identities, re-running completed decisions, or leaking private
information. This is the first step toward a game a player can reliably finish.

Explicitly **out of scope for this phase**: context-budget / memory retrieval
(section 9). Do not fold those two workstreams together.

### Layering: recovery is model-agnostic

The recovery path never assumes a specific model vendor. Three layers, with
knowledge flowing only downward (the recovery layer knows the interface, not the
vendors):

- **Game recovery layer** — checkpoints, decision numbers, budget accounting,
  state restore, and event catch-up. It does not know *which* model or adapter
  produced a decision.
- **Uniform model interface** — the only thing the recovery layer calls:
  connection re-verification, non-secret config validation, and call-budget
  restore.
- **Concrete adapters** — `api`, `command`, and `codex` each implement the
  interface. Codex is an *optional* adapter; the core recovery flow has no
  Codex-specific branch, and "Codex is installed" is never a proxy for "the
  game can recover".

## 2. Acceptance criteria

1. **Refresh does not lose the game.** Closing or refreshing the browser (SSE)
   does not end the session; reconnecting resumes the live stream.
2. **Restart does not re-deal identity.** After a process restart, the saved
   game keeps the same `player_id → role` mapping, seat order, and board.
3. **Recovery does not duplicate actions.** Recovered games do not re-vote,
   re-use potions, or re-issue model calls for decisions already committed.
4. **No private leakage.** A checkpoint never appears in the event stream,
   public record, review, or any emitted payload. It is stored with version
   validation, protected directory/file permissions, corruption handling, and a
   single-writer constraint. Restore never sends the current API key to a
   base URL the save designates but the user did not configure.
5. **Recovery is model-agnostic.** The recovery layer restores through the
   uniform model interface and is exercised against each adapter independently
   (`api`, `command`, `codex`). One adapter's availability does not gate the
   others, and recoverability is judged per adapter — never by whether Codex
   happens to be installed.

## 3. The event ledger is not a save file

`PublicRecord` (and `engine.history`) capture *what everyone saw*. They cannot
restore *where the game is executing*. A recoverable checkpoint must additionally
capture everything the ledger deliberately omits:

- **Identity and skill state** — `seat.role`, `seat.alive`, `seat.death_cause`,
  `witch_antidote`/`witch_poison`, `guard_last`, `knight_used`,
  `evil_knight_reflection_used`, `charmed`, `last_exiled(_wolf)`, `crow_target`.
- **Loop position** — current phase, speaking order, whose turn it is, and the
  pending `ask_player` request (including the new `model_retry` kind), plus
  loop-local values (`speech_events`, `election_speeches`, `knife`,
  `wolf_agents` ordering, `_triggered`).
- **Per-NPC private state** — `ModelNPCAgent` decision memory (`model_decisions`),
  `Brain` beliefs/suspicion/logs, `MatchState`, `CognitiveProfile`, each agent's
  `private_rng`, `reasoning`.
- **Model runtime / budgets** — the active `DecisionRuntime` backend (api,
  command, or codex) with its non-secret parameters and the `calls` counter,
  with credentials and command argv re-derived, not persisted.
- **Accepted decisions** — an append-only decision log with monotonic logical
  numbers and per-decision attempt numbers, used for duplicate-action protection.

## 4. Checkpoint schema

A checkpoint is a versioned document written atomically and **never emitted**;
it exists only on disk under the session's data directory. Serialization uses an
**explicit field allowlist** per component — never `asdict()` of a whole live
object, which would drag in references, transient queues, and credentials.

### 4.1 Engine core (`GameEngine`)

- `board_id`, `locale`, `player_role`, `cast_names`, `cast_personas`
- `seats`: for each seat — `pos, player_id, name, role, role_cn, faction, alive,
  is_player, is_wolf, death_cause, persona_id`
- `phase`, `day_count`, `night_count`, `sheriff`, `winner`, `end_reason`
- `witch_antidote`, `witch_poison`, `guard_last`, `knight_used`, `crow_used_day`,
  `charmed`, `last_exiled`, `last_exiled_wolf`, `crow_target`,
  `evil_knight_reflection_used`
- `seer_results`, `sg_results`, `grave_results` (private per-role results)
- `history` (the `GameEvent` ledger — also the public archive; events carry
  stable, monotonic numbers)
- `rng` state via `random.Random.getstate()` (tuple → list codec; restore via
  `setstate`). Required: `engine.rng` drives the deal, bomber victims, and seeds
  each NPC's private RNG.

### 4.2 Session / loop state (`GameSession`)

Durable:

- `conjecture`, `onboarding`, `memory_dir`, `finished`
- `public_record.entries` (stored directly — do not assume rebuildable from
  `history`; the two capture different scopes)
- `conjecture_ledger` — `history`, `private`, `roster`, `options`, `labels`
  (when conjecture mode is on)
- table-talk state — `_table_extra_turns`, `_table_extra_by_name`, `_table_pairs`,
  `_pending_questions`, `_questions_answered`, `_table_cooldown`,
  `_last_llm_status`
- `speech_events`, `player_last_speech`, `_triggered`
- **Resume point** (section 5.1): a step identifier plus a small `step_state`
  dict carrying loop-local values, and the pending `kind`/`data` if the loop was
  awaiting human input (this includes `model_retry`).

Transient — deliberately **not** persisted (re-created on restore):

- `stream_claimed`, `_events_started`, `_q`, `_event_q` (asyncio queues), any
  SSE consumer reference, `runner`/app wiring. Restoring these would resurrect a
  stale "already claimed" lock or a dead queue.

### 4.3 Per-agent private state

For each `ModelNPCAgent` (and legacy `StrategicNPCAgent`):

- `name`, `role_cn`, `is_wolf`
- `model_decisions` (per-seat, per-game decision memory — the list the model
  sees as "own previous decisions"; never emitted publicly)
- `brain`:
  - `style`, `cognition` (`to_dict`), `match_state` (`snapshot()`),
    `starting_state`
  - `sus`, `claims`, `claim_order`, `accuse_log`, `defend_log`, `vote_log`,
    `flips`, `resolved_exiles`, `speeches`, `silent`, `my_claims`,
    `wolf_strategy`, `notes`, `gut`, `decision_traces`
  - `rng` via `getstate()` — the agent's private `random.Random` (seeded from
    `engine.rng` but evolving independently; must be stored)
- `reasoning` (truncated decision log)

Each component needs a whitelisted `to_dict`/`from_dict` pair. This is the
largest mechanical surface (especially `Brain`), but bounded, and it doubles as
the information-boundary inventory the project already wants.

### 4.4 Model runtime (uniform interface + adapters)

The recovery layer never talks to a vendor directly. It calls one uniform
protocol — an *extended* `DecisionRuntime` — with three responsibilities:

- **connection re-verification** — re-establish liveness on restore; saved
  `verified=True` is never trusted (section 7);
- **non-secret config validation** — confirm persisted parameters match trusted
  local configuration before re-attaching credentials (section 7);
- **call-budget restore** — resume the `calls` counter from the reserved value.

The protocol is wider than any one implementation: `RuntimeBase` provides a
*default* implementation (persisting `backend`, `model`, `max_calls`, `timeout`,
`calls`), but an adapter is not required to inherit it — `CodexPlayerRuntime`,
for instance, does not. `verified` is **not** persisted — it is transient
liveness, re-established on restore (section 7). The backends below are
adapters that implement the protocol:

- **api** (`APIPlayerRuntime`): persist `config` fields `base_url`, `model`,
  `temperature`, `timeout_seconds`, `max_calls`, `reasoning_effort`,
  `reasoning_param`, `enabled` — **never `api_key`**. On restore, re-inject the
  key from current `.env`/`Config` **after** validating that the saved
  `base_url` equals the endpoint the current key was configured for (section 7).
- **command** (`CommandPlayerRuntime`): persist `model`, `max_calls`, `timeout` —
  **not `argv`**. The wrapper is trusted local configuration, re-derived from
  `WEREWOLF_AGENT_COMMAND` and validated on restore.
- **codex** (`CodexPlayerRuntime`): persist `model`, `effort`, `max_calls`,
  `timeout`, `calls`. No credential is stored (it uses the existing local Codex
  login). An optional adapter: its connection re-verification confirms the
  `codex` binary is on PATH and the local login is valid, but the recovery
  layer only calls the uniform re-verify method and never branches on Codex.
- **legacy expression** (`LLMClient`, host narration and NPC rephrasing on the
  `planner is None` path): persist `calls`, `failures`, `unavailable_reason`,
  and its `runtime` config (`base_url`, `model`, `temperature`,
  `timeout_seconds`, `max_calls`, `reasoning_effort`, `reasoning_param`,
  `enabled`) — never `api_key`.

`calls` is persisted **at reservation time** — before each attempt — so a crash
during an in-flight request cannot "un-count" quota already consumed.

### 4.5 Decision log (duplicate-action protection)

Two numbers, two purposes:

- `decision_no` (logical): identifies a game decision slot (e.g. "night 2 witch
  potions", "day 3 speech by seat 5"). Monotonic. Used to dedup **committed game
  actions** — an action already applied to the engine is never re-applied.
- `attempt_no` (physical): each real invocation of the external service for a
  given `decision_no`. Because a call can fail (timeout, invalid JSON), one
  logical decision may need several attempts; **every attempt consumes budget**.
  A retry is a new attempt, not a replay of the old one.

The log records, per decision: the reservation (budget increment), the accepted
result once it arrives, and whether the resulting action has been committed to
the engine. The checkpoint stores the last committed `decision_no`.

## 5. Resume mechanism

The hard part is that `GameSession._play()` is a single async coroutine whose
position cannot be pickled. Resume requires restructuring the loop.

### 5.1 State-machine decomposition

Convert `_play()` from one deeply nested coroutine into an explicit sequence of
steps, each a small async method, driven by a `step` cursor:

```
setup → night (gather per-role actions) → resolve_night → day_start
      → election → conjecture? → speeches (per seat) → table_questions
      → crow day-skill → conjecture? → vote → death triggers → win check
```

Each step restores loop-local values from `step_state`, checkpoints around every
external call (human `ask_player` or model call), records the result, and
advances the cursor. The existing `_npc_call()` wrapper (which already routes
model calls through `asyncio.to_thread`, catches `ModelTurnError`, and pauses on
`model_retry`) is the natural place to hang the checkpoint hooks, so the
recovery path and the in-place retry path share one code path.

This is the single largest refactor, which is why **extracting `GameSession`
out of `run.py` first** (a behavior-preserving move, already listed as
architectural debt) is the prerequisite: the checkpoint boundary wants a clean
session module with no FastAPI imports.

### 5.2 Checkpoint cadence: pre-call reservation + local atomic commit

One write is not enough. Each external call goes through two local checkpoint
writes, not a distributed two-phase commit: the external model service is not a
participant, and its side effects (quota, whatever it emitted) cannot be rolled
back. "Commit" here is purely local and atomic — our own engine state plus the
event batch.

1. **Pre-call (reservation).** Reserve the budget (`calls += 1` in the runtime),
   then write a checkpoint recording: the incremented `calls`, the
   `decision_no`, the new `attempt_no`, the step cursor, and the state-before-
   call. Only after this write does the call go out.
2. **Post-result (local commit).** When a valid result arrives, write a checkpoint
   that records, together: the decision result, the resulting engine state
   change, the advanced step cursor, and the event batch this step produced.
   Only after this write are the events emitted.

Plus a checkpoint at each **committed turn boundary** (night resolved, vote
resolved) so the common refresh case resumes cheaply.

Atomicity: write to `save.tmp` then `rename` to the authoritative path; never
leave a half-written checkpoint as authoritative. Corruption handling keeps the
previous good checkpoint (section 7).

### 5.3 What recovery guarantees — and what it does not

The precise, honest guarantees:

1. **A persisted decision is reused.** If the result was written at the commit
   checkpoint, recovery replays it and never re-requests it.
2. **An unpersisted decision is unknown.** If the crash happened after the call
   went out but before its result was committed, the result may not exist, or a
   retry may return a **different answer — including a different target**. A
   `decision_no` alone cannot de-duplicate against an external service.
3. **A committed action never takes effect twice.** Whatever the retry answers,
   the engine applies each committed `decision_no` at most once, so votes and
   potions are never double-applied.

There is no promise of byte-identical wording across a crash, nor that an
unpersisted decision will come back with the same target. The determinism
contract stays "same seed → same roles and rule settlement," not "identical
natural-language output."

### 5.4 Consistent commit boundary (no lost speech, no double apply)

The failure mode to prevent: the player already saw a speech, but recovery
"forgets" it (state rolled back behind an event that was already emitted). The
rule that closes this gap is **checkpoint-then-emit**: persist state + position
+ event batch, then push to the live queue. Combined with stable, monotonic
event numbers on the whole ledger, a reconnecting client resumes from the last
number it saw, so it neither misses an event nor processes one twice. "The
player saw it" and "recovery remembers it" become the same thing.

## 6. Web disconnect vs game end, and the reconnect payload

Today `stream` marks `stream_claimed=True` once and pops the game from `GAMES`
in the SSE `finally`, so a closed stream ends the game. Change this:

- The **game task** (`_game_task`) owns the session's lifetime, not the SSE
  consumer. `_play()` keeps running while waiting on `ask_player`, even with
  zero attached viewers.
- A session is **finished** only when the loop reaches `gameover` (or an
  unrecoverable error), at which point it is removed from the registry. Add an
  explicit leave/abandon action so stream close is not the only termination
  path.
- A finished game is **not purged immediately**: deleting the checkpoint at
  `gameover` would strand a player who disconnected just before the end — they
  could never reattach to receive the final result. Keep a recoverable endgame
  state (the final checkpoint, or a compact "ended" record holding the winner,
  the final events, and the review) for a grace period, and clean up only after
  that period or an explicit abandon (see open question 2).

**Reconnect is not a replay of the public ledger.** `PublicRecord` deliberately
excludes identity hints, private results, initialization, and action requests;
replaying it alone would leave the player unable to see their own seer results
or know what to do now. Nor is it the full checkpoint (that would leak). The
reconnect/restore payload is a **player-scoped recovery view**:

- the init/settings the player already received;
- private results **the player is entitled to** (their own `seer_results` /
  `sg_results` / `grave_results`), and no one else's;
- the public events, numbered, for **catch-up**;
- the **current pending action and its number** (so the client re-renders the
  exact prompt awaiting input);
- a hand-off point into the live stream with **no missing and no duplicate**
  events (join at the next event number after what the client last saw).

The second concurrent viewer of the single human seat remains rejected (the
existing 409 is still correct); reattach and duplicate-viewer are distinct.

## 7. Secrecy and integrity boundary

- The checkpoint contains every seat's role, private results, and NPC beliefs —
  the high-value secret. Store it under the session data directory with
  owner-only file permissions (`0600`) **and** a restricted parent directory
  (`0700`), never under `static/`.
- `0600` alone is not enough. The checkpoint must carry a **schema version**;
  restore validates it and refuses unknown versions. Writes are atomic
  (rename) and a **checksum** guards against truncation/corruption. A
  **single-writer** constraint (one game task owns its checkpoint file) prevents
  torn interleavings.
- **Corruption is not "resume from the previous checkpoint".** A torn write
  before the rename leaves the *previous* checkpoint as the authoritative one —
  that is the normal crash case and is safe to resume (events are emitted only
  after the rename). But a **checksum/version failure of the authoritative
  (latest) checkpoint** means the commit boundary is unconfirmable: falling back
  to an older checkpoint could re-apply actions that were already committed and
  emitted after it. In that case recovery **stops with an explicit error**
  instead of continuing.
- **Credentials.** `api_key` is never serialized. On restore, before re-injecting
  the key, validate the connection configuration: if the saved `base_url` differs
  from the endpoint the current key was configured for, refuse or require
  explicit user confirmation — never send the current key to an address the save
  designates (mirroring `LLMRuntimeConfig.from_request`, which already blanks the
  default key when `base_url` changes). Redirects remain disabled
  (`follow_redirects=False`), so the key cannot be forwarded to a redirect
  target. `command` argv is re-derived from
  trusted local configuration, never from the save.
- **Liveness is not durable.** Saved `verified=True` is not trusted; restore
  re-establishes the connection before play resumes (see open question 1).
- The `snapshot()/restore()` methods are written so they never accept
  `api_key`, never touch transient run state, and never produce a dict that
  `emit()` or `PublicRecord.observe()` could ingest. This is the information-
  boundary contract that already has regression tests (ARCHITECTURE.md).

## 8. Implementation phases and tests

Do these in order; each is independently testable. (Order fixed per review:
extract `GameSession` **before** adding snapshot code.)

1. **Extract `GameSession`** out of `run.py` into its own module,
   behavior-preserving; no snapshot work yet. Tests: the existing suite passes
   unchanged (event sequences / replay hashes unchanged).
2. **Define state and the secrecy boundary.** Add whitelisted
   `snapshot/restore` to `GameEngine`, `Brain`, `MatchState`, `CognitiveProfile`,
   `StrategicNPCAgent`, `ModelNPCAgent`, the `DecisionRuntime` protocol and each
   adapter (`api`, `command`, `codex`; `RuntimeBase` supplies a default), and
   `GameConjectures`. Tests: round-trip `snapshot → restore` yields a
   byte-identical `public_state` and identical RNG state; snapshot contains no
   `api_key`, no `argv`, no transient run fields; unknown schema version is
   rejected.
3. **Save, reconnect, process recovery, dedup.** Implement the state-machine
   cursor, the pre-call reservation + local atomic commit checkpoints, SSE reattach with the player-scoped
   recovery view, `game_id`-keyed restore on startup, and the decision log.
   Tests:
   - refresh/reattach resumes with the player-scoped view (their private
     results + pending action + numbered catch-up) and joins the live stream
     with no missing and no duplicate events;
   - kill the process after a commit checkpoint, restart, restore → same
     `player_id → role` map, no re-deal;
   - a committed vote/potion is not re-applied (decision log dedup);
   - a crash between the pre-call and post-result checkpoints re-issues the
     decision as a **new attempt that increments the budget**; a persisted
     decision is reused and consumes no new attempt;
   - a restored game never emits another seat's private events to the wrong
     consumer;
   - a saved `base_url` different from the configured endpoint is refused rather
     than receiving the current key.
4. **Fault tests**, then — and only then — **context budget and memory
   retrieval** as a separate workstream.

## 9. Context budget and memory (next phase — not now)

When phase 4 begins, it must not be a plain sliding window. Two tiers:

- **Full archive**: original text stays local forever, retrievable by event
  number. `engine.history` + `PublicRecord` already approximate this; make the
  numbering explicit and stable.
- **Model context**: rules + the actor's own lawful private info + key facts +
  recent verbatim statements + traceable summaries. Summaries must be
  *attributed claims*, never rewritten as facts: "X claimed Y is a wolf" is not
  "Y is a wolf".

Conjecture mode requires full traceable table versions and must not use the
normal mode's forgetting strategy.

## 10. Open questions

The three review decisions are locked in: whitelisted full logical snapshot
(not whole-object serialization); pre-call reservation plus post-result commit
checkpoints; extract `GameSession` first. Remaining open items:

1. **Restore-time liveness check.** Re-running `preflight()` proves the
   connection but consumes one budget call; a dedicated, no-budget health probe
   avoids that but adds a second protocol surface. Recommend accepting the
   one-call preflight (matches the existing "no silent fallback" posture) unless
   the budget cost matters.
2. **Endgame retention window.** Do **not** delete the checkpoint the moment the
   game ends — a player who lost the connection just before `gameover` still
   needs to reattach and receive the final result (section 6). Keep the final
   checkpoint (or a compact "ended" record) recoverable for a grace period; the
   open question is only its length and whether it retains the full private
   state or just the winner + final events + review. After the window, or on
   explicit abandon, delete the private state and keep nothing but the review
   artifact.
3. **Reconnect hand-off granularity.** Confirm the client can reliably report
   the last event number it received, so catch-up is a single `event > N` filter
   rather than a hash-based diff.
