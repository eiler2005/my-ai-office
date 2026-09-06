# Codex Skills Catalog

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This document tracks the project-specific Codex skills used with this repo.
It is intentionally separate from OpenClaw runtime docs: these skills help the
operator agent work on the system, not the production assistant answer end users.

---

## Purpose

We keep custom skills for workflows that are:

- repeated often enough to deserve a stable playbook
- specific to this deployment
- easy to get subtly wrong without local context
- good candidates for future expansion

The repo is the canonical source of truth. Installed local copies in
`~/.codex/skills/` should mirror the versions here.

---

## Current Skills

### `openclaw-cron-maintenance`

Canonical file: `skills/openclaw-cron-maintenance/SKILL.md`

Use when:

- updating OpenClaw-managed schedules for `telethon-digest`, `agentmail-email`, or similar bridges
- fixing `sync-openclaw-cron-jobs.sh`
- validating `jobs.json` after deploy
- recovering from a hanging `openclaw cron list` / cron CLI path

Core rule:

- on this deployment, prefer patching the cron store directly over relying on
  `openclaw cron list/add/remove`

Default safe workflow:

1. Read the managed prefix and expected schedules from the repo sync script.
2. Find the active cron store (`/opt/openclaw/config/cron/jobs.json` first, then `/home/deploy/.openclaw/cron/jobs.json`).
3. Back up the store to `jobs.json.bak-<timestamp>`.
4. Replace only the jobs owned by the managed prefix.
5. Preserve unrelated jobs untouched.
6. Restart `openclaw-openclaw-gateway-1`.
7. Wait until the gateway becomes `healthy`.
8. Validate expected names, cron expressions, and `enabled=true`.

Why it exists:

- `openclaw cron list` can hang on this server even while the gateway and scheduler are otherwise healthy
- the bridge jobs still work if `jobs.json` is patched correctly and the gateway is restarted

---

## Catalog Rules

Every new project skill should follow these rules:

1. One skill = one narrow operational problem space.
2. The repo copy is canonical and reviewable in git.
3. The skill must reference the real scripts/docs, not replace them.
4. The skill must encode the safest known path, especially around deploys, secrets, and rollback.
5. If a workflow has a server-specific gotcha, write it down explicitly.

---

## Suggested Next Skills

Good candidates for the next wave:

- `telethon-digest-ops` — deploy, auth, sync, smoke-test, and rollback flow for Telegram Digest
- `agentmail-email-ops` — poll/digest validation, lookback recovery, Redis queue checks, label safety
- `lightrag-maintenance` — ingest, reprocess, healthcheck, and query validation workflow
- `openclaw-runtime-deploy` — safe deploy/update procedure for the shared OpenClaw gateway stack
- `omniroute-maintenance` — provider health, tier validation, and upgrade checks

This keeps the catalog small but composable: one sharp skill per operational area.

---

## Install / Sync Pattern

Recommended workflow for local Codex usage:

1. Edit the repo copy in `skills/...`.
2. Review and commit it like normal code/docs.
3. Sync the final version into `~/.codex/skills/` for active local use.

Example:

```bash
mkdir -p ~/.codex/skills/openclaw-cron-maintenance
cp skills/openclaw-cron-maintenance/SKILL.md ~/.codex/skills/openclaw-cron-maintenance/SKILL.md
```

If we later automate this, we can add a tiny `scripts/install-codex-skill.sh` helper.
