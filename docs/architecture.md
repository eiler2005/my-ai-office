# Architecture

[Project overview](../README.md) · [Engineering case study](engineering-case-study.md) · [Operations](hermes/operations.md)

My AI Office connects a conversational assistant to durable background workflows. Hermes Agent supplies the runtime and interfaces; the `benka-integrations` package supplies the office-specific tools, adapters, queue handling, delivery controls, and migration logic.

The recorded production switch to Hermes took place on **6 September 2026**. The [cutover record](hermes/cutover-record-2026-09-06.md) and [acceptance record](hermes/acceptance.md) distinguish completed checks from open production acceptance. Earlier numbered OpenClaw documents describe the source deployment.

## Runtime boundaries

```mermaid
flowchart TB
    User["User"] <--> Interfaces["Telegram · CLI · Authenticated dashboard"]
    Interfaces <--> Gateway["Hermes Gateway / agent"]
    Gateway --> Plugin["Benka native tools"]
    Plugin --> Knowledge["Wiki / LightRAG / private archive"]
    Plugin --> Queue["Redis Streams"]
    Cron["Hermes cron scripts"] --> Queue
    Queue --> Workers["Integration workers"]
    Sources["Approved source APIs"] --> Workers
    Workers --> Models["Fresh AIAgent subprocess"]
    Models --> Validation["Result validation / deterministic fallback"]
    Validation --> Send["Hermes send + receipt tracking"]
    Send --> Topics["Telegram topics"]
    Workers --> Reconcile["Reconciliation records"]
    Send --> Reconcile
```

| Boundary | Responsibility | Source |
| --- | --- | --- |
| Hermes runtime | Agent execution, channel ingress, CLI, dashboard, native cron | [Pinned upstream](../vendor/hermes-agent) |
| Benka plugin | Seven office tools, wiki-first instructions, domain configuration | [plugin.py](../src/benka_integrations/plugin.py) |
| Integration workers | Source collection and deterministic processing around bounded model calls | [Package](../src/benka_integrations) · [Pipelines](../artifacts) |
| Redis | Job streams, slot deduplication, execution state, reconciliation, delivery receipts | [queue.py](../src/benka_integrations/queue.py) · [delivery.py](../src/benka_integrations/delivery.py) |
| Deployment | Separate services, networks, persistent mounts, resource limits, proxy configuration | [Compose and Docker files](../deploy/hermes) |

The agent runtime is containerized without the host Docker socket. Private deployment manifests bind source accounts, destinations, credentials, and domain paths. The public repository contains templates and code, not those bindings.

## Production topology

The production `benka-hermes` Compose project defines 13 services:

| Group | Compose services | Responsibility |
| --- | --- | --- |
| Agent access | `gateway`, `dashboard`, `caddy` | Telegram polling and profile routing; isolated browser UI; TLS/mTLS ingress. |
| State and knowledge | `redis`, `wiki`, `lightrag`, `omniroute` | Integration bus and receipts; durable wiki; graph retrieval; assigned provider routing. |
| Business workers | `worker-email-personal`, `worker-email-work`, `worker-telegram`, `worker-signals`, `worker-last30days`, `worker-maintenance` | Separate source processing, state, manifests, Redis groups, and delivery permissions. |

The `redis` service is the current **integration bus**. Hermes cron enqueues jobs into named streams; dedicated consumer groups process them; job status, confirmed delivery receipts, and reconciliation records remain in Redis. The inherited [`artifacts/integration-bus`](../artifacts/integration-bus) directory documents the predecessor's standalone Redis deployment and is not started as a second production bus.

External integrations are not containers. AgentMail, Telegram/Telethon, Reddit, Hacker News, GitHub, X, Bluesky, YouTube, Polymarket, and web discovery are source APIs or transports consumed by the relevant worker when enabled. Reddit's native JSON/RSS hybrid adapter is part of the Last30Days build under [`signals-bridge/last30days_patches`](../artifacts/signals-bridge/last30days_patches).

The VPS also hosts independent Compose projects: `reddit-compass`, `moex-futoi`, `cheap-intelligence`, and `stealth`. They share the host only. They are outside My AI Office's service graph, networks, state, and lifecycle commands. `reddit-compass` is therefore distinct from the external Reddit source used by Last30Days. See the [README service and source map](../README.md#services) and the [migration inventory](hermes/inventory.md#vps-hermes-и-соседние-проекты).

## Scheduling, execution, and delivery

Hermes cron owns application schedules after activation. Script jobs enqueue work into Redis and disable cron's automatic delivery; workers own processing and the shared delivery module owns publication.

1. The enqueue operation derives a stable run ID from the job and time slot. A Redis Lua operation checks the deduplication key and adds the job atomically.
2. A consumer group assigns work. Completed runs are acknowledged without repeating their work.
3. A worker processes the source data, validates any model-generated fields, and records the result.
4. Delivery reserves a fingerprint before calling `hermes send --json`, then saves confirmed message identifiers.
5. Recovered pending jobs and uncertain sends enter reconciliation. An operator must establish what happened before replaying consequential work.

This addresses duplicate scheduling and ambiguous delivery without claiming exactly-once effects across Redis and Telegram. The deduplication window is finite; explicit recovery still matters.

## Model execution

**Interactive assistant configuration and background integration routing are separate.** The main assistant uses the configured OpenAI route. Its dialogue, auxiliary, and delegation settings can select different models; this is configuration, not a universal automatic complexity classifier.

Background workflows use [models.py](../src/benka_integrations/models.py) and [model_child.py](../src/benka_integrations/model_child.py):

- Each call starts a fresh subprocess and temporary Hermes home, with tools disabled and personal memory, context files, and session persistence skipped.
- Explicit provider routes bound the fallback chain. Integration routes can differ from the main assistant and can use Qwen or DeepSeek first where configured.
- Iteration, token, and wall-clock limits constrain execution.
- Parsed output passes workflow-specific validation. When the model chain fails, the pipeline can return a deterministic fallback.

OmniRoute remains available for workloads assigned to it; it is not assumed to proxy every call. Model names and credentials are deployment configuration. Provider behavior and availability require live verification separately from fixture-based contract checks.

## Knowledge and context

| Store | Purpose | Boundary |
| --- | --- | --- |
| Markdown wiki | Durable, editable knowledge and idea chains, compatible with Obsidian | The primary knowledge store; records retain source metadata |
| LightRAG | Graph-assisted retrieval over selected knowledge | A search layer with its own indexing state and embedding requirements |
| Private SQLite FTS archive | Search over imported conversations and diaries | Historical material stays outside normal session context and outside Git |
| Hermes memory | Compact, persistent user facts and preferences | Selected durable context, not a copy of the full archive |

Wiki operations preserve fields such as `source_type`, `source`, `capture_mode`, and `promote_fingerprint`, and return artifact paths and RAG status. Captures and promotions retain provenance. The `обсуди:` convention requests discussion without automatic persistence, and whole mailboxes are not indexed by default.

Personal, work, family, and sandbox profiles receive separate configured domain bindings. Tool paths come from the deployment manifest rather than model-supplied paths. These controls need the routing and access checks in the acceptance matrix; profile names alone do not establish isolation. See the [plugin](../src/benka_integrations/plugin.py) and [wiki adapter](../src/benka_integrations/wiki.py).

## Interfaces and access

Telegram is the everyday conversational and briefing surface. CLI exposes operator and integration commands. A separate Hermes dashboard process sits behind Caddy with TLS/mTLS and application authentication.

The panel deployment uses a separate listener alongside existing VPS services. Its [runbook](hermes/panel.md) covers access, WebSocket behavior, and certificate operations; public documentation does not expose the production domain or credentials.

Source APIs and model providers are external dependencies. Persisting state on a private VPS does not make those requests local or eliminate provider-specific limits.

## Migration and recovery

The OpenClaw-to-Hermes migration preserves processing behavior and state contracts while replacing the runtime adapters. The tooling covers cold snapshot creation and verification, staged restore, a compatible OpenClaw import layout, archive indexing, and a three-way wiki comparison for rollback.

Deployment preparation and production activation are separate operations. Activation requires an explicit operator decision, a fresh consistent snapshot, and stopping the former writers. Rollback after new writes requires reconciling new artifacts, cursors, confirmed deliveries, and pending work before restarting old processors.

The [migration implementation](../src/benka_integrations/migration.py), [migration plan](25-hermes-migration-plan.md), and [cutover/rollback runbook](hermes/cutover-rollback.md) document the mechanics. The recorded switch retained the old state and stopped the former server's Docker services; observation and final acceptance are tracked separately.

## Verification boundary

Application builds and tests run on the VPS, using isolated containers and synthetic fixtures for rehearsal. The [acceptance record](hermes/acceptance.md) identifies the tested tree, container constraints, 209 regression results, native Hermes contracts, Redis recovery, and dashboard checks.

Those results establish specific behavior for the recorded candidate. They do not substitute for current provider authentication, a real Telegram conversation, full workflow acceptance, the observation period, or recovery verification after production writes.
