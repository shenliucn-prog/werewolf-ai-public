# Participant and observation refactoring

## R1a: identity and model-input boundary

This is the first implementation slice, not completion of the full architecture
plan. The existing session loop, gameplay rules, action protocols, retry slots,
budget reservation and checkpoint format remain in place.

The active model path is now:

`GameSession → ModelNPCAgent → ObservationGateway → ModelController → DecisionRuntime`

- `Participant` binds a stable `player_id` and seat to a match and controller.
  Humans belong to the same roster as NPCs. Display names are not identity keys.
- The roster is rebuilt from existing validated engine identities and the saved
  driver. It has no independent persisted state. Undealt saves have an empty
  roster; duplicate player IDs fail before restore applies changes.
- `ObservationGateway` assembles the existing lawful InformationSet, public
  context, own memory and rules. The model-visible request layout and budget are
  unchanged. Its detached observation also identifies the participant and last
  numbered public event; that metadata is not added to the model prompt.
- `ModelController` receives only the prepared observation, response constraints,
  model runtime and optional timing sink. It does not receive the engine, Brain,
  session, public ledger or other participants. It does not reserve budget or
  append decisions: the original session and adapter still own those operations.
- Public recovery events use the same gateway's public-only selection and are
  copied rather than exposing mutable references into the live record.

An observation's public-event cutoff is **not** a snapshot of all private state
and does not enable parallel decisions. Observation construction still runs in
the existing sequential decision path. The Python boundary is not a security
sandbox for a user-supplied executable with host filesystem access.

## Checks

`tests/test_observation_boundary.py` covers request-layout equivalence, human/NPC
identity, old-format JSON snapshot restoration, duplicate-ID rejection without
mutation, private-information noninterference for a civilian, authorized seer
results, detached nested data, wrong-actor rejection, public-event cursors,
single budget ownership across API/command/Codex doubles and invalid responses.
Existing model, full-session, recovery and frontend suites remain applicable.
These tests do not call a real model or claim exhaustive information-flow proof.

## R1b: action envelopes and stale-input protection

`actions.py` adds detached ActionRequest/ActionProposal envelopes shared by the
human submission and model-controller paths. Existing legal-action descriptions
and model JSON constraints stay unchanged; this does not unify or replace the
engine's rule validators.

- Human IDs derive from match ID + the existing durable request event number.
  Web and terminal echo the ID; stale or missing IDs are rejected before any
  pending action is consumed. A delayed old button cannot target the new prompt.
- A restored unanswered question reuses its request event and logical decision,
  rather than invalidating the ID while a reconnecting client is answering it.
  Old event ledgers gain the same ID in catch-up and recovery views without being
  rewritten. Terminal catch-up does not ask already-answered historical prompts.
- Model IDs derive from match ID + the session decision number. Context-local
  binding propagates to the model worker thread; retry attempts share the logical
  request ID while still consuming separate budget reservations. No IDs are
  added to model prompts or the external Agent wrapper protocol.
- Direct model unit/research calls explicitly have no durable request ID.
  Trusted old in-process `submit(payload)` callers remain compatible, but new
  clients must use bound submissions. IDs are not authentication or sandboxing.
- Participant seat is unknown (`None`) before dealing, permitting setup/retry
  prompts without inventing a seat; the stable human identity is already known.

`tests/test_action_contract.py` covers HTTP rejection, same-kind stale replies,
real-disk pending restoration, old-save delivery, terminal catch-up, legal target
validation, model retries and cross-match/participant refusal. DOM tests exercise
stale buttons and the actual frontend rejoin path. No live providers are called.

## R2a: bounded clarification queue

`QuestionQueue` now owns pending questions and the consumed-opportunity count.
The session routes human and NPC questions through enqueue/begin/finish, while
retaining ownership of external calls, checkpoints and public events. Answer or
skip consumption is committed with the answer (when present), before publication.
Duplicate completion is a no-op; unknown/dead targets consume no opportunity.

This slice preserves FIFO order, pair deduplication and the existing two-question
limit. It does **not** yet implement human-priority scheduling, third-party intent
arbitration or a general SocialIntent queue. Interruption selection and cooldown
remain unchanged. Name pairs remain the legacy storage/addressing format in this
slice; participant-ID intent migration must not be inferred as complete.

The existing `pending_questions`, `questions_answered` and
`step_state.answering_question` checkpoint fields remain compatible. Legacy
question dictionaries migrate in order. Invalid pairs/counts/in-flight markers
are rejected before any session mutation; malformed entries are no longer silently
dropped. Compatibility accessors for old in-process callers forward to the queue,
not a second copy of its state.

One additional `step_state.question_window` captures the remaining questions of
the current window. Questions created by answers stay outside it. An empty window
remains closed through later day-wrap actions and restart, until the next-day
reset. This closes a crash-path discrepancy without extending normal discussion
or increasing model calls. Old saves without this field start from their existing
pending queue; they cannot reconstruct an older window that was never recorded.

`tests/test_conversation_queue.py` covers FIFO/dedup, exactly-once consumption,
quota, active-question exclusivity, legacy decoding, detached snapshots,
failure-zero-mutation restore, dead targets and real-disk crash after a reply
creates a new question. Existing human answer/skip and crash tests still apply.

## R2b: durable interruption and floor arbitration

One active `InterruptionIntent` now lives in `step_state.table_talk` with a
version, stable source/interrupter participant IDs, original public event number,
public speech payloads and the stages select → interrupt → reply gate → reply →
close. A normal intent ID derives from its original speech event. Direct legacy
calls without a recorded source explicitly use a null reference, not a fabricated
quote. Invalid identity, version, stage and event/speaker/text links fail restore
before session mutation.

The main speech commits its pending interaction with its advanced speaking
cursor. On restart, the real speech-step dispatcher finishes that interaction
before moving to the next speaker. Selection and its RNG state are saved before
the model call; speech publication atomically saves stage advancement and counts.
Closing narration commits together with removal of the intent. Interruption and
reply decision slots include the intent ID, preventing an older exchange with the
same actor from being replayed as this one's response.

`FloorPolicy` extracts the existing score-then-seat ordering and the host's
deterministic closing reasons. Interest scores still come from the existing
agents; no extra LLM polling is added. Probabilities, cooldown, pair limits,
per-speaker limits, total-extra-turn cap and host wording are unchanged. Humans
can still reply or skip, and their pending request ID survives restart.

`tests/test_interruption_intent.py` compares six real-disk crash boundaries with
an uninterrupted one-speaker phase through `_play`/`_step_speeches`: source commit,
selection, accepted model decision, interruption commit, reply commit and closing
commit. It compares public events, calls, counters, pairs, cooldown and RNG state.
Additional cases cover human restoration/skip, stale exchange isolation, strict
restore rejection and moderation parity. These are phase integration tests with
model doubles, not live-model full-match evidence or hard-kill process tests.

Existing saves without an interaction cursor cannot recover an interaction that
was never recorded. They retain the old cursor behavior; the migration does not
invent a pending reply. This slice is **not** a general mailbox/social-intent
queue, human-priority reordering or a new third-party interrupt-request UI.

## R2c — source-linked statement projection

`ai/statement_memory.py` builds attributed summaries directly from public speech
events, carrying event number and day/night/phase. Main, election and table-talk
publication now includes the already-observed claim/accuse/defend metadata.
Repeated and changed role claims remain separate statements; the projection does
not assert truth, deception, or an exact disputed-reference link.

There is no second durable memory store or new Brain schema. Existing observation
logs provide explicitly unlinked fallback summaries when old public events lack
metadata; no text matching fabricates sources. New archives restore the projection
from the same public ledger. Summary counts and the whole-request size budget
still apply; source metadata can be trimmed before disputed originals.

Tests cover source/phase retention, repeated claims, legacy unknowns, detached
bounded projections, exclusion of non-speech payloads, request size, and a real
session table-speech publication/JSON snapshot restore round trip. No real models
were called. This does not implement semantic contradiction detection, explicit
retraction protocols, or guaranteed full-memory model access.

## R3a — background task lifecycle extraction

`lifecycle.py` now handles task creation/reuse, fault transitions, cancellation
cleanup, explicit abandon and terminal-state precedence. `GameSession` keeps its
existing methods as compatibility delegates and remains the sole state owner.
The supervisor uses the session's execution/checkpoint/event callbacks; it has no
engine or HTTP dependency, does not adjudicate completion, and does not settle
campaigns. The logger name and stream sentinel remain supplied by the session.

Cancellation still propagates after cleanup. Ordinary cancellation checkpoints
the pending input; explicit abandon cancels without recreating a removed save.
Fault messages, event/finalizer ordering, transient flags and save schema are
unchanged. This is task supervision extraction only, not recovery-codec migration
or a new lifecycle policy. Tests exercise the service without a game engine as
well as the existing session/transport/recovery suite.

## R3b — durable model-decision execution extraction

`decision_execution.execute` owns the former `_npc_call` orchestration; the
session method remains a compatibility delegate. Replay happens before opening
an attempt. Reservation precedes the pre-request checkpoint; accepted results
commit before returning to engine application. A failed model turn rolls back
only the failed appended model memory, persists the attempt, and asks the player
whether to retry. Retries remain new budgeted attempts. No fallback is added.

The service receives locale and session callbacks rather than accessing engine
rules. Ledger/counters/save schema remain owned by the session. Independent tests
cover ordering, failed pre-request persistence, replay of a false-valued result,
retry/memory rollback and the existing explicit offline compatibility path.
Full-session fault/recovery tests remain the integration gates. Cross-entry
restore coordination and checkpoint encoding have not yet moved.

## R3c — shared Web/chat restore coordination

`restore_coordinator` centralizes trusted runtime-option reconstruction and the
restore -> campaign reconciliation -> reserve -> checkpoint -> preflight sequence.
Both `run.restore_game` and `chat_game.play --resume` call it. Save driver/adapter
select the connection type, not credentials/argv/endpoints; actual runtime
options still come from the existing trusted local resolver. Explicit CLI
overrides retain their prior behavior, including subsequent snapshot validation.

Web keeps its per-game lock, file loading, ID check, registration and error
contract. Chat retains its CLI parameters, ID check and localized feedback.
Model factories remain at adapter boundaries for compatibility. The shared
service propagates failures and cannot register a partially restored session.
Tests cover ordering, rejection, disk failure before preflight, offline restore
and trusted option provenance, alongside the existing real-entry recovery suite.
Checkpoint encoding and session snapshot validation are not moved in this slice.

## R3d — trusted session snapshot codec extraction

`session_codec.py` now owns the existing freeze/thaw, snapshot whitelist and
restore validation/application implementation. `GameSession` retains four thin
compatibility methods, with no second state container. The schema, legacy
migration rules, trusted runtime checks and transient-field reset behavior are
unchanged. This trusted module reads all seats' private state; its output must
never be used as a player observation or transport response.

In addition to the snapshot/atomic-restore regression suite, a local comparison
executed the pre-extraction implementation and the new implementation on all
10 boards in both locales: 20 setup snapshot/JSON restore cases matched. This
used deterministic runtime doubles, not live models. New tests cover direct and
compatibility codec paths, nested speech encoding and version rejection. This
is a behavior-preserving extraction, not a new formal proof of all malformed
save handling or a change to checkpoint-file persistence.

## Restore review follow-up — loop-state rejection before mutation

Review reproduced a pre-existing partial-restore bug: invalid campaign profile,
triggered seats or speech rows could raise only after live engine restoration.
The codec now validates and materializes loop fields (including nested tagged
values, counters, pairs and flags) before applying components. The apply section
copies this prepared whitelist rather than performing fallible conversions.
Participant lookups are also checked on probe agents. A 14-case regression
matrix asserts ValueError, identical full snapshots and preserved live component
identities after rejection. This fixes the demonstrated loop-state gap; it is
not a claim of formal verification against every possible malformed save.

## Remaining migration

- R2: explicit revision/retraction semantics and broader social-intent/fairness work.
  Clarifications and the single active interrupt/reply chain are now durable;
  a general SocialIntent mailbox and human-priority arbitration are not complete.
  Do not duplicate the current pending-action state in Participant.
- R3: extract remaining application/recovery coordination, conversation scheduling and durable execution
  in separately reviewed, behavior-preserving steps.
- R4: onboarding and measured performance work. No concurrency or model/effort
  changes are included in R1a.
- R5: model-backed conjecture research and further rule extensions remain separate.
