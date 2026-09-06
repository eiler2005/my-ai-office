# Architecture decision records

An ADR captures **one decision, the situation that forced it, and what it cost** — at the moment it
was made, not in hindsight. The rest of this documentation describes what the system does; these
records explain why it does it that way, and what the alternatives would have meant.

Records here are never rewritten to look better later. When a decision turns out to be wrong, it is
superseded by a new record and its status changes; the original stays readable, including the parts
that did not survive contact with production.

## Index

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-self-host-on-one-private-vps.md) | Self-host the whole office on one private VPS | Accepted | 2026-05-31 |
| [0002](0002-telegram-as-the-operating-surface.md) | Use Telegram forum topics as the primary operating surface | Accepted | 2026-06-14 |
| [0003](0003-redis-streams-as-the-integration-bus.md) | Use Redis Streams as the integration bus | Accepted | 2026-07-02 |
| [0004](0004-separate-orchestration-from-domain-logic.md) | Keep orchestration separate from domain logic | Accepted | 2026-08-20 |
| [0005](0005-wiki-first-capture-rag-as-retrieval.md) | Capture into the wiki first; treat retrieval as a derived index | Accepted | 2026-07-18 |
| [0006](0006-bound-background-model-work.md) | Run background model work in a fresh bounded subprocess | Accepted | 2026-08-22 |
| [0007](0007-delivery-receipts-over-blind-retry.md) | Confirm delivery by receipt; reconcile instead of retrying | Accepted | 2026-08-25 |
| [0008](0008-tiered-model-routing-with-failover.md) | Route model work by tier with explicit provider failover | Accepted | 2026-06-20 |
| [0009](0009-migrate-runtime-to-hermes.md) | Migrate the agent runtime from OpenClaw to Hermes Agent | Accepted | 2026-09-06 |
| [0010](0010-single-public-listener-with-mtls.md) | Expose exactly one public listener, behind mTLS | Accepted | 2026-06-02 |
| [0011](0011-verification-on-the-vps-not-in-ci.md) | Verify on the VPS; keep CI to publication safety | Accepted | 2026-09-06 |
| [0012](0012-vendor-hermes-as-a-pinned-submodule.md) | Vendor Hermes Agent as a pinned Git submodule | Accepted | 2026-08-18 |

**Status values.** `Proposed` — written but not acted on. `Accepted` — in force. `Superseded by
ADR-NNNN` — replaced; the record stays. `Deprecated` — no longer applies and nothing replaced it.

## Template

Copy this for a new record. Number it with the next free integer and name the file after the
decision, not the component.

```markdown
# ADR-NNNN: <decision, as a sentence in the imperative>

- **Status:** Proposed | Accepted | Superseded by [ADR-NNNN](NNNN-....md) | Deprecated
- **Date:** YYYY-MM-DD
- **Context:** [links to the docs and code this decision governs]

## Context

What was true when this came up. The constraint, the failure, or the requirement that made a
decision necessary. Facts and measurements, not justification.

## Decision

What was decided, stated so that someone can tell whether the code follows it.

## Alternatives considered

What else was on the table and the specific reason it lost. A record with no alternatives is
usually a decision nobody actually made.

## Consequences

What this bought, and what it costs — including the costs that are still being paid. Name the
things this makes harder, not only the things it makes possible.
```

## Related

- [Architecture](../architecture.md) — what the system is
- [Engineering case study](../engineering-case-study.md) — the narrative version of several of these
  decisions
- [Archive](../archive/) — the OpenClaw-era documents that several records refer to
