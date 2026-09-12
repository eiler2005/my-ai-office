# Verification and readiness record

Date: 2026-09-06. **Status `ACTIVE_ON_HERMES`; the 48-hour observation window is still open.**

The actual switch, the fresh snapshot, and the stopping of the source Docker services are recorded
in the [cutover record](cutover-record-2026-09-06.md). Publishing code is not by itself an
activation; this cutover was performed only after a separate instruction from the owner.

By Denis's instruction, further builds and tests run on the VPS; GitHub Actions is not used for
them. Production tokens, the production bot, mail, and Syncthing are never used in rehearsal tests.

## Corrective deployment of Telegram and profile manifests

After the production cutover, a corrective deployment was performed on the Hermes VPS. An isolated
candidate run confirmed the build of the runtime and test images, **209** regression checks, the
native Hermes contracts, a synthetic `claw migrate`, and Redis recovery. A full `finalize` was
additionally executed against a separate local copy of the production state on the VPS with
`network=none`, before any live state was changed.

In production the finalizer assigned the home channel to the personal DM of the single trusted
owner, disabled `onboarding.profile_build`, issued four profile manifests, and issued four
activation receipts. The Gateway was recreated on the verified image and returned to `healthy`;
loading the personal manifest inside the running container was confirmed.

Compose also recreated the `wiki` service as a Gateway dependency; its persistent volume was not
modified, and the remaining Benka workers continued running without a restart.

The check did not send an artificial message into a real Telegram chat and did not repeat a
delivery. The external Telegram smoke test remains part of the observation window: the owner
verifies an ordinary message in Benka's personal DM after deployment.

## Recovery of the 17:00 MSK Telegram Digest

Native cron enqueued the release into Redis on time, but the production worker could not find
`hermes send` on its `PATH`. The binary sat next to the Python worker inside the virtualenv. The
error occurred **before** a Telegram message identifier was confirmed and was correctly stored as
`uncertain`, with no automatic retry.

The fix selects the CLI from the virtualenv and only then falls back to `PATH`. A new staged
candidate on the VPS passed the same **209** regression checks, the native contracts, and Redis
recovery. In production, only `worker-telegram` was recreated, using Compose `--no-deps`; the
Gateway, `wiki`, and the neighbouring services were not restarted.

Before recovery, a read-only check of the target topic's history found no Benka message between
16:55 and 17:10 MSK. A single controlled run then produced the release for the nominal 14:00–17:00
MSK window, completed normally, and obtained confirmed receipts. An independent re-check of the
history found both parts of the release.

The original `uncertain` receipt and the reconciliation entry are kept in the private operations log
and must not be replayed.

## Operational recovery of mail and Signals

During observation, missed mail digests and Signals were found while the sources and the Redis
workers were running. The causes were separated:

- A stale runtime image invoked `hermes send` through a non-existent host-style `PATH`.
- Production schedule preparation read only the inline Signals rules and skipped the reviewed
  `rule_files`.
- Send-capable workers were missing the private `uploads` and `worker-logs` bind-mount directories,
  so restoring the original Telegram context with media could not complete.

The fix uses the Hermes CLI next to the Python worker, expands the reviewed Signals rule fragments
before building the registry, and creates the writable worker directories during preparation.

After a confirmed source check, controlled catch-up releases were run for both mailboxes. For one
confirmed Signals miss, a source-scoped job with `source_id` and `target_message_id` was used: it
reads only the specified post and goes through the normal matching, Redis dedupe, Hermes receipt,
and source-context delivery, without replaying the accumulated feed. The job finished without
writing to reconciliation, and the new delivery receipts were confirmed. The original `uncertain`
receipts are retained for manual reconciliation and are not resent automatically.

On the VPS only `worker-signals` was updated; the Gateway and the neighbouring services were not
recreated. The new runtime and test image passed **209** isolated checks. After recovery the Gateway
remained `healthy`, and all active Signals sources are healthy with no stale or error state.

## Repair of the profile manifest path

**2026-09-07.** Every Benka tool failed with `FileNotFoundError` in every domain. The owner reported
it from the Knowledgebase surface after a save was refused.

The generated profile configs set `manifest_path` to `/state/hermes/profiles/<domain>.json`. That
path is inside the profile's Hermes home, where `<domain>` is a *directory*; the sibling
`<domain>.json` never existed. Compose mounts the manifests read-only at `/run/benka/profiles/`, and
[operations](operations.md#profiles-and-telegram) has always required `manifest_path` to point
there. `load_manifest` therefore raised on every tool call, including `benka_status`, which does
nothing else — that is what localised the fault.

Reproduced read-only inside the running Gateway before anything was changed:

```text
FileNotFoundError: [Errno 2] No such file or directory:
'/state/hermes/profiles/personal.json'
```

The root cause is in the generator, not the deployment: `profiles.py` composed the path from
`runtime_home` rather than the mount. It is fixed at the source, with the mount as a named constant,
and the regression test now asserts the full path and that the generator actually wrote a file
there. The previous test asserted only that the value ended with `<domain>.json`, which the wrong
path also satisfied.

### Deployment

The four live profile configs were corrected in place after being backed up. Only the Gateway and
the dashboard were restarted, with `--no-deps`; the dashboard shares the Gateway's PID and network
namespaces, so it follows the Gateway. The runtime image was not rebuilt.

| Check after the change | Result |
|---|---|
| Gateway health | `healthy` after 50 s |
| `benka_status`, personal domain | Returns the production personal manifest |
| `wiki_lint` | Reaches the wiki service, 1,485 pages scanned — manifest, activation receipt and credential file all resolve |
| `lightrag_query` | Returns a response with references |
| Other Benka containers | Eleven untouched, original uptimes |
| Neighbouring projects | All ten untouched |

**Still open.** No Telegram save was executed as part of this repair: writing test content into the
owner's knowledge base is a side effect that belongs to the owner, not the operator. The external
smoke test — an ordinary save from the Knowledgebase surface — remains part of the observation
window.

The improved tool error reporting committed alongside this fix is **not yet live**: it lives in the
runtime image and ships with the next image build.

## Restoring Knowledgebase auto-capture

**2026-09-07.** After the manifest path was repaired, a forwarded post in Knowledgebase still
produced only a conversational reply and no wiki page. Nothing had been written to the vault in six
hours apart from the scheduled Last30Days run.

The tools were working; they were simply never called. The live instructions said not to:

| Source | Rule | Deployed? |
|---|---|---|
| `workspace/TELEGRAM_POLICY.md` | A forwarded post, URL or long text **is** a capture request; when in doubt, save | **No** — the predecessor mounted `workspace/`; Hermes does not |
| `skills/benka-knowledge/SKILL.md` | "Capture only on the user's request" | Yes |
| Plugin system prompt | "Save only on explicit capture intent" | Yes |

So the per-surface capture rule was lost in the migration, while the topic's pinned message and the
README continued to promise it. Recorded as `D007` in the [drift log](drift-log.md).

The `workspace/` provenance was also documented incorrectly in this repository — those files were
described as mounted into the running agent. They are not, under Hermes. Corrected.

### What changed

The rule now lives in the two places that are actually deployed: `skills/benka-knowledge` and the
plugin's system prompt section. A forwarded post, a URL, long multi-line content, or an explicit
instruction is a capture request; short question-shaped messages are searches; ambiguous messages
are captured, because a page the owner did not need is cheaper than a lost source. `обсуди:` remains
the opt-out, and is now the *only* one — the agent may not decline because content looks
unimportant. A save may be reported as done only with a real `wiki/research/**` path in the result.

`memory_enabled` and `user_profile_enabled` were also switched on for the `personal` profile. The
reviewed files were within the documented limits beforehand: `USER.md` 1,376 characters against
1,375, which is the trailing newline, and `MEMORY.md` 2,183 against 2,200.

### Verification

The system prompt lives in the runtime image, so this required a rebuild rather than a config edit.
Candidate tree `2a245b48f3488b29663db843b7d60d45e38c805f`, built and verified with
`scripts/run-hermes-vps-tests.sh` on the isolated `benka-migration` builder, exit code 0:

| Suite | Result |
|---|---|
| Hermes safety / migration / archive / cron / profiles / maintenance / tool errors | 57 passed |
| AgentMail | 19 passed |
| Telegram Digest | 21 passed |
| Signals / Last30Days | 98 passed |
| Wiki-import | 26 passed |
| **Total** | **221 passed** |
| Native plugin / cron / AIAgent contract | 7 tools, paused idempotent cron, bounded API |
| Offline standby | `standby` / `sandbox` / `automatic_cutover=false` |

Runtime image `sha256:76f4f4271ae311ccbaa4d303dd0dd0ca104aa6fe46e337a9e2367160ee2e8637`, tagged
`benka-hermes:capture-fix-2a245b48`.

Deployed by recreating **only** the Gateway and the dashboard with `--no-deps`; the dashboard
follows because it shares the Gateway's namespaces. The six workers stayed on their previous image —
they do not use the plugin's prompt — and the ten neighbouring containers were untouched. Configs,
the env file and the four skill files were backed up first.

After deployment the Gateway reached `healthy` in 50 s, the new rule was confirmed present in the
loaded module and the old one absent, and `benka_status` returned the production personal manifest.

### The deployment alone was not enough

A forwarded post after the deployment still produced only a reply. The deployment was correct; the
**session** was not.

Hermes freezes a plugin's system prompt section into a session when the session is created and
persists it verbatim. Both live personal sessions — including the Knowledgebase topic, open with 25
messages — referenced one stored prompt, hash `d90d26505a0b6c96`, which contains the old rule and
not the new one:

```text
system_prompts.prompt : rows with the old rule = 1, with the new rule = 0
sessions              : both rows reference d90d26505a0b6c96, ended_at = null
```

An existing conversation therefore keeps the old instructions indefinitely, no matter how many times
the image is rebuilt. The procedure is recorded in
[operations](operations.md#changing-the-agents-instructions): rebuild, deploy the skills, **and
start a new session on every affected surface** — `/new` in the topic, which is in this profile's
`user_allowed_commands`.

**Still open.** The behavioural check is the owner's: send `/new` in Knowledgebase, forward a post
with no save instruction, and confirm a `wiki/research/**` page appears. No test capture was written
into the owner's knowledge base as part of this work.

## LightRAG could not write its own state

**Found and fixed 2026-09-07.** After Knowledgebase capture was restored, the first real
save reported the wiki page created and indexing failed. The service log:

```text
ERROR: Error /documents/upload: selectel.md:
[Errno 13] Permission denied: '/app/data/inputs/selectel.md'
```

It is not limited to uploads. The container cannot write **anywhere** under `/app/data`, including
`rag_storage`, where the graph and vector state live. The last successful state write was
**2026-09-06 12:53**; retrieval has been answering from that frozen index since.

The cause is a combination that looks safe in isolation. The image declares no user, so it runs as
root; the Compose service sets `cap_drop: [ALL]`, which removes `CAP_DAC_OVERRIDE` — the capability
that lets root bypass file permission checks. The state directories are owned by `1000:1000` with
mode 755, so root-without-override gets `r-x` and no write.

```text
container: uid=0(root), CapDrop=[ALL]
/app/data         drwxr-xr-x 1000 1000   NOT-WRITABLE
/app/data/inputs  drwxr-xr-x 1000 1000   NOT-WRITABLE
```

The fix is to run the service as the user that owns its data, which is what every other service in
the project already does: `user: "1000:1000"`.

### Deployment, and the second failure it exposed

Recreating `lightrag` alone with `--no-deps` made the data writable and immediately put the service
into a restart loop:

```text
PermissionError: [Errno 13] Permission denied: '/app/lightrag.log'
ValueError: Unable to configure handler 'file'
```

`/app` is a root-owned image layer. As root the server could create its log there and not write its
data; as uid 1000 it can write its data and not its log. The server reads `LOG_DIR`
(defaulting to the working directory), so the log now goes to `/app/data` with the rest of the
writable state.

This is worth recording because the intermediate state was **worse than the defect**: retrieval was
down for about four minutes, where before it had merely been serving a stale index. A container that
starts as root is not evidence that it will start as another user.

| Check after the fix | Result |
|---|---|
| Container user | `uid=1000 gid=1000` |
| `/app/data`, `/app/data/inputs`, `/app/data/rag_storage` | All writable |
| Startup errors | None |
| `lightrag_query` through the Gateway | Returns `response` and `references` |
| Log file | `/app/data/lightrag.log`, owned by 1000 |
| State directories writing again | `rag_storage` and `inputs` touched after restart; ingest markers `__enqueued__` / `__parsed__` present |
| Other containers | Twelve untouched |

Captures made while this was broken keep their wiki pages — the artifact is the store and the index
is derived ([ADR-0005](../adr/0005-wiki-first-capture-rag-as-retrieval.md)) — so they are re-indexed
by the scheduled refresh rather than re-captured.

**Still open.** The graph state files themselves still carry their 2026-09-06 12:53 timestamps; the
next scheduled refresh is what re-indexes the backlog. Confirm afterwards that a Knowledgebase
question about recently captured content returns references, not just a response.

## Why the index stayed frozen, and why Last30Days went undelivered

**2026-09-07.** Two separate causes, both now fixed. Manifests are hash-bound to their activation
receipts, so neither could be repaired by editing a file in place — the generator had to be fixed and
the manifests regenerated.

### Last30Days delivery is refused by the allowlist

The 07:00 MSK run on 2026-09-07 executed and wrote `Last30Days/Expanded/2026-09-07-last30daysTrend.md`,
then failed:

```text
delivery.py: PermissionError: Destination is not in this domain's allowlist
```

The worker posts to Telegram topic `414`. Every worker manifest carries the same four-topic
allowlist — `119`, `122`, `125`, `126` — and `414` is in none of them. There are five publishing
workers and four allowlisted topics.

`414` is the pipeline's own declared destination: the live reviewed `signals/config.json` names it
in three places — `.last30days.telegram.topic_id` and both presets — and Last30Days' state files
carry it back to April.

The cause is in the generator. `production.finalize()` built the allowlist by sweeping bridge `.env`
files for `EMAIL_DIGEST` / `DIGEST` / `SIGNALS` topic variables. Last30Days declares its topic in the
reviewed signals config instead, so the sweep never saw it: five publishing workers, four allowlisted
topics. `finalize()` now also collects reviewed topic ids from the signals config's `last30days`
section, using the `_find_topic_ids()` helper that already existed for bindings.

The delivery contract behaved correctly throughout. A worker may not publish to a destination that is
not configured, and it did not.

**Deployed 2026-09-07.** The manifest is hash-bound, so the receipt was rebound alongside it: `414`
was added to `delivery_targets`, the manifest digest recomputed, and `manifest_sha256` updated in
`activation/last30days.json` with `command`, `snapshot_sha256` and `old_writers_stopped` left
untouched. Both files were backed up first. `require_active(config, "send")` accepts the rebound
receipt.

The missed 2026-09-07 07:00 release was never sent — it failed before delivery, so there is no
duplicate risk in a controlled catch-up. That remains the owner's call; the next scheduled run
delivers normally.

### The RAG scan aborted on the first document LightRAG already had

Every 30 minutes since the cutover, `rag-scan` failed and went to reconciliation — 50 entries by
2026-09-07 11:30.

The first diagnosis in this record was wrong and is corrected here. It reported that the `personal`
profile manifest lacked `rag_source_root`, `rag_index_roots` and the `index` operation. That manifest
does lack them, but it is not the one the scan uses: `rag-scan` runs in the **maintenance** worker,
against `/run/benka/manifest.json`, which has all three:

```text
enabled_operations : ['worker', 'wiki_write', 'index']
rag_source_root    : /vault
rag_index_roots    : ['wiki', 'Telegram Digest', 'Last30Days', 'PlatformPulse', 'Recordings']
```

The real fault was in this project's code. `maintenance.upload()` called `raise_for_status()` on
every response, and LightRAG answers **409 Conflict** for content it already holds:

```text
HTTPError: 409 Client Error: Conflict for url: http://lightrag:9621/documents/upload
```

For a scan, 409 means "already indexed" — a success. Treating it as fatal aborted the run on the
first known file, so it never reached the new ones. `upload()` now records the digest and returns
`status: "duplicate"`, and the scan continues. Three regression tests cover the single response, the
scan continuing past it, and the digest preventing a re-upload on the next pass.

The permission defect fixed earlier the same day was real and independent: before it, the same
uploads returned 500. Fixing it changed the failure from 500 to 409 and revealed this one.

**Deployed 2026-09-07.** The maintenance worker was recreated on the verified image. The first real
scan afterwards completed across **2,760 files: 2,126 submitted, 482 duplicates, 152 unchanged** —
where before, the first duplicate ended the run.

Captures kept their wiki pages throughout, because the artifact is the store and the index is
derived. Nothing was lost; it was not yet searchable.

## Sweep of every Telegram topic against the predecessor

**2026-09-07.** A check that each surface still does under Hermes what it did under OpenClaw.

**Schedules.** The reviewed registry and the installed cron agree exactly — 26 declared, 26
installed, none missing and none extra. All are active and their last run reported `ok`. The single
exception is `benka-personal-wiki-weekly` (`30 3 * * 0`), which has never run because no Sunday has
occurred since the cutover; the first is 2026-09-13 and it is unverified until then.

> [!WARNING]
> Cron reporting `ok` means the job was **enqueued**, not that it delivered. The Last30Days release
> that never arrived is logged as `ok` in `hermes cron list`. Check the worker's job record and its
> log, not the scheduler, when output is missing.

**Delivery.** Every publishing worker's configured destination is now allowlisted, checked as a set
rather than by sampling:

| Worker | Configured topic | In its allowlist |
|---|---|---|
| `email-personal` | 119 · inbox-email | yes |
| `signals` | 122 · signals | yes |
| `email-work` | 125 · work-email | yes |
| `telegram` | 126 · telegram-digest | yes |
| `last30days` | 414 · last30daysTrend | yes, after today's fix |

Four of the five delivered on 2026-09-07. Last30Days is fixed but unverified in production until the
next 07:00 run.

**Documentation corrected.** The wiki maintenance times in this repository were wrong: daily is
`15 3 * * *` and weekly `30 3 * * 0`, not the 05:45 and Sunday 06:15 that `schedules.md`,
`workflows.md` and `knowledge.md` claimed. Every other documented time matches the installed cron.

### The gap this sweep found

Under the predecessor, `workspace/TELEGRAM_POLICY.md` and `TOOLS.md` gave each topic its own rules
and named the ids — `knowledge_channel` naming the Knowledgebase topic by its numeric id. Hermes mounts neither,
and a plugin prompt section receives only `session_id`, `model`, `provider`, `platform`,
`profile_name` and `cwd`: **no chat id and no thread id.**

So the agent could not tell Knowledgebase from Ideas. `capture_mode=ideas` and the promotion chain
were unreachable, and the capture rule applied to every surface equally rather than to the two it was
written for.

The Telegram session id is the one place the thread survives —
`agent:<profile>:telegram:group:<chat>:<thread>` — so the prompt section is now a callable that
resolves the trailing thread against a `surfaces` map in the profile's plugin settings and appends
surface-specific guidance. Recognised values are `knowledgebase`, `ideas` and `conversation`.

Deployed 2026-09-07 on candidate tree `c6798dee4bdb09ed40fb2f7d18c275ccb08da78e` (VPS run exit 0,
**232 passing**). Verified in the running Gateway that the section is a callable and that, with no
map configured, it renders exactly the previous text — the mechanism is inert until someone
configures it.

### The map, and where the ids came from

The thread ids were recovered from the predecessor's own `telegram-topic-map.json`, preserved in the
cutover snapshot — the authoritative source, since it is the file the pin tooling used. Two routes
were tried first and rejected: the Telethon user session, because a second connection with the same
auth key risks invalidating the digest worker's session, and the Bot API, which refuses
`GetForumTopics` for bots (`BotMethodInvalidError`).

Twelve threads are mapped: `knowledgebase` and `ideas` for the two capture surfaces, and
`conversation` for football, approvals, tasks, system, rag-log and the five outbound feed topics —
so a reply in a digest topic is not silently filed away.

Applied to the `personal` profile config and loaded by a Gateway restart. Verified against the live
configuration inside the running container:

```text
232   Knowledgebase  -> knowledgebase capture
639   Ideas          -> ideas capture
11    Football       -> conversation, capture OFF
123   System         -> conversation, capture OFF
999   unmapped       -> base rules only
```

**Still open.** Sessions freeze their prompt at creation, so each surface needs `/new` before the
change takes effect there. Ideas in particular has not been exercised end to end — the first
forwarded item after `/new` should produce a light-curation capture rather than a knowledgebase one.

## Fleet aligned to `main`

**2026-09-07.** Until now the deployed image lagged `main` and the fleet ran three different tags —
`operational-fix-...a`, `...b` and `finalize-fix-e04d0cb8` — each from a container that happened not
to have been recreated since. Correct, but the image a service runs could no longer be read off the
branch.

Candidate tree `3a0e1e77a6eda2d97cf7202f33c6511f3633a38d` was built and verified with
`scripts/run-hermes-vps-tests.sh`, exit code 0 and **238 passing** across five suites
(74 · 19 · 21 · 98 · 26), then tagged `benka-hermes:main-3a0e1e77`.

All nine services that run the runtime image — Gateway, dashboard, `wiki` and the six workers — were
recreated onto it with `--no-deps`. The Gateway returned to `healthy` in 50 s, the surface map still
resolves 232 to `knowledgebase` and 639 to `ideas`, the wiki service answers with `rag_degraded:
false`, and the ten neighbouring containers were untouched.

The change itself was a no-op at runtime: only `production.py` differed, as an extraction covered by
new tests, and it is reached from operator CLI commands rather than from the running services. The
roll was for the invariant, not the behaviour — **what runs is now the tip of `main`.**

## Personal Knowledgebase URL capture restored

**2026-09-12.** The personal profile manifest had no `wiki_source_types` value. The integration
correctly fell back to `text` only, so a URL in the Knowledgebase topic reached the capture decision
but was refused before it could reach the wiki service.

The profile now explicitly permits `text` and `url`; its hash-bound activation receipt was updated
in the same atomic maintenance step. The running Gateway reads the profile manifest per tool call,
so it did not need a restart. A direct production tool smoke for the owner-supplied link created a
`wiki/research/**` artifact and an import-queue entry. The initial retrieval state was `delayed`,
which preserves the capture and lets the normal maintenance worker complete indexing. The Gateway
remained healthy after the change.

`production.finalize` now emits the same allowlist for future personal production manifests. Other
profiles remain text-only until their data boundary and owner policy are separately reviewed.

## Verified on the Hermes VPS

The server-side run executed in containers with a read-only root, no production secrets, and a
2 CPU / 2 GiB RAM limit. Regressions and native contracts run with `network=none`; Redis was
verified on a separate `internal` Docker network with no published ports. The test dataset consists
of synthetic fixtures only. There is no GitHub Actions involvement.

| Suite | Result |
|---|---|
| Hermes safety / migration / archive / cron / profiles / maintenance + native model fixtures | 45 passed |
| AgentMail | 19 passed |
| Telegram Digest | 21 passed |
| Signals / Last30Days | 98 passed |
| Wiki-import | 26 passed |
| **Total** | **209 passed** |
| Native Hermes plugin / cron / AIAgent contract | 7 tools registered; paused cron idempotent; API parameters compatible |
| Compose configuration | `config --quiet` passes |
| History and working tree secret scan | Before the merge commit: 1,226 objects, 34 reviewed matches, 0 unresolved; the scanner self-test passes |
| VPS inventory | Both hosts checked read-only; details in private JSON reports |

The native model tests use the real pinned `AIAgent` and a local HTTP/SSE fixture: they verify the
absence of tools and inherited memory, the 401 → fallback path, and termination on timeout. **They
do not prove that the real OAuth or provider accounts are reachable.**

Snapshot tests verify the SHA of the whole archive and of each file, tampering, path traversal,
repeated import, an interrupted restore, and the absence of overwrites. Queue and delivery tests
verify slot dedupe, pending reconciliation, confirmed message IDs, and the prohibition on repeating
uncertain sends. **None of this replaces a real Telegram smoke test.**

## VPS check matrix

Server-run results are added as they are produced. Use separate container names, volumes, and
resource limits. Never attach production state or neighbouring projects.

| Check | Status before the server rehearsal | What it closes |
|---|---|---|
| Build of the pinned Docker image, including dashboard and Last30Days | PASS | Linux runtime and a separate test target build |
| Regressions in a container on the VPS | PASS, 209 tests | All five suites pass |
| Standby with networking disabled | PASS, CLI and a running container | `standby` / `sandbox` / `automatic_cutover=false`; healthy before and after restart, `network=none` |
| Native plugin / cron / model contracts on the VPS | PASS | 7 tools, paused cron, native model fixtures |
| Real Redis and a container restart | PASS | AOF preserves the slot, the delivery receipt, and pending; pending goes to reconciliation with no repeated send |
| TLS/mTLS, authentication, WebSocket dashboard | PASS, 9 checks | Refusal without a client certificate; refusal on missing session or wrong password; login, Secure/HttpOnly cookies, HTML/config/sessions API; WS upgrade and replay prohibition |
| Native OpenClaw importer | PASS, synthetic data | dry-run, import, repeat, source immutability, exclusion of private config, and pre-import backup |
| Neighbouring projects on the Hermes VPS | PASS | All 9 pre-existing containers keep their image ID, status, and health |

Re-verified Git tree: `e3350692a5fcb801b57414a4a2121dd88dc8f1c4` (staged candidate export 07).
Runtime image ID: `sha256:ba86d71c6b9fc882ca8d664ed3170a5827a6a8002f95bfb0774e15accd3ce40b`.
First full run: tree `f96facd124bc812143fe09152ec6e4ee70dea0ed` (code `c2ab557`).
Private logs: `/opt/benka-hermes/reports/<TREE>/`; the final exit code was 0.

Native Hermes detected SQLite 3.46.1 and selected the DELETE journal; WAL was not enabled.

The first run found — and helped fix — CRLF handling in the Git export, the path to the dashboard
build output, and a reference script missing from the test image. The repeat run passed completely.
Before the instruction to move to the VPS, 206 tests had previously passed locally.

The panel Compose changes and the operator scripts were then verified directly on the VPS: the
separate Caddy ingress network, the bounded trusted proxy in Hermes, Secure cookies, a dashboard
restart, and the native importer rehearsal. These do not require a change to the runtime image.

HTTPS works on the Reddit Compass domain with the separate port 8451; the source Caddy, DNS, and
SNI routes were not modified. Details and the private access files are described in the
[panel runbook](panel.md).

Full chat against the real models is **not yet verified**. TLS certificate refresh is still an
operator action.

On the source host, the other 14 previously registered containers were unchanged; the separate
third-party OpenClaw candidate from D003 disappeared during the work. The production Gateway was
preserved. This parallel rollout must be re-checked before cutover.

## Remaining before `READY_NOT_ACTIVE`

- Close the registry of actual source files, cron at all levels, volume sizes, and the pinned
  LightRAG / OmniRoute / Syncthing images.
- Port the necessary changes from the uncommitted OpenClaw project, without automatically including
  the unfinished runtime upgrade.
- Prepare the full private deployment manifest: every worker, scoped Redis/wiki/RAG, models, paths,
  volumes, and the panel domain.
- Verify domain routing, ACLs, and context isolation against a real Gateway with a separate test
  bot; prepare reviewed SOUL/USER/MEMORY/skills.
- Run the rehearsal against a verified backup: native importer dry-run and import, repeat,
  interruption, recovery, and archive search.
- Verify both mailboxes, Telegram sources and cursors, both Last30Days presets, triage, ideas and
  promotion, and the control LightRAG queries.
- Verify every provider and fallback, malformed JSON, auth errors, timeout, and the all-models-fail
  path with a deterministic result.
- Run a combined pass of a Telegram request, a digest, and indexing; assess OOM, restarts, and queue
  growth.
- Verify restart, reboot, and recovery on the VPS, with the neighbouring services staying healthy.
- Verify rollback both before and after new writes, including deliveries, cursor merge, and pending;
  a vault-delta report alone is not sufficient.
- Leave production connections disabled and all production cron paused. Only then record READY.

External checks still require somewhere to store the configuration of a separate test Telegram bot,
a verified backup, and the final private domain bindings. Secrets go into neither chat nor Git.

## After a separate cutover instruction

Repeat the inventory and drift review, transfer a fresh cold copy covering the whole waiting period,
and confirm the single polling owner. Close the plan's entire functional matrix. Observe for at
least 48 hours with real daily runs. Verify weekly maintenance against a copy and confirm recovery.
Until then the migration is not considered complete.

## Record format for each run

Record the date, the Git SHA plus dirty flag, the image ID, the pinned Hermes SHA, the dataset
class, the command, the counts and result, and the remaining gaps.

Logs containing mail or conversation content, receipt IDs, endpoint details, and auth are kept
private; only the de-identified result goes into Git. **A health check does not close functional
acceptance.**
