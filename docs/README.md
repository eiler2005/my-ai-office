# Documentation

[Project README](../README.md)

Start from the row that matches why you are here.

| If you are… | Read, in this order |
| --- | --- |
| **Evaluating this as engineering work** | [Engineering case study](engineering-case-study.md) → [Decision records](adr/) → [Architecture](architecture.md) |
| **Trying to understand the system** | [Architecture](architecture.md) → [Workflows](workflows.md) → [Knowledge](knowledge.md) |
| **Going to operate it** | [Operations](hermes/operations.md) → [Reliability](reliability.md) → [Security](security.md) → [Panel](hermes/panel.md) |
| **Looking something up** | [Glossary](reference/glossary.md) · [Services](reference/services.md) · [Schedules](reference/schedules.md) · [Versions](reference/versions.md) |
| **Here for the migration story** | [Migration plan](hermes/migration-plan.md) → [Acceptance](hermes/acceptance.md) → [Cutover record](hermes/cutover-record-2026-09-06.md) → [Archive](archive/) |

## Current documentation

### Design

| Document | What it covers |
| --- | --- |
| [Architecture](architecture.md) | Layered business and agent architecture, runtime boundaries, production topology, queue and delivery semantics, models, knowledge, interfaces, recovery. |
| [Workflows](workflows.md) | The interactive and background paths traced end to end, plus the catalogue of what runs on each. |
| [Reliability](reliability.md) | Slot identity, the pending list, delivery receipts, and reconciliation — with the incidents that exercised them. |
| [Knowledge](knowledge.md) | The five memory layers, why capture is explicit, and how grounded search works. |
| [Security](security.md) | What is protected, the six trust boundaries, secret handling, and the known limits. |
| [Engineering case study](engineering-case-study.md) | The design decisions as a narrative: integration boundaries, model limits, provenance, delivery uncertainty, migration. |

### Decisions

| Document | What it covers |
| --- | --- |
| [Decision records](adr/) | Twelve ADRs: the situation that forced each decision, what was chosen, what else was considered, and what it still costs. |

### Operations

| Document | What it covers |
| --- | --- |
| [Operations](hermes/operations.md) | Build, manifests and modes, profiles, model configuration, schedules and queues, knowledge services, the panel, observation. |
| [Panel runbook](hermes/panel.md) | The isolated dashboard: mTLS, authentication, WebSocket, certificate maintenance. |
| [Acceptance record](hermes/acceptance.md) | VPS verification scope, the 209 recorded checks, production fixes, and the gates still open. |

### Reference

| Document | What it covers |
| --- | --- |
| [Glossary](reference/glossary.md) | Terms that mean something specific here. |
| [Services](reference/services.md) | All 13 containers, their roles, and their boundaries. |
| [Schedules](reference/schedules.md) | Every recurring job, and how a schedule becomes a paused cron job. |
| [Versions](reference/versions.md) | What every component is pinned to, whether it is current, and how to move a pin. |

### Migration record

| Document | What it covers |
| --- | --- |
| [Migration plan](hermes/migration-plan.md) | The staged plan of record: rehearsal, waiting period, cutover, rollback, acceptance criteria. |
| [Transfer inventory](hermes/inventory.md) | Service and data mapping, host measurements, schedules, dependencies, and secret categories without their values. |
| [Cutover and rollback](hermes/cutover-rollback.md) | Cold snapshot, staged restore, activation, and the safe rollback procedure. |
| [Cutover record](hermes/cutover-record-2026-09-06.md) | The recorded production switch and the retained rollback boundary. |
| [Drift log](hermes/drift-log.md) | Behavioural changes in the source system that a snapshot could not carry. |

### Archive

| Document | What it covers |
| --- | --- |
| [Archive](archive/) | Earlier stages of the project, clearly marked as historical. Includes the original concept document and 26 documents from the predecessor runtime. |

## Conventions

**Language.** Everything is English, with three deliberate exceptions: the `обсуди:` trigger keyword,
Russian product names in historical changelog entries, and `workspace/*.md` — predecessor-era prompt
artifacts kept as a behavioural record, which Hermes does not mount. See
[CONTRIBUTING](../CONTRIBUTING.md#language).

**Status claims are bounded.** Where a check has not been run, the documentation says so. The
[acceptance record](hermes/acceptance.md) keeps its open gates open.

**Diagrams.** Mermaid for anything that changes with the code — it diffs in review and follows the
reader's theme. Hand-authored SVG for the four structural diagrams, generated as light/dark pairs by
[`scripts/render-diagrams.py`](../scripts/render-diagrams.py) so the pair cannot drift.

**Numbering.** Only ADRs are numbered. The numbering in `archive/openclaw/` is the predecessor's
original sequence and carries no meaning in the current documentation.

**Nothing secret is here.** Live addresses, credentials, message bodies, personal notes, and private
archives are excluded by design and gated by a secret scan on every push.
