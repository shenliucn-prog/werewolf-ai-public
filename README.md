# Werewolf AI

English | [简体中文](README.zh-CN.md)

A 12-player social deduction game with 11 independent AI opponents and an automated host. **The recommended experience is playing inside your own AI Agent's conversation**, in English or Chinese. The browser is optional. Currently, a capable local Agent can relay the terminal interface; a universal Agent plugin/MCP integration is not yet provided. See [Agent play](docs/AGENT_PLAY.md).

The core experience is the conversation: players form suspicions, make claims, interrupt one another, and respond before the host brings the table back to the game. Browser and chat share rules and public records. **Agent chat now defaults to Codex decision players; the browser still uses legacy rule-driven NPCs.** These are not equivalent reasoning experiences.

**Status:** an experimental, local-first prototype. Start with the Classic board. Eight original boards plus two Divine Witch experimental variants have playable ability paths under this project's [rule variant](docs/RULE_VARIANT.md); edge cases and balance still need testing. See [known limitations](docs/KNOWN_LIMITATIONS.md).

## What you can do

- Choose normal conversation (default). **Conjecture mode (beta)** remains available in the legacy test backend; Codex dual tables are not integrated yet and are explicitly rejected instead of silently substituted.
- Try **Divine Witch**: unlimited potions, either one type or both types per night. Choose the experimental board and select the Witch as your role. [Rules and stress tests](docs/DIVINE_WITCH.md).
- Assign each NPC a **fixed preset** or **random each game**, independently of names and hidden roles.
- Play with text only. **Voice and visual gameplay have no design or implementation yet**; portraits are decorative, not behavioral evidence.

See [game setup and conjecture play](docs/GAME_MODES.md). The separate
[extreme-personality research protocol](docs/EXTREME_EXPERIMENT.md) runs complete
seven-seat experimental games, not the twelve-seat playable board.

- Play against NPCs with distinct personalities, beliefs, cognitive profiles, and bounded match-to-match learning.
- Ask the host private rules questions without consuming your action.
- Take part in brief public exchanges that other players can react to; the host limits repeated two-person debates.
- Switch between English and Chinese before starting a game, including NPC names, catchphrases, prompts, and reviews.
- Codex players independently choose speech, votes, candidacy and abilities using public history and their own lawful private information. A working local Codex login is required and account usage applies.
- Model play stops on failure, timeout, invalid decisions or budget exhaustion. It never silently switches to local templates. Offline rule-flow tests remain explicitly available with `--offline`.

## Quick start

Fork this repository on GitHub, then clone your fork locally (or clone the
upstream below to try it). Both Agent and browser games run on your machine.
After installing dependencies, run `python -m werewolf_web.setup --lang en`.
Onboarding checks your environment, explains costs and entry points, guides
game settings, and leads into the host's rules/question phase. Night one waits
for Ready. Check without starting: `python -m werewolf_web.setup --check --lang en`.

Use Python 3.10 or newer. Run commands from the repository root.

```bash
git clone https://github.com/shenliucn-prog/werewolf-ai-public.git
cd werewolf-ai-public
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r werewolf_web/requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.

### Play inside your Agent — recommended experience

Ask your Agent to read this repository and [the Agent play instructions](docs/AGENT_PLAY.md), run the game and relay it in your conversation. You speak, ask rules questions and choose actions in the Agent, not in a terminal yourself. The Agent needs local command execution and a persistent interactive process. This is a capability-dependent bridge, not verified native support for every Agent product.

### Terminal bridge — for the Agent, or direct testing

The Agent can use the following command after installation and local Codex login. It first asks for the board, then verifies a real model response before dealing roles. Manual terminal play is also available. No browser server is needed.

```bash
python -u -m werewolf_web.chat_game --lang en
```

Choose your identity before play with `--role seer`, or leave it random.
Use `--model` and `--effort` for per-game configuration; defaults are
`gpt-5.6-terra` / `medium`. The default cap is 240 calls (including preflight),
adjustable with `--max-model-calls` up to 1000; each call times out after 180s.
Model turns can take tens of seconds each. This adapter requires a Codex CLI
supporting the isolation/structured-output flags it uses; unsupported versions
fail closed. It does not install tools, create keys or alter global settings.
`--board classic --list-roles --lang en` lists legal choices. The browser has
the same **Your role** selector. Other identities remain hidden and board
role counts stay unchanged. See [game setup](docs/GAME_MODES.md) and the
research-only [mechanics lab](docs/MECHANICS_LAB.md).

| Situation | Input |
| --- | --- |
| Speak | Type your statement |
| Claim a role / accuse a player | `I am the Seer. I suspect #3.` |
| Run for sheriff | `yes` or `no` |
| Vote | `vote 3` |
| Support no exile | `peaceful day` |
| Withdraw after candidacy speeches | `withdraw` or `stay` |
| Review public ballots / statements | `latest votes`, `day 2 speeches`, `/history` |
| See current seats | `/seats` |
| Choose a night target | `choose 3` |
| Use one Witch potion | `save 3` **or** `poison 4` |
| Skip an optional night action | `pass` |
| Duel / self-destruct / slander when prompted | `choose 3` or `pass` |
| Ask the host about rules | `?How does the Witch work?` |

On original boards, the Witch cannot use both potions in one night. The experimental
`divine_witch_dual` board allows `save 3 poison 4` in one action. Valid targets and
available potions are shown in the prompt. Rules questions do not consume your turn.

Use `--lang zh-CN` for Chinese or `--seed 42` for a repeatable initial setup. The chat action parser accepts a small explicit vocabulary; it is not a general natural-language command interpreter.

### Browser game — optional

```bash
python -m uvicorn werewolf_web.run:app --host 127.0.0.1 --port 8000
```

Open [localhost:8000](http://127.0.0.1:8000), choose **English** or **中文**, and start a game. Choose **Local AI only** in Model settings for offline play.

The conversation and current action occupy the main area; your role and compact player roster are on the left, alongside expandable private rules help. On narrow screens the conversation comes first and supporting details follow. Setup collapses after a successful start. Changing interfaces starts a new game, not a transfer of the current session.

New to Werewolf? Read the [two-minute player guide](docs/PLAYER_GUIDE.md).

### AI-only observer mode — developer tool, not the recommended player entry

```bash
python -m werewolf_web.cli_game --board classic --seed 42 --no-think
```

This developer-oriented mode is in Chinese and may expose every role and private reasoning. It is separate from the human-playable chat interface.

## Legacy API rephrasing (browser / `--backend legacy`)

This older path uses local rule decisions and optionally rephrases them with
an API model. It is **not** Codex decision play. `--offline` is a rule-flow test
requiring no game API key. Legacy rephrasing may fall back to local wording;
the normal Codex backend never does.

Copy the template and configure your own provider:

```bash
cp werewolf_web/.env.example werewolf_web/.env
```

| Setting | Purpose |
| --- | --- |
| `LLM_ENABLED` | Enable or disable model expression |
| `LLM_BASE_URL` | OpenAI-compatible Chat Completions endpoint |
| `LLM_API_KEY` | Provider credential |
| `LLM_MODEL` | Model ID offered by that endpoint |
| `LLM_TIMEOUT_SECONDS` | Per-call timeout |
| `LLM_GAME_MAX_CALLS` | Model-call budget per game |
| `LLM_REASONING_EFFORT` / `LLM_REASONING_PARAM` | Optional provider-specific reasoning field |

Leave reasoning settings empty unless your endpoint explicitly supports them. Native provider APIs that do not implement OpenAI-compatible Chat Completions are not supported directly.

Browser users can supply a key for one game. That key is sent to this game's Python backend, then used for requests to the configured provider; it is not a browser-only integration. The application omits keys from its game events, memory, and review files. Provider policies and server logs are outside that guarantee.

When online expression is enabled, the provider receives the speaking NPC's context, including its legal private role information and prior player statements. Do not include sensitive real-world information in game chat.

## Architecture

```text
Browser / terminal chat
          |
     GameSession
      /   |    \
 Rules  NPC adapter  Host
          |
 Codex decisions (Agent) / local Brain + optional rephrasing (legacy browser)
```

- `werewolf_web/run.py`: shared playable session and FastAPI/SSE adapter.
- `werewolf_web/game/`: seats, phases, actions, outcomes, and events.
- `werewolf_web/ai/brain.py`: local beliefs and decisions for each NPC.
- `werewolf_web/ai/codex_player.py`: isolated model calls, lawful context, per-seat decision memory and validated actions. Full public records are supplied each turn; no context truncation or cross-game model learning is implemented yet.
- `werewolf_web/ai/strategy.py`, `growth.py`, `affect.py`: decision traces, cognitive profiles, and bounded state changes.
- `werewolf_web/ai/host.py`: narration, public-rule help, table moderation, and post-game review.
- `werewolf_web/i18n.py`: localized NPC identities and game text.
- `werewolf_web/static/`: browser presentation.
- `werewolf_web/data/personas/`: canonical Chinese persona definitions.

NPCs keep stable IDs across languages. Canonical personas determine behavior; localization supplies display names and phrasing. If you edit a persona, update its English presentation in `i18n.py` as well. The Chinese persona headings are parser inputs, not documentation that can be translated independently.

## Local data and deployment

Runtime files are written under `werewolf_web/data/`: NPC memories, host style, and game reviews. These files and `.env` are ignored by Git. They can include game statements and private role information.

Browser and terminal matches each use a fresh session memory directory. The learning
machinery exists, but new playable sessions do not automatically inherit earlier
games' NPC memories. Active games live in memory and do not survive a process restart.

The backend is intended for your machine or a trusted development environment. It has no user authentication, durable sessions, or production-grade request/resource limits. Do not expose it as a public multi-user service without additional work. See [security guidance](SECURITY.md).

## Development and tests

```bash
python -m unittest discover -s tests -q
node --check werewolf_web/static/js/app.js
node --check werewolf_web/static/js/i18n.js
npm ci
npm test
python scripts/check_release.py
```

Use Node.js 24.15+ (24.x) for development checks and DOM tests. Node and npm are
not needed to play; the browser app has no build step. `npm ci` installs
development-only dependencies from the committed lockfile.

The suite includes a 40-match matrix across ten boards, two languages and two modes, plus targeted selected-role and Divine Witch games. Completion tests verify termination and review; they do not certify competitive balance or every provider's behavior. A separate frozen-extreme Divine Witch screen uses local AI decisions, not model API calls.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing rules or NPC information boundaries.
See [architecture and extension recipes](docs/ARCHITECTURE.md) for where to add
boards, roles, personalities, languages or transports.

## License and assets

Source code is licensed under the [MIT License](LICENSE). The maintainer generated the portraits locally with AI and authorized their use in this project and publication with the repository. Portraits are not covered by MIT; other uses require separate permission. See [asset provenance](docs/ASSETS.md) and [publication readiness](docs/PUBLIC_RELEASE.md).
