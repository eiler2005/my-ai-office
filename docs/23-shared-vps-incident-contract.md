# Shared VPS incident contract

This document is the safe handoff contract for an incident that affects
OpenClaw and a routing/edge workload on the same VPS. It records stable
diagnosis and ownership rules, not a raw incident transcript. All commands,
evidence and follow-up notes must use placeholders; never copy an address,
source allowlist, token, identifier, generated profile, provider-console
screenshot or raw journal into Git.

## Ownership and evidence

`openclaw_firststeps` owns the OpenClaw/OmniRoute/LightRAG application runtime
and its application-level diagnosis. `vps_management` owns the host Docker
daemon, systemd, UFW, monitoring and resource-policy overrides. The routing
project owns its managed-egress resolver, edge proxy and protocol runtime.

An OpenClaw container being healthy, an SSH session working, or a public
listener accepting TCP is not evidence that the routing data-plane works. The
routing owner closes its incident only with an active end-to-end managed egress
probe. Conversely, a failed routing probe does not establish that OpenClaw is
the cause.

## Failure classes to keep separate

| Evidence | Primary owner | First action | Not a valid conclusion |
|---|---|---|---|
| Active managed-egress/HTTPS probe fails, direct control passes | routing project | Run its data-plane runbook and inspect edge components | “SSH works, so egress works.” |
| Current-boot Docker `systemd` ordering-cycle warning | routing unit owner with host coordination | Inspect the unit graph; correct source-controlled unit ownership | “Restart Docker until it disappears.” |
| Kernel/cgroup OOM evidence, rising restart count, memory/CPU pressure | host + affected app owner | Inspect limits and workload evidence | “The OOM automatically caused every edge fault.” |
| One iPhone/client fails while peers work | client/profile owner | Check the single profile, DNS cache and local ownership | “The shared VPS is down.” |
| SSH access fails while public data-plane probe is green | host access owner | Check UFW and provider access policy separately | “The public listener is unavailable.” |

A Docker/resolver ordering cycle has a specific shape: a resolver waits for a
Docker bridge, Docker waits for a lookup target, and that resolver supplies the
same target. Systemd can break the cycle inconsistently across boots, leaving
an edge component unavailable. The routing owner must correct that unit through
its source-controlled role. OpenClaw must not edit that routing unit or add an
ad-hoc drop-in.

## Safe first response

1. Keep affected app changes frozen; do not redeploy or alter client profiles
   merely because a dashboard looks bad.
2. Ask the routing owner for the active end-to-end probe result and the host
   owner for Docker/current-boot monitor status.
3. Gather only read-only app evidence:

   ```bash
   docker compose ps
   docker stats --no-stream
   docker inspect <gateway-container> --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}} {{.HostConfig.RestartPolicy.Name}}'
   ```

4. If OpenClaw itself is unhealthy, follow its normal targeted application
   runbook. It is a parallel recovery track, not a substitute for the routing
   probe.
5. Hand off systemd/Docker/UFW changes to the correct owner. Provider firewall
   and host UFW are separate controls.

## Resource-pressure rules

The documented resource limits, bounded restart policy and log caps exist to
keep shared-host pressure from cascading. Do not change a bounded
`on-failure` restart policy to an unbounded restart loop during an outage. Do
not use `docker compose down -v`, volume prune, unfiltered system prune or a
mass restart as incident response.

An OOM record is a capacity follow-up until evidence links it to the current
failure. The proper sequence is: inspect memory/CPU/PID limits and restart
counts, agree a smallest safe limit change with the host owner, then recreate
only the affected application service after approval. Application compose files
remain owned by this project; host policy overrides remain owned by
`vps_management`.

## Access and rescue boundary

Provider rescue/console is an access-recovery mechanism, not an application
health check. If a temporary host-firewall rule is necessary, it must be for
one verified operator source, time-bounded, removed after recovery and omitted
from all tracked notes. Never disable UFW or add a broad source allow for
diagnosis.

## Closure criteria

Close the shared incident only when all relevant tracks are independently
green:

- routing owner’s active managed data-plane probe passes;
- Docker/current-boot unit graph has no ordering-cycle warning;
- affected OpenClaw services are healthy after their own targeted checks;
- any OOM/CPU issue is either resolved or recorded as a separate capacity
  follow-up;
- temporary access rules are removed;
- the incident note contains statuses and ownership facts only.

The detailed host procedure is in the companion
[Docker boot and OOM runbook](https://github.com/eiler2005/praefectus-ai/blob/main/docs/runbooks/docker-boot-and-oom.md);
the routing-specific data-plane procedure is kept with the routing project.
