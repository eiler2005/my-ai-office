# Memory Index

> [!NOTE]
> **Predecessor-era prompt artifact.** This file configured the retired OpenClaw runtime, which
> mounted `workspace/` into the agent. **Hermes does not**: the live prompt surface is each profile's
> `SOUL.md` plus its installed skills, and nothing here is read at runtime.
>
> It is kept as a behavioural record — some rules here were carried into
> [`skills/`](../skills/), and some were not. It stays in Russian for the same reason the archive
> does. See [CONTRIBUTING.md](../CONTRIBUTING.md#language).

Master catalog of the memory system. Read this first at boot — it tells you where everything is.

## Layer Map

```
LIVE > RAW > DERIVED
```

| Layer   | Trust rank | Answers                          | Location                          |
|---------|-----------|----------------------------------|-----------------------------------|
| Live    | 1 (highest) | "Is X running right now?"      | docker ps / curl / logs only      |
| Raw     | 2           | "Why did we decide X?"         | workspace/raw/YYYY-MM-DD-{topic}  |
| Derived | 3           | "What's worth remembering?"    | MEMORY.md, memory/INDEX.md        |

**Critical rule:** current-state questions → ALWAYS live-check. Never answer from memory.

---

## Core Templates (always loaded)

| File | Purpose | Load at boot? |
|------|---------|---------------|
| `MEMORY.md` | Long-term curated facts about Denis, projects, preferences | YES |
| `USER.md` | Denis's full profile: role, thinking style, family, comms | YES |
| `IDENTITY.md` | Бенька's persona | YES |
| `SOUL.md` | Anti-sycophancy protocol, values | YES |
| `AGENTS.md` | Mission, boot protocol, memory rules, forbidden behaviors | YES |
| `BOOT.md` | Session startup checklist | YES |
| `TOOLS.md` | Available tools including lightrag_query | YES |
| `HEARTBEAT.md` | Periodic task instruction | on heartbeat only |
| `TELEGRAM_POLICY.md` | Telegram surface roles, permissions assumptions, memory/RAG gates | when handling Telegram policy/routing |

---

## Daily Notes (load on-demand)

Location: `memory/YYYY-MM-DD[-topic].md`
Index: `memory/INDEX.md`

**Load policy:**
- Today's daily note → load if topic arises
- Yesterday's daily note → load only if today has <3 entries
- Older files → use lightrag_query instead of reading directly
- Archive → `memory/archive/` (do not load at boot)

---

## Raw Layer (load only on explicit recall)

Location: `raw/YYYY-MM-DD-{topic}.md`

**Never load at boot.** Load only when:
- User asks "why did we decide X"
- User asks about a specific past decision or root cause
- No relevant result from lightrag_query

**Promotion criteria (thread → raw):**
A thread goes to raw ONLY if it contains at least one of:
- Decision with explicit reasoning ("we chose X because Y")
- Root cause of a real failure
- New infrastructure entity (new service, tool, config key)
- Explicitly tagged `#canon`
- Rejected option with context and when to revisit

Before writing to raw: redaction pass (remove IPs, tokens, certs, credentials).

---

## LightRAG (knowledge graph brain)

Endpoint: `http://lightrag:9621`
Health: `GET /health`
Query: `POST /query` → `{"query": "...", "mode": "hybrid"}`

Use instead of reading archives directly. One API call ~2KB vs scanning MB of history.
Results are Derived-tier — not canonical current-state truth.

---

## Navigation Quick Reference

```
"What is Denis's background?"        → MEMORY.md (already in context)
"What did we discuss yesterday?"     → memory/INDEX.md → load that daily file
"Why did we choose X over Y?"        → raw/ → if not found, lightrag_query
"Is Docker service X running?"       → LIVE CHECK (docker ps, curl /health)
"Find notes about Kafka"             → lightrag_query("Kafka decisions Denis")
"What changed in the last session?"  → memory/INDEX.md → today's daily note
```
