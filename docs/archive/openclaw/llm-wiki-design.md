# LLM-Wiki: Personal Knowledge Base

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

> Current source of truth:
> `docs/archive/openclaw/10-memory-architecture.md`,
> `docs/archive/openclaw/15-llm-wiki-query-flow.md`,
> `docs/archive/openclaw/17-knowledge-management.md`,
> `docs/archive/openclaw/19-llm-wiki-memory-explained.md`,
> `docs/archive/openclaw/20-llm-project-orientation.md`,
> `artifacts/llm-wiki/SCHEMA.md`.

## What This Is

A structured, LLM-maintained personal wiki that replaces the previous ad-hoc Obsidian vault.
Instead of a flat collection of unlinked notes ingested blindly into LightRAG, the wiki is a
**persistent, accumulating artifact** — cross-linked, typed, and actively maintained by the bot.

Inspired by:
- ["LLM-Wiki: Personal Knowledge Base with LLM"](https://telegra.ph/LLM-Wiki--personalnaya-baza-znanij-s-LLM-04-07)
- [Graphify](https://github.com/safishamsi/graphify) — relationship confidence tagging, hub nodes
- Vannevar Bush's Memex — associative trails, not just search

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  INPUTS                                                          │
│  Obsidian Mac + Web Clipper  │  Last30Days  │  Manual bot cmd   │
│           ↓ Syncthing              ↓ writes        ↓            │
└───────────┼────────────────────────┼───────────────┼────────────┘
            ▼                        ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│  /opt/obsidian-vault/                                           │
│  ├── raw/          immutable sources (LLM reads, never writes)  │
│  │   ├── articles/     Obsidian Web Clipper clips               │
│  │   ├── signals/      Last30Days daily summaries               │
│  │   └── documents/    PDFs, transcripts                        │
│  └── wiki/         LLM-maintained, cross-linked pages           │
│      ├── SCHEMA.md      bot manual: conventions + workflows     │
│      ├── INDEX.md       master catalog (auto-updated by bot)    │
│      ├── LOG.md         append-only operation log               │
│      ├── concepts/      ideas, frameworks, patterns             │
│      ├── entities/      tools, people, projects, orgs           │
│      ├── decisions/     architecture decision records (ADRs)    │
│      ├── sessions/      daily operational notes                 │
│      └── research/      deep dives, comparisons                 │
└────────────────────────┬────────────────────────────────────────┘
                         │ 30-min cron: lightrag-ingest.sh
                         ▼
              LightRAG (semantic layer on top of wiki)
              NetworkX graph + NanoVectorDB
              Nodes = wiki pages │ Edges = [[wikilinks]] + semantic
                         │
                         ▼
              OpenClaw Bot
              wiki_read() │ wiki_ingest() │ wiki_lint() │ lightrag_query()
```

---

## Three-Layer Principle

| Layer | Owner | Purpose |
|-------|-------|---------|
| `raw/` | Human drops, LLM reads only | Immutable original sources |
| `wiki/` | LLM owns entirely | Synthesized, cross-linked knowledge |
| `SCHEMA.md` | Human writes, LLM follows | Conventions, templates, workflows |

---

## Wiki Page Types

| Type | Folder | Purpose |
|------|--------|---------|
| entity | `entities/` | Named things: tools, people, projects, orgs, services |
| concept | `concepts/` | Ideas, frameworks, patterns, technical concepts |
| decision | `decisions/` | ADRs — why X over Y |
| session | `sessions/` | Daily operational notes (bot-written) |
| research | `research/` | Deep dives, comparisons, syntheses |

Templates for all types: `artifacts/llm-wiki/templates/`

---

## Relationship Tagging (Graphify-inspired)

Every claim in a **Connections** section must carry a confidence marker:

| Marker | Meaning |
|--------|---------|
| _(unmarked)_ | CONFIRMED — verified from a primary source |
| `(INFERRED)` | Reasonable conclusion, not directly stated |
| `(AMBIGUOUS)` | Conflicting evidence, needs resolution |

Frontmatter `confidence` field reflects overall page confidence.

**Hub Nodes:** Pages with 5+ incoming `[[wikilinks]]` from other pages → `hub: true` in
frontmatter. These are the most load-bearing concepts. Visible as large nodes in Obsidian
Graph View.

---

## Key Operations

### Ingest
1. LLM reads the source.
2. Identifies 3–7 key concepts, entities, decisions.
3. Creates or updates wiki pages, adding cross-links.
4. Updates INDEX.md and appends to LOG.md.
5. LightRAG reindexes on next 30-min cron.

One source typically touches 3–10 pages.

### Query
1. Read INDEX.md for page categories.
2. `lightrag_query(question, mode="hybrid")` for semantic+graph retrieval.
3. `wiki_read(page_path)` to read 3–5 relevant pages directly.
4. Synthesize answer citing pages.
5. Save synthesis as `research/` page if valuable.

### Lint (weekly)
Checks: orphaned pages, stale pages (90+ days), missing links, contradictions,
hub candidates, empty sections. Report sent via Telegram.

---

## Auto-Ingest from Last30Days

Every day at 07:00 MSK after the digest posts to Telegram, `signals-bridge` writes:

```
/opt/obsidian-vault/raw/signals/YYYY-MM-DD.md
```

Format:
```markdown
---
type: signal-digest
date: YYYY-MM-DD
source: last30days
top_themes:
  - Theme One
  - Theme Two
---

# Last30Days Signal: YYYY-MM-DD

## Top Themes
1. **Theme One** — 5 HN threads, 3 Reddit posts...
```

Bot detects the new file → runs ingest → top themes become or update concept pages.

---

## Bot Tools (to add to workspace/TOOLS.md)

```
wiki_read(page_path)
  Read a wiki page by path (relative to wiki/).
  Example: wiki_read("entities/lightrag.md")

wiki_ingest(source)
  Ingest a new source (URL or raw text).
  Runs full workflow: read → pages → INDEX + LOG.

wiki_lint()
  Run health check. Returns lint report.

lightrag_query(question, mode="hybrid")
  Semantic + graph search across the wiki.
  mode: hybrid | local | global
```

---

## Integration with Existing Infrastructure

### LightRAG
- Change ingest source path from old unstructured vault to `wiki/**/*.md` + `raw/**/*.md`
- Graph nodes = wiki pages; graph edges = `[[wikilinks]]` extracted by LightRAG + semantic similarity
- Query endpoint unchanged: `POST http://lightrag:9621/query`

### Obsidian (Mac + Syncthing)
- Wiki lives at `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/DenisJournals/wiki/`
- Syncthing mirrors to `/opt/obsidian-vault/wiki/` on server
- `[[wikilinks]]` are native Obsidian format — Graph View works automatically
- Obsidian Web Clipper saves clips to `raw/articles/`
- Obsidian Dataview can query frontmatter

### signals-bridge
- After posting Last30Days digest to Telegram, add: `write_signal_digest(date, top_themes, obsidian_vault_path)`
- Writes `raw/signals/YYYY-MM-DD.md`

---

## Migration (Fresh Start)

```bash
# 1. Stop LightRAG
ssh -i ~/.ssh/id_rsa deploy@<server> "cd /opt/lightrag && docker compose stop"

# 2. Clear old LightRAG graph data
ssh -i ~/.ssh/id_rsa deploy@<server> "
  rm -rf /opt/lightrag/data/graph_storage* &&
  rm -rf /opt/lightrag/data/vdb_storage* &&
  rm -rf /opt/lightrag/data/kv_storage*
"

# 3. Clear old Obsidian vault content
ssh -i ~/.ssh/id_rsa deploy@<server> "rm -rf /opt/obsidian-vault/*"

# 4. Create new directory structure
ssh -i ~/.ssh/id_rsa deploy@<server> "
  mkdir -p /opt/obsidian-vault/wiki/{concepts,entities,decisions,sessions,research} &&
  mkdir -p /opt/obsidian-vault/raw/{articles,signals,documents}
"

# 5. Deploy wiki scaffold from this repo (scripts/deploy-llm-wiki.sh)

# 6. Restart LightRAG
ssh -i ~/.ssh/id_rsa deploy@<server> "cd /opt/lightrag && docker compose start"

# 7. Run bootstrap ingest (see Bootstrap Checklist in artifacts/llm-wiki/INDEX.md)
```

---

## Files in This Repository

### New files (created by this plan)
| File | Purpose |
|------|---------|
| `docs/archive/openclaw/llm-wiki-design.md` | This document |
| `artifacts/llm-wiki/SCHEMA.md` | Wiki schema + bot manual → deploy to server |
| `artifacts/llm-wiki/INDEX.md` | Index template with bootstrap checklist |
| `artifacts/llm-wiki/LOG.md` | Log template |
| `artifacts/llm-wiki/templates/entity.md` | Entity page template |
| `artifacts/llm-wiki/templates/concept.md` | Concept page template |
| `artifacts/llm-wiki/templates/decision.md` | Decision page template |
| `artifacts/llm-wiki/templates/session.md` | Session page template |
| `artifacts/llm-wiki/templates/research.md` | Research page template |

### Files to create during implementation
| File | Purpose |
|------|---------|
| `scripts/deploy-llm-wiki.sh` | Deploy scaffold to server |
| `scripts/setup-llm-wiki.sh` | Full migration: clear + deploy + bootstrap |

### Files to modify during implementation
| File | Change |
|------|--------|
| `workspace/TOOLS.md` | Add `wiki_read`, `wiki_ingest`, `wiki_lint` |
| `workspace/MEMORY.md` | Boot algorithm: read `wiki/INDEX.md` on startup |
| `scripts/lightrag-ingest.sh` | Change source paths to `wiki/` + `raw/` |
| `artifacts/signals-bridge/last30days_runner.py` | Add `write_signal_digest()` after Telegram post |
| `CHANGELOG.md` | Document LLM-Wiki rollout |
| `README.md` | Add LLM-Wiki to architecture section |
| `docs/archive/openclaw/07-architecture-and-security.md` | Add wiki layer to memory architecture |
| `docs/archive/openclaw/11-lightrag-setup.md` | Update ingest paths, add wiki context |

---

## Verification

After implementation:

1. `ssh server "find /opt/obsidian-vault/wiki -name '*.md' | head -20"` — structure exists
2. `ssh server "bash /opt/lightrag/scripts/lightrag-ingest.sh"` — reindex succeeds
3. Ask bot: _"What is LightRAG and why did we choose it?"_ → answer cites `entities/lightrag.md` + `decisions/why-lightrag.md`
4. Ask bot: _"How are OpenClaw and Obsidian connected?"_ → traces path via wiki links
5. Drop article URL to bot → verify INDEX.md updated, LOG.md appended, 2–3 pages created
6. `wiki_lint()` → clean report, 0 false positives
7. Edit wiki page on Mac → appears on server within 5 min (Syncthing)
8. Check `raw/signals/` the morning after 07:00 MSK for signal digest file

---

## Implementation Order (for another LM)

Read `artifacts/llm-wiki/SCHEMA.md` first — it's the most important file.

1. Create `scripts/deploy-llm-wiki.sh` and `scripts/setup-llm-wiki.sh`
2. Update `workspace/TOOLS.md` with 3 new tools
3. Update `workspace/MEMORY.md` boot algorithm to read `wiki/INDEX.md`
4. Update `scripts/lightrag-ingest.sh` source paths to `wiki/` + `raw/`
5. Modify `artifacts/signals-bridge/last30days_runner.py` — add `write_signal_digest()` after Telegram post (env var `LAST30DAYS_OBSIDIAN_ROOT` already exists at line 299)
6. Update `CHANGELOG.md`, `README.md`, `docs/archive/openclaw/07-architecture-and-security.md`, `docs/archive/openclaw/11-lightrag-setup.md`
7. Run migration on server (migration commands above)
8. Bootstrap: ingest 5–7 seed sources to populate initial wiki pages (see INDEX.md checklist)
