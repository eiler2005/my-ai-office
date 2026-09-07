# Engineering a personal AI office

**By [Denis Ermilov](https://github.com/eiler2005)** · [Project overview](../README.md) · [Architecture](architecture.md)

My AI Office brings information-heavy daily work into a single operating surface: email triage, Telegram digests, signal monitoring, research, and a searchable knowledge base. The project combines source-specific Python pipelines with Hermes Agent, Redis, a Markdown wiki, and graph retrieval.

My contribution is the system around the agent: workflow design, integration code, persistence contracts, model execution boundaries, deployment, and migration tooling. Hermes supplies the underlying agent runtime.

## The problem

Information arrives through different channels, with different meanings. A forwarded email needs its original sender preserved. A digest needs category balance and source links. An idea needs a durable home and a path to promotion. A failed request needs a predictable outcome.

Bringing these together requires more than a shared prompt. Each workflow needs an input contract, a processing policy, a storage decision, and a delivery and recovery path.

| Design pressure | Response |
| --- | --- |
| Many sources, one person's attention | Route concise, source-linked outputs into the appropriate Telegram topics |
| Variable model output and availability | Combine deterministic processing with bounded model calls and validators |
| Scheduled work can be interrupted | Persist job state, deduplicate slots, and reconcile ambiguous outcomes |
| Useful context should outlive a chat | Keep a curated wiki, a retrieval layer, and a separate historical archive |
| The runtime must be replaceable | Preserve workflow algorithms and state contracts behind explicit adapters |

## 1. Keep orchestration separate from domain logic

The original system already contained useful source parsing, scoring, triage, and formatting. Moving to Hermes did not require discarding that work — see [ADR-0009](adr/0009-migrate-runtime-to-hermes.md).

The integration package registers native tools and connects cron, workers, model calls, and delivery. The source-specific pipelines remain recognizable Python modules. This makes the runtime boundary visible to a reviewer and keeps workflow behavior easier to carry across platforms.

**Inspect:** [Benka plugin](../src/benka_integrations/plugin.py), [integration package](../src/benka_integrations), and [source pipelines](../artifacts).

## 2. Make failure states part of the workflow

A scheduled job and a Telegram publication cross different systems. If a process stops after sending but before saving a receipt, an automatic retry can publish twice.

The queue uses stable job/slot identities and atomic Redis enqueue deduplication. The delivery module reserves a fingerprint and distinguishes a confirmed send from an uncertain outcome. Recovered pending work enters reconciliation instead of being replayed blindly.

The tradeoff is deliberate: some ambiguous failures need operator attention. This is preferable for these workflows to silently accepting duplicate publications. The implementation does not promise exactly-once delivery across independent services.

**Inspect:** [Queue lifecycle](../src/benka_integrations/queue.py) and [delivery receipts](../src/benka_integrations/delivery.py).

## 3. Bound the model's job

The model contributes classification, summarization, or synthesis within a pipeline. It does not need a user's entire conversational memory to score a digest item.

Background calls run through a fresh Hermes subprocess with restricted context, disabled tools, explicit provider routes, and execution limits. Workflow validators check the result, and deterministic fallbacks preserve a usable outcome when model calls fail.

Interactive assistant settings and background provider chains are independent. This allows task-specific model choices without hiding provider behavior inside every source integration. It also means the main assistant's fallback order should not be assumed to apply to all background jobs.

**Inspect:** [Model adapter](../src/benka_integrations/models.py), [isolated runner](../src/benka_integrations/model_child.py), and the [model architecture](architecture.md#model-execution).

## 4. Separate knowledge from accumulated data

The wiki is the durable knowledge store. LightRAG provides graph-assisted retrieval. Earlier conversations and diaries go into a private searchable archive, while Hermes memory carries a compact set of stable facts.

Capture is explicit, source metadata is retained, and idea promotion follows an existing chain. This prevents every incoming message from automatically becoming another piece of long-term context and keeps the resulting knowledge editable outside the agent runtime.

The cost of this separation is operational: indexing state, embedding compatibility, archive access, and wiki maintenance each need their own checks.

**Inspect:** [Wiki integration](../src/benka_integrations/wiki.py), [wiki-import](../artifacts/wiki-import), and [knowledge boundaries](architecture.md#knowledge-and-context).

## 5. Treat migration as an implementation problem

Replacing a working assistant means transferring much more than its prompt: schedules, cursors, queues, delivery receipts, wiki artifacts, retrieval state, and user context all have to remain coherent.

The migration tooling verifies cold snapshots, restores into staging, prepares the layout expected by the upstream importer, and reports rollback differences. The runbook separates preparation from activation and requires a fresh snapshot when the actual switch occurs. After new writes, rollback includes reconciliation rather than simply restoring an older archive over current data.

This work carries the original project's Git history forward and records the operational switch separately from code publication.

**Inspect:** [Migration code](../src/benka_integrations/migration.py), [plan](hermes/migration-plan.md), [rollback procedure](hermes/cutover-rollback.md), and [executed cutover](hermes/cutover-record-2026-09-06.md).

## Evidence and present limits

The public record contains sanitized results; source data, credentials, and detailed production logs remain private.

| Recorded evidence | What it establishes |
| --- | --- |
| **209 regression checks in VPS rehearsal** | Recorded coverage across Hermes integration/migration, email, Telegram digest, Signals/Last30Days, and wiki-import |
| **Native Hermes contract checks** | Tool registration, paused cron behavior, and real `AIAgent` interactions with local fixtures |
| **Redis restart checks** | Persistence of dedupe state, delivery receipts, and pending-work reconciliation |
| **Dashboard checks** | Authentication, client-certificate enforcement, and WebSocket ticket behavior |
| **Snapshot/import checks** | Integrity verification, unsafe archive rejection, repeat import, and interrupted restore behavior |
| **Production cutover record, 6 September 2026** | Fresh state transfer, activation on Hermes, and shutdown of the former server's Docker services |

The [acceptance record](hermes/acceptance.md) includes the tested tree and scope. The 209-check result belongs to the recorded rehearsal candidate. Live model availability, complete production workflow acceptance, 48-hour observation, and recovery after production writes require their own evidence.

## What this project demonstrates

The repository connects **AI workflow design**, **Python integration engineering**, **knowledge and retrieval architecture**, and **production migration planning** in one inspectable system. The most useful evidence is the path from a daily requirement to its implementation and recovery procedure.

To review that path, start with [the architecture](architecture.md), follow the linked source modules, and compare their guarantees with [the acceptance record](hermes/acceptance.md).
