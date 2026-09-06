# ADR-0003: Use Redis Streams as the integration bus

- **Status:** Accepted
- **Date:** 2026-07-02
- **Context:** [`queue.py`](../../src/benka_integrations/queue.py) ·
  [README — where the integration bus lives](../../README.md#where-the-integration-bus-lives) ·
  [Reliability](../reliability.md)

## Context

Scheduling and work needed to come apart. Cron knows *when* a slot opens; it does not know whether
the previous run for that slot already happened, whether a worker died mid-job, or whether the
message it produced was ever delivered.

Running the work directly from cron loses all of that on the first crash. The failure that matters
is not "the job errored" — it is "the job half-ran and nobody can tell". A restarted container
must not redo work that already produced an external side effect.

Two hard constraints shaped the choice. Redis was already deployed and holding state, so adding a
second piece of infrastructure had to earn its place. And the original host had 4 GB of RAM total
for the entire office, so a broker with its own JVM or its own database was not affordable.

## Decision

Use **Redis Streams with consumer groups** as the single integration bus. A cron slot derives a
stable run identifier, `XADD`s one small job, and returns. A dedicated worker consumes it through a
consumer group.

The stream carries four responsibilities beyond transport:

- **Slot deduplication**, atomic in Redis, so one slot produces one logical run.
- **The pending entries list**, so a job claimed by a worker that then died is visible rather than
  lost.
- **Job state and delivery receipts** ([ADR-0007](0007-delivery-receipts-over-blind-retry.md)).
- **`benka:reconcile`**, where anything ambiguous goes for a human decision.

The completed record is written **before** `XACK`, so a crash between the two leaves a
re-processable job rather than a silently dropped one.

Persistence is AOF-backed. New keys are namespaced `benka:`; existing field formats were preserved
unchanged to keep the runtime migration reversible.

## Alternatives considered

**Celery, or RQ, with Redis as the broker.** Mature, and would have supplied retries and scheduling
for free. Rejected because its retry semantics are the wrong default here: an automatic retry of a
job that may already have posted to Telegram creates duplicates, which is precisely the failure this
system is built to avoid. Fighting a framework's defaults is worse than writing the small amount of
queue code this needs.

**RabbitMQ or NATS.** Better delivery semantics and real routing. Rejected on cost: a second
stateful service, its own operational surface, and its own memory footprint on a host that had
4 GB — to serve six low-volume streams.

**A Postgres table as a queue.** Transactional, and would have unified state with the job record.
Rejected because there is no Postgres in this system and adding one for a queue is a large
dependency for a small need.

**Cron running the work directly, no queue.** Simplest. Rejected as the thing being fixed: it has no
slot identity, no way to see an interrupted run, and no place to record that a delivery outcome is
unknown.

## Consequences

Interrupted work is **visible** — pending entries and the reconciliation queue are the record of it
— rather than inferred from missing output.

Scheduling and processing can be reasoned about separately: cron owns *when*, the stream owns *which
run*, the worker owns *how*.

**The bus is honest about its limits.** Redis makes the internal handoff durable; it cannot prove a
remote side effect. That distinction is why receipts exist as a separate concept and why
`uncertain` is a first-class state rather than an error.

**Reconciliation is manual, by design and forever.** `benka:reconcile` has no automatic cleanup, so
queue age and depth must be watched rather than just "is the worker process alive". Verified in
production: after an AOF-backed restart the slot, receipt, and pending entry all survived, pending
went to reconciliation, and no message was re-sent.
