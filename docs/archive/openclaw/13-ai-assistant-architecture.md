# AI Assistant Architecture

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This document describes the design principles, model routing, channel interaction model,
and memory strategy for the Бенька / Benka AI assistant running on OpenClaw.

Use this file for assistant behavior and routing policy.
For the core memory architecture, use `docs/archive/openclaw/10-memory-architecture.md`.
For the human explanation of `raw -> wiki -> LightRAG -> OpenClaw`, use `docs/archive/openclaw/19-llm-wiki-memory-explained.md`.
For `Ideas` / `Knowledgebase` behavior, use `docs/archive/openclaw/17-knowledge-management.md`.

---

## Core Design Principles

### Least privilege by default

The assistant does not accumulate permissions, memory, or access beyond what is
needed for the current task. Each surface has its own mode, and the safest mode
is the default.

### Memory is earned, not automatic

Telegram messages are not memory by default. A message can be answered without being saved.
Saving to long-term memory requires either an explicit user command or a high-importance
signal with sufficient confidence. Family content always requires explicit approval.

### Approval before action

Destructive operations, external sends, deploys, credential changes, purchases, and
high-sensitivity memory writes require user confirmation before proceeding. This rule
applies regardless of channel.

### One response, one surface

The assistant responds where it was invoked. It does not cross-post between surfaces
(e.g., from Family to Ops) unless explicitly asked. Context from one domain does not
leak into another.

### Conservative by default, explicit to expand

If a surface, action, or memory write is ambiguous, the safer interpretation wins.
Expansion of permissions or memory scope requires explicit instruction.

---

## Model Routing Architecture

### Primary flow

```text
User message
  -> OpenClaw gateway
     -> Agent runner
        -> Primary route: openai/gpt-5.5
            on rate_limit / auth error / provider error:
            -> Fallback: deepseek-direct/deepseek-chat
```

Fallbacks are configured in `agents.defaults.model.fallbacks` in `openclaw.json`.
This is channel-agnostic — applies to all surfaces (Telegram, web UI, API).
OpenAI `openai/gpt-5.5` is the primary Gateway route and uses ChatGPT/Codex OAuth transport
(`openai-chatgpt-responses`), not the direct OpenAI Platform API-key path. `deepseek-direct/deepseek-chat`
is the direct reserve for interactive Gateway turns. OmniRoute remains available as a separate service
route for digest/signals/RAG flows, but it is intentionally not in the interactive Gateway fallback
chain after the 2026.6.1 continuation failure (`Cannot continue from message role: assistant`) seen
in Telegram smokes.

### OmniRoute tiers

OmniRoute runs inside the same Docker Compose stack (`http://omniroute:20129/v1`).
It provides three routing tiers, each with a priority fallback list internally:

| Tier | Primary model | Use case |
|------|--------------|----------|
| `smart` | kiro/claude-sonnet-4.5 | Code generation, architecture review, multi-step reasoning, context >8K tokens |
| `medium` | kiro/claude-haiku-4.5 | Q&A, summarization, translation, standard dialog |
| `light` | kiro/claude-haiku-4.5 | Classification, data extraction, formatting, quick lookups |

Each tier has internal fallbacks (e.g., openrouter models) if the primary fails.

### Model selection rules (agent-side)

The agent (running in the primary model context) selects OmniRoute tiers for subtasks:

1. Code >50 lines, architecture review, multi-step reasoning, context >8K → `smart`
2. Standard dialog, Q&A, summarization → `medium`
3. Classification, tagging, data extraction → `light`
4. LightRAG lookups and classification → `light`
5. Knowledgebase save, Ideas capture, and Ideas promotion stay on the `medium` wiki-first path unless the user explicitly asks for deeper analysis

For Telegram save/promote actions, the preferred write path is:

- `wiki_ingest(url)` when a stable source URL already exists
- `wiki_ingest(text)` only when there is no reliable URL or the source is a plain note

The main user response uses OpenAI first. OmniRoute is the first reserve route, not the default.

### Response footer

Every response in Telegram ends with a one-line footer:

```
_light · primary · 8% · standard · memory_
```

Fields (separated by ` · `):

| Field | Values | Meaning |
|-------|--------|---------|
| Model | `light` / `gpt-5.5` / `smart` / `medium` | Which model generated the response |
| Source | `primary` / `fallback` / `delegated` | How the model was selected |
| Context % | `5%` … `95%` | Rough fill of the context window this session |
| Complexity | `complex` / `standard` / `simple` | Task tier that drove model selection |
| `memory` | optional suffix | Memory files were loaded in this session |

Examples:
```
_light · primary · 8% · standard · memory_
_gpt-5.5 · fallback · 8% · standard · memory_
_smart · fallback · 31% · complex_
_medium · fallback · 12% · standard · memory_
_light · delegated · 5% · simple_
```

---

## Telegram Interaction Model

### Surface hierarchy

| Surface | Mode | Proactivity | Memory writes |
|---------|------|-------------|---------------|
| DM (`Benka_Clawbot_base`) | Control | Medium | Decisions/facts on explicit command |
| Ops supergroup (`Benka_Clawbot_SuperGroup`) | Ops hub | Medium | OPLOG only |
| Inbox Email (topic) | Digest | Medium | Summaries only, no raw email bodies |
| Work Email (topic) | Digest | Low | Summaries only, no raw email bodies |
| Telegram Digest (topic) | Digest | Low | Digest summaries only |
| Signals (topic) | Alert | High, narrow | Compact alert record |
| Family (separate group) | Family | Low, mention-only | Never without explicit approval |
| Knowledgebase (supergroup topic, id=232) | Knowledge | Low | Question → search; explicit save content → auto-structured `raw/**` + `wiki/research/**` + optional canonical enrichment |
| Ideas (supergroup topic, id=639) | Idea capture | Low | Light-curated `raw/**` + `wiki/research/**` immediately; promoted to Knowledgebase later for deeper enrichment |
| Sandbox / Lab | Testing | Free | Never production memory |

### Trigger rules

- All groups require `@mention` or direct reply by default.
- The ops supergroup hub is the only surface where mention-free operation is allowed
  (configured per topic ID, not by name).
- DMs from non-allowlisted users are rejected before the agent runs.

### What the bot reads vs. what it acts on

The bot does **not** read the full message stream by default in any group.
In the ops supergroup, it reads only what is directed at it (mention/reply)
unless a specific topic workflow explicitly enables whole-stream reading for a
bounded task (e.g., a timed digest window).

---

## Project Skills Layer

### Why project-specific skills exist

Built-in Codex tools are not enough to preserve deployment-specific muscle memory.
This repository now keeps a small catalog of project-owned skills for recurring
maintenance flows that have sharp edges or server-specific gotchas.

The goal is simple:

- make fragile operational knowledge reusable
- keep the "correct" procedure close to the repo
- reduce re-discovery during future deploy/debug sessions

### Canonical locations

- Repo source of truth: `skills/`
- User-installed runtime copy: `~/.codex/skills/`
- Human-facing catalog and expansion plan: `docs/archive/openclaw/14-codex-skills.md`

### Current custom skill

| Skill | Purpose |
|-------|---------|
| `openclaw-cron-maintenance` | Safe workflow for OpenClaw cron-store maintenance when `openclaw cron list/add/remove` is unreliable; patch `jobs.json`, restart gateway, validate health |

### Scope boundary

These project skills are for **repeatable local/server workflows**, not for product
logic. The actual runtime behavior still lives in normal repo code
(`sync-openclaw-cron-jobs.sh`, deploy scripts, bridges, prompts, policies). Skills
only codify how an operator agent should work with that codebase safely.

---

## Memory Architecture

### Memory classes

| Class | What | Sources | Retention | RAG | Obsidian |
|-------|------|---------|-----------|-----|---------|
| `LIVE` | Current conversation, temp task state | Any | Session only | No | No |
| `OPLOG` | Task status, approval outcomes | Ops topics, tools | 14–30 days | No | No |
| `RAW` | Redacted decisions, `#canon` threads, candidate ideas | DM explicit, ops decisions, Ideas | 30–90 days | Only redacted decisions | No |
| `DERIVED` | Summaries, digests, extracted tasks | Work Email, Digest, Signals | 30–180 days | Selective | Optional |
| `CURATED` | Structured durable knowledge | Knowledgebase topic (auto-structured by bot), promoted Ideas | Durable | Yes | Yes |
| `LONG_TERM` | Stable user facts, preferences | DM explicit, Knowledge explicit | Durable until revoked | Yes | Optional |

### Strict rules

- Telegram messages → `LIVE` by default. Not persisted unless promoted.
- Inbox email full bodies → never indexed. Compact summaries and metadata only.
- Work email full bodies → never indexed. Compact summaries only.
- Family content → `LIVE` only. Long-term requires explicit approval.
- Credentials, tokens, keys → never stored in memory, RAG, or Obsidian.
- Sandbox → excluded from all production memory paths.

### Session startup

1. Load `MEMORY.md` (~2KB, always).
2. Load `memory/INDEX.md` → find today's and yesterday's daily files.
3. Load today's daily file (if exists and topic is relevant).
4. Load yesterday's daily file (only if today has <3 entries).
5. Check LightRAG health: `GET http://lightrag:9621/health` (non-blocking).
6. Note unresolved items from previous sessions.
7. Confirm readiness briefly — no verbose preamble.

Cold-start limit: ~5–8KB context. Do not load `raw/` at startup.

---

## LightRAG Integration

### What goes in

Only structured, curated content:

- **Telegram Digest derived notes** — scored, summarised digests written by `persistence.py`
  to `/app/obsidian/Telegram Digest/Derived/YYYY-MM-DD/` → uploaded via `ingest:rag:queue`
- **Telegram Digest curated notes** — high-signal items extracted by OmniRoute medium;
  written to `/app/obsidian/Telegram Digest/Curated/` → uploaded via `ingest:rag:queue`
- Obsidian vault markdown (synced from Mac via Syncthing) — picked up by the 30-min cron ingest script
- Explicit saves from Knowledgebase or Ideas go through `wiki-import`; only the resulting wiki pages are enqueued to LightRAG
- `CURATED` knowledge items with required fields
- Redacted root-cause / `#canon` decision records

### What does NOT go in

- Raw Telegram chat or full post text
- Full email bodies
- Operational logs
- Credentials or sensitive data
- Sandbox content

### Ingestion paths

Two paths feed LightRAG; neither blocks the main pipeline:

| Path | Trigger | Latency |
|------|---------|---------|
| **Integration bus** (`ingest:rag:queue`) | `persistence.py` XADD after each digest | seconds (RAG consumer loop) |
| **Cron ingest script** | `/opt/lightrag/scripts/lightrag-ingest.sh` every 30 min | up to 30 min |

The bus path covers fresh digest notes immediately. The cron path covers the full
Obsidian vault (reading notes, project wiki, personal knowledge) on its own schedule.

### Integration bus → LightRAG flow

```
persistence.py
  └── _enqueue_lightrag_uploads([derived_path, curated_paths...])
        └── XADD ingest:rag:queue {source, file_path, file_name}
              ↓ async
        cron-bridge rag-consumer thread
              └── _upload_file_to_lightrag_sync(file_path, file_name)
                    ├── httpx POST lightrag:9621/documents/upload  → 200 OK
                    └── httpx POST lightrag:9621/documents/reprocess_failed
```

Fallback: if `REDIS_URL` is unset or Redis unreachable, `persistence.py` falls back to
calling LightRAG directly (original synchronous path).

### Query

```
POST http://lightrag:9621/query
{"query": "...", "mode": "hybrid"}
```

Results are `DERIVED`-level — not authoritative for current system state.
Use live checks (`docker ps`, `curl`) for current state, not LightRAG.

### WebUI

LightRAG has a built-in WebUI. Access via SSH tunnel:

```bash
ssh -i ~/.ssh/id_rsa -L 9621:127.0.0.1:8020 deploy@<server-host> -N
# → http://127.0.0.1:9621
```

The UI shows the knowledge graph, documents list, and allows ad-hoc queries.

### URL note

Use DNS alias `lightrag` (not container name `lightrag-lightrag-1`):

```
http://lightrag:9621/health   ✓
http://lightrag-lightrag-1:9621/health   ✗  (blocked by SSRF policy)
```

---

## Approval Gates

These actions always require explicit user confirmation, regardless of surface:

- Destructive operations (delete, drop, rm, wipe)
- External sends (email replies, Telegram posts to external chats)
- Deploys, restarts, config changes
- Purchases or irreversible commitments
- Credential or token changes
- High-sensitivity memory writes (sensitivity ≥ 0.70)
- Any family long-term memory
- Cross-domain content movement (work ↔ family ↔ personal)

Scheduled digests and summaries within Telegram do not require approval
if they only summarize and publish within the configured topic.

---

## Anti-Patterns to Avoid

- Treating Telegram as a memory stream (it is a communication channel).
- Posting full email bodies into Telegram topics or memory.
- Mixing family, work, and ops contexts in one surface.
- Using LightRAG as a source of truth for current system state.
- Making the bot full admin in groups.
- Storing secrets, logs, or raw code dumps in Obsidian or RAG.
- Writing memory from Sandbox / Lab.
- Calling `smart` for trivial classification tasks.
- Proxying the main user response through OmniRoute when Codex is available.

---

## Telegram Channel Digest

### Overview

A scheduled service reads 150–200 Telegram channels Denis subscribes to,
scores posts by folder priority and pinned-dialog status, summarizes via
OmniRoute `medium`, and posts a compact digest to the `telegram-digest`
topic in `Benka_Clawbot_SuperGroup` — 5× daily (08:00, 11:00, 14:00, 17:00, 21:00 МСК).

### Architecture

```
Host cron (08:00/11:00/14:00/17:00/21:00 МСК)
  └── /opt/telethon-digest/trigger-digest.sh
        └── HTTP POST /trigger → telethon-digest-cron-bridge
              └── XADD ingest:jobs:telegram → HTTP 202 (immediate)

                        ↓ async (Redis Streams)

              telethon-digest-cron-bridge (consumer loop, same container)
                    └── python digest_worker.py --now
                          └── telethon-digest container context (Python, async)
              ├── reader.py       — Telethon MTProto, batched reads (10/batch), FloodWait-safe
              ├── scorer.py       — Pass 1: folder_priority × pin_boost; top-30 → LLM
              ├── link_builder.py — t.me deep links per post
              ├── summarizer.py   — OmniRoute medium, structured digest prompts
              ├── pulse.py        — pulse ranking: buckets, diversity, novelty, interest profile
              └── poster.py       — Bot API → telegram-digest topic, split at 4000 chars
```

**Integration bus** (`integration-bus-redis`, Redis 7 Alpine):

```
                            REDIS STREAMS (integration-bus-redis)
                       ┌──────────────────────────────────────────────┐
 [Producers]           │                                              │  [Workers]
                       │  ingest:jobs:telegram ───────────────────────┼──► cron-bridge consumer loop
 cron /trigger ────────┤    {run_id, digest_type, config_ref}        │    → digest_worker.py --now
                       │                                              │
                       │  ingest:jobs:email ──────────────────────────┼──► agentmail-email-bridge
 email-trigger ────────┤    {run_id, job_type, digest_type}          │    → AgentMail HTTP bridge
                       │                                              │    → poll labels / derived events / scheduled digest post
                       │  ingest:jobs:signals ────────────────────────┼──► signals-bridge
 signals scheduler ────┤    {run_id, ruleset_id, source_id?}         │    → AgentMail + Telethon
                       │                                              │    → deterministic filter
                       │                                              │    → OpenClaw/OpenAI → OmniRoute → DeepSeek
                       │                                              │    → signals topic + derived events
                       │  ingest:events:email ────────────────────────┼──► scheduled digest recap builder
 email-poller ─────────┤    (derived inbox-email events, 7d)         │
                       │  ingest:events:signals ──────────────────────┼──► future recap / analytics / tuning
 signals worker ───────┤    (derived signal events, 14d)             │
                       │  ingest:events:telegram ─────────────────────┼──► telethon-event-listener (future)
 Telethon listener ────┤    (individual messages, real-time)         │    → enrich → classify → alert/rag
                       │                                              │
                       │  ingest:rag:queue ───────────────────────────┼──► cron-bridge rag-consumer
 persistence.py ───────┤    {source, file_path, file_name}           │    → httpx /documents/upload
                       │                                              │    + /reprocess_failed
                       │  dlq:failed ─────────────────────────────────┼──► monitoring / retry
                       └──────────────────────────────────────────────┘

Stream naming:
- `ingest:jobs:{source}` — batch job triggers (telegram, email)
- `ingest:events:{source}` — derived or real-time item events (signals, private groups)
- `ingest:rag:queue` — items queued for LightRAG indexing
- `dlq:failed` — dead letter queue (all sources)

Container `telethon-digest-cron-bridge` shares the `openclaw_default` network, mounts the Docker
socket so it can exec OpenClaw/OpenAI requests inside the live gateway, and has direct access to
`http://omniroute:20129/v1` plus `http://integration-bus-redis:6379`.

The scheduler of record is `/etc/cron.d/telethon-digest`. Host cron evaluates
the schedule in UTC and passes the intended Moscow slot as script arguments:

- `05:00 UTC` → `08:00 MSK` morning
- `08:00 UTC` → `11:00 MSK` interval
- `11:00 UTC` → `14:00 MSK` interval
- `14:00 UTC` → `17:00 MSK` interval
- `18:00 UTC` → `21:00 MSK` editorial

The old OpenClaw Telethon agent-turn cron jobs are disabled on the live server.
After the 2026.5.x upgrade they could report a successful cron run while the
lightweight agent context refused the shell command needed to call the bridge.
Host cron keeps the trigger path deterministic and avoids spending model tokens
just to enqueue a digest job.

### Rate limit handling

- Channels read in batches of 10 with 1.5 s pause between batches.
- Telethon auto-retries on `FloodWaitError` internally.
- Full read of 200 channels: ~30–60 s (well within the longest regular interval).

### Integration bus status

**Implemented:**

| Stream | Status | Worker |
|--------|--------|--------|
| `ingest:jobs:telegram` | ✅ Live | `digest-consumer` thread → `digest_worker.py` |
| `ingest:jobs:email` | ✅ Live | `agentmail-email-bridge` trigger queue for poll/digest jobs |
| `ingest:jobs:email:work` | ✅ Live | `agentmail-work-email-bridge` trigger queue for work poll/digest jobs |
| `ingest:jobs:signals` | ✅ Live artifact | `signals-bridge` internal 5-minute scheduler + worker queue |
| `ingest:events:email` | ✅ Live | derived inbox-event buffer for scheduled recaps |
| `ingest:events:email:work` | ✅ Live | derived work-email event buffer for work digest/state tracking |
| `ingest:events:signals` | ✅ Live artifact | 14-day derived signal log for dedup / future analytics |
| `ingest:rag:queue` | ✅ Live | `rag-consumer` thread → LightRAG `/documents/upload` |
| `ingest:events:telegram` | Planned | real-time Telethon listener (v2) |

The digest path still runs two consumer threads in the same `telethon-digest-cron-bridge`
container; `signals-bridge` is a separate standalone worker with its own internal scheduler.
`integration-bus-redis` (Redis 7 Alpine) is a standalone project at `/opt/integration-bus/`.

### Telegram Digest source mix

`telethon-digest/scorer.py` keeps the source pool broad before LLM summarization:

- `news` remains in the read allowlist and Tier A scoring, but has a default content-mix target of 30% and hard cap of 35% during selection.
- The cap is enforced across the coverage, primary, secondary, and final fallback selection passes, so a noisy folder cannot refill the issue after folder diversity caps have run.
- The cap is elastic: if other allowlisted folders do not have enough scored candidates for the slot, `news` can exceed 35% to keep the digest populated.
- Runtime override lives in `/opt/telethon-digest/config.json` under `content_mix.capped_folders`; tracked `config.example.json` documents the shape.

### `Пульс дня` ranking

`Пульс дня` now behaves like a compact editor, not a raw repetition counter.

- Input: strong scored Telegram posts after dedup
- Candidate generation: sanitized LLM `themes`, then local extraction, then fallback storyline lines
- Ranking factors:
  - cross-channel / repeated-signal strength
  - bucket fit to Denis's interests
  - novelty vs recently published pulse lines
  - line quality (prefer storyline/theme over source-like labels)
  - diversity constraints so one category does not dominate the block
- Output rule: pick one strong line per bucket first, then fill the remaining slots with the next
  best lines, capped per bucket

The interest profile lives in `/app/state/pulse-profile.json` and is updated after each digest from
the current strong-post pool. It stores bucket momentum, learned terms, and recent pulse signatures.
This makes the digest adapt over time and keeps the ranking layer reusable for future AgentMail
recap selection.

**Backlog (v2):**

- `ingest:events:telegram` — real-time Telethon listener for private groups and signal channels
- move from 5-minute batch polling toward optional near-real-time per-item signal routing where needed
- Per-item pipeline: individual posts as events (vs. current whole-digest-as-job)
- Monitoring/metrics for Redis streams (XLEN, DLQ alerts)

## Signals Bridge

`signals-bridge` is a separate Python service for narrow, time-sensitive signals such as trading
alerts. It now shares the same model reserve order as the digest path: OpenClaw/OpenAI first,
OmniRoute light second, DeepSeek final, then local deterministic rendering.

### Architecture

```text
signals-bridge (every 5 minutes, internal scheduler)
  └── XADD ingest:jobs:signals → HTTP 202 / internal enqueue

                    ↓ async (Redis Streams)

        signals-bridge worker loop
              ├── email source:
              │     AgentMail HTTP API → sender / username prefilter
              ├── telegram source:
              │     Telethon user session → chat / author / hashtag prefilter
              ├── deterministic rules first
              ├── OpenClaw/OpenAI batch prompt for matched candidates only
              ├── fallback to cheap OmniRoute `light`, then DeepSeek
              │     max_tokens kept low; local fallback if all model routes are unavailable
              └── Telegram topic `signals` + XADD ingest:events:signals
                    Telegram items carry source links; email items keep a compact excerpt
```

### Runtime guarantees

- Poll cadence is every 5 minutes end-to-end; there is no 30-second signal loop.
- `signals-bridge` uses an internal Python scheduler and does **not** create OpenClaw Cron Jobs.
- Public artifact examples stay generic; real local rules are expected to be loaded from separate
  JSON files via `rule_files`.
- Source reads stay inside the bridge: AgentMail HTTP API for email, Telethon for Telegram.
- LLM usage is deliberately constrained:
  - OpenClaw/OpenAI first, then `OmniRoute light`, then DeepSeek
  - short JSON-only prompt
  - low `max_tokens`
  - local rule-based fallback if all model routes are unavailable
- `ingest:events:signals` stores only derived summaries + metadata for 14 days; no raw email bodies
  or full Telegram dumps are persisted.

### V1 rule shape

- Email: exact sender match `noreply@tradingview.com` plus TradingView username allowlist
- Telegram group 1: exact hashtag rule such as `#si`
- Telegram group 2: exact author id plus FX/currency keyword set
- Cross-source duplicates are **not** collapsed in V1; email and Telegram hits stay as separate items
  inside the same 5-minute mini-batch

## AgentMail Inbox Email

A separate bridge polls the personal AgentMail inbox every 5 minutes through an
internal scheduler inside the AgentMail HTTP bridge and publishes scheduled recaps to
the `inbox-email` topic. Scheduled recaps run at `08:00`, `13:00`, `16:00`, and `20:00`
Moscow time and are rendered directly from the mailbox window so counts, senders, and
subjects reflect the real inbox state. The bridge is a standalone Docker service at
`/opt/agentmail-email`, separate from `telethon-digest-cron-bridge`.

The `work-email` Telegram topic is now backed by a second live bridge at `/opt/agentmail-work-email`.
It reuses the same shared codebase, but runs with isolated Redis streams, labels, status key, Docker
container, and secret env.

### Architecture

```text
Host cron (08:00/13:00/16:00/20:00 МСК)
  └── /opt/agentmail-email/trigger-email-digest.sh
        └── HTTP POST /trigger → agentmail-email-bridge
              └── XADD ingest:jobs:email → HTTP 202 (immediate)

agentmail-email-bridge internal scheduler (every 5m)
  └── XADD ingest:jobs:email → internal poll enqueue

                        ↓ async (Redis Streams)

              agentmail-email-bridge (consumer loop)
                    ├── poll job:
                    │     AgentMail HTTP API → thread snapshots
                    │     → deterministic prefilter
                    │     → shared OpenClaw JSON-only classifier (only for candidate threads)
                    │     → XADD ingest:events:email (derived events)
                    └── digest job:
                          AgentMail HTTP API → mailbox window
                          → direct digest render
                          → Telegram topic `inbox-email`
                          → label underlying emails as `benka/digested`
```

### Runtime guarantees

- Mail access happens inside the Python bridge via the AgentMail HTTP API; OpenClaw sees only
  prepared thread snapshots or derived events.
- Internal labels `benka/polled`, `benka/low-signal`, and `benka/digested` are used for dedup
  and lifecycle tracking without touching read-state.
- `ingest:events:email` stores only derived poll summaries and metadata with 7-day retention; raw
  bodies and attachments are excluded, and scheduled digests no longer depend on Telegram history.
- The 5-minute poll is now internal to the bridge, which removes the OpenClaw cron-enqueue token cost
  and lets obvious low-signal / empty windows skip the LLM entirely.
- Scheduled digest delivery is host-cron driven rather than OpenClaw agent-turn Cron driven; this
  avoids false-positive OpenClaw cron runs when the cron context has no shell/exec tool.
- Manual recovery/backfill uses `lookback_minutes` on `/trigger`, which widens the poll or digest
  window without changing the standalone bridge architecture.
- Live validation on `2026-04-13`: the bridge self-enqueued a poll via the internal scheduler,
  the poll finished with `exit_code=0`, and `/status` exposed prefilter counters directly in the
  final `poll summary`.

## AgentMail Work Email

The work-email runtime mirrors the same standalone-bridge architecture, but targets
`workmail.denny@agentmail.to`, listens on `127.0.0.1:8094`, and publishes into Telegram topic
`work-email`. It keeps the same mailbox-window rendering path, but additionally resolves the
original sender from forwarded-message headers for work mail only. The rendered digest now keeps
the top-level storyline recap and then splits the same window into explicit `Нужно реагировать`
versus `Для информации` sections.

### Work runtime specifics

- internal poll scheduler every 5 minutes
- scheduled digest slots: `08:30`, `10:00`, `11:30`, `13:00`, `14:30`, `16:00`, `17:30`, `19:00`
  Europe/Moscow, triggered by `/etc/cron.d/agentmail-work-email`
- Redis jobs stream: `ingest:jobs:email:work`
- Redis events stream: `ingest:events:email:work`
- consumer group: `email-workers-work`
- labels: `workmail/polled`, `workmail/low-signal`, `workmail/digested`
- forwarded sender lookup from inline header blocks (`От:` / `From:`) is enabled only in this work
  runtime, so forwarded messages can be grouped under the real author instead of the forwarding
  account

### Live validation

- on `2026-04-13`, the work bridge deployed successfully to `/opt/agentmail-work-email`
- internal scheduler poll finished with `exit_code=0`, scanned `10` threads, and emitted `6`
  derived events into `ingest:events:email:work`
- manual `digest interval lookback=240` finished with `exit_code=0` on `127.0.0.1:8094`
- on `2026-04-14`, the bridge was redeployed with work-only forwarded-sender resolution; post-deploy
  `GET /health` / `GET /status` returned `last_exit_code=0`
- on `2026-04-14`, a live mailbox-window probe inside the bridge resolved forwarded CNews mail to
  `Elena Zabrodina`, confirming that work-email grouping now uses the underlying author when the
  inline forwarded headers are present
- on `2026-05-29`, the pollers were healthy but OpenClaw Cron digest runs were false-positive `ok`
  without bridge execution; both AgentMail digest schedules moved to host cron direct trigger, with
  legacy OpenClaw Cron AgentMail jobs disabled.

### Scoring

```
score = folder_priority × (pin_boost if pinned else 1)
```

Posts below `min_score` (default: 2) are dropped.
Top 30 by score → LLM. Rest discarded.

### Memory / state

- `state.json` (Docker volume `telethon-state`): per-channel `last_seen_msg_id` watermarks.
- `last_run` timestamp drives the read window for the next cycle.
- Session file (Docker volume `telethon-sessions`): Telethon user session.
- Read scope is application-enforced: `read_only=true`, explicit folder/channel allowlists,
  and `read_broadcast_channels_only=true` by default. Telegram user sessions do not provide
  server-side API scopes, so the service fails closed if the allowlist selects no channels.

### Setup steps (one-time)

Current status: completed and running on the server through OpenClaw Cron Jobs.

```bash
# 0. Work from the standalone project directory
cd /opt/telethon-digest
# 1. Fill in /opt/telethon-digest/telethon.env
#    Local gitignored source: secrets/telethon-digest/telethon.env
# 2. Authorize session
docker compose run --rm telethon-digest python auth.py
# 3. Sync folder/channel list from Telegram
docker compose run --rm telethon-digest python sync_channels.py
# 4. Manual smoke test
docker compose run --rm telethon-digest python digest_worker.py --now
# 5. Sync OpenClaw Cron Jobs
/opt/telethon-digest/sync-openclaw-cron-jobs.sh
```

### Digest format (Telegram HTML)

```html
📊 <b>Дайджест</b> | 11:00–14:00 (143 каналов, 12 постов)

📁 <b>VIP</b>
• <b>КаналA</b>: Краткое резюме события. (<a href="https://t.me/...">→</a>)
• <b>КаналB</b> 📌: Закреплено — ключевая новость.

📁 <b>Finance</b>
• <b>КаналC</b>: ...

<i>medium · delegated · 5% · simple</i>
```
