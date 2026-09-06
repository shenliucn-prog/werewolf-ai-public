# Security

## Deployment scope

The supported use is a local or trusted development environment. Start the server on `127.0.0.1`. Publishing the source code does not make the application suitable for an unauthenticated public hosting service.

The current server lacks user authentication, durable sessions, comprehensive rate limits, and a deployment-level outbound-network policy. Custom model endpoints can target local network services. Synchronous model calls can delay other work on the server. Add appropriate access controls, HTTPS, resource limits, secret handling, and network restrictions before hosting for untrusted users.

## Data and model calls

- Browser-supplied API keys reach the Python backend and the selected provider. They are not stored in game memory or review files by the application.
- Model prompts can include NPC-private role information and user statements. Provider retention policies are separate from this project.
- Reviews and NPC memory are local files under `werewolf_web/data/`; treat them as private match data.
- The checked-in `.env.example` is a template. Never commit `.env`, credentials, provider responses containing secrets, or runtime transcripts.
- The current LLM intent checks are heuristic, not a formal guarantee that generated language matches every structured decision.

## Reporting a vulnerability

Do not disclose exploitable details or credentials in a public issue. If GitHub private vulnerability reporting is enabled, use the repository's Security tab to report privately. Otherwise, open a neutral issue asking the maintainer for a private reporting channel, without including vulnerability details, tokens, or personal data.

Include affected versions/commits and a minimal reproduction once a private channel is available. No response-time or supported-version commitment has been established yet.
