# LightRAG Setup And Usage

LightRAG is the knowledge graph brain for the memory system. It indexes curated markdown
(workspace files + LLM-Wiki + raw signal digests) and provides hybrid retrieval (vector + graph traversal).

This file is **ops/setup only**.

If you need:
- intuition -> `docs/19-llm-wiki-memory-explained.md`
- memory architecture -> `docs/10-memory-architecture.md`
- runtime query path -> `docs/15-llm-wiki-query-flow.md`

---

## Why LightRAG Exists

Short version:
- `wiki/` is the source of truth
- `LightRAG` is the retrieval layer over curated markdown
- use it for historical/contextual recall, not live-state truth

This doc focuses on how to deploy, ingest, check health, and troubleshoot that layer.

---

## Architecture Position

```
Mac iCloud vault (/DenisJournals) ──Syncthing bidirectional sync────────┐
workspace/ markdown files ──────────────────────────────────────────────┤
                                                                        ▼
                                                           /opt/obsidian-vault/
                                                           /opt/openclaw/workspace/
                                                                        │
                                                                        ▼
                                                           LightRAG (:8020)
                                                           [127.0.0.1 only]
                                                                        │
                              ┌─────────────────────────────────────────┘
                              ▼
                     OpenClaw bot (Бенька)
                     lightrag_query tool call
```

LightRAG is NOT exposed publicly. Caddy does not proxy it. Internal access only.

---

## Data Lifecycle

### What goes in

LightRAG indexes markdown from two source trees:

| Source | Server path | Purpose | Write owner |
|--------|-------------|---------|-------------|
| OpenClaw workspace | `/opt/openclaw/workspace` | bot identity, boot rules, curated memory, daily notes, raw decision threads | OpenClaw / deploy scripts |
| Obsidian wiki | `/opt/obsidian-vault/wiki` | curated entity/concept/decision/research/session pages | Syncthing from Mac and bot writes |
| Raw signal digests | `/opt/obsidian-vault/raw/signals` | daily Last30Days digests written by `signals-bridge` | `signals-bridge` |

The LightRAG container mounts both paths read-only under `/app/data/inputs/`. The source files
remain the canonical human-editable records; LightRAG stores only its derived graph/vector/index
state under `/opt/lightrag/data/rag_storage/`.

Explicitly excluded from LightRAG ingest v1:
- `/opt/obsidian-vault/raw/articles`
- `/opt/obsidian-vault/raw/documents`
- legacy vault material outside `wiki/`

Builtin OpenClaw `memorySearch` uses a narrower profile than LightRAG: it indexes `MEMORY.md`,
`memory/**/*.md`, and `/opt/obsidian-vault/wiki/**/*.md` only. That keeps the gateway's local
recall layer focused on curated facts and canonical wiki pages, while LightRAG handles the broader
historical retrieval layer over `workspace + wiki + raw/signals`.

On the `CX23` VPS, builtin memory is also tuned more conservatively than a default desktop/server
setup: Gemini provider-side batch mode is enabled with `concurrency=1`, the candidate pool is
smaller, and MMR reranking is disabled to reduce host pressure during future rebuilds.

### How data is ingested

`/opt/lightrag/scripts/lightrag-ingest.sh` runs every 30 minutes from cron and can also be run
manually after bulk edits. It:

1. Checks `GET http://127.0.0.1:8020/health`.
2. Finds markdown files in `/opt/openclaw/workspace`, `/opt/obsidian-vault/wiki`, and `/opt/obsidian-vault/raw/signals`.
3. Uploads each file with `POST /documents/upload`.
4. Calls `POST /documents/reprocess_failed` so pending or previously failed documents are retried.

LightRAG deduplicates by document identity/content, so repeated cron runs are expected. The useful
operational check is not "did upload return 200?" but whether `/documents/status_counts` converges
to `processed > 0` and `failed = 0`.

OpenClaw agent cold starts also expect compact top-level wiki navigation files in the agent
workspace, especially `wiki/OVERVIEW.md`. Keep
`/opt/openclaw/workspace/wiki/{OVERVIEW.md,INDEX.md,TOPICS.md,SCHEMA.md,LOG.md,CANONICALS.yaml,IMPORT-QUEUE.md}`
mirrored from `/opt/obsidian-vault/wiki/` without replacing workspace-only `wiki/research/**` pages.

### What LightRAG builds

During processing, LightRAG:

- splits documents into text chunks;
- calls the configured extraction LLM (`light` via OmniRoute's OpenAI-compatible endpoint);
- extracts entities and relationships;
- stores vectors in NanoVectorDB and graph edges in NetworkX;
- records document lifecycle in `kv_store_doc_status.json`.

The index can be rebuilt from source markdown plus `/opt/lightrag/.env`, but `/opt/lightrag/data/`
is backed up because rebuilding takes API quota and time.

### How data is retrieved

OpenClaw reaches LightRAG over Docker DNS:

```text
OpenClaw container → http://lightrag:9621/query
Server host        → http://127.0.0.1:8020/query
```

The bot uses `lightrag_query` for questions such as:

- "What did we decide about OmniRoute?"
- "Why did we reject the previous sync approach?"
- "Find notes about Semikhatov / недосказанность."
- "What context do we have about project X?"

The response contains a synthesized answer plus references to source files. Those references tell
the bot which raw/workspace/Obsidian file to inspect next if the answer needs stronger grounding.

---

## Resource Requirements (Hetzner CX23: 2 vCPU, 4GB RAM)

| Component | Choice | Why |
|-----------|--------|-----|
| Graph storage | NetworkX (built-in) | File-based, no Neo4j |
| Vector storage | NanoVectorDB (built-in) | File-based, no Qdrant |
| KV storage | JsonKV (built-in) | File-based, no Redis |
| LLM | OmniRoute `light` (Qwen first, DeepSeek reserve) | OmniRoute order deployed on 2026-08-14; LightRAG still requires its own extraction smoke before replacing the current direct-DeepSeek route |
| Embedding | `wiki-import` local OpenAI-compatible endpoint | Keeps Knowledgebase indexing functional without Gemini/OpenRouter credits; dimensions stay at 3072 |

All graph/vector data lives under `/opt/lightrag/data/` on the host.

Live resource guardrail on this host: LightRAG runs with `cpus: "0.45"`, `mem_limit: 2304m`,
`memswap_limit: 2816m`, and `pids_limit: 128`. The current graph has roughly 20k nodes and 26k
edges; a 1536MB cap caused `Exit 137` during cold start.

**Current production split:** direct DeepSeek is used because OmniRoute `light` returned
`api_bridge_timeout` during LightRAG extraction. OmniRoute now has the Qwen-first
combo, proven by a controlled Qwen smoke, but LightRAG remains direct DeepSeek
until a separate Qwen-first extraction smoke passes. DeepSeek is its final
reserve once that switch is made.
Embeddings use the local OpenAI-compatible endpoint exposed by `wiki-import`:

- `LLM_BINDING_HOST=https://api.deepseek.com/v1`
- `LLM_MODEL=deepseek-chat`
- `EMBEDDING_BINDING_HOST=http://wiki-import:8095/v1`
- `EMBEDDING_MODEL=local/hash-embedding-3072`
- `EMBEDDING_DIM=3072`

When the dedicated extraction smoke is approved, point LightRAG at
`http://omniroute:20129/v1` and model `light`. The OmniRoute Qwen-first sync is
already deployed; these commands are retained only for an intentional rerun:

```bash
OPENCLAW_HOST=deploy@<server-host> ./scripts/sync-omniroute-qwen-provider.sh
OPENCLAW_HOST=deploy@<server-host> ./scripts/sync-omniroute-deepseek-provider.sh
```

DeepSeek is only a RAG LLM reserve. It does not expose an OpenAI-compatible embeddings endpoint.
The local `wiki-import` embedding endpoint is a lightweight deterministic fallback, not a paid
semantic embedding model. It is good enough to keep saves searchable and LightRAG ingestion live
when external providers are unavailable. If a funded Gemini/OpenRouter/OpenAI embeddings route is
restored, switch embeddings back intentionally and schedule a full LightRAG rebuild after backing up
`/opt/lightrag/data/`, because old vectors and new vectors are not semantically identical even when
the dimension remains `3072`.

New Knowledgebase saves should return `rag_status=queued` or `success`, not `degraded`. If both the
local endpoint and external embeddings fail, it is acceptable to set `WIKI_IMPORT_RAG_DEGRADED_REASON`
temporarily so wiki-save remains successful while retrieval is being repaired.

---

## Directory Layout on Server

```
/opt/lightrag/
├── docker-compose.yml          ← upstream file (from GitHub clone)
├── docker-compose.override.yml ← our overrides (ports, volumes, image)
├── .env                        ← secrets, gitignored
├── data/                       ← LightRAG persistent state (graph + vectors + kv)
│   └── inputs/
│       ├── obsidian/           ← mounted from /opt/obsidian-vault (read-only)
│       └── workspace/          ← mounted from /opt/openclaw/workspace (read-only)
└── scripts/
    └── lightrag-ingest.sh      ← manual/cron re-index trigger

/opt/obsidian-vault/
├── wiki/                      ← curated LLM-Wiki pages (indexed)
└── raw/
    ├── signals/               ← indexed signal digests
    ├── articles/              ← stored only; imported later via wiki-import
    └── documents/             ← stored only; imported later via wiki-import
```

---

## Docker Compose

The upstream `docker-compose.yml` is not modified. Our settings go in `docker-compose.override.yml`.

File: `/opt/lightrag/docker-compose.override.yml`

```yaml
services:
  lightrag:
    image: lightrag-local:latest   # local build; falls back to ghcr.io/hkuds/lightrag:latest
    networks:
      default:
      openclaw_default:
        aliases:
          - lightrag
    ports: !override
      - "127.0.0.1:8020:9621"      # internal only; container port is 9621
    volumes:
      - ./data:/app/data
      - /opt/obsidian-vault:/app/data/inputs/obsidian:ro
      - /opt/openclaw/workspace:/app/data/inputs/workspace:ro
    restart: unless-stopped
    cpus: "0.45"
    mem_limit: 2304m
    memswap_limit: 2816m
    pids_limit: 128
    healthcheck:
      test: ["CMD", "/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9621/health', timeout=5).read()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 90s

networks:
  openclaw_default:
    external: true
```

`ports: !override` is intentional: the upstream compose file publishes `${HOST:-0.0.0.0}:${PORT:-9621}:9621`; the override replaces that with the host-local `127.0.0.1:8020` mapping.

**Start command** (always use both files):

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
'
```

**Image note:** local build `lightrag-local:latest` was built from `Dockerfile.lite` in the cloned repo.
The upstream `ghcr.io/hkuds/lightrag:latest` is also available and equivalent.

---

## Environment File

File: `/opt/lightrag/.env` (never commit — keep actual key in `LOCAL_ACCESS.md`)

Generate it with:
```bash
./scripts/create-lightrag-env.sh
```

Or manually from template `scripts/lightrag.env.template`:

```env
# LLM: OmniRoute light (Qwen primary, DeepSeek reserve)
LLM_BINDING=openai
LLM_MODEL=light
LLM_BINDING_API_KEY=<omniroute-api-key>
LLM_BINDING_HOST=http://omniroute:20129/v1
LLM_MAX_TOKEN_SIZE=32768

# Embeddings: wiki-import local fallback
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=local/hash-embedding-3072
EMBEDDING_BINDING_API_KEY=<wiki-import-token>
EMBEDDING_BINDING_HOST=http://wiki-import:8095/v1
EMBEDDING_DIM=3072
EMBEDDING_MAX_TOKEN_SIZE=8192
EMBEDDING_TOKEN_LIMIT=8192
EMBEDDING_SEND_DIM=false
EMBEDDING_BATCH_NUM=16
CHUNK_SIZE=1200
CHUNK_OVERLAP_SIZE=100

# Storage: file-based
LIGHTRAG_KV_STORAGE=JsonKVStorage
LIGHTRAG_VECTOR_STORAGE=NanoVectorDBStorage
LIGHTRAG_GRAPH_STORAGE=NetworkXStorage
LIGHTRAG_DOC_STATUS_STORAGE=JsonDocStatusStorage

# Rate limiting (important for free tier)
MAX_PARALLEL_INSERT=1
MAX_ASYNC=1
TIMEOUT=180

# Server
HOST=0.0.0.0
PORT=9621
CORS_ORIGINS=http://127.0.0.1
LIGHTRAG_WORKING_DIR=/app/data
WEBUI_TITLE=БенькаMemory
```

Secrets in this setup:
- `LLM_BINDING_API_KEY` = OmniRoute API key
- `EMBEDDING_BINDING_API_KEY` = wiki-import bearer token

---

## Obsidian Vault Sync

### Method: Syncthing bidirectional sync

The vault is synced between the Mac iCloud Obsidian folder and the server with Syncthing. This
means both Denis and the bot can add notes, and the changes converge without using git for the
vault itself.

**Mac vault path:** `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/DenisJournals`  
**Server path:** `/opt/obsidian-vault/`

LightRAG does not watch the filesystem directly. Syncthing moves markdown files into place;
LightRAG picks them up on the next ingest cron run or when `/opt/lightrag/scripts/lightrag-ingest.sh`
is run manually.

### Legacy rsync

`scripts/sync-obsidian.sh` and `scripts/com.openclaw.obsidian-sync.plist.template` are legacy
one-way sync tools. They remain in the repo as a fallback/runbook artifact, but the deployed sync
method is Syncthing.

---

## Ingestion

**Important:** `POST /documents/scan` does NOT recurse into subdirectories. Use `POST /documents/upload` file-by-file instead.

### Ingest script on server

File: `/opt/lightrag/scripts/lightrag-ingest.sh`

```bash
#!/bin/bash
# Uploads workspace + curated wiki markdown files to LightRAG one by one
set -euo pipefail
API="http://127.0.0.1:8020"
UPLOADED=0
FAILED=0

upload_dir() {
  local DIR="$1"
  while IFS= read -r -d "" file; do
    curl -sf -X POST "${API}/documents/upload" \
      -F "file=@${file}" > /dev/null 2>&1 && UPLOADED=$((UPLOADED+1)) || FAILED=$((FAILED+1))
  done < <(find "${DIR}" -name "*.md" -not -path "*/archive/*" -print0)
}

upload_dir "/opt/openclaw/workspace"
upload_dir "/opt/obsidian-vault/wiki"
upload_dir "/opt/obsidian-vault/raw/signals"

if [ "${FAILED}" -eq 0 ]; then
  curl -sf -X POST "${API}/documents/reprocess_failed" > /dev/null 2>&1 || true
fi

echo "Done: ${UPLOADED} uploaded, ${FAILED} failed"
```

### Trigger manually from local machine

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '/opt/lightrag/scripts/lightrag-ingest.sh'
```

### Cron (installed on server)

```
*/30 * * * * /opt/lightrag/scripts/lightrag-ingest.sh >> /var/log/lightrag-ingest.log 2>&1
```

---

## Querying

From OpenClaw bot (Бенька) via `lightrag_query` tool (see `workspace/TOOLS.md`):

```
POST http://lightrag:9621/query
Content-Type: application/json

{"query": "why did we choose PostgreSQL over Redis", "mode": "hybrid"}
```

Direct test from server:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf -X POST http://127.0.0.1:8020/query \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"test query\", \"mode\": \"hybrid\"}" | jq .
'
```

### How OpenClaw should use results

LightRAG is a retrieval helper, not an authority. Бенька should treat the answer as a shortlist of
likely relevant context:

1. Use the `response` field for quick recall when the question is low-risk.
2. Use `references[].file_path` to inspect the source file when the answer affects a decision.
3. For live operational state, ignore LightRAG and run Docker/curl/log checks instead.
4. If references are empty or weak, say that memory did not find enough context and continue with
   live checks or explicit file reads.

---

## Operations

### Start LightRAG

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
'
```

### Check status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml ps
'
```

### Check health

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/health | jq .
'
```

### View logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml logs --tail=100 lightrag
'
```

### View indexed documents

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/documents | jq .
'
```

### WebUI access (via SSH tunnel)

LightRAG has a built-in WebUI at port 9621. Access it locally via SSH tunnel:

```bash
ssh -i ~/.ssh/id_rsa -L 9621:127.0.0.1:8020 "$OPENCLAW_HOST" -N &
# Then open: http://127.0.0.1:9621
```

### Restart

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml restart lightrag
'
```

---

## Initial Indexing Notes

During bulk indexing, external embedding providers can return temporary capacity or quota errors.
The live fallback avoids them by using `wiki-import` local embeddings. If you intentionally switch
back to OpenRouter/OpenAI embeddings and see `401`, `403`, `429`, `credits_exhausted`, or
`No credentials for embedding provider: openrouter`:

1. Run `scripts/sync-omniroute-openrouter-provider.sh` to refresh OmniRoute's encrypted OpenRouter provider record
2. Verify `/v1/embeddings` through OmniRoute from the LightRAG container
3. Keep `MAX_PARALLEL_INSERT=1` and `MAX_ASYNC=1` in `.env` to serialize requests
4. If the upstream is genuinely out of quota, set `WIKI_IMPORT_RAG_DEGRADED_REASON` only until quota/credentials are restored

After quota resets, re-run: `ssh deploy@<server> '/opt/lightrag/scripts/lightrag-ingest.sh'`

---

## Security Notes

- LightRAG host port `8020` is bound to `127.0.0.1` only — not reachable from internet
- Container port `9621` is available only on Docker networks; OpenClaw uses `http://lightrag:9621`
- Caddy does NOT proxy LightRAG (no public API endpoint)
- `.env` contains API keys — never commit, keep in `LOCAL_ACCESS.md`
- Obsidian vault mounted read-only in the container
- Workspace files mounted read-only in the container
- `raw/articles` / `raw/documents` stay out of LightRAG until curated import materializes them into `wiki/`

---

## Files to Back Up

- `/opt/lightrag/.env` (OmniRoute API key + wiki-import token)
- `/opt/lightrag/data/` (graph + vector state — rebuild requires re-ingestion)
- `/opt/lightrag/docker-compose.override.yml`
- `/opt/lightrag/scripts/lightrag-ingest.sh`
