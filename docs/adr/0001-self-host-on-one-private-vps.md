# ADR-0001: Self-host the whole office on one private VPS

- **Status:** Accepted
- **Date:** 2026-05-31
- **Context:** [Architecture — runtime boundaries](../architecture.md#runtime-boundaries) ·
  [Archived OpenClaw security model](../archive/openclaw/07-architecture-and-security.md)

## Context

The office reads the owner's personal mailbox, his work mailbox, roughly 150–200 Telegram channels
he follows, and the notes he writes about his own business. That is a complete picture of one
person's professional life in one place.

Every managed alternative implies handing that corpus to a third party under terms the owner does
not control and cannot audit. The exposure is not a single leak but a standing one: whatever is
indexed stays indexed.

The counter-pressure was capacity. The first deployment target was a Hetzner CX23 — 2 vCPU, 4 GB
RAM — which is not enough to run local models. So "self-hosted" could never mean "no external
inference"; the only honest question was which boundary to draw.

## Decision

Run every component that **stores or routes** the owner's data on hardware he controls: the
gateway, the queue, the workers, the wiki, the retrieval index, and the archive. Send to external
services only the specific text a specific task needs, at the moment it needs it, and record which
provider each workload uses.

Everything runs as one Docker Compose project on a single host. There is no multi-node story and no
orchestrator.

## Alternatives considered

**A managed agent platform.** Fastest to stand up and the only option with no operational burden.
Rejected because the data set is exactly the data set one does not hand over, and because the
office's value comes from workflow logic that a platform would constrain.

**Self-hosted with local models only.** The strongest privacy position, and briefly attractive.
Rejected on measurement: the available host could not run a model good enough for the summarisation
and triage work, and buying a machine that could was disproportionate to the problem.

**A managed queue and database, self-hosted agent.** A middle path. Rejected because it splits state
across a trust boundary for very little operational gain at this scale — the whole system's state
fits comfortably on one disk.

**Multiple hosts, separating personal and work.** Rejected as premature: the domain separation the
owner actually needs is enforced by profiles and manifests
([ADR-0002](0002-telegram-as-the-operating-surface.md)), not by hardware.

## Consequences

The owner keeps the corpus. Retrieval, the wiki, the archive, and the queue never leave the host,
and a provider change affects inference only, not stored data.

**The cost is that operations are his.** There is no vendor to page. Backups, disk headroom,
certificate renewal, and upgrades are all manual work, and the
[operations runbook](../hermes/operations.md) exists because of this decision.

**A single host is a single point of failure**, accepted deliberately: the office degrades to "the
owner reads his own mail for a day", which is tolerable.

The host is shared with unrelated Compose projects (`reddit-compass`, `moex-futoi`,
`cheap-intelligence`, `stealth`). That makes blast radius a real concern and is why the
[transfer inventory](../hermes/inventory.md) forbids blanket `docker compose down`, `docker system
prune`, and restarts of another project's proxy. A careless command here damages someone else's
service.

"Self-hosted" is stated precisely in the README rather than implied: configured model providers and
source APIs do receive requests. Claiming otherwise would be false.
