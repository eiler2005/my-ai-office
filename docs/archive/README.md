# Archive

Documents in this directory describe **earlier stages of the project**. They are kept because the
migration record is part of the engineering story — not because they describe the running system.

> [!IMPORTANT]
> Nothing in this directory deploys, configures, or operates the current office. Production has run
> on Hermes Agent since **2026-09-06**. Start from the [documentation map](../README.md).

## What is here

| Path | Era | Why it is kept |
| --- | --- | --- |
| [`original-concept.md`](original-concept.md) | Pre-migration concept | The first public statement of the idea: five agent roles, design principles, and the intended scope before any of it was built on Hermes. Useful as a "what was promised vs. what shipped" reference. |
| [`openclaw/`](openclaw/) | OpenClaw runtime, 2026-05 → 2026-09 | 26 operational documents from the predecessor system: server state, runbooks, security model, memory architecture, the LLM-Wiki design, and the version-compatibility ledger that ultimately motivated the runtime migration. |

## The OpenClaw era in one paragraph

The first working version of this office ran on [OpenClaw](https://github.com/coollabsio/openclaw)
as a self-hosted gateway with four bridge services, OmniRoute model dispatch, LightRAG memory, and
a Telegram supergroup as the interface. It worked, and most of its *business* logic survives
unchanged in the current system. What did not survive was the runtime: the
[version compatibility ledger](openclaw/22-openclaw-version-compatibility-ledger.md) records the
accumulated defects and workarounds that made an upgrade path untenable, and the
[migration plan](../hermes/migration-plan.md) is the response to it. The predecessor repository is
frozen at [`eiler2005/clawden-ai`](https://github.com/eiler2005/clawden-ai).

The decision itself, with its trade-offs, is recorded as
[ADR-0009: Migrate the agent runtime from OpenClaw to Hermes Agent](../adr/0009-migrate-runtime-to-hermes.md).

## Reading the OpenClaw archive

If you are here for engineering context rather than history, these four are the ones worth reading:

| Document | Why |
| --- | --- |
| [`README.md`](openclaw/README.md) | The full predecessor overview — architecture, services, data flows, and Telegram topology as they stood at freeze. |
| [`07-architecture-and-security.md`](openclaw/07-architecture-and-security.md) | The security model (mTLS, UFW, tool profiles) that the current system inherited. |
| [`10-memory-architecture.md`](openclaw/10-memory-architecture.md) | The three-layer memory design — live / raw / derived — still the basis of [knowledge.md](../knowledge.md). |
| [`22-openclaw-version-compatibility-ledger.md`](openclaw/22-openclaw-version-compatibility-ledger.md) | The defect ledger that justified replacing the runtime. |

Documents here are numbered in their original OpenClaw-era sequence. That numbering has no meaning
in the current documentation, which is organised by topic.
