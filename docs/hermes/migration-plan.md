# Migrating Benka: OpenClaw → Hermes Agent on the Hermes VPS

## 1. Outcome and timeline

Move the agent, its knowledge, and the live workflows into a new Git repository and onto the
existing Hermes VPS. Preserve the Git history, rework the integrations for Hermes, and provide
Telegram, CLI, and a web panel.

**Development and cutover are separate.** The Hermes code, migrators, configuration, and tests are
completed first. OpenClaw then continues to serve every workflow for roughly another two weeks. The
switch happens later, and only on a separate instruction from Denis.

| Period | OpenClaw | Hermes |
|---|---|---|
| Preparation | Keeps running | Development, tests, installation of an isolated candidate |
| Roughly two weeks of waiting | The only production system | Code ready; production connections and schedules disabled |
| Separate instruction from Denis | Stopped for the final transfer | Fresh state import, verification, activation |
| After the switch | Stopped, retained for rollback | Running; at least 48 hours of observation |

**The two weeks elapsing does not trigger the switch automatically.**

Obsidian, LightRAG, Syncthing, Redis, and OmniRoute are all retained. Conversation history moves
into a protected searchable archive; Hermes starts new sessions.

**Document status:** an agreed plan. The actions and criteria below are not a completion report;
readiness is confirmed by the separate [verification record](acceptance.md).

**Implementation:** [eiler2005/my-ai-office](https://github.com/eiler2005/my-ai-office). Current
status and actual checks are in the [acceptance record](acceptance.md); VPS details are in the
[transfer inventory](inventory.md).

> [!NOTE]
> This document was written **before** the cutover and is preserved as the plan of record. The
> production switch has since been performed — see the
> [cutover record](cutover-record-2026-09-06.md). Statements below in the future tense describe the
> plan as it stood, not the current state.

The plan is based on the project's local files and the official Hermes documentation as verified on
2026-09-06. The current state of both VPS hosts must be confirmed before execution.

## 2. Target architecture

### Target VPS details, clarified from reddit-compass

- The target is the HostKey machine `vps-hostkey-hermes`; access goes through
  `vps_management/ansible/scripts/ssh-vps.sh --host vps-hostkey-hermes`. The IP, user, and key are
  resolved by the wrapper script from the protected vault; they are not duplicated in this document
  or in the new Git repository.
- It is a shared server already running the `reddit-compass`, `cheap-intelligence`, `moex-futoi`,
  and `stealth` stacks. The neighbouring projects' directories, data, Compose files, and cron are
  excluded from this migration's changes.
- Per the Reddit Compass documentation, port 80 is used for ACME, 443 belongs to the L4/SNI router
  in `router_configuration`, and 8450 is Reddit Compass HTTPS. Do not move the old Caddy across in a
  way that claims 80/443, and do not modify the existing SNI routing.
- Allocate `/opt/benka-hermes`, a dedicated Docker network, and dedicated volumes for Benka. The
  preferred HTTPS port for the panel is 8451, subject to an occupancy check. Publish the panel
  through its own Caddy with TLS/mTLS; supply the certificate separately, without attempting to
  claim another project's ACME port. Service ports stay on loopback or the private network.
- Clarification from Denis, 2026-09-06: use the Reddit Compass domain or one adjacent to it without
  disrupting its operation. The existing `RC_PUBLIC_HOST` was chosen, with a separate port 8451 and
  a copy of the live certificate; the address and credentials are kept only in the private manifest.
  Details in [panel.md](panel.md).
- Historical snapshot from 2026-08-01: 8 CPU, roughly 15 GiB RAM, roughly 157 GiB disk. This is not
  the current capacity gate: repeat the measurements before installation and before the switch,
  accounting for neighbouring batch jobs and memory limits.
- Sources: `reddit-compass/docs/HOSTING.md`, `reddit-compass/deploy/hostkey/README.md`,
  `vps_management/docs/ownership-matrix.md`, and `vps_management/docs/containers.md`.

| Component | Implementation after the transfer |
|---|---|
| Benka | Hermes Gateway with adapted identity, instructions, skills, and user profile |
| Telegram | The existing bot, chats, and topics; routing and permissions by trusted identifiers |
| Personal and work mail | Hermes integrations preserving polling, filtering, original-sender resolution, and actionable/informational triage |
| Telegram Digest | A Hermes integration using Telethon; the previous sources, folders, cursors, scoring, category balance, and links |
| Signals / Last30Days | The previous rules, sources, presets, and deduplication, driven by Hermes |
| Knowledgebase / Ideas | Hermes tools over the `wiki-import` core, preserving wiki-first behaviour |
| LightRAG | The transferred graph and data; the local `wiki-import` embedding endpoint retained |
| Redis | Streams, events, cursors, deduplication, and recovery of unfinished jobs |
| OmniRoute | Retained routes for the corresponding workloads |
| Syncthing | The Mac connects to the new server after the final transfer and vault reconciliation |
| Management | Hermes CLI and a separate web-panel process behind Caddy, TLS/mTLS, and authentication |

**Integration code.** Create a `benka-integrations` Python package: Hermes tools and commands, cron
scripts, and Redis handlers. Replace the old HTTP bridges and OpenClaw wrappers with the new
integration runtime. Reuse the verified processing algorithms and their tests. Register extensions
through the Hermes plugin system.
[Hermes plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)

**Model calls.** Replace `docker exec ... openclaw agent` with an adapter over the Hermes Python
API. For background tasks, create a separate `AIAgent`, disable personal memory and context files,
and bound tools, iterations, and execution time. Preserve the result validators and the
deterministic fallback results used when an LLM fails.
[Hermes Python API](https://hermes-agent.nousresearch.com/docs/guides/python-library)

**Interfaces and state.**

- Preserve the meaning of `wiki_ingest`, `wiki_read`, `wiki_lint`, and `lightrag_query`; add workflow
  triggering, status checks, and archive search.
- Preserve the wiki fields `source_type`, `source`, `capture_mode`, `promote_fingerprint` and the
  results `wiki_page_paths`, `raw_path`, `rag_status`.
- In the first stage, preserve the Redis event formats and the existing state, for transfer and
  rollback compatibility.
- Separate `personal`, `work`, `family`, and `sandbox`: the restrictions apply to tools, files,
  memory, and context assembly.

**Schedules and delivery.** After the switch, Hermes cron becomes the sole owner of the
application's schedules. Fixed scripts enqueue jobs into Redis; handlers do the work and record the
result. Disable automatic cron delivery for those jobs. Use a shared module over
`hermes send --json`, preserve confirmed message identifiers, and route uncertain sends to
reconciliation rather than repeating them blindly.
[Script-only cron](https://hermes-agent.nousresearch.com/docs/guides/cron-script-only) ·
[Message delivery](https://hermes-agent.nousresearch.com/docs/guides/pipe-script-output)

**Memory.** Move stable facts and the profile into Hermes's compact memory. Leave full diaries and
conversations in the archive; the wiki keeps its role as the primary knowledge store and LightRAG
its role as the retrieval layer.
[Hermes memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)

## 3. Execution stages

### A. Inventory without stopping OpenClaw

- Check both VPS hosts: OS, architecture, resources, disks, containers, networks, ports, volumes,
  permissions, background processes, and neighbouring services.
- Record the running versions and image digests. Do not include the unfinished OpenClaw upgrade in
  the transfer.
- Reconcile the Git HEAD, the uncommitted changes, and the server files; determine the exact source
  set.
- Build the registry: function → Hermes implementation → state to transfer → acceptance check.
- Collect schedules from OpenClaw cron, system cron, and internal schedulers, including wiki and
  LightRAG maintenance.
- List the required secrets by purpose, without values.

**Result:** registries of components, functions, data, schedules, and transfer obstacles.

### B. Complete the code and the new repository

- Create a separate checkout with history, branches, and tags; leave the old remote untouched.
- Scan the history and the selected current changes for secrets. If a leak is found, stop
  publication until it is resolved.
- Make the new remote private by default; the URL is supplied as the `<NEW_REPO_URL>` parameter.
- Exclude from Git: `.env`, Hermes auth and state, Telethon sessions, archives, the vault, Redis, and
  LightRAG.
- Implement the integrations, adapters, configuration, Docker Compose, and the install, import,
  verification, and rollback procedures.
- Prepare the migrators for the final fresh state, including a safe repeat run and a report of
  skipped objects.
- Update the README, CHANGELOG, and operational instructions.
- Commit and push only after separate confirmation, per the project rules.

**Result:** the Hermes code and verified migrators are ready; production still runs on OpenClaw.

### C. Prepare the Hermes VPS and run a rehearsal

- Record the target VPS's existing services; allocate separate directories and a separate Compose
  project.
- Place Hermes and the runtime dependencies in containers, with no Docker socket and no
  administrative host access for the agent.
- Pin versions and dependencies; configure persistent storage, resource limits, restart policy, and
  log rotation.
- Prepare the web panel, Caddy, and TLS/mTLS. Verify authentication and WebSocket through the proxy.
  [Hermes web dashboard](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard)
- Rehearse the import against de-identified fixtures and an available verified backup. Do not copy
  running databases as ordinary files.
- Verify Telegram with a separate test bot and test topics.
- Verify recovery from a failed import and a repeat run of the migrator.
- Leave the production bot, mail polling, Telethon, deliveries, and schedules disabled on Hermes.
- Do not connect the test vault to production Syncthing.

**Result:** status `READY_NOT_ACTIVE` — code, migrators, configuration, and rehearsal checks are
ready; Hermes is not yet serving production.

### D. Waiting period — roughly two weeks

- OpenClaw remains the sole owner of production polling, schedules, deliveries, and data writes.
- The Hermes candidate is held at a fixed code and dependency version. Auto-deploy and automatic
  cutover are disabled.
- Normal OpenClaw backups continue.
- Every change to the source project during this period — fixes, new features, schedules, sources,
  settings, and secret rotations — is recorded in the drift log.
- Behavioural changes are ported into the Hermes candidate and verified by the corresponding tests.
- Ordinary new mail, messages, notes, and cursors accumulate only in the production system. They
  will be moved by the final snapshot.
- The rehearsal snapshot is not treated as current production state and is not used to activate
  Hermes without a refresh.

**Exit condition:** a separate instruction from Denis to switch. Until then OpenClaw runs, however
long the wait lasts.

### E. Re-verification immediately before the switch

- Re-run the inventory and close the drift log for the waiting period.
- Verify access, and that the secrets, OAuth, sources, and models are current.
- Confirm that the final code is ready and repeat the tests for anything that changed.
- Confirm by measurement that disk, RAM, and time are sufficient for the copy and the restore.
- Verify that the Mac, the backup storage, and the SSH route are all reachable.
- Prepare a clean Hermes production state, separate from the rehearsal results.
- If an open functional gap is found, leave OpenClaw running and close the gap before the window
  opens.

### F. Final transfer inside the agreed window

1. Block new OpenClaw jobs and wait for active ones to finish; record unfinished tasks and uncertain
   sends.
2. Stop only the migration-related schedulers, Gateway, handlers, and writing processes. Pause
   Syncthing on both sides.
3. Record the Telegram update watermark, Telethon cursors, mail watermarks, Redis pending entries,
   and confirmed deliveries.
4. Create a **fresh consistent cold copy** covering every change made during the waiting weeks:
   OpenClaw, workspace, vault, integrations, Redis, LightRAG, OmniRoute, configuration, and secrets.
5. Stream the archive to a protected directory on the Mac; verify its contents, SHA-256, and
   restore. Keep the old server's images and configuration.
6. Restore the data onto the Hermes VPS with the correct owners, permissions, and volumes.
7. Assemble a separate OpenClaw layout for the importer: in the current deployment `config` and
   `workspace` are split. Run `hermes claw migrate --dry-run` with `--source` and the `user-data`
   preset, then import the reviewed identity, skills, and compact memory.
8. Apply the prepared adaptations for instructions, cron, plugins, and channel bindings. **The
   standard import does not restore all of these automatically.**
   [Migrating from OpenClaw](https://hermes-agent.nousresearch.com/docs/guides/migrate-from-openclaw)
9. Configure secrets and OAuth through supported Hermes mechanisms; verify the models, embeddings,
   wiki, and queues.
10. Enable the single production Telegram polling process on Hermes and run the manual checks.
11. Enable the schedules and process the accumulated backlog.
12. Connect Syncthing with a new device identity after reconciling the vault and confirming there
    are no unexpected deletions.

Do not treat the existing Gateway update script as a ready-made migrator for the whole stack. Do not
stop neighbouring projects on either VPS.

**Schedules for the source reconciliation, Europe/Moscow:** Telegram Digest 08/11/14/17/21; personal
mail 08/13/16/20; work mail eight slots between 08:30 and 19:00; mail polling and Signals every five
minutes; Last30Days at 07:00; LightRAG every 30 minutes. Add the daily and weekly wiki maintenance.
The confirmed server registry taken before the switch is the final source of truth.

## 4. Checks and readiness criteria

| Check | Success condition |
|---|---|
| Regressions | Behavioural data-processing tests pass after the runtime is replaced |
| Migration rehearsal | Import, repeat run, interruption, and recovery verified on isolated data |
| Changes during the waiting period | Every new OpenClaw feature and setting is accounted for in the Hermes candidate |
| Identity and archive | Style and stable facts preserved; old conversations reachable by search with their source |
| Telegram | A manual message and a follow-up produce an inbound event and a reply in the correct topic |
| Permissions | Unauthorised users are rejected; personal / work / family / sandbox stay separate |
| Mail | Both mailboxes, forwards, triage, and deduplication work; full emails are not indexed by default |
| Telegram Digest | Sources, folders, cursors, category balance, and links preserved |
| Signals / Last30Days | Rules and both presets work; one failed source does not break the whole release |
| Models | Primary, every fallback, timeouts, auth errors, malformed responses, and all-LLMs-fail verified |
| Knowledgebase | Search uses the knowledge base; a save creates a wiki page; `обсуди:` does not save the message |
| Ideas | Capture creates a page; promotion updates the existing chain without a duplicate |
| LightRAG | Control queries find the expected pages; the embedding model and dimension are preserved |
| Cron and Redis | One run per slot; reprocessing is safe; pending entries recover |
| Web panel | Login, chat, WebSocket, sessions, and settings work; unauthorised access is rejected |
| Reliability | Restart and reboot recover the system; no OOM, no restart loops, no growing queue |
| Rollback | Return to the old runtime verified both before and after new writes exist |

Before the switch, use fixtures, a test bot, and controlled failures. Run a combined load pass of a
Telegram request, a digest, and indexing.

After the switch, observe for at least **48 hours**, obtain real runs of every daily workflow, and
verify the weekly maintenance against a copy of the data. **A successful health check does not by
itself close functional acceptance.**

## 5. Rollback and completion

**Rollback triggers:** no Telegram ingress, broken topics or permissions, data loss, repeated
publications, a non-functioning knowledge base, or an unstable runtime.

**Before any new production writes:** stop Hermes and the handlers, and restore the old stack from
the state captured immediately before the switch.

**After new writes:** stop the new system and preserve its state. Move back the new wiki artifacts,
confirmed deliveries, cursors, and compatible queue state; archive the new Hermes conversations.
Reconcile pending entries and uncertain sends before re-enabling the old handlers. Do not replace
current data with the original archive without reconciling the differences.

**Assumptions and limits:**

- The existing bot, topics, sources, and models are preserved; disabled features are not enabled
  automatically.
- VPS addresses, the repository URL, the panel domain, and secrets are defined in the private
  deployment manifest.
- The default budget for the final window is four hours, with rollback starting no later than the
  third. Before stopping anything, confirm by measurement that the transfer or restore fits that
  budget.
- The two-week wait happens with OpenClaw running. Extended downtime is not acceptable: Telegram
  retains unprocessed Bot API updates for no more than 24 hours.
  [Telegram Bot API](https://core.telegram.org/bots/api#getting-updates)
- The old stack and the verified archive are kept for at least 14 days **after Hermes acceptance**.
  That period is counted separately from the waiting period.
- Removing the old deployment is a separate operation.

**The code is ready for the waiting period** when the implementation, migrators, documentation,
preliminary tests, and rehearsal are complete and Hermes production activation is disabled.

**The migration is complete** when Denis has separately initiated the switch, fresh state has been
transferred, the whole function matrix is closed, 48 hours of observation have passed, and recovery
has been verified.

Deliverables: the Markdown plan, the transfer inventory, the drift log for the waiting period, the
verification record, the cutover and rollback runbook, and the updated operational documents.
Production data and secrets stay outside Git.
