# OpenClaw Version Compatibility Ledger

> Историческая справка исходного OpenClaw. Для Hermes используйте [реестр](hermes/inventory.md), [эксплуатацию](hermes/operations.md) и [переключение/откат](hermes/cutover-rollback.md). Production остаётся на OpenClaw; эти старые команды не развёртывают Hermes.

This is the canonical, versioned record of OpenClaw compatibility findings for this deployment.
It answers three questions before any upgrade:

1. Which local adaptations must be carried into the candidate image?
2. Which earlier failure signatures must be explicitly re-tested?
3. What evidence is sufficient to promote, hold, or roll back the candidate?

This ledger is intentionally separate from the image timeline in
[docs/02-openclaw-installation.md](02-openclaw-installation.md) and the chronological narrative in
[docs/06-command-log.md](06-command-log.md). The timeline says *what was used*; this ledger says
*why a version can or cannot be used*. No entry for a version means **unknown compatibility**, not
approval.

All entries are safe for Git: record component names, version tags, symptoms, decisions, and
sanitized evidence only. Keep live chat identifiers, tokens, hostnames, and private configuration
out of this document.

## Required use

Before building or deploying any new OpenClaw version:

1. Read the active and blocked records below, plus the current production record.
2. Create a candidate record before changing the live image reference. Carry every active local
   adaptation forward deliberately; never assume an upstream change made it obsolete.
3. Back up the current image reference and Gateway configuration, and name the known-good image in
   the candidate record.
4. Run the version-specific gates in each applicable record in addition to generic health checks.
5. Record both positive and negative evidence. A green health check or an outbound-only Telegram
   send cannot close a Telegram UI-ingress gate.
6. Mark the candidate `production-verified`, `held`, or `rolled-back` and link its command-log
   section before another version is considered.

Do not remove a local adaptation merely because an upstream release note looks related. It may be
removed only by a candidate result that proves the original failure path is fixed.

## Status vocabulary

| Status | Meaning | Deployment rule |
| --- | --- | --- |
| `production-verified` | Known good in the live deployment with all required gates passed. | May be retained as a rollback target. |
| `active-workaround` | Current production needs a local adaptation. | Carry it into every candidate until revalidated away. |
| `blocked` | The version showed a confirmed unacceptable failure. | Do not deploy it again without a new, documented reason and full revalidation. |
| `candidate-held` | Candidate is not proven safe; evidence is incomplete or a gate failed. | Do not promote; retain the last known-good image. |
| `rolled-back` | Candidate was deployed or switched and then safely restored. | Preserve the evidence and rollback cause. |
| `historical-verified` | A past production release with retained validation evidence and no active adaptation of its own. | Diagnostic reference only; it is not a current rollback target. |
| `superseded` | Historical record only; a later version replaced its operational value. | Keep for diagnosis, do not use as current guidance. |

## Current decision summary

| Scope | Status | Required action before the next upgrade |
| --- | --- | --- |
| Derived-image baseline (`iproute2`) | `active-workaround` | Keep `iproute2` in the derived image and verify `ip` inside the Gateway. |
| Telegram isolated polling | `active-workaround` on current 2026.6.9 production | Carry `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0`; require a fresh manual Telegram UI inbound-and-outbound smoke. |
| OpenAI OAuth/auth-store migration | `production-verified`, revalidate on every auth/storage change | Probe the OpenAI primary and check its intended OAuth transport before promotion. |
| Qwen direct reserve | `production-verified` for text route (2026-08-14) | Keep Qwen before DeepSeek; verify a controlled text smoke after provider/catalog changes. Image/audio/video auto-understanding stays disabled unless a separately verified vision route is introduced. |
| Direct DeepSeek reserve | `production-verified`, revalidate on every model-catalog change | Run an explicit reserve-model smoke; do not substitute it for the primary route. |
| OpenClaw 2026.6.11 | `candidate-held` | Rebuild only as a candidate and complete the manual Telegram UI gate; the prior MTProto automation is inconclusive. |

Every retained OpenClaw release in the image timeline has a record below. A record may explicitly say
that no version-specific defect was found; that distinction is deliberate and must not be replaced by
an omitted entry.

## Record format

Every new version entry must contain these fields. A concise record is better than a long narrative
that omits the decision-critical evidence.

```text
ID: OCL-YYYY.M.D-COMPONENT
Upstream / derived image: version and sanitized image tag
Status: production-verified | active-workaround | blocked | candidate-held | rolled-back | superseded
Known-good parent: image to restore
Affected surface: startup | auth | model routing | Telegram ingress | resource use | other
Failure signature: observable symptom and what it does not prove
Cause: confirmed / suspected / unknown, with scope
Workaround or decision: exact tracked mechanism, or why none is applied
Required gates: version-specific checks in addition to generic checks
Rollback: image/config restoration point and post-rollback checks
Evidence: command-log and documentation references; include negative evidence when relevant
Removal condition: exact proof needed to retire an active workaround
```

## Upgrade and rollback protocol

The ledger is part of the release procedure, not post-facto documentation.

```text
read active records
  -> create candidate record + name known-good parent
  -> back up current image reference and Gateway config
  -> build derived candidate + verify required patch/assets
  -> generic health/config/model/channel gates
  -> version-specific gates from active records
  -> manual Telegram UI ingress/outbound gate when Telegram is affected
  -> promote and mark production-verified
     or restore known-good image and mark held/rolled-back
  -> update command log, server state, image timeline, and this ledger
```

The generic checks are necessary but never sufficient by themselves: image version, container health,
`/healthz`, configuration validation, Telegram channel probe, and explicit reserve-model smoke.
For this deployment, a fresh manual Telegram UI message must produce both an inbound Gateway event
and an outbound reply whenever the candidate changes OpenClaw or its Telegram implementation.

## Version records

### OCL-2026.4.2-IMAGE-DEPENDENCY

- **Upstream / derived image:** OpenClaw 2026.4.2 and later derived images.
- **Status:** `active-workaround`.
- **Known-good parent:** the current production derived image listed in
  [docs/01-server-state.md](01-server-state.md).
- **Affected surface:** Gateway startup in `bind=lan` mode.
- **Failure signature:** the upstream image lacked `ip`; the Gateway depends on `ip neigh show` in
  the selected network mode and could enter a bad startup state even with otherwise correct config.
- **Cause:** confirmed deployment dependency absent from the upstream image.
- **Workaround:** build the minimal derived image from the chosen upstream slim tag and install only
  `iproute2`; do not move this runtime dependency to the host OS.
- **Required gates:** image build succeeds, `openclaw --version` matches the candidate, and `ip` is
  available inside `openclaw-gateway`.
- **Rollback:** restore the known-good derived image reference and recreate only the Gateway.
- **Removal condition:** a candidate image proves the required runtime command is present and the
  `bind=lan` startup path passes without the derived dependency.
- **Evidence:** [docs/02-openclaw-installation.md](02-openclaw-installation.md),
  [docs/07-architecture-and-security.md](07-architecture-and-security.md).

### OCL-2026.4.5-STARTUP-SPIN

- **Upstream / derived image:** OpenClaw 2026.4.5-derived attempts.
- **Status:** `blocked`.
- **Affected surface:** Gateway startup.
- **Failure signature:** high CPU spin loop; the Gateway port never bound.
- **Cause:** confirmed behavioral instability in this deployment; no local workaround was accepted.
- **Decision:** do not return to this version. A later stable version replaced it.
- **Required gates if ever reconsidered:** cold-start CPU observation, bound-port check, `/healthz`,
  and an extended healthy period before any user-facing smoke.
- **Rollback:** immediately restore the last known-good derived image.
- **Evidence:** [docs/01-server-state.md](01-server-state.md),
  [docs/02-openclaw-installation.md](02-openclaw-installation.md).

### OCL-2026.4.8-STARTUP-RECOVERY

- **Upstream / derived image:** OpenClaw 2026.4.8.
- **Status:** `historical-verified`.
- **Affected surface:** Gateway startup.
- **Finding:** this release was the successful replacement for the blocked 2026.4.5 startup path.
  The Gateway bound its port, became ready with normal logs, and remained idle at normal CPU.
- **Resolution:** retain the derived `iproute2` baseline and use `bind=lan` for an isolated
  Docker-port-mapped candidate smoke; `bind=loopback` tests only the container loopback and give a
  misleading negative result.
- **Required lesson for later releases:** a candidate smoke must use the same network mode as the
  deployed Gateway and must check port binding and idle CPU, not just image build success.
- **Rollback:** restore the known-good image preceding the candidate under test.
- **Evidence:** command log section 15.

### OCL-2026.4.11-SLIM-BASELINE

- **Upstream / derived image:** OpenClaw 2026.4.11 slim-derived production image.
- **Status:** `historical-verified`.
- **Affected surface:** image contents and startup baseline.
- **Finding:** no additional OpenClaw version-specific incompatibility is retained for this release.
  The relevant operational decision was to keep the minimal derived image: `iproute2` remained while
  unused Whisper, ffmpeg, and the extra Python toolchain stayed out of the runtime.
- **Resolution:** treat image size and runtime contents as an explicit deployment contract; verify
  `ip` is present inside the Gateway and do not install agent-facing dependencies only on the host.
- **Required lesson for later releases:** validate both the required tool and intentionally absent
  heavy tools after rebasing the image.
- **Rollback:** use the immediately previous known-good derived image if the slim candidate does not
  meet its runtime contract.
- **Evidence:** [docs/01-server-state.md](01-server-state.md),
  [docs/02-openclaw-installation.md](02-openclaw-installation.md).

### OCL-2026.5.12-RUNTIME-AND-RETRIEVAL-STATE

- **Upstream / derived image:** OpenClaw 2026.5.12.
- **Status:** `historical-verified`.
- **Affected surface:** derived runtime and dependent retrieval service.
- **Finding:** Gateway version, health, `iproute2`, doctor, fallback routing, and Telegram delivery
  all validated. The contemporaneous LightRAG hybrid retrieval smoke was unavailable because every
  external embedding option lacked usable quota or credentials; this was not an OpenClaw image
  defect.
- **Resolution:** preserve the Gateway release as healthy and record retrieval as an explicit
  degraded dependency state instead of masking it with a false-green smoke. Later work restored a
  local embeddings path outside this OpenClaw release decision.
- **Required lesson for later releases:** separate Gateway compatibility evidence from dependent
  provider/quota failures; do not label an upstream image broken when its independent gates pass.
- **Rollback:** restore the prior derived image only for a Gateway failure, not for an isolated
  external-embeddings outage.
- **Evidence:** command log sections 26–27.

### OCL-2026.5.26-AUTH-AND-COMPACTION

- **Upstream / derived image:** OpenClaw 2026.5.26.
- **Status:** `historical-verified`; its lessons remain covered by later active auth/model records.
- **Affected surface:** OpenAI fallback authentication and automatic compaction recovery.
- **Failure signature:** the existing OpenAI fallback token was expired after the upgrade path, and
  the configured compaction reserve floor was absent. Default-route recovery therefore depended on
  a refresh and a bounded compaction configuration.
- **Resolution:** refreshed only the agent-scoped OpenAI OAuth profile, set the validated
  `reserveTokensFloor`, restarted the Gateway, and proved both explicit and default fallback paths.
  Stale managed Codex package state was removed so the bundled registry matched the image.
- **Required lesson for later releases:** back up auth state, probe the intended primary/fallback
  routes, and verify compaction settings against the candidate schema rather than assuming a prior
  configuration remains effective.
- **Rollback:** restore the backed-up auth/config state and previous derived image if the route cannot
  be proven.
- **Evidence:** command log section 28.

### OCL-2026.5.27-OAUTH-AND-RESERVE-ROUTING

- **Upstream / derived image:** OpenClaw 2026.5.27.
- **Status:** `historical-verified`; later provider/auth records supersede its active configuration.
- **Affected surface:** OpenAI OAuth primary, bridge routing, and DeepSeek reserve.
- **Failure signature:** stale OAuth profile aliases could leave Telegram sessions using expired auth
  state; the reserve path also had to be proven separately from embeddings capability.
- **Resolution:** re-authenticated the OpenAI OAuth profile and restored the expected aliases, then
  ran direct primary, bridge-primary, and forced-reserve smokes. DeepSeek was explicitly recorded as
  an LLM reserve, not an embeddings provider.
- **Required lesson for later releases:** verify the primary route, each bridge route, and a forced
  reserve independently; model availability does not imply embeddings compatibility.
- **Rollback:** restore the prior auth profile/order and known-good derived image if any required
  route loses proof.
- **Evidence:** command log section 29.

### OCL-2026.6.1-AUTH-STORE

- **Upstream / derived image:** OpenClaw 2026.6.1; still relevant to later upgrades that alter auth
  storage or provider resolution.
- **Status:** `production-verified`; revalidation required on auth/storage changes.
- **Affected surface:** OpenAI OAuth primary route and per-agent auth storage.
- **Failure signature:** an upgrade left no usable OpenAI profile visible to the active agent; default
  turns then fell back even when a legacy OAuth profile still existed.
- **Cause:** confirmed migration from legacy auth files to a per-agent SQLite store, compounded by
  provider resolution selecting a direct API-key transport instead of the intended ChatGPT/Codex OAuth
  transport.
- **Workaround:** use the OpenClaw migration path to import the legacy profile, pin the tracked OpenAI
  provider to the intended OAuth transport, and set the verified active profile order. Do not use a
  broad doctor repair as a substitute for this targeted migration.
- **Required gates:** primary-provider auth probe, default-route smoke that reports the primary
  provider with no fallback, configuration validation, and a direct reserve-model smoke.
- **Rollback:** restore the backed-up auth store and previous Gateway configuration before recreating
  the Gateway.
- **Removal condition:** a candidate proves the primary OAuth route after any storage/provider change
  without relying on a fallback.
- **Evidence:** [docs/03-operations.md](03-operations.md), command log sections 44–45.

### OCL-2026.6.8-SERVICE-SCOPE

- **Upstream / derived image:** OpenClaw 2026.6.8.
- **Status:** `historical-verified`.
- **Affected surface:** post-upgrade Compose service scope.
- **Failure signature:** broad operations in `/opt/openclaw` could recreate a stale
  `telethon-digest` service even though the active digest runs in its own Compose project. A missing
  AgentMail env file could also select a conflicting container name.
- **Resolution:** removed the stale service/container, kept Telegram Digest in its dedicated project,
  and started the work-email bridge only with its explicit env file. The Gateway itself passed version,
  health, config, doctor, and required-runtime-tool checks.
- **Required lesson for later releases:** enumerate the intended service set after Gateway recreate;
  a green Gateway is not proof that broad Compose operations left no stale services behind.
- **Rollback:** restore the previous image and Compose scope if service separation or the Gateway
  validation fails.
- **Evidence:** command log section 41.

### OCL-2026.6.9-TELEGRAM-ISOLATED-INGRESS

- **Upstream / derived image:** OpenClaw 2026.6.9, current derived production hotfix image.
- **Status:** `active-workaround`.
- **Affected surface:** Telegram Bot API UI ingress. This is separate from Telethon/MTProto bridge
  jobs.
- **Failure signature:** Gateway health, channel status, and outbound Telegram delivery were green,
  but a fresh Telegram UI message did not produce an inbound Gateway event or a bot reply.
- **Cause:** confirmed isolated polling ingress behavior in this deployment.
- **Workaround:** carry the derived-image kill switch
  `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0`, retaining the regular polling handler.
- **Required gates:** inspect the candidate asset/patch, check channel probe, then send a fresh manual
  Telegram UI prompt that requires an answer. Require both an inbound Gateway log event and an
  outbound reply. `openclaw agent --deliver`, a channel probe, and a scripted MTProto message are not
  sufficient proof of this gate.
- **Rollback:** restore the `2026.6.9-telegram-polling-hotfix` image reference, recreate the Gateway,
  and repeat health, channel, and manual UI checks.
- **Removal condition:** a candidate with the switch removed passes the fresh manual UI
  inbound-and-outbound gate after deployment; record the exact evidence before deleting the patch.
- **Evidence:** [docs/03-operations.md](03-operations.md), command log section 49.

### OCL-2026.6.9-RESERVE-MODEL-ROUTE

- **Upstream / derived image:** OpenClaw 2026.6.9; revalidate when the model catalog or provider
  adapters change.
- **Status:** `production-verified`.
- **Affected surface:** direct reserve-model routing.
- **Failure signature:** the built-in DeepSeek route returned an unknown-model error while the direct
  OpenAI-compatible route succeeded with the verified model identifier.
- **Cause:** confirmed provider/catalog compatibility issue in the deployed route configuration; this
  does not justify making the reserve the global primary.
- **Workaround:** retain the dedicated direct reserve route and use it only as the fallback. Keep the
  intended OpenAI OAuth primary route.
- **Required gates:** explicit reserve-model probe/smoke and a separate default-route primary smoke.
- **Rollback:** restore the prior tracked provider configuration with the known-good image if either
  route changes unexpectedly.
- **Removal condition:** the built-in route is considered only after it passes the same explicit
  reserve smoke on a candidate.
- **Evidence:** [docs/01-server-state.md](01-server-state.md), command log section 44.

### OCL-2026.6.11-CANDIDATE-UI-GATE

- **Upstream / derived image:** `ghcr.io/openclaw/openclaw:2026.6.11-slim`, tested as a derived
  candidate on 2026-07-10.
- **Status:** `candidate-held` and `rolled-back` from the candidate switch; production remains on the
  2026.6.9 Telegram polling hotfix.
- **Known-good parent:** `2026.6.9-telegram-polling-hotfix` derived image.
- **Affected surface:** release proof for Telegram UI ingress, not a confirmed upstream defect.
- **Evidence:** candidate image version, derived patch presence, config validation, Gateway health,
  Telegram channel probe, and direct reserve-model smoke all passed. A scripted MTProto message
  produced no inbound event or reply on both candidate and restored baseline, so it cannot distinguish
  an upstream regression from a weak test path.
- **Decision:** do not promote or diagnose this as a 2026.6.11 regression until the manual Telegram
  UI inbound-and-outbound smoke is completed. Reuse the active 2026.6.9 ingress workaround in any
  retry.
- **Required gates:** all active-record checks plus the fresh manual Telegram UI proof described in
  `OCL-2026.6.9-TELEGRAM-ISOLATED-INGRESS`.
- **Rollback:** already completed to the known-good parent; keep it available until promotion is
  proven.
- **Promotion condition:** the manual UI smoke passes on the candidate and the record is updated with
  its evidence; only then may the candidate become `production-verified`.
- **Evidence:** [docs/01-server-state.md](01-server-state.md),
  [docs/02-openclaw-installation.md](02-openclaw-installation.md), command log section 53.

## Updating the ledger after a release

At the end of every OpenClaw candidate, update this ledger in the same change set as the relevant
image/config/docs changes:

- add a record for any new symptom, workaround, or unproven release gate;
- update the current summary table and the record status;
- add the detailed chronological evidence to [docs/06-command-log.md](06-command-log.md);
- align current state in [docs/01-server-state.md](01-server-state.md) and the image timeline in
  [docs/02-openclaw-installation.md](02-openclaw-installation.md);
- update [docs/05-rollback-and-backup.md](05-rollback-and-backup.md) if the rollback mechanism
  changes.

This makes the next upgrade an evidence-driven comparison against known failure modes rather than a
fresh diagnosis.
