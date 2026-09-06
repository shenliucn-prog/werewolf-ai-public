# First public snapshot

Publication authorized by the maintainer on 2026-09-06 UTC.

Destination: [shenliucn-prog/werewolf-ai-public](https://github.com/shenliucn-prog/werewolf-ai-public).

This is an experimental, text-driven, local Werewolf game and research environment. It supports English and Chinese, browser and conversational play, selectable player roles, configurable/random NPC personalities, optional conjecture mode and experimental Divine Witch boards. Voice and behavioral visual input are not implemented. No API key is required to play locally; optional model usage may incur provider charges.

## Publication boundaries

- Source code is MIT licensed; portrait permissions are separately described in [ASSETS.md](ASSETS.md).
- The public history starts from a reviewed snapshot, not the private development repository's Git objects. Original development files and history remain unchanged.
- The twelve portrait copies retain pixel data and the separate AI provenance envelope. Only the reviewed independent description fields were redacted. Remaining provenance identifiers exist and cryptographic signature validity is not asserted.
- The base candidate passed 198 Python tests, frontend DOM/syntax checks and compatibility replay of 96 recorded Divine Witch games without new model calls. The first public commit additionally updates publication documentation and clone URLs. Check [GitHub Actions](https://github.com/shenliucn-prog/werewolf-ai-public/actions) for that exact commit's results; prior local checks are not a substitute for CI.
- Four earlier model experiment artifacts include two completed games and two protocol failures; replaying a recorded failure does not turn it into a successful experiment. None of these small experiments establishes game balance.
- The application is not a production-ready public game server. Bind to localhost and read [SECURITY.md](../SECURITY.md) before considering deployment.

## Maintenance

Contribute through the public repository's pull requests. Public releases should receive reviewed file-level updates, not merges of private history or copies of runtime memories, real transcripts, credentials or unreviewed assets. The intended branch policy requires passing Python matrix and dependency checks, disallows force pushes/deletion and applies to administrators. A second maintainer's approval is not required.

The root `PUBLICATION_MANIFEST.json` records the initial snapshot's file hashes, excluding itself. It is a historical packaging record, not a signature or a dynamically updated integrity database for future commits. Git commits identify subsequent versions. Exporters generate a fresh manifest for later history-free packages.

The older audit and preparation documents are retained as dated evidence, with their original limitations. Current visibility and protection settings should be verified on GitHub rather than inferred from these historical notes.
