# Offline choice games / 离线选项局

An explicit, terminal-first alternative to free-language model play. It uses
the same `GameSession` and rules engine, but NPCs use local strategies and
players select structured actions. No model connection or model calls are
required, and **no campaign attempts, unlocks or scores are recorded**.

## Start

After installing the normal Python dependencies, run from the repository root:

```sh
python -m werewolf_web.offline_game --cast --lang en
python -m werewolf_web.offline_game --board classic --character xicao --lang en
python -m werewolf_web.offline_game --board classic --character laomai --role witch --lang en
python -m werewolf_web.offline_game --board classic --spectate --lang en
```

The twelve fixed personalities are independent of the randomly dealt game
roles. `--character` replaces that character with you; their autonomous version
does not also appear at another seat. `--name` optionally changes your name.
You are not forced to roleplay the selected personality. `--role` can select
any role on the chosen board, or `random`. All ten existing boards are accepted;
experimental boards retain their existing rule and balance limitations.

`--spectate` runs twelve local NPCs and displays **public information only**.
It does not display any seat's private night menu, role or check. Public flips
and final role reveals remain visible according to the existing rules. This
entry has no omniscient mode and cannot switch from spectator to player during
a match. Output advances automatically after the initial ready confirmation;
it is not a paced replay viewer.

## Play with options

At each request, choose a category, then a numbered option. Categories include
role claims, provisional suspicion/support, questions, reports, responses and
citations of recent public speeches/events. Report options are available to
bluffing players too: selecting a report does not certify that it is true.
Night skills, sheriff candidacy/withdrawal and ballots use the engine's legal
candidate lists. Witch menus respect potion availability and dual-use rules.

Use `?` followed by a rules question, `/seats`, or `/history` at a menu without
spending the action. Ordinary free text is not interpreted as debate. The
host retains ordered speeches and bounded interruptions/clarification windows.

NPCs consume the structured claim/accusation/defense fields rather than trying
to understand arbitrary text. Admissions and refusals have small personality-
dependent effects, at most once per identical response per day. These are
heuristics, not proof of alignment. Wolves maintain a per-night bluff report;
actual seers use only their own lawful checks. Every claim stays a claim until
public evidence resolves it. Night actions and votes use the existing local
Brain strategy; this release is not a new optimal Werewolf solver.

## Save and continue

The startup banner prints the game ID and a resume command:

```sh
python -m werewolf_web.offline_game --resume GAME_ID
```

Type `q` at a menu to save and exit. EOF also pauses. Checkpoints use the
existing atomic, checksummed private storage under the ignored checkpoints
directory. The character, language, spectator/player mode, NPC memory and
pending choice are restored. A normal `chat_game`/Web restore must not silently
load this save as a different mode: use `offline_game --resume`.

There is no cross-game personality growth in this mode. Saves may contain all
roles and private NPC state; do not share them or commit them to Git. Only
synthetic fixtures belong in tests. Multiple processes must not run the same
saved game concurrently.

## Scope

This is a complete local rule game, unlike the earlier
[single-scene discussion lab](OFFLINE_DISCUSSION_LAB.md). It supports the
terminal, an Agent relaying that terminal, and the Web's separate **Offline
choice game** panel. Choose the board and role above that panel, then a fixed
character or public spectating. Confirm offline play explicitly; the normal
Continue game button restores its choices. Model-driven interfaces are unchanged.
Conjecture tables and omniscient research viewing are not exposed here.

Automated coverage includes all boards, every playable role, public spectator
filtering, fixed cast replacement, both languages, invalid/stale submissions,
and pause/resume through the real terminal loop. This demonstrates rule-flow
completion, not balanced win rates or proven character appeal. Dialogue is
authored and necessarily less varied than model-driven free conversation.

## 中文快速说明

```sh
python -m werewolf_web.offline_game --cast
python -m werewolf_web.offline_game --board classic --character xicao
python -m werewolf_web.offline_game --board classic --character tiandou --role seer
python -m werewolf_web.offline_game --board classic --spectate
```

- 12 个固定人格，身份另行分配；可替代其中一个，也可公共视角旁观。
- 使用「类别 → 编号」发言，不需要输入自然语言。查验报告选项也允许伪装者使用。
- 发牌、夜间技能、上警退警、投票、死亡技能和胜负共用现有引擎。
- 输入 `q` 保存退出，按启动时给出的 `--resume` 命令继续；不能中途换视角。
- `?规则问题`、`/seats`、`/history` 不消耗行动。
- 完全不调用模型、不计正式闯关成绩。存档只留本地，不要上传。
- 支持终端／Agent 转述终端，以及网页独立的「离线选项玩法」面板。使用上方板子与身份，选择人物或公开旁观；「继续游戏」可恢复选项。旁观自动推进，没有全知开关。
- 程序策略和人物台词仍有局限；跑通对局不代表平衡已经认证。
