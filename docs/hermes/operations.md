# Hermes operations

## Current production status

Benka has run on the Hermes VPS since 2026-09-06. The current switch and verification record is
[cutover-record-2026-09-06.md](cutover-record-2026-09-06.md). The older candidate and rehearsal
sections below are retained as the repeat-rehearsal procedure; **they are not an instruction to stop
the running production system.**

Current status and limitations are in the [acceptance record](acceptance.md). None of the commands
here constitute permission to switch production.

## Installation

Inside the image, use Python 3.14, `uv sync --frozen --extra hermes`, and Git submodules. Add
`--extra test` for tests. The agent's Python dependencies are not installed on the VPS host: the
Docker `test` target contains the required environment.

### Isolated builder for VPS checks

`scripts/run-hermes-vps-tests.sh` uses a separate Docker Buildx builder, `benka-migration`. Create
and bootstrap it once before the first run on the VPS:

```bash
docker buildx inspect benka-migration >/dev/null 2>&1 || \
  docker buildx create --name benka-migration --driver docker-container --bootstrap
```

The builder is used only for candidate images. Production Compose neither switches to it nor grants
the agent's containers access to the Docker socket.

Hermes is pinned to `caafe5389ae585ef77387a962aee05b1bcf17029` (release `v0.23.3`). Last30Days is pinned
to `01812ec1851e5c3d92a9049a41b7da4adbfbcb5d` with the existing Reddit and GitHub adaptations. Updating
any pin requires re-running the native-contract checks and the regressions.

[Pinned versions](../reference/versions.md) records every pin, when currency was last checked, and
the procedure for moving one.

The Dockerfile builds the Hermes dashboard in a separate stage with the pnpm version pinned by
upstream. It installs the Python API from the submodule and uses the upstream install stamp to
report the release and commit. The runtime runs as UID/GID 1000, with a read-only root,
memory/CPU/PID limits, and no Docker socket. Container logs are rotated.

### Runtime upgrade rehearsal

Export a staged source tree with `scripts/package-hermes-candidate.py`. Extract it on the VPS in
a private candidate directory with `tar --no-same-owner --same-permissions -xzf` so source modes
survive the operator's private umask and UID 1000 can read the image. Leave production polling
and scheduled jobs with the current Gateway while the candidate is under test.

Run the VPS suite, including the native plugin, paused cron, bounded agent, and Redis checks.
Run [the state verification script](../../scripts/verify-hermes-state.py) with `HERMES_HOME`
pointing to a disposable copy in an offline container. It checks that the runtime can read
existing transcripts and load cron jobs with the same identities and enabled status.
Use a consistent, isolated copy of the current profile and session state to check that existing
sessions resume, Telegram topic routing and permissions survive, the dashboard still authenticates,
and existing cron jobs keep their identity and paused or enabled state without dispatching
duplicate runs. Rehearse restoring that snapshot with the current image before any live switch.

For promotion, retain the previous image and a fresh consistent snapshot. Check an ordinary
inbound Telegram message and its reply through the UI, and verify receipt tracking and scheduler
state. Use the [acceptance record](acceptance.md) to record the observed results.

SQLite is configured with `journal_mode: delete`; WAL may be enabled only after verifying the fixed
upstream SQLite version. **Never transfer a running SQLite database as a single file without its WAL
and SHM.**

> [!WARNING]
> Do not apply `chown -R` to the whole production state. Redis stores its AOF as UID/GID 999,
> OmniRoute writes SQLite as root, and Caddy — running with `cap_drop: ALL` — reads the mTLS key
> through the root group. After the finalizer runs, ownership may be reset only for
> `state/runtime`, `private/activation`, `private/manifests`, and `private/bridges`, which are
> UID/GID 1000. The ownership of Redis, OmniRoute, and `private/panel/tls` is left unchanged.

Compose starts only the offline standby by default. The `rehearsal` profile holds templates for the
Gateway, the dashboard, one worker, `wiki`, Redis, and Caddy. That is a template for a single
isolated domain; before a full rehearsal you must create separate worker instances, volumes, and
secrets for both mailboxes, Telegram, Signals, Last30Days, RAG, and maintenance.

LightRAG, OmniRoute, and Syncthing require their own verified deployment manifest with live image
digests and volumes. They are not replaced by empty new services during the import.

```bash
docker compose -f deploy/hermes/compose.yaml config --quiet
docker compose -f deploy/hermes/compose.yaml build candidate
docker compose -f deploy/hermes/compose.yaml up -d candidate
docker compose -f deploy/hermes/compose.yaml ps
```

`/state`, the profile homes, and the vault must be owned by UID/GID 1000. For pre-existing bind
mounts, set the permissions before starting. Each send-capable worker additionally receives private
`/state/uploads` and `/state/worker-logs` directories: these are created during production
preparation, because a read-only image cannot create them after the bind mount.

Mount the private manifest and the secrets read-only, outside any path the agent can reach.

## Manifest and modes

`BENKA_MANIFEST` points at a JSON document with `schema: 1`; `mode` and exactly one `domain` from
`personal` / `work` / `family` / `sandbox` are required.

| Mode | Conditions |
|---|---|
| `standby` | Every side effect is refused; the default candidate has no network |
| `rehearsal` | `data_class=test`, `production_connections=false`, explicitly listed `enabled_operations` |
| `production` | A separate instruction from the owner, plus a receipt carrying the manifest SHA, the SHA of the fresh snapshot, and stopped writers |

Operations: `gateway`, `dashboard`, `worker`, `poll`, `send`, `enqueue`, `wiki`, `wiki_read`,
`wiki_write`, `index`, `archive_read`. Grant only the operations a given service actually needs. The
defaults are empty.

> [!IMPORTANT]
> The receipt is an **operational interlock, not cryptographic authorisation from the owner.** Only
> the operator may create one, and only after a separate instruction from Denis. There is no
> automatic activation generator and no timer anywhere in this project.

## Profiles and Telegram

### Benka's personal channel and the first conversation

The production-configuration finalizer sets the home Telegram channel to the personal DM of the
single trusted user in the `personal` domain, and nothing else. A forum, the work group, and the
family route cannot become the default home channel: cron results and cross-platform notifications
must not land in a shared chat.

If `personal` does not contain exactly one user, the finalizer leaves the home channel unset and
requires a deliberate operator decision.

For an imported Benka, `onboarding.profile_build` is always `off`. The standard Hermes first-contact
questionnaire is meant for a clean install; here the profile, memory, and rules are already
prepared.

> [!CAUTION]
> Do not run `/sethome` inside a forum topic — it changes the notification route for the entire
> Gateway.

Each multiplex profile gets its own manifest in the private `private/benka-manifests/`; the Gateway
mounts that directory read-only as `/run/benka/profiles/`. The `manifest_path` field in the profile
config must point at `/run/benka/profiles/<domain>.json`. Do not substitute the shared Gateway
manifest: the domain's tool and data restrictions must hold on every plugin invocation.

The finalizer moves the profile manifests to `production` and creates a separate activation receipt
per domain. For `personal` it creates separate read-only Redis, wiki, and LightRAG files in
`private/profile-secrets/personal/`. The `work`, `family`, and `sandbox` domains remain read- and
archive-only until the operator prepares their own verified credential files and widens the
permitted operations through a separate policy change.

Define all four domains in the private `bindings.json`:

```json
{"domains": {
  "personal": {"users": [101], "admins": [], "routes": [{"chat_id": -1001, "thread_id": 1}]},
  "work": {"users": [101], "admins": [], "routes": [{"chat_id": -1001, "thread_id": 2}]},
  "family": {"users": [102], "admins": [], "routes": [{"chat_id": -1002}]},
  "sandbox": {"users": [101], "admins": [], "routes": [{"chat_id": -1003}]}
}}
```

These are synthetic identifiers illustrating the format; the real ones come from the verified private
registry.

```bash
.venv/bin/benka profiles-prepare deploy/hermes/private/bindings.json .migration/profile-staging --repo "$PWD"
```

The generator creates the private staging area, SOUL stubs, two skills, the plugin, and separate
`.env`, config, and manifest files per profile. **Telegram is disabled in every profile.** The
reviewed identity and instructions must be filled in before the rehearsal.

After the compact `USER` and `MEMORY` files are reviewed, enable `memory.memory_enabled` and
`memory.user_profile_enabled` only in the corresponding interactive profiles. They are off in the
template, and background AIAgents always start without that memory.

One root Gateway owns polling and routes messages into the domain profiles; an unmatched route
receives no tools. Verify native profile routing, an outsider's access attempt, and the absence of
another domain's files or memory in the assembled context.

Keep the admin ID lists empty and the dangerous toolsets disabled until the Hermes policies are
separately reviewed. Do not grant the terminal, file, browser, cronjob, or kanban toolsets to user
sessions.

`delegate_task` can run a single isolated Qwen3.8 Flash subagent with no terminal, files, browser,
memory, or further delegation. Use it for a bounded independent step that Sol can review.

Place the generated `benka-manifests/*.json` in the read-only `/run/benka/profiles/`, and the
credential files in `/run/benka/profile-secrets/<domain>/`. The config holds the paths; values are
not shared through the global environment between multiplex profiles.

For the panel, choose a separate scoped `HERMES_HOME` and a permitted profile; do not open the
shared administrative profile to the family.

### Changing the agent's instructions

Hermes stores the rendered system prompt for each session. After deploying an image with a changed
prompt section or updating a profile's skill files, ask continuing sessions to rebuild their prompt.
The refresh preserves the session ID and history and takes effect on the next turn.

```bash
docker exec benka-hermes-gateway-1 hermes --profile personal sessions refresh-prompts --json
```

Repeat for the affected profiles. `benka_status` reads the installed Hermes version from the runtime
so the agent can answer version questions without opening a shell.

## Models and integrations

The main model uses the private Codex OAuth credential configured for Benka.

| Tier | Model and purpose |
|---|---|
| Dialogue and orchestration | GPT-6.2 Sol (`gpt-6.2-sol`), medium reasoning |
| Auxiliary tasks | Qwen3.8 Flash (`qwen3.8-flash`) for titles, compression, and background review |
| Delegated step | At most one bounded task on Qwen3.8 Flash, with Sol reviewing the result |
| Interactive reserve | Qwen3.8 Flash |

Short questions, status checks, and edits run directly in the main model. Bounded worker
calls use Qwen3.8 Flash, then DeepSeek V4.1 Flash.

Personal Telegram also exposes native OpenAI web search for current public information. The
search runs through the existing Codex OAuth route and the model cites the source. The runtime
image lets the web provider discover the shared Codex login used by routed profiles. This
capability uses the Codex Responses transport. The profile keeps web extraction, browser,
terminal, and anonymous search fallback disabled.

`BENKA_MODEL_PROVIDERS_FILE` is the path to a private JSON array of the form
`[{"model": "...", "provider": "...", "base_url": "...", "api_key": "..."}]`, with a maximum of four
routes. Standard OAuth is configured through Hermes; the existing OmniRoute keeps its own routes and
OAuth state. **Never put real keys in examples or in shell history.**

Every background task's model runs as a separate process with an empty temporary Hermes home, no
tools, no memory or context files, and no session persistence. There are turn, token, and time
limits, strict JSON output, and route-based fallback. The integrations' existing validators and
deterministic results are preserved.

A worker receives the service's previous variables with remapped paths: `EMAIL_CONFIG_PATH` /
`CONFIG_PATH`, state, sessions, vault mounts, the wiki and RAG URLs, and Redis. Check exact names
against the specific service's `load_config`. For native send, that worker needs its own configured
Hermes home and a trusted `delivery_targets` allowlist. Do not run the old entrypoint or cron-bridge
HTTP endpoints alongside the new worker.

`benka_integrations.delivery` runs `hermes send` from the same virtualenv as the worker's Python,
and only then falls back to `PATH`. Before updating a send-capable worker, verify that
`/opt/benka/.venv/bin/hermes` exists inside the container.
Each send gets a short-lived writable Hermes home. It links to the existing read-only gateway
configuration and environment files so the CLI can create its runtime lock without writing into
the shared mount.

> [!IMPORTANT]
> An `uncertain` receipt does not mean a confirmed delivery. First check the target Telegram topic,
> then take a single recorded operator decision about recovery. A successful exit code is not a
> substitute: only a Hermes response carrying `success` and a `message_id`, with no `skipped`,
> produces a confirmed receipt.

## Schedules and queues

The private reviewed-source JSON consumed by `jobs-prepare` contains:

- `timezone: Europe/Moscow` and `server_verified: true` after live reconciliation;
- `email.personal` and `email.work`: `enabled`, `stream`, `group`, `inbox_ref`, `poll_schedule`, and
  `slots` with `time` and `digest_type`;
- `telegram`: `enabled`, `domain`, `slots`;
- `signals`: a list of `enabled`, `domain`, `ruleset_id`, `schedule`;
- `last30days`: a list of `enabled`, `domain`, `preset_id`, `schedule`;
- `maintenance`: a list of `enabled`, `domain`, `action` (`wiki-daily` / `wiki-weekly` / `rag-scan`),
  `schedule`;
- `signals_cleanup`: `enabled`, `schedule` — preserves the cleanup of old Signals events (the source
  interval was one hour).

`signals.rule_files` is part of the production configuration, not merely a convenience of the
original OpenClaw runtime. When building the registry, the finalizer expands these reviewed
fragments relative to `integrations/signals/`. Reading only the inline `rule_sets` is not enough:
Hermes would then create no Signals or Last30Days jobs even with the rules and state fully
preserved.

```bash
.venv/bin/benka jobs-prepare deploy/hermes/private/reviewed-schedules.json > .migration/job-registry.json
BENKA_MANIFEST=/private/standby-manifest.json HERMES_HOME=/private/hermes-home .venv/bin/benka cron-prepare /private/hermes-home
```

Copy only that domain's jobs into its manifest, and use separate Redis credentials and ACLs. The
cron script reads `cron_connection_file` for `redis_url`, because Hermes clears the environment of
script-only jobs. Jobs are created paused; re-running preparation updates them by stable name, and
removed jobs stay paused. Do not run the `cron-prepare` CLI with a `HERMES_HOME` different from the
home passed to it.

If a registry-only gap is found after the cutover has already happened, the operator uses the
verified source snapshot and the active state directory rather than repeating the whole import and
finalize. `production-schedules-refresh` changes only the schedule manifest and its hash-bound
receipt; `cron-sync-production` then idempotently adds or updates the reviewed jobs, enables the
required ones, and pauses obsolete Benka jobs. The command validates the production receipt and is
not suitable for a candidate or a rehearsal:

```bash
benka production-schedules-refresh /private/verified-source /private/production-state
benka cron-sync-production /state/hermes /state/hermes/benka/schedules.json
```

`benka worker` processes a single selected `worker.pipeline` and the stream and group from the
manifest. Slot dedupe is atomic in Redis. Recovered pending entries and errors go to
`benka:reconcile` with their original payload. A completed record is confirmed before `XACK`, so a
crash between the two does not repeat the work.

Uncertain `sending` receipts and `benka:reconcile` are resolved manually: check Telegram, the stored
artifacts, the cursors, and pending; record the decision in the private operations log. **Blindly
restarting with a new `run_id` can create a duplicate.** Check queue age and size, not merely
whether the worker process is alive. The reconciliation queue has no automatic cleanup.

For one confirmed Signals miss, the operator may place `source_id` and `target_message_id` into a
private Redis job. The worker then loads only that Telegram message ID, skips the usual wide window,
and applies the same rule, deduplication, Hermes receipt, and source-context delivery. Such a job
must never be used without `source_id`; message identifiers and run IDs stay in the private
operation record.

TradingView author subscriptions run in the existing Signals worker and may use an existing
scheduled ruleset. Back up the private Signals config before adding sources or rules, validate
the merged config against the candidate image, then stop and recreate the Signals and Last30Days
workers. Both workers load the shared Signals config and need a compatible image. Recreating
them also picks up atomic replacements of the private bind-mounted config files. Check the
Signals source status and chart delivery receipts. See
[TradingView author subscriptions](../tradingview-signals-design.md).

## Wiki and LightRAG

Wiki and RAG require tokens. File paths are restricted to the domain root; URL ingest is disabled by
default. `rag_source_root` and `rag_index_roots` are set explicitly. `legacy_path_map` translates the
queue's old absolute paths into paths relative to the new root; unknown paths and `..` are rejected.

An upload receipt means the document was accepted. Successful search and completed indexing are
verified separately.

Carry over the embedding model identity and the 3072 dimension; do not repoint the graph at a new
incompatible model.

## Panel

Caddy on 8451 requires the server cert and key plus a trusted client CA in `private/tls`. TLS/mTLS
is complemented by Hermes authentication:
`HERMES_DASHBOARD_BASIC_AUTH_USERNAME`, `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`, and
`HERMES_DASHBOARD_BASIC_AUTH_SECRET`. Verify the exact scheme against the pinned version. The stable
auth secret is stored outside Git.

The dashboard shares the PID and network namespace with the Gateway; Hermes needs this for correct
live status and operator actions. Caddy therefore proxies to `gateway:9119`, and a separately
isolated dashboard container cannot be used.

Verify ordinary HTTP, the WebSocket upgrade, sessions, repeated login, and the negative cases with
no password and no client certificate. Domains, certificates, and SNI are agreed with the existing
infrastructure owner; 80 and 443 stay with the neighbours.

## Waiting and observation

Until a separate switch instruction: the candidate stays immutable, production credentials are
absent or disabled, cron is paused, only OpenClaw polls, and the test vault does not sync with the
Mac.

Record every secret rotation and every change in source behaviour in the [drift log](drift-log.md).

After the switch, at least 48 hours of real runs of every daily workflow are required, with stable
queues and stable memory.
