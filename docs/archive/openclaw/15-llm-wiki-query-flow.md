# LLM-Wiki Query Flow

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This document explains the full end-to-end mechanics of the LLM-Wiki stack in this repo:

- where the canonical knowledge lives;
- what LightRAG stores vs what it does not store;
- how curated import works;
- how OpenClaw decides to use memory lookup;
- how a final answer is assembled;
- how to verify that the flow is actually working in production.

This is the **runtime/query doc**.

Read first:
- `docs/archive/openclaw/19-llm-wiki-memory-explained.md` for intuition
- `docs/archive/openclaw/10-memory-architecture.md` for the technical memory model

Then use this file for the question:
- "How does OpenClaw actually answer from memory?"
- "When does LightRAG get called?"
- "What happens between retrieval and the final answer?"

Use this document when the question is not "how do I deploy LightRAG?" but rather:

- "How does the LLM-Wiki actually work here?"
- "What is the source of truth?"
- "Where does OpenClaw get memory context from?"
- "When is LightRAG used during answer generation?"

See also:

- `docs/archive/openclaw/10-memory-architecture.md` for the global memory model
- `docs/archive/openclaw/11-lightrag-setup.md` for LightRAG deployment and operations
- `workspace/AGENTS.md` and `workspace/TOOLS.md` for the agent-facing behavior contract

---

## 1. Executive Summary

This file deliberately focuses on runtime behavior, not the full storage model.
If you need folder rules, themes, canonical slugs, or storage constraints, use `docs/16` or `SCHEMA.md`.

In this deployment:

- the **canonical human-readable knowledge base** is the Obsidian-backed `wiki/` tree;
- `raw/` stores source material and signal snapshots;
- **LightRAG is not the primary database** of the wiki;
- **LightRAG is the retrieval engine** layered on top of the wiki and selected workspace files;
- **OpenClaw** is the runtime that decides when retrieval is needed and then uses the retrieved context to compose the final answer.

The shortest accurate mental model is:

```text
raw sources -> curated wiki -> LightRAG index -> OpenClaw answer synthesis
```

And more concretely:

```text
/opt/obsidian-vault/raw
        ↓
wiki-import normalizes and curates
        ↓
/opt/obsidian-vault/wiki
        ↓
LightRAG indexes wiki + workspace + raw/signals
        ↓
OpenClaw calls lightrag_query(...)
        ↓
OpenClaw reads references and writes the final answer
```

---

## 2. Runtime Roles of Each Layer

### 2.1 Canonical Source of Truth: `wiki/`

Canonical knowledge lives in:

- `/opt/obsidian-vault/wiki/`

This is the human-readable, persistent LLM-Wiki layer. It is:

- synced through Syncthing;
- visible in Obsidian;
- readable without any specialized tool;
- linkable with native `[[wikilinks]]`;
- the place where durable knowledge is supposed to accumulate.

Important system pages:

- `wiki/CANONICALS.yaml`
- `wiki/SCHEMA.md`
- `wiki/TOPICS.md`
- `wiki/INDEX.md`
- `wiki/OVERVIEW.md`
- `wiki/IMPORT-QUEUE.md`
- `wiki/LOG.md`

This means:

- if you want to inspect "what the wiki knows", look in `wiki/`;
- if you want to edit or review the knowledge artifact as a human, use `wiki/`;
- if LightRAG vanished tomorrow, the knowledge would still exist in `wiki/`.

### 2.2 Source Material: `raw/`

Raw material lives in:

- `/opt/obsidian-vault/raw/signals/`
- `/opt/obsidian-vault/raw/articles/`
- `/opt/obsidian-vault/raw/documents/`

Roles:

- `raw/signals/`: indexed in v1 because these are compact daily signal snapshots that are useful as near-curated input
- `raw/articles/`: stored sources waiting for curated import; **not** directly indexed in v1
- `raw/documents/`: stored sources waiting for curated import; **not** directly indexed in v1

Important distinction:

- passive scheduled feeds may remain in raw/derived layers without a wiki page;
- explicit user saves must leave a visible `wiki/research/**` artifact immediately.

This separation matters because it prevents the retrieval layer from being flooded with noisy source material before the bot has synthesized it into a stable wiki shape.

### 2.3 Retrieval Engine: `LightRAG`

LightRAG stores **derived state**:

- chunks
- vectors
- entities
- relationships
- document statuses

It does **not** store the authoritative editable wiki artifact.

That is why LightRAG should be thought of as:

- an index;
- a retrieval cache/graph;
- a memory acceleration layer;
- not the canonical database.

### 2.4 Answer Runtime: `OpenClaw`

OpenClaw is the agent runtime that:

- receives the user question;
- decides whether memory lookup is needed;
- chooses the right tool path;
- optionally calls `lightrag_query`;
- reads references if needed;
- synthesizes the final answer.

LightRAG does retrieval.
OpenClaw does reasoning and response composition.

---

## 3. Actual Ingestion Boundary

Current active LightRAG ingest boundary:

- `/opt/openclaw/workspace/**/*.md`
- `/opt/obsidian-vault/wiki/**/*.md`
- `/opt/obsidian-vault/raw/signals/**/*.md`

Explicitly excluded:

- `/opt/obsidian-vault/raw/articles/**`
- `/opt/obsidian-vault/raw/documents/**`
- legacy vault trees outside `wiki/` and `raw/signals/`

Why this boundary exists:

- keep retrieval focused on curated knowledge;
- allow signal digests to participate quickly;
- avoid pulling in full Web Clipper/PDF noise;
- preserve the principle that source material becomes searchable only after curation.

---

## 4. Curated Import Flow

### 4.1 Entry Point

Curated import is handled by the internal `wiki-import` bridge:

- project root: `/opt/wiki-import`
- port: `127.0.0.1:8095`

Supported input types:

- `url`
- `text`
- `server_path`

Supported capture modes:

- `knowledgebase`
- `ideas`
- `promotion`

`curation_level` is a workflow signal, not a value judgment about the source:

- `light` means “safe source-centric landing page first”
- `curated` means “this item has passed promotion and can update canonical concepts/entities”

Public conceptual tools:

- `wiki_read(page_path)`
- `wiki_ingest(source)`
- `wiki_lint()`

In practice `wiki_ingest(...)` maps to `POST /trigger` on `wiki-import`.

Maintenance endpoint:
- `POST /maintain` for lifecycle-aware dry runs and safe archive refreshes

### 4.2 What `wiki-import` Does

For a new source, the bridge:

1. normalizes the source;
2. saves it under `raw/articles/` or `raw/documents/`;
3. writes/updates `wiki/IMPORT-QUEUE.md`;
4. creates or updates one source-centric `wiki/research/**` page;
5. reads `SCHEMA.md`, `CANONICALS.yaml`, `INDEX.md`, `OVERVIEW.md`, `TOPICS.md`;
6. resolves canonical entities and aliases before any deeper page creation;
7. optionally updates canonical pages if confidence is high enough for the chosen capture mode;
8. regenerates `OVERVIEW.md`, `TOPICS.md`, and `INDEX.md`;
9. appends to `LOG.md`;
10. only then enqueues touched `wiki/**/*.md` pages for immediate LightRAG indexing.

The bridge is intentionally a **single writer** for bot-owned wiki artifacts.

### 4.3 Why This Matters for OpenClaw

This design preserves a clean boundary:

- OpenClaw does not need direct arbitrary write access to the vault;
- knowledge is materialized into a readable wiki;
- only after that does LightRAG index the result;
- an explicit save is successful because the wiki artifact exists, not because LightRAG returned `uploaded`.

That means the memory layer stays inspectable and debuggable.

### 4.4 Canonical vs Thematic Navigation

The wiki now has two complementary navigation layers:

- **typed storage**: `entities/`, `concepts/`, `decisions/`, `research/`, `sessions/`
- **thematic navigation**: `themes` metadata on pages plus `TOPICS.md`

This follows the LLM-Wiki pattern more closely:

- canonical entity pages are the stable anchor nodes;
- research pages are source-centric or synthesis-centric;
- thematic browsing happens through metadata and topic maps rather than through domain folders.

---

## 5. LightRAG Ingestion Flow

### 5.1 Trigger

The tracked ingest script is:

- `/opt/lightrag/scripts/lightrag-ingest.sh`

It runs on cron and can be triggered manually.
Interactive explicit saves additionally use immediate enqueue from inside `wiki-import`, but only for touched `wiki/**/*.md` pages.

### 5.2 What It Does

For each markdown file in the allowed source trees, it:

1. calls `POST /documents/upload`
2. lets LightRAG enqueue the document for extraction
3. finally calls `POST /documents/reprocess_failed`

After upload, LightRAG asynchronously:

- chunks content
- extracts entities and relations
- builds vector/graph state
- marks document status as `processed`, `pending`, `processing`, or `failed`

### 5.3 Important Consequence

There is a gap between:

- "file uploaded"
- and "file fully usable in retrieval"

That is why explicit save UX must stay wiki-first:

- `wiki/research/**` existing means the knowledge is saved;
- `rag_status=queued/indexed/delayed` only describes search freshness.

So immediately after a large ingest it is normal to see:

- many `pending`
- a few `processing`
- incomplete query quality for some minutes

That is not a bug by itself; it is the background extraction pipeline.

---

## 6. Query-Time Decision Flow in OpenClaw

When a user asks something, OpenClaw first decides what kind of question it is.

### 6.1 If It Is a Live-State Question

Examples:

- "Is OpenClaw healthy right now?"
- "What containers are running?"
- "What is the current config?"

Then OpenClaw should use:

- shell checks
- Docker status
- logs
- HTTP health endpoints

It should **not** trust LightRAG for this.

### 6.2 If It Is a Historical / Knowledge Question

Examples:

- "Why did we choose LightRAG?"
- "What do we know about Syncthing here?"
- "What is the role of signals-bridge in this stack?"

Then OpenClaw should:

1. call `lightrag_query(...)`
2. inspect returned references
3. open the top 2-5 referenced wiki/workspace pages
4. if top results are index/tooling/navigation pages, follow one step deeper to the canonical content pages
5. only then synthesize a final answer

**Telegram entry point:** Only a short question-like message in the `Knowledge` channel should trigger this flow automatically (`lightrag_hybrid` + memory_search -> open top refs -> answer in grounded expanded form with citations/source links when provenance exists). In this path, internet `web_search` is not the default fallback; it should run only when the user explicitly asks for internet/latest/online search or the question inherently depends on fresh external data. Forwarded posts, URLs, explicit save commands, and long-form multiline content in the same channel should be ingested as CURATED knowledge instead of being answered conversationally first.

### 6.3 If It Is Mixed

Examples:

- "Why did we choose X and is it still deployed?"

Then the correct flow is mixed:

1. use LightRAG for historical rationale
2. use live checks for current state
3. combine both in the answer

This mixed-path behavior is part of the trust hierarchy:

```text
LIVE > RAW > DERIVED
```

---

## 7. How OpenClaw Builds the Final Answer

This is the real answer assembly path.

### Step 1. User asks a question

Example:

```text
What is LightRAG and why did we choose it?
```

### Step 2. OpenClaw classifies the question

This is a historical architecture/memory question, so retrieval is useful.

### Step 3. OpenClaw calls `lightrag_query`

Conceptually:

```http
POST http://lightrag:9621/query
Content-Type: application/json

{"query": "What is LightRAG and why did we choose it?", "mode": "hybrid"}
```

### Step 4. LightRAG returns ranked context

Typical output includes:

- a synthesized response string
- references to matching documents/pages

After rollout verification on `2026-04-14`, the query returned references that included:

- `lightrag.md`
- `lightrag-setup-and-operations.md`
- `lightrag-lightrag.md`
- `llm-wiki-rollout-design.md`
- `openclaw.md`

Those are exactly the kinds of wiki-derived references we wanted to see.

### Step 5. OpenClaw treats the response as retrieval context, not gospel

The safe rule is:

- trust the references more than the prose blob
- in `Knowledgebase` search, inspect source pages before answering, not only when precision "might" matter
- do not claim "nothing relevant was found" until the top retrieved pages were actually opened
- extract 2–4 supportable facts or short evidence snippets from the opened pages before synthesis
- if references already support part of the answer, do not fall back to generic "not enough information"

This is why `workspace/TOOLS.md` explicitly says to check `references[].file_path` when the answer affects a decision.

### Step 6. OpenClaw writes the user-facing answer

The final answer is produced by the main model after it has:

- the user question;
- the retrieved LightRAG context;
- optionally the directly opened wiki pages.

So the final answer is not "generated by LightRAG alone."

It is:

```text
LLM answer = user question + retrieved context + agent reasoning
```

For `Knowledgebase`, the default answer shape should be `grounded expanded`:

- 3–6 sentence conclusion anchored in opened refs
- then 2–4 evidence bullets
- then a short interpretation block such as "what this means" / "what may be useful"
- each bullet tied to a concrete `references[].file_path`
- only short snippets/quotes when they materially prove a claim
- include original source links when provenance exists: canonical URL, Telegram deeplink, or best available provenance

The degraded-answer guard is:

- generic fallback is allowed only after top refs were opened and no supportable facts were found
- partial support must be stated explicitly, e.g. "opened refs confirm X and Y, but do not directly confirm Z"
- if refs exist and contain relevant material, the bot should answer with the supported subset rather than "I do not have enough information"
- for thought/post/theme questions, the answer should not stop at a terse snippet list; it should synthesize a broader but still source-grounded interpretation

---

## 8. Why LightRAG Exists at All

Without LightRAG, OpenClaw would have three bad options:

1. forget older decisions;
2. manually open many files on every question;
3. bulk-load too much history into context and degrade quality/cost.

LightRAG provides the middle layer:

- fast retrieval over large accumulated knowledge;
- graph-aware relationships between pages;
- lower prompt bloat;
- better recall for older decisions and linked concepts.

In this repo, that is especially useful because knowledge is spread across:

- workspace docs
- LLM-Wiki pages
- signal history
- decision artifacts

LightRAG turns those into a searchable long-term memory surface.

---

## 9. What "Working Correctly" Looks Like

LLM-Wiki + LightRAG is working correctly when all of the following are true:

### 9.1 The wiki exists as a readable artifact

You can browse:

- `wiki/OVERVIEW.md`
- `wiki/INDEX.md`
- actual entity/concept/decision/research pages

### 9.2 LightRAG indexes the right scope

Included:

- workspace markdown
- `wiki/**/*.md`
- `raw/signals/**/*.md`

Excluded:

- `raw/articles/**/*.md`
- `raw/documents/**/*.md`
- legacy vault noise

### 9.3 Query responses reference wiki pages

The crucial success signal is not just "the query returned something."

The success signal is:

- references now include wiki-derived pages relevant to the question.

### 9.4 OpenClaw still does live checks for live-state questions

The retrieval layer must not replace real-time operational validation.

---

## 10. Verification Commands

### 10.1 Check LightRAG health

```bash
ssh -i ~/.ssh/id_rsa deploy@<server-host> \
  'curl -sf http://127.0.0.1:8020/health'
```

### 10.2 Check document status counts

```bash
ssh -i ~/.ssh/id_rsa deploy@<server-host> \
  'curl -sf http://127.0.0.1:8020/documents/status_counts'
```

### 10.3 Check that excluded trees are not in the index

```bash
ssh -i ~/.ssh/id_rsa deploy@<server-host> \
  'curl -sf http://127.0.0.1:8020/documents'
```

Then verify there are no document paths from:

- `raw/articles/`
- `raw/documents/`
- legacy vault folders

### 10.4 Run a real query

```bash
ssh -i ~/.ssh/id_rsa deploy@<server-host> '
  curl -sf -X POST http://127.0.0.1:8020/query \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"What is LightRAG and why did we choose it?\",\"mode\":\"hybrid\"}"
'
```

### 10.5 Check wiki-import health

```bash
ssh -i ~/.ssh/id_rsa deploy@<server-host> '
  token="$(sudo awk -F= "/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}" /opt/wiki-import/wiki-import.env | tail -n1)"
  curl -sf http://127.0.0.1:8095/health && echo
  curl -sf http://127.0.0.1:8095/status -H "Authorization: Bearer ${token}"
'
```

---

## 11. What Was Verified During Rollout

On `2026-04-14` the following was verified on the production server:

- `wiki-import` healthy on `127.0.0.1:8095`
- `LightRAG` healthy on `127.0.0.1:8020`
- narrowed ingest script installed at `/opt/lightrag/scripts/lightrag-ingest.sh`
- no `raw/articles` / `raw/documents` / legacy-vault noise in indexed document paths
- bootstrap curated imports created actual wiki pages under `/opt/obsidian-vault/wiki`
- query results for LightRAG started returning wiki-derived references such as `lightrag.md` and related pages

This is enough to say the basic LLM-Wiki retrieval loop is functioning.

It does **not** mean the current deterministic importer is perfect. The current v1 importer is operationally correct but still rough in naming/ontology quality. The architecture works; page quality can continue to improve.

---

## 12. Known Limitations of the Current v1

These are not hidden bugs; they are expected v1 limitations.

### 12.1 Deterministic importer naming is still crude

Examples already observed:

- duplicated-looking entity names
- title-shaped pages derived too literally from source text
- overly generic concept pages

This affects knowledge cleanliness more than the retrieval architecture itself.

### 12.2 LightRAG indexing is asynchronous

Immediately after a bulk ingest:

- query quality may lag;
- some docs may still be `pending` or `processing`;
- transient model-side failures can happen during extraction.

### 12.3 `raw/signals` depends on successful daily posting

The new file in `raw/signals/YYYY-MM-DD.md` appears only after a successful Last30Days Telegram post.

So absence of the file can mean:

- no run yet;
- post failed;
- post succeeded but digest write failed.

### 12.4 OpenClaw still needs explicit behavior discipline

The stack works only if the agent follows the memory rules:

- use LightRAG for history;
- use live checks for current state;
- read references for high-importance answers.

---

## 13. Final Mental Model

If you remember only one thing, remember this:

```text
The wiki is the knowledge base.
LightRAG is the retrieval layer over that knowledge base.
OpenClaw is the agent that decides when to retrieve and how to answer.
```

Or operationally:

```text
Human/bot source material -> curated wiki pages -> LightRAG index -> OpenClaw answers
```

That is the actual LLM-Wiki architecture in this repo.
