# ADR-0009: Migrate the agent runtime from OpenClaw to Hermes Agent

- **Status:** Accepted
- **Date:** 2026-09-06
- **Context:** [Migration plan](../hermes/migration-plan.md) ·
  [Cutover record](../hermes/cutover-record-2026-09-06.md) ·
  [Archived compatibility ledger](../archive/openclaw/22-openclaw-version-compatibility-ledger.md)

## Context

The office ran on OpenClaw from its first deployment and worked. The problem was not the runtime's
capability but its upgrade path.

Defects and local workarounds accumulated to the point of needing their own document — the
[version compatibility ledger](../archive/openclaw/22-openclaw-version-compatibility-ledger.md) —
which is itself the diagnosis: a system whose defect list needs a dedicated file has an upgrade
problem, not a bug. The 2026.9.1 candidate was evaluated and **not accepted**, so production stayed
pinned on 2026.6.9 with a Gateway rebuilt from a pinned compatibility Dockerfile.

Meanwhile the integration surface had drifted. Every source ran as its own HTTP bridge service, and
model calls went through `docker exec ... openclaw agent` — coupling every scheduled job to the
interactive runtime's process and lifecycle.

The decisive factor was that the expensive part had already been protected. Because domain logic
lived outside the runtime ([ADR-0004](0004-separate-orchestration-from-domain-logic.md)), replacing
the runtime meant replacing orchestration, not rewriting the office.

## Decision

Migrate the agent runtime to [Hermes Agent](https://github.com/NousResearch/hermes-agent), and treat
the migration itself as an engineering problem with the same rigour as the system.

Hermes takes the human interfaces, profile routing, sessions, native tools, model selection, and
cron. `benka_integrations` takes the business algorithms, which move across largely intact. The
per-source HTTP bridges become in-process workers on the existing Redis bus
([ADR-0003](0003-redis-streams-as-the-integration-bus.md)).

The migration was staged deliberately:

1. Build the candidate and the migrators while OpenClaw keeps serving production.
2. Reach `READY_NOT_ACTIVE` — code and rehearsal complete, production connections disabled.
3. Wait roughly two weeks, recording every behavioural change in a [drift log](../hermes/drift-log.md).
4. Cut over only on a separate explicit instruction from the owner.
5. Observe for at least 48 hours before calling it accepted.

Two rules constrained everything: **the waiting period elapsing never triggers the switch** — there
is no timer and no automatic activation generator anywhere in the project — and the old stack plus
its verified archive are retained for at least 14 days *after* acceptance.

## Alternatives considered

**Stay on OpenClaw and maintain the fork.** No migration risk. Rejected because the ledger was
growing and the accepted version was already behind, so the cost was an indefinite maintenance
burden on a runtime nobody else was fixing.

**Write a bespoke runtime.** Complete control. Rejected as the wrong problem: sessions, tool
protocols, and cron are solved work, and the office's value is in its workflows.

**Big-bang cutover — build, switch, fix forward.** Much less process. Rejected because the office
handles the owner's real mail and messages; "fix forward" on a system with 24-hour Telegram update
retention means losing real information.

**Run both runtimes in parallel on live data.** Attractive for confidence. Rejected outright: two
pollers on one bot means duplicated or lost updates, and two writers to one vault means divergence
with no arbiter.

## Consequences

The runtime is supported upstream and pinned deliberately
([ADR-0012](0012-vendor-hermes-as-a-pinned-submodule.md)). The HTTP bridge layer is gone, and with
it a class of "is the bridge up" failures.

**The staged approach produced its own evidence.** 209 regression checks, native contract checks,
Redis persistence and recovery checks, and authenticated dashboard checks — all run on the VPS, all
recorded in the [acceptance record](../hermes/acceptance.md).

**The claim is bounded honestly.** Status is `ACTIVE_ON_HERMES` with the 48-hour observation window
still open and full production acceptance still outstanding. Full chat against the real models was
not verified at cutover. The documentation says so rather than rounding up to "migrated".

**Rollback stayed real, not theoretical.** The source host's Docker services were stopped and
retained rather than deleted, and `benka rollback-delta` produces a three-way report that overwrites
nothing — because after new writes exist, restoring the old archive would destroy work.

Post-cutover the design was tested immediately by three real incidents — a missing `hermes send` on
`PATH`, schedule preparation that read only inline Signals rules, and missing writable worker
directories. Each was found, isolated to a single service, fixed, and recorded. The digest,
mailboxes, and Signals recovered without duplicate deliveries.
