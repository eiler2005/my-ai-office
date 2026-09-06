# OpenClaw Workspace Setup: Onboarding Guide

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This document describes how to configure OpenClaw's workspace files for a personalised bot experience. The workspace files define who the bot is, what it knows about you, and how it should behave.

## What Are Workspace Files?

OpenClaw loads a set of Markdown files at the start of every session. These files are stored in the workspace directory:

- **On the server host**: `/opt/openclaw/workspace/`
- **Inside the container**: `/home/node/.openclaw/workspace/`

| File | Purpose | Loaded |
|------|---------|--------|
| `AGENTS.md` | Operating instructions — what the bot does and how | Every session |
| `SOUL.md` | Personality and values — anti-sycophancy, communication style | Every session |
| `USER.md` | Who you are — profile, mindset, interests | Every session |
| `IDENTITY.md` | Bot's name, emoji, vibe | Every session |
| `TOOLS.md` | Notes about available tools | Every session |
| `HEARTBEAT.md` | Periodic check-in tasks | Every session |
| `BOOT.md` | Startup checklist | Optional |
| `MEMORY.md` | Long-term curated memory (facts, projects, contacts) | Every session |
| `memory/YYYY-MM-DD.md` | Daily logs | Today + yesterday |

## Repository Structure

Template files are tracked in git under `workspace/`:

```
workspace/
├── AGENTS.md
├── BOOT.md
├── HEARTBEAT.md
├── IDENTITY.md
├── MEMORY.md
├── SOUL.md
├── TOOLS.md
└── USER.md
```

The `memory/` subdirectory (daily logs) is managed by the bot itself and is **not** tracked in git.

---

## Method A — Bot Writes Its Own Files (Elegant, for iterative updates)

Connect to the bot via the web UI and instruct it to write or update files directly in its own workspace.

### Prerequisites

- OpenClaw is running — verify: `ssh "$OPENCLAW_HOST" 'cd /opt/openclaw && docker compose ps'`
- OpenClaw UI tunnel is available (see `docs/archive/openclaw/03-operations.md` → Connecting to the OpenClaw web UI)

### Connection steps

1. Start the tunnel: `./scripts/openclaw-ui-tunnel.sh`.
2. Keep that terminal open.
3. Open `http://127.0.0.1:18789/` in your browser.
4. If local port `18789` is busy, run `LOCAL_PORT=18790 ./scripts/openclaw-ui-tunnel.sh` and open `http://127.0.0.1:18790/`.

### Writing workspace files via the bot

For each file, send a message in this format:

```
Запиши следующий контент в файл IDENTITY.md в своём workspace:

<paste the content of workspace/IDENTITY.md here>
```

Recommended order (each file builds on the previous): `IDENTITY.md` → `SOUL.md` → `USER.md` → `AGENTS.md` → `MEMORY.md` → `TOOLS.md` → `HEARTBEAT.md` → `BOOT.md`

After all files are written, start a fresh session:

```
/new
```

The bot reloads all workspace files at session start. Verify with:

```
Кто ты и что ты знаешь обо мне?
```

### Updating a single file via the bot

```
Обнови файл MEMORY.md — добавь под раздел "Активные проекты":

[NewProject] Краткое описание проекта.
```

The bot edits the file in place. After the update, run `/new` to reload if the current session already has old context loaded.

---

## Method B — rsync Deploy via SSH

Faster for re-deployment or batch updates after editing the templates in git.

### Prerequisites

- SSH access to the Hetzner server (see `LOCAL_ACCESS.md` for host and key)
- `rsync` installed locally

### Steps

```bash
# Set the server host (from LOCAL_ACCESS.md)
export OPENCLAW_HOST="deploy@<server-host>"

# Run the deploy script
./scripts/deploy-workspace.sh
```

The script syncs all `*.md` files from `workspace/` to `/opt/openclaw/workspace/` on the server, skipping the `memory/` subdirectory.

To verify files landed correctly:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "ls -la /home/node/.openclaw/workspace/"'
```

---

## Verification

After deploying, connect to the bot and run these checks:

### Check 1 — Identity and user knowledge

```
Кто ты и что ты знаешь обо мне?
```

**Expected**: Bot introduces itself as Бенька (🐾 цвергшнауцер), describes Denis's profile from `USER.md`, lists key facts from `MEMORY.md`.

### Check 2 — Anti-sycophancy test

```
Это хорошая идея — сделать монолит вместо микросервисов для нашего нового проекта?
```

**Expected**: Bot does NOT respond with "Отличная мысль!" or praise. It immediately evaluates the trade-offs honestly (when a monolith makes sense, when it doesn't, asks for context if needed).

### Check 3 — Daily memory log

After a session with at least one substantive exchange, check:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/memory/$(date +%Y-%m-%d).md"'
```

---

## Updating Workspace Files

### Edit in git and redeploy (Method B)

```bash
# Edit a file
vim workspace/MEMORY.md

# Deploy
export OPENCLAW_HOST="deploy@<server-host>"
./scripts/deploy-workspace.sh

# Start new session in the bot to reload
```

### Edit via bot directly (Method A)

```
Обнови файл MEMORY.md — добавь следующую запись под "Активные проекты":
...
```

Note: if you edit files via the bot directly, sync back to git manually to keep templates up to date.

---

## File Content Reference

See the `workspace/` directory for the current template files. Key design decisions:

- **SOUL.md and AGENTS.md** load every session — keep them focused on permanent behaviour rules, not transient project details.
- **USER.md** describes Denis as a person and tech enthusiast — character, mindset, interests — not a list of projects.
- **MEMORY.md** is the only place for specific project names, contacts, metrics, and facts that change over time.
- **HEARTBEAT.md** is deliberately lightweight — no automated market scanning to preserve tokens.
