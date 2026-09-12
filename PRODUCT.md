# Werewolf AI product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People running a local single-player Werewolf game, including first-time players,
in Chinese or English. The player may use an Agent conversation, terminal, or
the optional browser interface.

## Product Purpose

Make a complete game against NPCs understandable and playable. The game, not
its UI, is the core experience. The browser must make setup, twelve seats,
public discussion, private player actions, and the result easy to follow.

## Operating Context

Python enforces rules and saves local progress. Existing HTML, CSS and JavaScript
serve a local browser client. Agent conversation remains the recommended entry.

## Capabilities and Constraints

- Model API and supported user-Agent adapters drive formal play. Connection
  checks precede dealing. Failures never silently become offline play.
- Explicit offline simulation is separate and does not earn campaign progress.
- Campaign, free game and continuing a saved game are existing workflows.
- Public seats and speech must remain distinct from private player information.
- Text is the only gameplay medium. Portraits are decoration, not visual clues.
- Preserve existing rules, driver contracts, saves, teaching and review retries.
- Support Chinese, English, desktop and mobile web.

## Brand Commitments

Retain the existing Werewolf AI / 暗夜茶馆 product identity. No Nothing company
design assets or branding are part of this personal open-source project.

## Evidence on Hand

README.md, README.zh-CN.md, docs/PLAYER_GUIDE.md and the implemented browser
entrypoints describe current capabilities. Automated browser fixtures are
synthetic; they do not establish real-model playing strength.

## Product Principles

- Make the next action clear without hiding the table or discussion.
- Keep the full original public speech available.
- Disclose uncertainty and explicit simulation modes.
- Preserve recovery and error paths while improving presentation.

## Confirmation

The user confirmed this scope on 2026-09-11. Visual direction is selected
separately; this record does not prescribe a palette or composition.
