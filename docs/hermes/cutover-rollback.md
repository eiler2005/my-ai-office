# Cutover and rollback

> [!IMPORTANT]
> The actual cutover was performed on 2026-09-06 after a separate instruction from Denis. The fresh
> snapshot is held in the private production state of the Hermes VPS, with no copy on the Mac; all
> Docker services on the source VPS are stopped and retained. See the
> [cutover record](cutover-record-2026-09-06.md).
>
> The sections below are the rollback and re-transfer procedure — **not** an instruction to restart
> OpenClaw automatically.

**Execute only after a separate instruction from Denis.** The two-week waiting period does not open
the window by itself. Before the switch, close out the [candidate acceptance](acceptance.md) and the
[drift log](drift-log.md).

## Before stopping anything

Re-verify the inventory of both VPS hosts, the existence of a working backup, Mac access, and
sufficient disk. The source VPS has little free space: do not create an additional multi-gigabyte
archive there. The streaming export goes to a protected disk on the Mac. Measure transfer and
restore speed in advance.

The window budget is four hours; begin rollback no later than the third hour if acceptance is not
passing.

Record the final Git SHAs, upstream pins, image IDs, deployment manifest, and secrets by purpose.
Separate rehearsal state from the clean production destination and remove it from the final import
paths. Repeat any check whose inputs changed. If a functional gap is found, OpenClaw keeps running
until it is closed.

## Fresh cold snapshot

1. Stop new OpenClaw jobs from being enqueued, wait for active ones to finish, and export pending
   and uncertain deliveries.
2. Stop only the Benka-related cron, polling, bridge workers, and writing processes. Pause Syncthing
   on the Mac and on the old VPS.
3. Record the Bot API update watermark, Telethon cursors, both mail watermarks, the Redis PEL, and
   the confirmed message IDs.
4. Stop Redis / LightRAG / OmniRoute before copying their files, or use that database's own verified
   consistent-snapshot mechanism.
5. Copy every component and image to the Mac over SSH; verify the file manifest and SHAs. Do not
   stop neighbouring projects.

The prepared `benka snapshot` operates on an **already consistent local layout** — it does not stop
the server itself. The root structure is: `openclaw/`, `workspace/`, `vault/`, `integrations/`,
`redis/`, `lightrag/`, `omniroute/`, `config/`, `secrets/`.

Use the real mount sources from the private inventory for volumes. Copying a running database with
an ordinary `cp` is not permitted. Symlinks and special files require explicit preparation; the
migrator rejects them. Keep Docker images and host-level configuration as separate verified archives
next to the snapshot, outside Git.

The cold receipt JSON records `writers_stopped: true`, `syncthing_paused: true`, and the list of all
nine `components`. Missing components must also be explicitly accounted for by the operator; check
`absent_components` in the manifest before importing. **The receipt records that actions were
performed; it does not substitute for stopping the writers.**

```bash
umask 077
.venv/bin/benka snapshot /private/final-layout /private/final-export --cold-receipt /private/cold-receipt.json
.venv/bin/benka restore /private/final-export/snapshot.tar /private/final-export/manifest.json /private/restores
.venv/bin/benka restore /private/final-export/snapshot.tar /private/final-export/manifest.json /private/restores --apply
```

Without `--apply`, only verification runs. The import goes through staging and an atomic rename into
a directory named by the snapshot SHA. A repeat run verifies every previously imported file; a
changed import is not treated as successful. An interruption or an incomplete archive must leave the
old runtime untouched.

After verification, move staging into the corresponding volumes and bind mounts and set the UID,
GID, and permissions for each service.

## Transferring Hermes user data

The source OpenClaw stores `config` and `workspace` separately. In a separate curated workspace,
prepare reviewed `SOUL`, `IDENTITY`, `AGENTS`, `USER`, and `MEMORY` files. `MEMORY` is limited to
2,200 characters and `USER` to 1,375; diaries do not belong in that memory.

Review tools, OpenClaw instructions, paths, and trust boundaries. Source prompt instructions are not
copied blindly.

```bash
.venv/bin/benka claw-layout /private/restored/openclaw /private/curated-workspace /private/claw-layout
HERMES_HOME=/private/new-hermes-home .venv/bin/hermes claw migrate --source /private/claw-layout --preset user-data --dry-run
```

Read the pinned importer's output, then run the same command without `--dry-run` against a verified
workspace target.

> [!WARNING]
> Hermes 0.21.0 creates a default `SOUL.md` on the first CLI run, including a dry run. A conflict
> with it can abort the entire import **while still exiting 0**. Check the actual files and the
> report, not just the process exit code.

Only in a new isolated destination, and only after reviewing the conflict list, repeat the dry run
with `--overwrite`, then apply with that flag and keep the standard pre-migration backup. Do not use
`--overwrite` against an unverified directory that already holds user data. Reconcile `SOUL` and
`memories/{USER,MEMORY}.md`.

Transfer reviewed skills separately: install `plugins/benka` and `skills/benka-*`, apply the domain
profiles, and install the paused cron jobs. The standard import does **not** turn OpenClaw bridges,
plugins, cron, or Telegram bindings into Hermes integrations automatically.

```bash
.venv/bin/benka archive-index /private/domain-transcripts /private/domain-state/archive.sqlite
```

Reconcile the imported sources against the `skipped` report. Full conversations remain available
through search with source and line number; Hermes starts new sessions. Each domain gets its own
archive and its own compact memory.

## Activation

Configure and verify secrets and OAuth, the models and every fallback, the embedding endpoint, the
wiki, Redis, and the profile permissions.

For each production manifest the operator creates a separate read-only activation receipt:
`command=ACTIVATE_HERMES_BY_DENIS`, the exact `manifest_sha256`, the SHA of the **final** snapshot,
and `old_writers_stopped=true`. The values are filled in after the real instruction and after
verifying that writers stopped. The file is not stored in Git and is not reachable by the agent's
tools.

Enable the single production polling Gateway and verify Telegram inbound → a reply in the correct
topic → a follow-up. Then enable the verified cron jobs and workers, and watch the accumulated queue
and its deduplication.

Before resuming Syncthing, compare the vault against the Mac; connect the new device identity
without unexpected deletions.

Verify all functions for at least 48 hours; additionally run the weekly wiki procedure against a
copy.

## Rollback

Triggers: no Telegram ingress, broken topics or ACLs, data loss, repeated publications, wiki/RAG
failure, or an unstable runtime.

**Before any new writes:** stop the Hermes Gateway, workers, cron, and Syncthing; restore the source
data and the known images, confirm the single polling owner, and resume OpenClaw.

**After new writes:** first capture Hermes's cold state. Do not overwrite current data with the old
archive.

```bash
.venv/bin/benka rollback-delta /private/baseline-vault /private/hermes-vault /private/old-vault > /private/rollback-report.json
```

The command produces a three-way report: safe new and changed files, files that already match,
conflicts, and deletions to reconcile. **It overwrites nothing.** The operator moves the agreed
wiki and raw artifacts, archives the new Hermes conversations, and reconciles confirmed deliveries,
cursor advances, and Redis pending entries across both runtimes.

A new RDB cannot be mechanically replaced by the old one: streams, PEL, and dedupe must be
reconciled semantically, including the uncertain sends. Restarting the old handlers is permitted
only after that reconciliation.

Keep the old stack and the verified archive for at least 14 days **after Hermes acceptance**.
Deleting them is a separate operation.
