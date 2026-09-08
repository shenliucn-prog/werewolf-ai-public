# Werewolf AI

English | [简体中文](README.zh-CN.md)

A local single-player Werewolf game: you play one seat against 11 AI opponents.
**Normal play requires a model API or a supported connection to your own Agent.**
Models decide NPC speech and actions; Python enforces rules and saves progress.
The browser is optional—not a browser-only game.

Playing in your Agent's conversation is recommended. The Agent needs local
command execution and a persistent interactive process. Relaying the game does
**not** automatically connect that Agent's model to the NPCs. There is no
universal Agent plugin or separate native app yet.

## Choose a mode

| Entry | What it does |
| --- | --- |
| Campaign | Start as a Civilian and win to unlock the next role across 16 fixed-board levels. A faction win counts even if you died. |
| Free game | Choose a board, your role or random, NPC names and fixed/random personalities. |
| Continue | Resume an interrupted saved game instead of starting over. |

Losses can be retried. Draws count as attempts but do not unlock a level;
abandoning a started attempt counts as a non-win. Model failures pause play,
never silently substitute program-controlled NPCs. Role teaching and short
loss reviews use the model and can be retried.

**Offline simulation must be explicitly selected.** It is a rule-flow test,
makes no model calls and does not count toward campaign progress.

## Quick start

Python 3.10+ is required. Fork and clone your fork to customize the game, or
try the upstream below. Run commands from the repository root.

```bash
git clone https://github.com/shenliucn-prog/werewolf-ai-public.git
cd werewolf-ai-public
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r werewolf_web/requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

### 1. Connect a model

Choose one:

- **API/local model server:** copy `werewolf_web/.env.example` to
  `werewolf_web/.env`; configure `LLM_BASE_URL`, `LLM_MODEL` and
  `LLM_API_KEY` if required. The endpoint must support OpenAI-compatible
  Chat Completions. Keyless local servers are supported.
- **Your own Agent:** configure a trusted local wrapper implementing the
  [decision protocol](docs/MODEL_CONNECTIONS.md), then select
  `--backend command`. An arbitrary Agent executable is not automatically compatible.
- **Optional Codex adapter:** use `--backend codex` with an existing local
  Codex login. Codex is not required.

A real connection check runs before dealing roles. The default call budget is
240; API users can set `LLM_GAME_MAX_CALLS`. Retries, teaching and short reviews
consume calls when they request the model; cached teaching does not.
A call cap is not a monetary cap. Only set reasoning options supported by your
provider. See [connection settings](docs/MODEL_CONNECTIONS.md).

Setup guidance: `python -m werewolf_web.setup --lang en`.
Add `--check` to check the environment without starting a game.

### 2. Start or continue

Ask your Agent to read [Agent play](docs/AGENT_PLAY.md), run the game and relay
your choices without autoplaying. Direct terminal play uses the same commands:

```bash
# Campaign: current unlocked role
python -u -m werewolf_web.chat_game --campaign --lang en

# Free game: choose a board interactively
python -u -m werewolf_web.chat_game --lang en

# Free game: selected board and role
python -u -m werewolf_web.chat_game --board classic --role seer --lang en

# Resume: replace GAME_ID with the saved game's identifier
python -u -m werewolf_web.chat_game --resume GAME_ID --lang en
```

Campaign profiles default to `default`; `--profile NAME` selects another local
profile. Start the campaign entry again after finishing a level. Campaign starts
can reuse non-secret saved model settings; keep credentials in trusted local
configuration for recovery.

For the optional browser interface:

```bash
python -m uvicorn werewolf_web.run:app --host 127.0.0.1 --port 8000
```

Open [localhost:8000](http://127.0.0.1:8000), select a language and model
connection, then Campaign, Free game or Continue. A key entered in the browser
goes to the local Python backend for that connection, not into the settings file.

### 3. Play

The host introduces the rules and seating map. Ask questions, then confirm Ready
to begin night one.

| At a terminal action prompt | Input |
| --- | --- |
| Speak | Your statement |
| Seats / public history | `/seats` / `/history` |
| Ask rules without taking an action | `?How does the Witch work?` |
| Vote / select a target | `vote 3` / `choose 3` |
| Skip an optional action | `pass` |
| Retry campaign teaching | `/teaching` |
| Retry short review at the post-game prompt | `/review` |

Follow the prompt for legal choices. The parser uses explicit commands, not
general natural language. An Agent may translate your choices but must not
invent events or inspect hidden NPC state. See the [player guide](docs/PLAYER_GUIDE.md).

## Modes and current limits

- Text only, in English or Chinese. Voice and visual gameplay have no design
  or implementation; portraits are decorative.
- Normal debate is the default. Model-driven conjecture tables are not yet
  integrated; conjecture is restricted to explicit legacy/offline research play.
- Ten boards; start with Classic. Divine Witch and extreme-personality
  experiments are not certified balanced.
- Local prototype, not a fair leaderboard or anti-cheat system. Automated tests
  do not certify every provider or Agent. Complete real-API/Agent campaign runs
  remain a final release-verification item.

See [game modes](docs/GAME_MODES.md), [Divine Witch](docs/DIVINE_WITCH.md),
[project rules](docs/RULE_VARIANT.md) and [known limitations](docs/KNOWN_LIMITATIONS.md).

## Saves and privacy

Checkpoints, campaign archives, settings, teaching cache and runtime memories
stay under `werewolf_web/data/`, ignored by Git and excluded from release exports.
**Checkpoints contain hidden roles and NPC private state: do not share them or
read them for a gameplay advantage.** Keys are excluded from settings and
checkpoints; restoring model play requires a trusted live connection again.
Missing or corrupt saves are not guaranteed recoverable.

Browser reconnect and terminal `--resume GAME_ID` use saved sessions. Do not
control the same live game from two interfaces at once. New playable sessions
do not automatically inherit previous games' NPC memories.

The provider receives each acting NPC's permitted context, including your
statements and that NPC's private information. Avoid sensitive real-world chat.
There is no account system or hardened public multi-user deployment; run locally.
See [security](SECURITY.md).

## For contributors

| Location | Responsibility |
| --- | --- |
| `werewolf_web/session.py` | Shared session, events and recovery |
| `werewolf_web/run.py`, `chat_game.py` | Web and terminal adapters |
| `werewolf_web/game/` | Deterministic rules and outcomes |
| `werewolf_web/ai/model_player.py`, `ai/decision_runtime.py` | Model decisions and API/Agent adapters |
| `werewolf_web/ai/model_context.py` | Bounded requests; full records remain in saves |
| `werewolf_web/campaign*.py` | Levels, progress, teaching and short reviews |
| `werewolf_web/static/`, `i18n.py` | Browser UI and localization |

Legacy Brain/research tools are separate from normal model decision play.
`cli_game.py` is an omniscient developer observer, **not a player entry**.
Persona source headings are parser inputs; do not translate them blindly.

```bash
python -m unittest discover -s tests -q
npm ci
npm test
node --check werewolf_web/static/js/app.js
node --check werewolf_web/static/js/i18n.js
python scripts/check_release.py
```

Node.js 24.15+ (24.x) is for development tests only; playing needs no npm build.
Read [contribution guidance](CONTRIBUTING.md) and
[architecture / extension recipes](docs/ARCHITECTURE.md). Research/design docs
are not promises that every proposed feature is implemented.

## License

Code: [MIT](LICENSE). AI-generated portraits are authorized for this project and
repository distribution, but are **not** covered by MIT; other uses require
separate permission. See [asset provenance](docs/ASSETS.md).
