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
