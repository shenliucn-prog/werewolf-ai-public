# Security

## Deployment scope

The supported use is a local or trusted development environment. Start the server on `127.0.0.1`. Publishing the source code does not make the application suitable for an unauthenticated public hosting service.

The current server lacks user authentication, comprehensive rate limits, and a deployment-level outbound-network policy. Durable local game checkpoints exist; they are not authenticated multi-user sessions. Custom model endpoints can target local network services. Synchronous model calls can delay other work on the server. Add appropriate access controls, HTTPS, resource limits, secret handling, and network restrictions before hosting for untrusted users.

## Data and model calls

- Browser-supplied API keys reach the Python backend and the selected provider. They are not stored in game memory or review files by the application.
- Model prompts can include NPC-private role information and user statements. Provider retention policies are separate from this project.
- Reviews and NPC memory are local files under `werewolf_web/data/`; treat them as private match data.
- The checked-in `.env.example` is a template. Never commit `.env`, credentials, provider responses containing secrets, or runtime transcripts.
- The current LLM intent checks are heuristic, not a formal guarantee that generated language matches every structured decision.

## Reporting a vulnerability

Do not disclose exploitable details or credentials in a public issue. Private vulnerability reporting is enabled for this repository: use [Report a vulnerability](https://github.com/shenliucn-prog/werewolf-ai-public/security/advisories/new). If unavailable in a fork, ask its maintainer for a private channel without disclosing details.

请通过上述私密漏洞入口报告安全问题，勿在公开 Issue 上传密钥或完整存档。
本项目支持本地持久化对局，但没有面向公网多用户的认证隔离。

Include affected versions/commits and a minimal reproduction once a private channel is available. No response-time or supported-version commitment has been established yet.
