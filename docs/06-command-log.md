# Command Log

High-signal, sanitized setup log.

This file intentionally records the sequence of work and the kinds of commands used, but avoids live credentials, raw tokens, and real connection coordinates.

## 1. Initial host inspection

Used to capture:

- OS and kernel version
- running services
- Docker containers
- listening ports
- resource headroom

Representative command shape:

```bash
ssh -i ~/.ssh/id_rsa deploy@<server-host> 'hostnamectl; uptime; free -h; df -h; docker ps; ss -lntup'
```

## 2. OpenClaw project bootstrap

Created:

- `/opt/openclaw`
- `/opt/openclaw/config`
- `/opt/openclaw/workspace`

Pulled and adapted upstream deployment material.

## 3. Runtime alignment

Adjusted Compose behavior to match the real container entrypoint used by the upstream image.

Representative runtime shape:

```bash
node openclaw.mjs gateway --allow-unconfigured --bind lan --port 18789
```

## 4. Auth profile materialization

Used a temporary local-auth bootstrap to let OpenClaw create its own provider profile, then removed the temporary bootstrap source from the server.

## 5. Public access experiments

The public path evolved through several phases:

1. localhost-only via SSH tunnel
2. reverse proxy experiments
3. early public access with HTTP auth
4. final public path with `mTLS`

## 6. Final public architecture

The stable public design became:

- `Caddy` on `80/443`
- client certificate required at the edge
- full Control UI + API traffic proxied to the local OpenClaw gateway

## 7. Runtime image fix

A small derived image was built to add `iproute2`, because the chosen bind/network mode depended on `ip neigh show` and the upstream image did not include that binary.

## 8. Local-only access materials

The following were deliberately kept out of committed docs:

- server access notes
- client certificate files
- certificate passwords
- tokenized dashboard URLs

## 9. Container transcription tools (Whisper + ffmpeg)

Date: `2026-04-05`

Goal: enable speech-to-text in the same runtime context where OpenClaw executes tools (the gateway container image).

Why this mattered:

- installing Whisper on the host OS did not make it available to tool execution inside the container

Key choices:

- bake `ffmpeg` + `openai-whisper` into the derived OpenClaw runtime image
- use an isolated venv in the image (`/opt/openclaw-whisper-venv`)
- force a CPU-only `torch` wheel to avoid pulling CUDA stacks on a CPU-only VPS
- keep the host OS lean by removing the earlier host-side experiment packages
- explicitly verify the boundary after cleanup: absent on host, present in `openclaw-gateway`

Representative command shape (sanitized):

```bash
cd /opt/openclaw

# update derived Dockerfile (iproute2 + ffmpeg + whisper venv)
sudo $EDITOR /opt/openclaw/Dockerfile.iproute2

sudo docker build -t openclaw-with-iproute2:20260405 -f Dockerfile.iproute2 .
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260405/" /opt/openclaw/.env
sudo docker compose up -d --force-recreate openclaw-gateway

docker compose exec -T openclaw-gateway which whisper
docker compose exec -T openclaw-gateway which ffmpeg
docker compose exec -T openclaw-gateway which ffprobe

# host cleanup (only if previously installed on host)
sudo apt-get purge -y ffmpeg python3-pip python3-venv || true
sudo apt-get autoremove -y || true
```

## 10. OpenClaw core update test (latest) and rollback

Date: `2026-04-06`

Goal: update runtime from `OpenClaw 2026.4.2` to the latest available upstream release.

Validation source:

- GitHub Releases for `openclaw/openclaw` showed `openclaw 2026.4.5` marked as latest.

Applied update shape:

```bash
cd /opt/openclaw

# validate latest image version from GHCR
sudo docker pull ghcr.io/openclaw/openclaw:latest
sudo docker run --rm ghcr.io/openclaw/openclaw:latest openclaw --version

# rebuild derived runtime image on top of latest upstream
sudo docker build --pull -t openclaw-with-iproute2:20260406 -f Dockerfile.iproute2 .

# switch deployment image and recreate gateway
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260406/" /opt/openclaw/.env
sudo docker compose up -d --force-recreate openclaw-gateway

# verify
sudo docker compose exec -T openclaw-gateway openclaw --version
```

Result:

- latest image path (`2026.4.5`) was validated
- runtime rollback was applied to keep service stability:
  - running container image: `openclaw-with-iproute2:20260405`
  - running OpenClaw version: `2026.4.2`

## 11. Health and proxy architecture normalization

Date: `2026-04-06`

Goal: remove split UI serving and define a deterministic readiness contract.

Applied shape:

```bash
# Compose: strict readiness probe on gateway /healthz
cd /opt/openclaw
sudo $EDITOR docker-compose.yml
sudo docker compose up -d openclaw-gateway

# Caddy: proxy all HTTP + WebSocket traffic to gateway
sudo $EDITOR /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Result:

- edge now has a single backend path (`127.0.0.1:18789`) for UI + API
- no host-side static UI copy is required for serving requests
- `docker compose ps` now reflects strict readiness (`starting/unhealthy/healthy`) based on `/healthz`

## 12. 2026.4.5 upgrade execution and rollback incident

Date: `2026-04-06`

Goal:

- move runtime from `openclaw-with-iproute2:20260405` (`OpenClaw 2026.4.2`)
- to `openclaw-with-iproute2:20260406` (`OpenClaw 2026.4.5`)

What was executed:

```bash
cd /opt/openclaw
sudo docker pull ghcr.io/openclaw/openclaw:latest
sudo docker run --rm ghcr.io/openclaw/openclaw:latest openclaw --version
sudo docker build --pull -t openclaw-with-iproute2:20260406 -f Dockerfile.iproute2 .
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260406/" .env
sudo docker compose up -d --force-recreate openclaw-gateway
```

Observed behavior:

- version switch succeeded (`OpenClaw 2026.4.5` in container)
- gateway process entered a high-CPU state and did not bind `:18789`
- edge returned persistent `502 Bad Gateway` instead of converging after startup
- attempted mitigations (`--force`, `bind=custom` + `customBindHost=0.0.0.0`) did not restore availability

Rollback action:

- reverted image tag in `.env` to `openclaw-with-iproute2:20260405`
- restored pre-change `docker-compose.yml` and `openclaw.json` backups

Current caveat at incident time:

- during rollback validation, SSH access to the host started timing out during banner exchange
- final post-rollback health confirmation could not be completed from this workspace session

Status:

- superseded by Section 13 after access recovery and full validation

## 13. Recovery confirmation after temporary SSH firewall widening

## 14. LLM-Wiki rollout v2 and safe cutover attempt

Date: `2026-04-14`

Goal:

- introduce curated `wiki/` + narrowed `raw/signals/` ingest for LightRAG
- deploy the internal `wiki-import` bridge
- switch LightRAG away from indexing the full legacy vault
- prepare bot-owned curated import flow

Representative command shape:

```bash
# deploy deterministic curated import bridge
OPENCLAW_HOST="deploy@<server-host>" bash scripts/deploy-wiki-import.sh

# safe LightRAG cutover without wiping /opt/obsidian-vault
OPENCLAW_HOST="deploy@<server-host>" bash scripts/setup-llm-wiki.sh
```

Observed result:

- `wiki-import` deployed to `/opt/wiki-import`, bound to `127.0.0.1:8095`
- scaffold deployment to `/opt/obsidian-vault/wiki` started successfully
- tracked `/opt/lightrag/scripts/lightrag-ingest.sh` was replaced with the narrowed v2 script
- LightRAG rebuild/restart path became heavy enough that the host stopped completing new SSH banner exchanges during the rollout window

Operational note:

- the cutover flow was adjusted to use `sudo` for clearing derived LightRAG state because parts of
  `/opt/lightrag/data/` were root-owned
- rollout validation and bootstrap imports must resume only after SSH responsiveness is restored

Date: `2026-04-06`

What was verified after SSH access was restored:

- host reachable over SSH again
- compose state:
  - `openclaw-openclaw-gateway-1` is `Up ... (healthy)`
  - running image is back to `openclaw-with-iproute2:20260405`
  - `openclaw --version` reports `OpenClaw 2026.4.2`
- public access check with client certificate:
  - `https://<public-host>/` returns `HTTP/1.1 200 OK`

Additional isolation test:

- `2026.4.5` was reproduced in clean throwaway containers (with fresh config volume and loopback bind)
- same symptom appeared: high CPU `openclaw-gateway`, no listening port, `/healthz` connection reset

Conclusion:

- keep production pinned to `20260405` for now
- treat `2026.4.5` as blocked in this environment until upstream/root-cause fix is available

## 14. Second 2026.4.5 upgrade attempt — blocked by smoke-test

Date: `2026-04-07`

Goal: retry upgrade to `OpenClaw 2026.4.5` using the new safe upgrade SOP (backup → isolated smoke-test → switch).

Pre-flight:

- backup taken: `/opt/openclaw-backup-20260407-121633`
- baseline confirmed: `openclaw-with-iproute2:20260405`, `OpenClaw 2026.4.2`, `healthy`

Image built:

```bash
sudo docker pull ghcr.io/openclaw/openclaw:latest   # confirmed 2026.4.5
sudo docker build --pull -t openclaw-with-iproute2:20260407 -f Dockerfile.iproute2 .
```

Smoke-test (isolated throwaway container, loopback bind, port 19999):

```bash
sudo docker run -d \
  --name openclaw-test-upgrade \
  -p 127.0.0.1:19999:18789 \
  openclaw-with-iproute2:20260407 \
  node openclaw.mjs gateway --allow-unconfigured --bind loopback --port 18789
sleep 25
curl -sf http://127.0.0.1:19999/healthz   # → FAIL
```

Observed:

- container running, ExitCode=0
- CPU: ~130% (high-CPU spin loop)
- port 18789 not bound
- container logs: empty (process stalls before logger init)
- identical to Section 12–13 failure mode

Result:

- smoke-test caught the failure **before touching production**
- production remained on `20260405` throughout — no rollback needed
- `2026.4.5` still blocked in this environment
- await upstream fix or release notes explaining the startup regression

## 15. Successful upgrade to OpenClaw 2026.4.8

Date: `2026-04-08`

Goal: upgrade from `openclaw-with-iproute2:20260405` (`OpenClaw 2026.4.2`) to `2026.4.8` following the safe upgrade SOP.

Note: `:latest` resolved to `2026.4.8` (not `2026.4.7` as initially expected — upstream released a patch).

Pre-flight:

- backup: `/opt/openclaw-backup-20260408-073652`
- baseline: `20260405`, `OpenClaw 2026.4.2`, `healthy`

Build:

```bash
sudo docker pull ghcr.io/openclaw/openclaw:latest  # → OpenClaw 2026.4.8
sudo docker build --pull -t openclaw-with-iproute2:20260408 -f Dockerfile.iproute2 .
```

Smoke-test (key lesson from prior attempts):

- `--bind loopback` inside container = 127.0.0.1 on container loopback, not reachable via Docker port mapping
- must use `--bind lan` for smoke-test so Docker port mapping (127.0.0.1:19999→18789) works

```bash
sudo docker run -d \
  --name openclaw-test-upgrade \
  -p 127.0.0.1:19999:18789 \
  openclaw-with-iproute2:20260408 \
  node openclaw.mjs gateway --allow-unconfigured --bind lan --port 18789
# PASS at t=30s
```

Startup profile vs 2026.4.5:
- 2026.4.5: empty logs, CPU ~130%, port never bound → broken
- 2026.4.8: logs normal, gateway ready in ~14s, CPU ~0% at idle → healthy

Production switch:

```bash
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260408/" .env
sudo docker compose up -d --force-recreate openclaw-gateway
```

doctor output: no errors; applied startup optimization hints:

```bash
# added to .env:
NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache
OPENCLAW_NO_RESPAWN=1
sudo mkdir -p /var/tmp/openclaw-compile-cache
```

Result:

- `openclaw-with-iproute2:20260408`, `OpenClaw 2026.4.8`, `healthy`
- startup time: ~90s to `healthy` (Compose probe convergence)
- `2026.4.5` startup regression confirmed fixed in `2026.4.8`

## 17. Workspace onboarding — bot personalisation

Date: `2026-04-08`

Goal: configure OpenClaw workspace files to give the bot a persistent identity, user profile, and operating rules.

### Context

OpenClaw loads Markdown files from its workspace at the start of every session. Before this step, the workspace was empty (only a pre-existing `BOOTSTRAP.md` was present from initial setup). After this step, the bot has a named identity ("Бенька"), knows who Denis is, and operates under explicit anti-sycophancy rules.

### Files created in `workspace/` (tracked in git as templates)

| File | Purpose |
|------|---------|
| `IDENTITY.md` | Bot name (Бенька 🐾), emoji, schnauzer personality |
| `SOUL.md` | Anti-sycophancy protocol, communication values, techno-minimalist purpose |
| `USER.md` | Denis's profile — tech enthusiast, builder, domain character, interests |
| `AGENTS.md` | Operating instructions, session protocol, decision approach |
| `MEMORY.md` | Long-term curated memory: active projects, partnerships, professional facts |
| `HEARTBEAT.md` | Lightweight periodic tasks (no heavy sweeps — preserves tokens) |
| `TOOLS.md` | Workspace tools + Denis's external tools and stack |
| `BOOT.md` | Session startup checklist |

### Deploy script created

`scripts/deploy-workspace.sh` — rsync-based deploy from `workspace/` to `/opt/openclaw/workspace/` on the server.

### Deployment (Method B — rsync via SSH)

```bash
OPENCLAW_HOST="deploy@<server-host>" ./scripts/deploy-workspace.sh
```

Transfer result: 9 files, 7982 bytes sent, speedup 1.74x.

### Verification on server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "ls -la /home/node/.openclaw/workspace/"'
```

All 8 files confirmed present alongside pre-existing `BOOTSTRAP.md`.

### Functional test

Connected to the bot via web UI, ran `/new` to start a fresh session:

- bot responded with name "Бенька" ✓
- bot described Denis's profile from `USER.md` ✓
- anti-sycophancy mode active ✓

### Documentation added

- `docs/09-workspace-setup.md` — full onboarding guide (both Method A and B)
- `docs/03-operations.md` — expanded with detailed web UI connection steps and workspace management commands

## 16. Web search enabled

Date: `2026-04-08`

Goal: add web search capability using the existing OpenAI Codex provider (no new API keys).

Configuration added to `/opt/openclaw/config/openclaw.json` under `tools.web.search`:

```json
{
  "tools": {
    "web": {
      "search": {
        "enabled": true,
        "provider": "duckduckgo",
        "maxResults": 5,
        "cacheTtlMinutes": 15,
        "openaiCodex": {
          "enabled": true,
          "mode": "cached",
          "contextSize": "high",
          "userLocation": {
            "country": "RU",
            "timezone": "Europe/Moscow"
          }
        }
      }
    }
  }
}
```

How it works:

- `openaiCodex.enabled: true` — activates provider-native search for `openai-codex/*` models (already configured). No new API key needed — uses the existing Codex auth profile.
- `provider: "duckduckgo"` — key-free HTML-based fallback for non-Codex models or if Codex search is unavailable.
- `mode: "cached"` — recommended default, avoids redundant search calls.

Applied via Python merge script (same pattern as security settings), then `docker compose up -d --force-recreate openclaw-gateway`. Gateway converged to `healthy` with no config errors.

## 17. Telegram group configured for all-message mode (no mention required)

Date: `2026-04-08`

Goal: make bot respond to all messages in the "Семья" supergroup (with topics) without requiring @mention or reply.

Context:

- group is a Telegram forum supergroup with topics
- bot is already admin with Privacy Mode disabled in BotFather
- previously: `groups."*".requireMention: true` — bot only responded to @mention

Configuration added to `channels.telegram` in `/opt/openclaw/config/openclaw.json`:

```json
{
  "channels": {
    "telegram": {
      "groupAllowFrom": ["<owner-user-id>"],
      "groups": {
        "*": {
          "requireMention": true
        },
        "<supergroup-chat-id>": {
          "requireMention": false,
          "groupPolicy": "open"
        }
      }
    }
  }
}
```

Key settings:

- `groupAllowFrom` — explicit user allowlist for group triggers (separate from DM `allowFrom`)
- `requireMention: false` — bot reads and responds to every message in this group
- `groupPolicy: "open"` — any group member can trigger the bot (not just allowlisted users)
- `"*"` default kept as `requireMention: true` — all other groups still require @mention

Group chat ID found in OpenClaw session store (`sessions.json`) — actual value in `LOCAL_ACCESS.md`.

Apply shape:

```bash
# Python merge into /opt/openclaw/config/openclaw.json
# then:
sudo docker compose up -d --force-recreate openclaw-gateway
```

Result:

- gateway `healthy`, bot responds to all messages in target group without @mention
- other groups unaffected

## 18. Security hardening — OpenClaw config and Caddy

Date: `2026-04-07`

Reference: [docs.openclaw.ai/gateway/security](https://docs.openclaw.ai/gateway/security)

Goal: apply all relevant security settings from the official security reference to the running deployment.

### Pre-step: capture Docker bridge IP for trustedProxies

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker network inspect opt_openclaw_default \
    --format "{{range .IPAM.Config}}{{.Gateway}}{{end}}" 2>/dev/null ||
  docker network inspect bridge \
    --format "{{range .IPAM.Config}}{{.Gateway}}{{end}}"
'
```

Actual IP recorded in `LOCAL_ACCESS.md` (not committed).

### Changes to /opt/openclaw/config/openclaw.json

Added the following top-level sections (merged with existing `agents` and `auth` sections):

```json
{
  "gateway": {
    "mode": "local",
    "auth": { "allowTailscale": false, "rateLimit": {} },
    "trustedProxies": ["<docker-bridge-gateway-ip>"],
    "allowRealIpFallback": false
  },
  "tools": {
    "profile": "messaging",
    "exec": { "security": "deny", "ask": "always" },
    "fs": { "workspaceOnly": true },
    "elevated": { "enabled": false }
  },
  "logging": { "redactSensitive": "tools" },   // "all" rejected by 2026.4.2 (allowed: "off", "tools")
  "discovery": { "mdns": { "mode": "off" } },
  "session": { "dmScope": "per-channel-peer" },
  "browser": { "ssrfPolicy": { "dangerouslyAllowPrivateNetwork": false } }
}
```

Representative apply shape:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo $EDITOR config/openclaw.json   # merge new sections
  sudo docker compose up -d --force-recreate openclaw-gateway
  sleep 15
  docker compose ps
  docker compose exec -T openclaw-gateway openclaw --version
'
```

### Changes to /etc/caddy/Caddyfile

Updated HSTS max-age from 300 to 31536000 (1 year production standard):

```
Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
```

Apply shape:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo $EDITOR /etc/caddy/Caddyfile
  sudo caddy validate --config /etc/caddy/Caddyfile
  sudo systemctl reload caddy
'
```

### Validation after apply

```bash
# Gateway healthy
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && docker compose ps'

# mTLS public endpoint
curl -skI --cert-type P12 \
  --cert /path/to/client.p12:<password> \
  https://<public-host>/
# Expected: HTTP/1.1 200 OK

# Verify HSTS header value
curl -skI --cert-type P12 \
  --cert /path/to/client.p12:<password> \
  https://<public-host>/ | grep -i strict
# Expected: max-age=31536000
```

Result:

- gateway remained healthy after config reload
- all security settings applied as documented in `docs/07-architecture-and-security.md`
- redacted artifacts updated in repo (`artifacts/openclaw/`)

## 19. Builtin OpenClaw memorySearch enabled over curated wiki only

Date: `2026-04-15`

Goal: enable the gateway's builtin memory layer for fast local recall without breaking the existing
LLM-Wiki / LightRAG architecture.

Configuration applied to `/opt/openclaw/config/openclaw.json`:

```json
{
  "memory": {
    "citations": "auto"
  },
  "agents": {
    "defaults": {
      "memorySearch": {
        "enabled": true,
        "provider": "gemini",
        "model": "gemini-embedding-001",
        "extraPaths": ["/opt/obsidian-vault/wiki"],
        "cache": {
          "enabled": true,
          "maxEntries": 50000
        },
        "query": {
          "hybrid": {
            "enabled": true,
            "vectorWeight": 0.7,
            "textWeight": 0.3,
            "mmr": {
              "enabled": true,
              "lambda": 0.7
            }
          }
        }
      }
    }
  }
}
```

Runtime change:

- forwarded `GEMINI_API_KEY` into `openclaw-gateway` and `openclaw-cli`
- reused the existing Gemini embedding key already present in `/opt/lightrag/.env`
- kept the retrieval boundary narrow: builtin memory indexes only `MEMORY.md`, `memory/**/*.md`,
  and `/opt/obsidian-vault/wiki/**/*.md`
- explicitly did not expand builtin memory to `raw/signals`, `raw/articles`, `raw/documents`, or
  legacy vault trees

Why this shape:

- builtin memory is a fast local recall layer for curated files
- LightRAG remains the broader historical retrieval layer over `workspace + wiki + raw/signals`
- raw vault sources stay out of retrieval until curated import materializes them into canonical wiki pages

Applied on the live server with targeted config and compose updates, then verified via:

- `curl http://127.0.0.1:18789/healthz`
- `docker compose ps openclaw-gateway`
- `openclaw memory index --force`
- `openclaw memory status --deep`
- `openclaw memory search "LightRAG"`

## 20. Builtin memorySearch post-tuning for Hetzner CX23

Date: `2026-04-15`

Goal: reduce host impact from future builtin memory indexing and search on the small `CX23` VPS
without changing the retrieval boundary.

Configuration adjustments:

```json
{
  "agents": {
    "defaults": {
      "memorySearch": {
        "remote": {
          "batch": {
            "enabled": true,
            "concurrency": 1,
            "wait": false
          }
        },
        "query": {
          "hybrid": {
            "candidateMultiplier": 2,
            "mmr": {
              "enabled": false
            }
          }
        }
      }
    }
  }
}
```

Why this shape:

- `candidateMultiplier=2` shrinks the hybrid search candidate pool from the more expensive default
- disabling MMR removes an extra reranking pass that is unnecessary on the small curated corpus
- provider-side Gemini batch mode keeps embedding work gentler for future reindex runs
- `concurrency=1` avoids turning reindex into a bursty background job on a 4 GB VPS

Operational note:

- after the first builtin memory backfill, avoid launching multiple `openclaw memory ...` commands
  in parallel on this host
- prefer one-at-a-time smoke checks (`memory status`, then `memory search`) and schedule forced
  rebuilds off-hours when possible

## 28. Knowledgebase + Ideas topics: search, auto-ingest, dual-mode

Date: `2026-04-16`

### 28a. Knowledgebase topic (topic_id=232) — dual-mode

Goal: make the Knowledgebase supergroup topic dual-purpose — plain-text messages trigger knowledge base search; any other content (forwarded post, link, plain text) is auto-structured and ingested by the bot without any manual fields from Denis.

Changes:

- `artifacts/openclaw/telegram-surfaces.redacted.json` — added Knowledgebase surface: type `supergroup_topic`, chat_id `<ops-supergroup-chat-id>`, topic_id=232; `search_mode` with backends `lightrag_hybrid` + `memory_search`, max 5 results, snippet+citations format; `auto_structure: true`, `required_fields_filled_by: agent` (bot extracts title/domain/source/date/summary automatically)
- `workspace/TELEGRAM_POLICY.md` — Knowledgebase row: question → search, any content → bot auto-extracts + wiki_ingest
- `workspace/TOOLS.md` — `knowledge_channel` section: intent routing + response format template; bot extracts all metadata, Denis never fills structured fields manually
- `docs/12-telegram-channel-architecture.md`, `docs/15-llm-wiki-query-flow.md`, `docs/03-operations.md` — updated to reflect dual-mode

**Note:** `openclaw.json` groups section was NOT changed — the existing supergroup entry already covers all topics including Knowledgebase.

### 28b. Ideas topic (topic_id=639) — frictionless capture

Goal: create a dedicated Ideas topic in the supergroup for zero-friction capture of Telegram posts, links, and thoughts; promote to Knowledgebase on demand.

Changes:

- Created forum topic `💡 Ideas` in `Ben'ka_Clawbot_SuperGroup` via Bot API `createForumTopic`; assigned topic_id=639
- `artifacts/openclaw/telegram-surfaces.redacted.json` — added Ideas surface: type `supergroup_topic`, topic_id=639, mode `idea_capture`; bot auto-captures, classifies, tags, queues; no RAG write without explicit promotion
- `workspace/TOOLS.md` — `ideas_capture` section: any message in topic_id=639 → auto-capture, respond "✅ Захвачено: [тема]. Тег: [domain]"
- `workspace/TELEGRAM_POLICY.md` — Ideas row: any content → auto-capture + queue, promote on demand
- `artifacts/openclaw/telegram-topic-map.json` — added `knowledgebase: 232` and `ideas: 639`
- Pinned usage instructions in both topics via Bot API

### 28c. Knowledgebase search fallback tightened

Observed issue: a short `Knowledgebase` query could still call `web_search` and surface a tool error such as `fetch failed`, even though this topic is supposed to be a local knowledge lookup first.

Fix:

- `workspace/TOOLS.md` — explicit rule added: `Knowledgebase` search must stay on `lightrag_query + memory search` by default
- `workspace/TELEGRAM_POLICY.md` — internet search is now opt-in only for this topic
- `docs/15-llm-wiki-query-flow.md`, `docs/17-knowledge-management.md`, `docs/12-telegram-channel-architecture.md`, `docs/01-server-state.md` — aligned wording

Practical rule:

- in `Knowledgebase`, failure to retrieve local results is **not** a reason to auto-run `web_search`
- first say "nothing relevant found in local knowledge base"
- only then offer a separate internet search, unless Denis explicitly asked for internet/latest/online data in the original message

## 29. Knowledgebase grounded-answer + source-links runtime rollout

Date: `2026-04-21`

Goal:

- strengthen `Knowledgebase` search answers without changing the wiki-first storage architecture
- require broader, source-grounded answers for thoughts/posts/themes
- prefer human-usable source links (`Wiki`, canonical URL, Telegram deeplink) over raw vault paths

Contract changes:

- `workspace/TOOLS.md` — search path tightened to:
  `lightrag_query + memory_search -> open 2-5 refs -> extract 2-4 supportable facts -> grounded expanded answer`
- `workspace/AGENTS.md` and `workspace/TELEGRAM_POLICY.md` — added degraded-answer guard and
  explicit requirement to include source links when provenance exists
- `artifacts/openclaw/telegram-surfaces.redacted.json` — `Knowledgebase.search_mode.response_format`
  changed from snippet-style replies to `grounded_expanded_with_source_links`
- `artifacts/openclaw/telegram-pins/knowledgebase.txt` — pinned instructions updated to explain
  broader answers and provenance-aware source links
- `docs/15-llm-wiki-query-flow.md`, `docs/17-knowledge-management.md`,
  `docs/21-knowledgebase-query-quality.md` — aligned with the new retrieval-to-synthesis contract
- `scripts/smoke-check-knowledge.sh` — extended from health-only smoke checks to answer-quality
  regression checks (`has_refs`, `expected_ref_hit`, `degraded_answer`, `has_source_links`)

Representative deployment shape:

```bash
# sync workspace instructions used by runtime synthesis
OPENCLAW_HOST="deploy@<server-host>" bash scripts/deploy-workspace.sh

# replace active Telegram surface policy after backup
scp artifacts/openclaw/telegram-surfaces.redacted.json deploy@<server-host>:/tmp/telegram-surfaces.policy.json
ssh deploy@<server-host> '
  sudo cp /opt/openclaw/config/telegram-surfaces.policy.json \
    /opt/openclaw/config/telegram-surfaces.policy.json.bak-$(date -u +%Y%m%dT%H%M%SZ)
  sudo install -m 0644 /tmp/telegram-surfaces.policy.json \
    /opt/openclaw/config/telegram-surfaces.policy.json
'

# restart gateway and refresh Telegram pins
ssh deploy@<server-host> 'cd /opt/openclaw && sudo docker compose restart openclaw-gateway'
OPENCLAW_HOST="deploy@<server-host>" bash scripts/post-telegram-pins.sh
```

Validation performed:

- gateway health: `curl http://127.0.0.1:18789/healthz`
- `LightRAG` convergence: `curl http://127.0.0.1:8020/health` + `/documents/status_counts`
- `Knowledgebase` regression smoke check via `scripts/smoke-check-knowledge.sh`
- live Telegram owner-session test inside the real `Knowledgebase` topic

Observed result:

- runtime picked up the new contract after workspace + policy deploy and gateway restart
- Telegram answers became broader and started including explicit source sections
- retrieval quality and provenance were good enough to surface original web links for factual queries
- remaining weakness shifted from missing data to synthesis quality and link ranking: raw vault paths
  can still appear as fallback when cleaner provenance links are not extracted first

---

## 26. OpenClaw 2026.5.12 runtime target preparation

Date: `2026-05-16`

Goal: prepare the repository for upgrading the derived OpenClaw runtime image from `OpenClaw 2026.4.11` to the latest stable upstream release.

External version check:

- GitHub releases mark `openclaw 2026.5.12` as `Latest`; newer `2026.5.16-beta.*` entries are pre-releases.
- `docker run --rm ghcr.io/openclaw/openclaw:latest openclaw --version` returned `OpenClaw 2026.5.12`.
- `docker buildx imagetools inspect ghcr.io/openclaw/openclaw:2026.5.12-slim` resolved to digest `sha256:e2482a66682de6f540dcfd9921e410c23fd060dcd441382ff952247ee911a672`.

Repository changes:

- added `artifacts/openclaw/Dockerfile.iproute2` as the sanitized derived-image template
- the template uses configurable `DEBIAN_MIRROR` package sources before `apt-get update`; the default `https://mirror.yandex.ru` was reachable from the local network while `deb.debian.org` timed out
- updated `artifacts/openclaw/env.redacted.example` to `OPENCLAW_IMAGE=openclaw-with-iproute2:20260516-slim-2026.5.12`

Local validation:

```bash
docker build \
  -f artifacts/openclaw/Dockerfile.iproute2 \
  -t openclaw-with-iproute2:20260516-slim-2026.5.12 \
  artifacts/openclaw

docker run --rm openclaw-with-iproute2:20260516-slim-2026.5.12 \
  sh -lc 'openclaw --version; command -v ip'
```

Validation result:

- local image built successfully on Docker Desktop `linux/arm64`
- `openclaw --version` returned `OpenClaw 2026.5.12`
- `command -v ip` returned `/usr/bin/ip`
- `whisper`, `ffmpeg`, and `ffprobe` stayed absent

Deployment status:

- deployed to `/opt/openclaw` on 2026-05-16
- live Gateway health confirmed after rebuild/recreate

---

## 27. OpenClaw 2026.5.12 live deploy and validation

Date: `2026-05-16`

Goal: switch the live OpenClaw Gateway to the prepared `OpenClaw 2026.5.12` runtime target and
validate server behavior before commit/push.

Representative deployment shape:

```bash
scp artifacts/openclaw/Dockerfile.iproute2 deploy@<server-host>:/tmp/Dockerfile.iproute2

ssh deploy@<server-host> '
  cd /opt/openclaw
  sudo install -m 0644 /tmp/Dockerfile.iproute2 Dockerfile.iproute2
  sudo docker build --pull \
    --build-arg DEBIAN_MIRROR=https://mirror.yandex.ru \
    -t openclaw-with-iproute2:20260516-slim-2026.5.12 \
    -f Dockerfile.iproute2 .
  sudo cp .env ".env.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260516-slim-2026.5.12/" .env
  sudo docker compose up -d --force-recreate openclaw-gateway
'
```

Live core validation:

- `/healthz` returned live status
- `openclaw --version` returned `OpenClaw 2026.5.12`
- `command -v ip` returned `/usr/bin/ip`
- `whisper`, `ffmpeg`, and `ffprobe` remained absent
- `openclaw doctor` exited 0 with warnings only

Routing result:

- Gateway primary remains `omniroute/light`
- `openai/gpt-5.5` is configured only as fallback after OmniRoute/OpenRouter failure
- a default fallback smoke first hit OmniRoute 503, then returned `OK` through `openai/gpt-5.5`
- the Knowledgebase Telegram delivery smoke returned a source-style reply from the bot in the live topic

Known blocker:

- `scripts/smoke-check-knowledge.sh` currently fails at LightRAG `/query/data` because no live
  3072-dimensional embedding provider has quota: Gemini is blocked by the monthly spending cap,
  OmniRoute/OpenRouter embeddings have no usable OpenRouter quota, and the Codex/OpenAI subscription
  fallback does not provide a usable API embeddings route on this server.

Local validation:

- `artifacts/telethon-digest` tests: 2 OK
- `artifacts/wiki-import` tests: 23 OK
- `artifacts/signals-bridge` tests: 84 OK
- `artifacts/agentmail-email` tests: 18 OK
- total: 127 tests OK

## 28. OpenClaw 2026.5.26 live upgrade and Telegram bridge recovery

Date: `2026-05-28`

Goal: upgrade the live derived OpenClaw Gateway image to the latest stable upstream release and
repair Telegram bridge delivery after the Sunday outage.

Version source:

- GitHub Releases marked `openclaw 2026.5.26` as the latest stable release.
- `2026.5.27-beta.1` was present as a pre-release and was intentionally not selected.

Representative OpenClaw deployment shape:

```bash
scp artifacts/openclaw/Dockerfile.iproute2 deploy@<server-host>:/tmp/Dockerfile.iproute2.openclaw-20260528

ssh deploy@<server-host> '
  sudo install -m 0644 /tmp/Dockerfile.iproute2.openclaw-20260528 /opt/openclaw/Dockerfile.iproute2
  cd /opt/openclaw
  sudo docker build --pull \
    --build-arg OPENCLAW_BASE_IMAGE=ghcr.io/openclaw/openclaw:2026.5.26-slim \
    --build-arg DEBIAN_MIRROR=https://mirror.yandex.ru \
    -t openclaw-with-iproute2:20260528-slim-2026.5.26 \
    -f Dockerfile.iproute2 .
  sudo cp .env ".env.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260528-slim-2026.5.26/" .env
  sudo docker compose up -d --force-recreate openclaw-gateway
'
```

Live core validation:

- `/healthz` returned live status.
- `openclaw --version` returned `OpenClaw 2026.5.26`.
- `command -v ip` returned `/usr/bin/ip`.
- `whisper`, `ffmpeg`, and `ffprobe` remained absent.
- stale managed npm `codex@2026.5.12` was uninstalled; plugin registry now uses bundled `codex` from `2026.5.26`.
- model catalog contains `omniroute/light`, `openai/gpt-5.5`, `omniroute/smart`, and `omniroute/medium`; no `gpt-5.4` refs were present.

OpenAI fallback recovery:

- The live `openai-codex` fallback token profile had expired after the upgrade path.
- A fresh local Codex auth bootstrap was copied to a server temp file, used to update only the agent-scoped `openai-codex:codex-cli-current` token profile, then removed from `/tmp`.
- Direct `openai/gpt-5.5` smoke returned `OK_OPENAI_FALLBACK`.
- Default route smoke first hit OmniRoute `503 all upstream accounts are inactive`, then returned `OK_DEFAULT_FALLBACK` through `openai-codex/gpt-5.5`.
- Post-registry-refresh default smoke returned `OK_POST_PLUGIN` through the same fallback chain.

Auto-compaction reserve recovery:

- `agents.defaults.compaction.reserveTokensFloor` was absent in the live config.
- The OpenClaw 2026.5.26 config schema validates `agents.defaults.compaction.reserveTokensFloor`, so the live config was backed up and set to `20000`.
- Gateway was restarted and `/healthz` returned live status.
- A default agent smoke first hit OmniRoute `503 all upstream accounts are inactive`, then returned `OK_COMPACTION_FALLBACK` through `openai-codex/gpt-5.5`.
- Recent Gateway logs did not show `Missing API key for provider "openai-codex"`, `No credentials found for profile`, or `Auto-compaction could not recover`.

Telegram bridge recovery:

- Host clock was about 39 seconds behind Telegram HTTPS time, while `systemd-timesyncd` was timing out on UDP NTP. Telethon logs showed repeated `Server sent a very new message` and `Too many messages had to be ignored consecutively`.
- Host time and RTC were corrected from HTTPS `Date`, and a small `openclaw-https-time-sync.timer` guard was installed on the server because UDP NTP remained unavailable.
- `signals-bridge` and `telethon-digest-cron-bridge` were restarted.
- Stale `signals` Redis jobs from the stuck Sunday run were fast-forwarded, the stale `lock:signals:ruleset:trading-si` lock was cleared, and one fresh `trading-si` run completed with `ok=true`, `pending=0`, `lag=0`.
- A fresh `telethon-digest` interval run completed with exit code `0`, posted four chunks, persisted the digest note, and enqueued/uploaded the derived note to LightRAG.

Deprecated retrieval gate:

- `scripts/smoke-check-knowledge.sh` no longer uses a remote temp JSON file + `scp`; the first server probe now streams JSON over SSH stdout.
- LightRAG `/query/data` still cannot run hybrid retrieval because the live embedding path returns `No credentials for embedding provider: openrouter`, while direct Gemini embeddings return a monthly spending-cap error and the Codex/OpenAI subscription fallback does not provide an API embeddings route.
- This was accepted as a temporary **deprecated retrieval** state rather than a code regression. The smoke script now exits successfully for this specific paywall/credential condition and reports `retrieval_status=deprecated_external_embeddings_unavailable` plus the underlying query errors.

## 29. OpenClaw 2026.5.27 live upgrade, OpenAI OAuth refresh, and DeepSeek reserves

Date: `2026-05-28`

Goal: move the live Gateway from `OpenClaw 2026.5.26` to the latest stable upstream release,
restore the user-requested OpenAI-primary route, and make DeepSeek the last reserve for bridge
LLM work without pretending it can replace embeddings.

Version source:

- GitHub Releases marked `openclaw 2026.5.27` as the latest stable release.
- The derived runtime image was rebuilt as `openclaw-with-iproute2:20260528-slim-2026.5.27`.

Live deployment shape:

```bash
ssh deploy@<server-host> '
  sudo install -m 0644 /tmp/Dockerfile.iproute2 /opt/openclaw/Dockerfile.iproute2
  cd /opt/openclaw
  sudo docker build --pull \
    --build-arg DEBIAN_MIRROR=https://mirror.yandex.ru \
    -t openclaw-with-iproute2:20260528-slim-2026.5.27 \
    -f Dockerfile.iproute2 .
  sudo cp .env ".env.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260528-slim-2026.5.27/" .env
  sudo docker compose up -d --force-recreate openclaw-gateway
'
```

Live validation:

- `/healthz` returned `{"ok":true,"status":"live"}`.
- `openclaw --version` returned `OpenClaw 2026.5.27`.
- `command -v ip` returned `/usr/bin/ip`; `whisper`, `ffmpeg`, and `ffprobe` remained absent.
- `openclaw models list` showed `openai/gpt-5.5` as default, `omniroute/light` as fallback #1,
  and `deepseek/deepseek-v4-flash` as fallback #2, all with auth present.

Auth and routing:

- Server-side OpenAI Codex OAuth was re-authenticated with the device-code flow.
- The fresh OAuth profile was aliased back to the legacy `openai-codex:*` ids so existing Telegram
  sessions stop seeing stale expired profile state.
- Direct Gateway smoke returned the requested exact text through `openai/gpt-5.5`.
- `telethon-digest` and `signals-bridge` route smokes both used `gpt-5.5` first with
  `provider_fallback=false`.
- Forced bridge fallback smokes, with OpenClaw and OmniRoute intentionally broken, reached
  `deepseek-v4-flash` and did not fall to local deterministic output.

OmniRoute and LightRAG:

- DeepSeek was registered inside OmniRoute's provider store and added as the final `light` combo
  reserve using `scripts/sync-omniroute-deepseek-provider.sh`.
- `scripts/smoke-check-knowledge.sh` now reports `model_routes.omniroute_light_llm.ok=true` and
  `resolved_model=deepseek-v4-flash` when OpenRouter-backed `light` routes are unavailable.
- The same smoke explicitly records `deepseek_embeddings.supported=false`. DeepSeek has no
  OpenAI-compatible embeddings endpoint, so LightRAG hybrid retrieval still needs a funded
  Gemini/OpenRouter/OpenAI embeddings route.

Bridge runtime cleanup:

- `telethon-digest` and `signals-bridge` were redeployed after adding Docker SDK fallback routing and
  Redis socket timeouts longer than the `XREADGROUP` block window.
- Recent bridge logs no longer show repeating `Timeout reading from socket` traceback loops.

Validation summary:

- Local tests: `telethon-digest` 5 OK, `wiki-import` 23 OK, `signals-bridge` 87 OK,
  `agentmail-email` 18 OK; total `133` OK.
- Knowledge smoke: service healthy, LLM reserve healthy, retrieval intentionally deprecated until a
  funded embeddings route is restored.

## 30. Telethon Digest scheduler repair and LLM validation smoke

Date: `2026-05-29`

Problem:

- The `Telethon Digest · 08:00` OpenClaw cron run reported `ok`, but its run summary said the
  bridge HTTP call was not executed because the lightweight cron agent context had no shell tool
  available.
- Earlier OpenClaw cron runs also showed heredoc/exec-wrapper failures while still advancing the
  cron state, which made the schedule look healthy without enqueuing `ingest:jobs:telegram`.

Fix:

- Deployed `/opt/telethon-digest/trigger-digest.sh`, which calls the live
  `telethon-digest-cron-bridge` `/trigger` endpoint from inside the bridge container using its own
  environment token.
- Replaced Telethon Digest scheduling with `/etc/cron.d/telethon-digest`:
  `08:00 morning`, `11:00 interval`, `14:00 interval`, `17:00 interval`, `21:00 editorial`.
- Disabled the legacy OpenClaw Telethon Digest agent-turn cron jobs so they no longer spend model
  tokens or produce false-positive `ok` runs.
- Fixed `summarizer.py` URL validation so `post_url` values keep Telegram URLs instead of passing
  through the general text cleaner, which strips `https://...`.

Validation:

- Manual trigger returned `{"ok":true,"status":"enqueued"}` and the bridge status finished with
  `exit_code=0`.
- The fresh derived note was written as
  `/opt/obsidian-vault/Telegram Digest/Derived/2026-05-29/interval-0529-0545.md` with
  `model: gpt-5.5` and `fallback: false`.
- Telethon readback from the `telegram-digest` topic found the bot-posted message
  `Дайджест | 08:00–08:45` at `2026-05-29T05:50:16Z`.
- Local Telethon Digest tests: `6` OK, including coverage for missing LLM `post_url` repair.

Follow-up correction:

- The first host cron file used local Moscow hours with `TZ=Europe/Moscow`. On this server the cron
  daemon evaluated schedule fields in UTC, while `TZ` only affected the command environment. As a
  result, the `11:00` slot fired at `14:00 MSK` and posted an old `09:00-11:00` window.
- The live `/etc/cron.d/telethon-digest` was corrected to explicit UTC times:
  `05:00 -> 08:00 MSK`, `08:00 -> 11:00 MSK`, `11:00 -> 14:00 MSK`,
  `14:00 -> 17:00 MSK`, `18:00 -> 21:00 MSK`.
- Follow-up on `2026-05-30`: the live `/opt/telethon-digest/config.json` still carried the older
  `[08:00, 09:00, 13:00, 17:00, 21:00]` schedule, so nominal host-cron triggers produced labels
  such as `09:00-11:00` and `13:00-14:00`. The deploy now rewrites schedule config to
  `[08:00, 11:00, 14:00, 17:00, 21:00]`, and `digest_worker.py` reads/filters exact nominal
  windows instead of relying on `last_run` drift. `Главное` bullets now get source `→` links from
  matching digest items.

## 31. AgentMail digest delivery repair

Date: `2026-05-29`

Problem:

- `inbox-email` and `work-email` topics looked stale, but both AgentMail bridge pollers were healthy:
  `/status` showed recent 5-minute polls with `exit_code=0`, and Redis streams contained fresh
  `ingest:jobs:email*` plus derived `ingest:events:email*` entries.
- OpenClaw Cron digest runs for AgentMail reported `ok` while their summaries said the bridge HTTP
  trigger was not executed because no exec/shell tool was available in the lightweight cron context.

Fix:

- Added `/opt/agentmail-email/trigger-email-digest.sh`, reused by the personal and work email
  deployments, to call the running bridge `/trigger` endpoint from inside the bridge container.
- Replaced AgentMail digest delivery with host cron:
  `/etc/cron.d/agentmail-email` for `08:00/13:00/16:00/20:00 MSK`, and
  `/etc/cron.d/agentmail-work-email` for `08:30/10:00/11:30/13:00/14:30/16:00/17:30/19:00 MSK`.
- Disabled legacy `AgentMail Inbox · ...` and `AgentMail Work Email · ...` OpenClaw Cron digest jobs
  after backing up the cron store, preventing duplicate sends while preserving the old records.

Validation:

- Polling remained internal to the bridge and continued every 5 minutes.
- Fresh work-email derived events were present before the repair, including contract/payment threads,
  confirming the outage was Telegram delivery only rather than AgentMail ingestion.

## 32. Knowledgebase save degraded RAG guard

Date: `2026-05-30`

Problem:

- A `Knowledgebase` save created the expected `raw/**` and `wiki/research/**` files, but immediate
  LightRAG indexing failed because embeddings were unavailable.
- The live LightRAG route was switched to direct Gemini embeddings, but Gemini returned the provider
  monthly spending-cap error. OmniRoute/OpenRouter embeddings were still unavailable, and DeepSeek is
  only an LLM fallback, not an embeddings provider.
- After the successful wiki save, Telegram also surfaced a raw internal diagnostic command failure
  (`getent hosts ... (agent) failed`) as a separate user-visible message.

Fix:

- Added `WIKI_IMPORT_RAG_DEGRADED_REASON` support to `wiki-import`. When set, interactive saves skip
  the known-failing immediate LightRAG upload/reprocess path and return `rag_status=degraded` with a
  human message while still materializing wiki artifacts.
- Protected live-only `wiki-import.env` and `docker-compose.override.local.yml` from
  `scripts/deploy-wiki-import.sh --delete` rsync, and added Yandex Debian mirror build args for the
  wiki-import image after the default Debian mirror was unreachable from the server.
- Updated OpenClaw workspace instructions so `rag_status=degraded` is treated as a successful
  wiki-first save and raw infra-debug command output is not posted to Telegram after success.

Validation:

- Local `artifacts/wiki-import` unit tests: `24` OK, including a degraded-mode test that verifies no
  LightRAG HTTP calls are made.
- Deployed `wiki-import` and workspace policy to the server.
- Live `/status` reports `rag_degraded=true` and `lightrag_url=http://lightrag:9621`.
- Container smoke verified a degraded save creates `wiki_page_paths`, returns `partial_success`, and
  does not call LightRAG.

Follow-up on `2026-05-31`:

- A new `Knowledgebase` message still surfaced the OpenClaw auto-compaction recovery warning.
- The live config already had `agents.defaults.compaction.reserveTokensFloor=20000`; Gateway logs
  showed stale session compaction failures on `agent:main:main` with `already_compacted_recently`.
- Backed up and removed the stale `agent:main:main` and `Knowledgebase topic_id=232` session mappings
  from `/opt/openclaw/config/agents/main/sessions/sessions.json`, preserving their transcript files
  under `reset-backups/knowledgebase-compaction-<timestamp>/`.
- Recreated `openclaw-gateway`; it returned healthy.
- Telethon owner-session smoke posted an `обсуди:` probe into `Knowledgebase`; the bot replied without
  `Auto-compaction could not recover`, and fresh session mappings were created for topic `232` and
  `agent:main:main`.

## 33. Docker CPU/RAM guardrails after Knowledgebase stall

Date: `2026-05-31`

Problem:

- After a forwarded `Knowledgebase` save, Gateway logs showed a long active model call with very large
  context and an eventual timeout. The user also observed the VPS degrading to near-100% CPU.
- The server class is `CX23`, but live inspection showed the current instance exposes `2 vCPU` and
  about `3.7GiB` RAM, so unbounded AI containers can starve SSH, Docker, Redis, Caddy/networking, and
  bridge services.
- An initial memory-only LightRAG cap of `768m` was too low for the current graph and caused
  `Exit 137` during cold start.

Fix:

- Applied active Docker Compose resource guardrails in the live override files:
  - `/opt/openclaw/docker-compose.override.yml`:
    `openclaw-gateway` = `0.90 CPU / 1224m / 256 pids`, `omniroute` = `0.25 CPU / 512m / 128 pids`
  - `/opt/lightrag/docker-compose.override.yml`:
    `lightrag` = `0.45 CPU / 1536m / 128 pids`
- The main AI path is capped at `1.60` out of `2.00` vCPU, leaving about 20% host headroom.
- Updated workspace policy so forwarded posts, URLs, and long save content must use the direct
  `wiki_ingest` path instead of spending a Telegram turn on broad OpenClaw/source diagnostics.

Validation:

- `docker inspect` confirmed `NanoCpus`, memory, memory-swap, and pid limits on all three containers.
- `openclaw-gateway`, `omniroute`, and `lightrag` were healthy after recreate.
- `GET /healthz` on OpenClaw returned live, and LightRAG health returned healthy on the host-local
  `127.0.0.1:8020` mapping.
- A low-idle `docker stats --no-stream` sample showed the capped containers below their CPU and memory
  ceilings, and host load returned to normal.
- Knowledge smoke returned the expected `deprecated_external_embeddings_unavailable` retrieval status
  while keeping LightRAG service health green and confirming DeepSeek only as an LLM reserve.
- Local unit tests passed: `telethon-digest` 8, `wiki-import` 24, `signals-bridge` 87,
  `agentmail-email` 18 (`137` total).

## 34. Gateway wiki-import wrapper repair

Date: `2026-05-31`

Problem:

- A fresh `Knowledgebase` forwarded-save attempt no longer spiraled into diagnostics, but it replied
  that `wiki_ingest` was unavailable in the current runtime.
- Root cause: `wiki_ingest` was documented as the conceptual workflow, but not exposed as a native
  OpenClaw tool in the Telegram agent runtime. The Gateway also did not have a `wiki-import` token
  file, so a direct authenticated `POST /trigger` could not be called from a narrow wrapper.

Fix:

- Added `workspace/bin/wiki_import_tool.py`, a small standard-library wrapper for `status`,
  `trigger`, `lint`, and `maintain` calls to `wiki-import`.
- Mounted the live `wiki-import` token into `openclaw-gateway` as
  `/run/secrets/wiki_import_token` and set `WIKI_IMPORT_URL=http://wiki-import:8095` plus
  `WIKI_IMPORT_TOKEN_FILE=/run/secrets/wiki_import_token`.
- Updated workspace policy: if no native `wiki_ingest` tool is exposed, use the wrapper rather than
  broad source/repo diagnostics.
- For LightRAG/wiki API-only LLM work, the route remains OmniRoute first and DeepSeek API fallback;
  DeepSeek is not an embeddings provider.

Validation:

- Gateway wrapper `status` returned `ok=true`, `rag_degraded=true`, and the internal LightRAG URL.
- Direct wrapper `trigger` created `raw/articles/**` plus `wiki/research/**` and returned
  `rag_status=degraded`.
- Telegram owner-session save smoke in `Knowledgebase` returned `✅ Сохранено в wiki` with a
  concrete page path and `LightRAG: degraded`, with no `wiki_ingest unavailable` error.
## 35. LightRAG local embeddings and DeepSeek extraction recovery
Date: `2026-05-31`

Problem:

- `wiki-import` saves were correctly materializing wiki pages, but LightRAG stayed in explicit
  degraded mode because the previous direct Gemini embeddings route hit a provider spending cap.
- OmniRoute had `OPENROUTER_API_KEY` in its env, but its encrypted provider store still carried stale
  no-credential/quota state, so LightRAG saw `No credentials for embedding provider: openrouter`.
- After the OpenRouter provider record was repaired, OpenRouter still returned account-level
  `Insufficient credits` / prompt-token-limit errors for real document embeddings.
- OmniRoute `light` also timed out during LightRAG LLM extraction with `api_bridge_timeout`.
- DeepSeek was available as an LLM reserve, but it cannot provide embeddings.

Actions:

- Synced the live OpenRouter key from the OmniRoute container env into OmniRoute's encrypted provider
  table without printing the key, backed up the SQLite store, cleared stale provider error/rate-limit
  fields, and recreated OmniRoute.
- Added `scripts/sync-omniroute-openrouter-provider.sh` so the OpenRouter provider-store repair is repeatable if paid credits are restored.
- Added a local OpenAI-compatible `/v1/embeddings` endpoint to `wiki-import`. It returns
  deterministic 3072-dimensional lexical vectors and is protected by the existing wiki-import bearer
  token.
- Switched `/opt/lightrag/.env` embeddings to `wiki-import` local embeddings:
  `EMBEDDING_BINDING=openai`,
  `EMBEDDING_MODEL=local/hash-embedding-3072`,
  `EMBEDDING_BINDING_HOST=http://wiki-import:8095/v1`,
  `EMBEDDING_DIM=3072`.
- Switched LightRAG LLM extraction to direct DeepSeek fallback:
  `LLM_MODEL=deepseek-chat`,
  `LLM_BINDING_HOST=https://api.deepseek.com/v1`.
- Recreated `wiki-import` and LightRAG, and cleared `WIKI_IMPORT_RAG_DEGRADED_REASON` in `wiki-import`.

Validation:

- Direct `wiki-import` embeddings probe from the LightRAG runtime returned a 3072-dimensional vector.
- Direct DeepSeek chat smoke returned the requested marker text.
- `wiki-import` status reported `rag_degraded=false`.
- Direct `wiki-import` trigger returned `rag_status=queued` and included `rag_enqueued_paths`.
- LightRAG `/documents/status_counts` showed processing advancing again; remaining pending files are
  historical backlog, not a new credential failure. The backlog is expected to take longer because it
  is now doing real LLM extraction via the direct fallback route.

Operational note:

- Keeping `EMBEDDING_DIM=3072` avoids immediate vector-shape crashes, but old Gemini/OpenRouter
  vectors and new local vectors are not semantically identical. If retrieval quality looks
  inconsistent, schedule a backed-up full LightRAG rebuild from source markdown.

## 36. Telegram ingress spool recovery and Knowledgebase backfill

Date: `2026-06-01`

Problem:

- Telegram Bot API polling was receiving updates, but `General` and `Knowledgebase` stopped replying
  after an `openclaw-gateway` recreate.
- The isolated polling spool contained old `.json.processing` claims from the previous container.
  The new container reused the same internal PID, so OpenClaw treated the old claims as owned by a
  live process and blocked the affected Telegram lanes.
- Several `Knowledgebase` messages were received during the block but did not get wiki-save replies.

Actions:

- Backed up and requeued the stale `.json.processing` files in the live Telegram ingress spool.
- Reset only the stale `Knowledgebase` topic 232 session mapping, then recreated `openclaw-gateway`.
- Added `scripts/recover-telegram-ingress-spool.sh`, which requeues only processing claims older than
  the current Gateway container start time.
- Installed `/usr/local/sbin/openclaw-telegram-spool-guard` plus
  `/etc/cron.d/openclaw-telegram-spool-guard` so the safe recovery runs once per minute.
- Backfilled the missed `Knowledgebase` messages into `wiki-import` as three curated sources:
  the OpenClaw/deterministic-orchestration critique, the `#такМожноБыло` video note, and the
  Harness article note.

Validation:

- Telegram spool returned `pending=0 processing=0 failed=0`.
- A live `General` smoke returned `OK_GENERAL`.
- A live `Knowledgebase` smoke returned `✅ Сохранено в wiki` with `LightRAG: queued`.
- The three backfilled sources show `status=done` in `wiki/IMPORT-QUEUE.md`.
- LightRAG `/documents/pipeline_status` reported `busy=false` and `request_pending=false` after the
  backfill. The only remaining failed document records were two older duplicate records already known
  from the previous LightRAG recovery.

## 37. OpenClaw 2026.6.1 stable upgrade and Telegram Digest recovery

Date: `2026-06-06`

Problem:

- Telegram Digest scheduled jobs kept enqueuing, but every run after `2026-06-03T14:00:00Z` failed
  within a few seconds with `ValueError: too many values to unpack (expected 5)` while opening the
  Telethon SQLite session.
- The live session table had the newer `tmp_auth_key` column, while the deployed image still pinned
  `Telethon 1.36.0`, which expected the older five-column session schema.

Actions:

- Upgraded the live OpenClaw derived gateway image from
  `openclaw-with-iproute2:20260528-slim-2026.5.27` to
  `openclaw-with-iproute2:20260606-slim-2026.6.1`, based on upstream stable `OpenClaw 2026.6.1`.
- Backed up the live OpenClaw `.env`, rebuilt the derived image with `iproute2`, updated
  `OPENCLAW_IMAGE`, and recreated only `openclaw-gateway`.
- Updated `telethon-digest` to `Telethon 1.43.2`, backed up the live session file inside the
  `telethon-sessions` volume, rebuilt `telethon-digest-cron-bridge`, and recreated the bridge.
- Restored executable bits on `/opt/telethon-digest/trigger-digest.sh`,
  `/opt/telethon-digest/cron-digest.sh`, and `/opt/telethon-digest/sync-openclaw-cron-jobs.sh` after
  the manual rsync deploy.

Validation:

- `openclaw --version` returned `OpenClaw 2026.6.1`, the gateway returned healthy, `/healthz`
  returned `{"ok":true,"status":"live"}`, and `command -v ip` returned `/usr/bin/ip`.
- `telethon-digest-cron-bridge` reported `Telethon 1.43.2`, and `reader.build_client()` could open
  the existing session database with the `tmp_auth_key` column.
- A manual Telegram Digest interval trigger returned `status=enqueued` and finished with
  `exit_code=0`, posting three chunks, persisting
  `/opt/obsidian-vault/Telegram Digest/Derived/2026-06-05/interval-0500-0800.md`, and enqueuing RAG.
- The digest LLM route still degraded: the manual digest fell back to deterministic local output after
  two empty LLM responses. A small bridge route smoke reached `deepseek-v4-flash` with
  `provider_fallback=true`, proving the reserve route works.
- Direct `openai/gpt-5.5` gateway smokes on `2026.6.1` still report a provider-auth selection error
  with the existing ChatGPT/Codex OAuth profiles. The live config was backed up and tested with
  `auth.order.openai` OAuth profile mappings and `models.providers.openai.auth=oauth`, but the direct
  OpenAI-primary path remains a follow-up item.

## 38. Knowledgebase save recovery after OpenClaw 2026.6.1

Date: `2026-06-06`

Problem:

- A new `Knowledgebase` topic post reached Telegram ingress, but no save confirmation appeared in the
  topic.
- The wiki-import service and spool were healthy (`pending=0 processing=0 failed=0`), so the failure was
  not a stuck ingress queue or RAG outage.
- Gateway logs showed the turn entered the `Knowledgebase` topic, failed the direct `openai/gpt-5.5`
  primary route with the same provider-auth selection error seen after the `2026.6.1` upgrade, then hit
  stale transcript compaction on the old topic session.

Actions:

- Backed up the affected OpenClaw session registry and transcript records under the live
  `agents/main/sessions/reset-backups/knowledgebase-compaction-<timestamp>/` directory.
- Removed only the stale `agent:main:main` and `Knowledgebase` topic 232 session mappings from the live
  session registry, preserving the transcript files in the backup.
- Recreated `openclaw-gateway` and waited for the Gateway to return healthy.
- Recovered the missed source with a direct `wiki_import_tool.py trigger` call from the Gateway runtime,
  using `capture_mode=knowledgebase` and a sanitized source payload.

Validation:

- `wiki_import_tool.py status` returned `ok=true`, `rag_degraded=false`, and empty pending/processing
  queues before recovery.
- The manual import returned `status=success`, created `raw/articles/**`, `wiki/research/**`, related
  `wiki/entities/**` and `wiki/concepts/**` pages, and returned `rag_status=queued`.
- A fresh Telegram smoke in topic 232 was received by the Gateway and produced an outbound Telegram
  reply in the same thread after falling back from the broken OpenAI primary route to `omniroute/light`.
- At this point the direct `openai/gpt-5.5` route was still a separate follow-up. It was resolved in
  the auth-order hardening pass recorded in Section 39.

## 39. Knowledgebase OpenAI auth-order hardening after 2026.6.1
Date: `2026-06-06`
Problem:
- A follow-up `Knowledgebase` Telegram smoke still showed the earlier recovery warning in the topic UI
  even though `wiki_import_tool.py status` proved the forwarded source had already been saved to
  `raw/**` and `wiki/research/**`.
- Gateway `models status` showed live `openai:*` OAuth profiles, but runtime auth initially reported
  `openai via codex ... status=missing` and later `models status --probe --probe-provider openai`
  marked all usable `openai:*` profiles as `Excluded by auth.order for this provider`.
- Root cause: `openclaw.json` and the agent-scoped `auth-state.json` order override had drifted into
  legacy `openai-codex:*` / bare profile ids after the 2026.6.1 upgrade.
- The temporary fallback through `omniroute/light` was also not acceptable for interactive Telegram:
  it could hit `Cannot continue from message role: assistant` after compaction retries. DeepSeek
  succeeded when selected directly.
Actions:
- Backed up and removed only the stale `agent:main:main` and `Knowledgebase topic_id=232` session
  mappings from `agents/main/sessions/sessions.json`, preserving transcript files under
  `sessions/reset-backups/knowledgebase-*/`.
- Ran `openclaw doctor --fix` and `openclaw config validate`; doctor migrated active OpenAI Codex auth
  profile material to the canonical OpenAI provider and repaired stale session routes.
- Set `auth.order.openai` in `openclaw.json` to canonical `openai:*` profile ids.
- Set the agent-scoped override with
  `openclaw models auth order set --provider openai ...`, because `auth-state.json` still pinned a
  stale `openai-codex:codex-cli-current` token after the config-level order was fixed.
- Removed `omniroute/light` from the interactive Gateway fallback chain and kept
  `deepseek/deepseek-v4-flash` as the direct reserve route.
- Recreated `openclaw-gateway` after each config/order change so in-memory routing state was cleared.
Validation:
- `openclaw models status --probe --probe-provider openai` returned `ok` for two canonical `openai:*`
  OAuth profiles.
- `openclaw models status --probe --probe-provider deepseek` returned `ok`.
- Final `Knowledgebase` owner-session smoke in topic 232 received a Telegram `OK` reply.
- The fresh topic transcript recorded the assistant response as `provider=openai`, `model=gpt-5.5`,
  followed by the OpenClaw delivery mirror. This confirms the final acceptance path used OpenAI primary,
  not a fallback.
- Tracked config now matches the live policy: `openai/gpt-5.5` primary and
  `deepseek/deepseek-v4-flash` fallback.

## 40. Telethon Digest scheduled-window cursor fix

Date: `2026-06-18`

Problem:

- Scheduled Telegram Digest windows had exact slot bounds, but channel reads still used per-channel
  `last_seen_msg_id` as `min_id`.
- If a manual, delayed, or duplicate run advanced a cursor past a later nominal window, scheduled
  runs could see only a small subset of active channels.

Actions:

- Changed scheduled slot runs to backread by time window without cursor prefiltering.
- Kept cursor-based reads for non-slotted/manual fallback runs.
- Made bulk cursor writes monotonic so a scheduled backread cannot move a watermark backwards.
- Added a low-coverage scheduled-read retry with slower Telethon pacing.
- Deployed `telethon-digest` with the repo deploy helper and restarted the cron bridge.

Validation:

- Local `telethon-digest` unit suite passed with 12 tests.
- Live host cron still lists the five Moscow digest slots: `08:00`, `11:00`, `14:00`, `17:00`, `21:00`.
- Live bridge accepted a manual `interval` trigger for the `11:00` slot and finished with `exit_code=0`.
- The run read 172 posts, kept 69 posts in the exact `08:00-11:00` window, selected 37 posts with
  21 unique channels, and posted both Telegram chunks successfully.
- The persisted digest note recorded `# Дайджест | 08:00–11:00 (21 канал, 37 постов)` and
  `Просмотрено 69 новых постов из 366 каналов в скоупе`.
- Follow-up audit of the `14:00-17:00` window found the scheduled run had under-read the window:
  the posted run saw 76 posts and selected 16 posts from 6 channels, while an independent no-post
  bridge audit found 163 posts from 49 channels and would select 42 posts from 29 channels.
- After deploying the low-coverage retry, a controlled `17:00` slot trigger completed with
  `exit_code=0`; the persisted digest recorded 121 new posts, 42 selected posts, and
  `# Дайджест | 14:00–17:00 (32 канала, 42 поста)`.

## 41. OpenClaw 2026.6.8 live upgrade and service startup check

Date: `2026-06-19`

Goal:

- Upgrade the live derived OpenClaw Gateway image from `OpenClaw 2026.6.1` to the latest stable
  `OpenClaw 2026.6.8`.
- Bring up the current service set after the Gateway recreate.
- Check whether the recent Telegram Digest low-channel counts still indicate reader-side truncation.

Actions:

- Updated the derived-image template from `ghcr.io/openclaw/openclaw:2026.6.1-slim` to
  `ghcr.io/openclaw/openclaw:2026.6.8-slim`.
- Backed up the live `/opt/openclaw/.env` and `/opt/openclaw/Dockerfile.iproute2`, installed the new
  Dockerfile, rebuilt `openclaw-with-iproute2:20260619-slim-2026.6.8`, updated `OPENCLAW_IMAGE`, and
  recreated `openclaw-gateway`.
- Brought up the current service set and removed the stale `telethon-digest` service plus the accidental
  stale container created by running the broad `/opt/openclaw` compose project. The active digest
  service remains `/opt/telethon-digest` / `telethon-digest-cron-bridge`.
- Started `agentmail-work-email-bridge` with `docker compose --env-file email.env ...`; running without
  the env file falls back to the inbox bridge container name and conflicts with `agentmail-email-bridge`.

Validation:

- `openclaw --version` returned `OpenClaw 2026.6.8`.
- `/healthz` returned `{"ok":true,"status":"live"}` and the Gateway container returned to `healthy`.
- `command -v ip` inside `openclaw-gateway` returned `/usr/bin/ip`.
- `openclaw config validate` returned `Config valid: ~/.openclaw/openclaw.json`; `openclaw doctor`
  only reported the known startup-env warning in the exec CLI context.
- Current services were up: `openclaw-gateway`, `omniroute`, `telethon-digest-cron-bridge`,
  `signals-bridge`, `agentmail-email-bridge`, `agentmail-work-email-bridge`, `wiki-import`, and
  `lightrag`.
- `/opt/openclaw` compose now lists only `omniroute` and `openclaw-gateway`; Telegram Digest remains
  isolated in its dedicated `/opt/telethon-digest` compose project.
- `telethon-digest-cron-bridge` reported `Telethon 1.43.2`; the `11:00` MSK digest run completed with
  `exit_code=0`, kept 57 posts in the exact `08:00-11:00` MSK window, selected 16 posts from 7 unique
  channels, posted two chunks, persisted `interval-0500-0800.md`, and enqueued RAG ingest.
- The same `11:00` MSK digest fell back to deterministic local summarization after two LLM responses
  contained retry markers. This is a quality/fallback issue, not a channel-reader truncation issue.
- The `08:00` MSK morning digest remained a separate follow-up: logs show the bridge restarted at
  `2026-06-19T05:12:22Z` after starting the morning run, with no `Pipeline completed OK` line.

## 42. Telegram Digest status/header/fallback cleanup

Date: `2026-06-19`

Problem:

- A bridge/container restart during `digest_worker.py --now` could leave
  `/app/state/cron-bridge-status.json` stuck at `running=true` even though no worker process survived.
- The Telegram header mixed raw active-channel count with selected-post count, so a line like
  `9 каналов, 19 постов` looked like the reader had only seen 19 source posts.
- Fenced JSON responses from the LLM summarizer were rejected as retry markers before JSON extraction,
  causing avoidable deterministic fallback.

Actions:

- Added bridge startup recovery: stale `running=true` status is marked `interrupted`, `exit_code=130`,
  and the matching Redis digest run lock is released.
- Changed the Telegram header to show active channels, processed source messages, and selected posts
  separately.
- Changed summarizer validation order so fenced/extractable JSON is parsed before retry-marker checks.
- Added unit tests for interrupted status recovery, header counter wording, and retry-marker handling.
- Redeployed `telethon-digest` and restarted `telethon-digest-cron-bridge`.

Validation:

- Server-side container test run passed: `18 tests OK`.
- `telethon-digest-cron-bridge` `/health` returned `ok=true`, `running=false`, and last digest
  `exit_code=0`.
- Host cron still contains the five Moscow slots for `08:00`, `11:00`, `14:00`, `17:00`, and `21:00`.
- Current containers were up: `openclaw-gateway`, `omniroute`, `telethon-digest-cron-bridge`,
  `signals-bridge`, `agentmail-email-bridge`, `agentmail-work-email-bridge`, `wiki-import`, and
  `lightrag`.

## 43. Telegram Digest content-mix cap for news-heavy slots

Date: `2026-06-23`

Problem:

- The scored Telegram Digest source pool could become dominated by the `news` folder when news
  channels were active, crowding out `evolution`, `startups`, `growth.me`, `fintech`, `investing`,
  `work`, `eb1`, `гребенюк`, `personal`, and `faang`.
- The existing folder soft/hard caps improved diversity in early selection passes, but the final
  fallback pass could still refill the issue from the same noisy folder.

Actions:

- Added a default `content_mix` cap in `scorer.py`: `news` targets 30% and hard-caps at 35% when
  enough other allowlisted folders have scored candidates.
- Kept the cap elastic: when non-news candidates are sparse, `news` can exceed 35% to fill the
  selected source pool instead of producing a thin digest.
- Documented the runtime config shape in `config.example.json`, README, server-state, operations,
  and architecture docs.
- Redeployed `telethon-digest` and restarted `telethon-digest-cron-bridge`.

Validation:

- Local `.venv` test run passed: `20 tests OK`.
- Local compile/json checks passed for `artifacts/telethon-digest`.
- Diff sensitive-value scan found no live credential additions.
- Server-side test run in the deployed image with mounted artifact passed: `20 tests OK`.
- Running bridge imported `news_target=0.3` and `news_hard=0.35`.
- `telethon-digest-cron-bridge` health returned `ok=true`, `running=false`.
- Host cron still contains the five Moscow slots for `08:00`, `11:00`, `14:00`, `17:00`, and `21:00`.

## 44. OpenClaw 2026.6.9 live upgrade and direct DeepSeek fallback repair

Date: `2026-06-24`

Goal:

- Upgrade the live derived OpenClaw Gateway image from `OpenClaw 2026.6.8` to the current stable
  `OpenClaw 2026.6.9`.
- Verify that the Gateway starts, validates config, and can answer agent turns after the upgrade.
- Repair the interactive fallback route without reintroducing `omniroute/light` into Gateway-level
  fallback.

Actions:

- Verified the latest stable upstream target as `OpenClaw 2026.6.9`; the newer
  `2026.6.10-beta.2` release was prerelease-only and was not used for production.
- Updated the derived image template from `ghcr.io/openclaw/openclaw:2026.6.8-slim` to
  `ghcr.io/openclaw/openclaw:2026.6.9-slim`.
- Backed up the live `/opt/openclaw/.env` and `/opt/openclaw/Dockerfile.iproute2`, installed the new
  Dockerfile, rebuilt `openclaw-with-iproute2:20260624-slim-2026.6.9`, updated `OPENCLAW_IMAGE`, and
  recreated `openclaw-gateway`.
- Restored DeepSeek auth from the existing runtime env SecretRef and added the sanitized
  `deepseek-direct` provider to the tracked config template.
- Replaced the interactive fallback from `deepseek/deepseek-v4-flash` with
  `deepseek-direct/deepseek-chat`. On OpenClaw 2026.6.9, the built-in DeepSeek route returned an
  unknown-model error, while the direct OpenAI-compatible DeepSeek route succeeded with the bare
  `deepseek-chat` model id.

Validation:

- `openclaw --version` returned `OpenClaw 2026.6.9` in the derived image and in the running Gateway
  container.
- `command -v ip` inside `openclaw-gateway` returned `/usr/bin/ip`.
- `/healthz` returned `{"ok":true,"status":"live"}` and `openclaw-gateway` returned to Docker
  `healthy`.
- `openclaw config validate` returned `Config valid: ~/.openclaw/openclaw.json`.
- `openclaw models status --probe --probe-provider deepseek-direct` returned `ok` for
  `deepseek-direct/deepseek-chat`.
- Explicit agent smoke with `--model deepseek-direct/deepseek-chat` returned the requested
  `OK_OPENCLAW_2026_6_9` marker.
- Default-route agent smoke returned the requested `OK_DEFAULT_ROUTE_2026_6_9` marker after falling
  back from the `openai/gpt-5.5` primary route to `deepseek-direct/deepseek-chat`.
- Current containers were up after the Gateway recreate, including `openclaw-gateway`, `omniroute`,
  `telethon-digest-cron-bridge`, `signals-bridge`, both AgentMail bridges, `wiki-import`, and Redis.

Initial caveat, later resolved in Section 45:

- OpenAI primary is not counted healthy yet after the 2026.6.9 upgrade: the new auth store did not
  expose a usable `openai:*` OAuth profile, so default-route success currently depends on the direct
  DeepSeek fallback. Section 45 resolved this by importing the legacy auth profiles into SQLite and
  pinning the OpenAI provider to ChatGPT/Codex OAuth transport.

## 45. OpenAI primary restore after 2026.6.9 SQLite auth migration

Date: `2026-06-24`

Problem:

- `openclaw models status --probe --probe-provider openai` initially reported no usable OpenAI
  profile in the new per-agent SQLite auth store, while legacy `auth-profiles.json` still existed.
- Importing the legacy profiles made `openai:default` probe successfully, but default agent turns
  still fell back to `deepseek-direct/deepseek-chat` because `openai/gpt-5.5` resolved to the direct
  OpenAI Platform `openai-responses` transport, which requires an API key and rejects OAuth.

Actions:

- Backed up the live agent auth files before repair.
- Imported legacy `auth-profiles.json` and `auth-state.json` into
  `agents/main/agent/openclaw-agent.sqlite` with OpenClaw's own auth-profile SQLite migration
  function. The migration created `.sqlite-import.*.bak` backups and reported no warnings.
- Pinned `models.providers.openai` to ChatGPT/Codex OAuth transport:
  `baseUrl=https://chatgpt.com/backend-api/codex`, `api=openai-chatgpt-responses`, `auth=oauth`.
- Set both config-level and agent-level OpenAI auth order to the verified `openai:default` profile so
  expired legacy profiles remain stored but are excluded from active routing.
- Recreated `openclaw-gateway` so the running service loaded the repaired auth store and provider
  transport.

Validation:

- `openclaw models auth list --provider openai --json` returned the restored OpenAI profiles from
  `openclaw-agent.sqlite`.
- `openclaw models status --probe --probe-provider openai` returned `ok` for `openai/gpt-5.5` with
  the `openai:default` OAuth profile.
- `/healthz` returned `{"ok":true,"status":"live"}` and `openclaw-gateway` returned to Docker
  `healthy`.
- Final default-route agent smoke returned `OK_OPENAI_PRIMARY_FINAL_2026_06_24` with
  `provider=openai`, `model=gpt-5.5`, and `fallbackAttempts=0`.
- `deepseek-direct/deepseek-chat` remains configured as the direct reserve fallback.

## 46. Telegram tool-error diagnosis and LightRAG cold-start recovery

Date: `2026-06-24`

Problem:

- A Telegram group request in topic `11` showed intermediate tool errors:
  `wiki/OVERVIEW.md` read failed with `exit 2`, and `http://lightrag:9621/health` failed from the
  Gateway container.
- The same request was also interrupted by the planned Gateway recreate during OpenAI auth repair.

Actions:

- Verified the Telegram run was recovered by OpenClaw startup recovery and completed with
  `stopReason=stop` on `openai/gpt-5.5`.
- Started the dormant LightRAG compose service and found it OOMKilled on cold start at the old
  `1536m` limit while loading the current graph.
- Raised the live LightRAG override to `mem_limit: 2304m` and `memswap_limit: 2816m`, then recreated
  the service.
- Synced top-level wiki navigation files from `/opt/obsidian-vault/wiki` into
  `/opt/openclaw/workspace/wiki` so agent cold starts can read `wiki/OVERVIEW.md`.

Validation:

- `openclaw-gateway` remained healthy and `/healthz` returned live status.
- LightRAG became Docker `healthy`; host-local `127.0.0.1:8020/health` and Gateway-side
  `http://lightrag:9621/health` returned healthy status.
- `wiki/OVERVIEW.md`, `wiki/INDEX.md`, `wiki/TOPICS.md`, and `wiki/SCHEMA.md` were present inside the
  Gateway workspace.

## 47. Football topic Telegram routing recovery

Date: `2026-06-24`

Problem:

- A follow-up message in Telegram forum topic `11` did not produce a bot reply.
- OpenAI primary was suspected. The first live probe showed `openai/gpt-5.5` with the active
  `openai:default` profile was healthy, but a later probe during the same incident showed the same
  profile in Codex usage cooldown until reset.
- A live Gateway request hit `FailoverError` during that cooldown instead of cleanly answering through
  `deepseek-direct/deepseek-chat`, so the fallback chain still needed proof rather than a primary-route
  switch.
- Gateway logs did not contain a new Telegram inbound event for topic `11`, and Bot API
  `getUpdates` showed no pending update to recover.
- Reusing the old topic session without an explicit model override returned `exit:137` and restarted
  the Gateway, so the stale session state was treated as part of the incident.

Actions:

- Proved the model path with an isolated agent smoke: the transcript returned
  `OK_OPENAI_PRIMARY_1033` through provider `openai`, model `gpt-5.5`, and `stopReason=stop`.
- Sent the requested football schedule answer directly to topic `11` with Telegram Bot API so the
  chat was not left without an answer.
- Added `football: { message_thread_id: 11 }` to the live server
  `/home/node/.openclaw/telegram-topic-map.json` and restarted `openclaw-gateway`.
- Backed up and removed the stale session key
  `agent:main:telegram:group:<ops-supergroup-chat-id>:topic:11` under
  `sessions/reset-backups/football-topic-11-<timestamp>/`, preserving the old transcript and session
  entry.
- Ran a clean delivered smoke to the same Telegram topic. The new session used
  `deepseek-direct/deepseek-chat` after the OpenAI cooldown fallback and returned the expected status
  message.
- Temporarily switched the global primary route to DeepSeek while diagnosing the missed fallback, then
  rolled that back after review: the correct live policy is still `openai/gpt-5.5` primary with
  `deepseek-direct/deepseek-chat` as reserve.
- Recreated `openclaw-gateway` after restoring the model policy so the running Gateway dropped the
  temporary in-memory route state.
- Sent the missed Botafogo/CSKA answer through the restored topic delivery path with a prepared answer,
  avoiding another live web/tool turn while the `exit:137` trigger was still under diagnosis.

Validation:

- Telegram Bot API `sendMessage` returned `ok=true` for the football topic.
- Gateway returned healthy after restart, `/healthz` returned live status, and the Telegram provider
  restarted isolated polling.
- The live topic map now contains the `football` topic entry.
- Final clean `openclaw agent --session-key ... --deliver` smoke returned `status=ok`,
  `provider=deepseek-direct`, `model=deepseek-chat`, and `deliveryStatus.status=sent`.
- After rollback, runtime config again reported `primary=openai/gpt-5.5` and
  `fallbacks=[deepseek-direct/deepseek-chat]`; both provider probes succeeded after the OpenAI reset.
- Simple default-route and topic-delivery smokes succeeded through OpenAI primary. A tool/web-heavy
  topic turn still reproduced `exit:137`, so it remains a separate follow-up from the model policy.
- A post-rollback health check returned `/healthz` live, Docker reported `openclaw-gateway` healthy
  with `oom=false`, and short default-route plus explicit reserve agent smokes both returned
  `status=ok` without another Gateway restart.
- The affected topic session updated from explicit `--deliver` smokes, but not from the earlier user UI
  message observed during the incident; do not treat outbound delivery as proof that Telegram inbound
  polling has fully recovered.
- Final channel probe showed Telegram polling connected, recent outbound activity, `groups:unmentioned`,
  `works`, and `audit ok`.

## 48. AgentMail poll containment after football topic no-reply

Date: `2026-06-24`

Problem:

- A fresh user message in Telegram forum topic `11` again received no automatic answer.
- The Gateway had restarted at the same time with `exit=137`, `oom=false`, and no normal JavaScript
  exception in the Gateway log.
- Docker events showed two AgentMail 5-minute `openclaw agent` execs started in parallel inside
  `openclaw-gateway` immediately before the container died. This made the football no-reply look like
  a Telegram/model issue, but the direct cause was AgentMail poll load killing the shared Gateway.

Actions:

- Stopped both AgentMail bridge containers to stop the recurring 5-minute overload while diagnosing.
- Changed the shared AgentMail bridge so `poll_llm_enabled` defaults to `false`; the poll path now uses
  the deterministic prefilter/label fallback without launching an OpenClaw agent turn unless explicitly
  re-enabled.
- Updated both AgentMail deploy helpers to propagate `poll_llm_enabled=false` into existing server
  configs and to treat a missing legacy OpenClaw cron store as a warning because host cron owns digest
  delivery.
- Redeployed `agentmail-email-bridge` and `agentmail-work-email-bridge`, repaired the partially
  interrupted `work-email` env hydration, and restarted both bridge containers.
- Tried to enable Telegram typing feedback with `channels.telegram.typingIndicator=true`, but
  OpenClaw 2026.6.9 rejected that key as an additional property. The config change was rolled back and
  `openclaw-gateway` was recreated successfully.
- Sent the missed Botafogo-player answer directly to the football topic so the chat was not left
  without a reply.

Validation:

- Local AgentMail tests passed: `test_poll_prefilter` (`8 tests OK`) and `test_footer` (`11 tests OK`).
- `bash -n` passed for both AgentMail deploy helpers.
- Both live AgentMail configs reported `poll_llm_enabled=false`.
- The next personal and work 5-minute polls self-enqueued without creating any `openclaw agent` exec
  event in `openclaw-gateway`.
- `openclaw-gateway` returned healthy after rollback of the unsupported typing key, with
  `primary=openai/gpt-5.5` and `fallbacks=[deepseek-direct/deepseek-chat]`.
- Telegram channel probe returned enabled, connected, polling, `groups:unmentioned`, `works`, and
  `audit ok`.

## 49. OpenClaw 2026.6.9 Telegram ingress hotfix

Date: `2026-06-24`

Problem:

- After AgentMail poll containment, fresh user messages in Telegram forum topic `11` still sometimes
  produced no automatic answer.
- Gateway health, Telegram channel status, model probes, and outbound `sendMessage` delivery all
  looked healthy, but fresh UI messages did not advance the Telegram update offset and did not log
  `Inbound message telegram:...`.
- The earlier post-upgrade validation was incomplete: `openclaw agent --deliver` proved model
  execution plus outbound Telegram delivery, but did not prove the Telegram UI ingress path.
- This was not a Telethon issue. Telethon is used by digest/MTProto jobs; the interactive Sir Ben'ka
  bot receives Telegram messages through Bot API polling inside OpenClaw.

Actions:

- Enabled live Telegram ingress diagnostics with `OPENCLAW_LOG_LEVEL=debug` and
  `OPENCLAW_DEBUG_TELEGRAM_INGRESS=1`.
- Confirmed the live Gateway was running `OpenClaw 2026.6.9` with
  `primary=openai/gpt-5.5` and `fallbacks=[deepseek-direct/deepseek-chat]`; the model route was not
  changed to DeepSeek primary.
- Checked webhook state, bot permissions, topic config, local token holders, and Telegram spool
  counts. Webhooks were disabled, the bot could read group messages, the football topic did not
  require mentions, and no local bridge was consuming updates with `getUpdates`.
- Found that OpenClaw 2026.6.9 defaults Telegram Bot API ingress to an internal
  `isolatedIngress.enabled=true` path. The public config schema does not expose this as an ordinary
  `openclaw.json` key.
- Patched the derived OpenClaw image so `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0` disables the isolated
  worker and uses the regular polling handler.
- Built and deployed
  `openclaw-with-iproute2:20260624-slim-2026.6.9-telegram-polling-hotfix`, updated the live
  `OPENCLAW_IMAGE`, added `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0`, and recreated only
  `openclaw-gateway`.

Validation:

- The hotfix image contains the `OPENCLAW_TELEGRAM_ISOLATED_INGRESS` patch and the running Gateway
  reports `OpenClaw 2026.6.9`.
- `/healthz` returned live and Docker reported `openclaw-gateway` healthy on the hotfix image.
- Telegram channel probe returned enabled, configured, connected, `mode:polling`, `groups:unmentioned`,
  `works`, and `audit ok`.
- After the hotfix, the log showed the regular polling path instead of
  `isolated polling ingress started`.
- A recovered topic run sent a Telegram answer successfully with `telegram outbound send ok`.
- A fresh Telegram UI smoke logged `telegram ingress`, `Inbound message telegram:group:<...>:topic:11`,
  `run_completed`, `message_completed`, and `dispatchCompleteMs=18315`, proving the UI ingress path was
  restored. That short test text did not emit a separate outbound message, so future end-to-end smokes
  should use an explicit prompt such as `answer exactly OK_STATUS`.

## 50. Gateway resource containment after VPS outage

Date: `2026-07-05`

Problem:

- `maxtg_bridge` stopped delivering messages while the CX23 host was effectively offline after
  `2026-07-03 06:56 MSK`.
- The previous boot had repeated OpenClaw cgroup OOM/restart evidence, and the Gateway had a restart
  count in the twenties before the host stopped reporting metrics.
- The Gateway already had CPU/RAM/PID caps, but `restart: unless-stopped` allowed a failing Gateway to
  keep retrying indefinitely.

Actions:

- Changed the tracked Gateway policy to `restart: on-failure:5`.
- Added Docker json log rotation for the Gateway: `10m x3`.
- Added `OPENCLAW_NODE_OPTIONS=--max-old-space-size=768` so the Node heap remains below the
  `1224m` Docker memory ceiling.
- Kept host-level cgroup policy in `vps_management`; OpenClaw only owns the app-level compose and env
  template.

Validation:

- Validate the redacted compose template with `docker compose --env-file artifacts/openclaw/env.redacted.example -f artifacts/openclaw/docker-compose.redacted.yml config`.
- After deploy, verify live policy with `docker inspect openclaw-openclaw-gateway-1` and confirm
  `Restart=on-failure:5`, `Memory=1283457024`, `MemorySwap=1283457024`, `PidsLimit=256`, and log
  config `json-file max-size=10m max-file=3`.
- If the Gateway exhausts its five retries, treat the stopped container as a host-protection signal;
  inspect OOM/restart cause before manually recreating it.

## 51. AgentMail work-email scheduled delivery recovery

Date: `2026-07-06`

Problem:

- New mail reached `workmail.denny@agentmail.to`, and the `agentmail-work-email-bridge` poll path was
  healthy, but scheduled Telegram recaps were not appearing in the `work-email` topic.
- Live host cron was installed for all eight work-email digest slots, but `/var/log/agentmail-work-email-cron.log`
  showed repeated `Permission denied` failures when cron executed the trigger script directly.

Actions:

- Verified sanitized live state: bridge container up, `GET /health` ok, work config targeting
  `work-email`, `poll_llm_enabled=false`, forwarded-sender resolution enabled, `workmail/*` labels
  present, and Telegram chat/topic env values matching the intended work topic.
- Restored live trigger script modes to `0755`.
- Changed the tracked work-email deploy helper so `/etc/cron.d/agentmail-work-email` invokes the
  trigger through `bash /opt/agentmail-work-email/trigger-email-digest.sh ...`.

Validation:

- Manual `interval` digest trigger with a 240-minute lookback finished with `exit_code=0`.
- The run rendered `3` messages across `3` threads, counted `2` important and `1` low-signal message,
  and applied `workmail/digested=3`.
- The OpenClaw Gateway stayed healthy and legacy `AgentMail Work Email · ...` OpenClaw Cron jobs were
  absent from the checked cron store path.

## 52. OpenClaw 2026.6.11 upgrade assessment

Date: `2026-07-06`

Problem:

- Production was on `OpenClaw 2026.6.9` with a local Telegram polling hotfix, while upstream had newer
  stable and beta releases available.

Findings:

- Live Gateway remained healthy on `openclaw-with-iproute2:20260624-slim-2026.6.9-telegram-polling-hotfix`.
- Live `openclaw --version` reported `OpenClaw 2026.6.9`.
- The live route stayed `openai/gpt-5.5` primary with `deepseek-direct/deepseek-chat` fallback.
- GitHub/GHCR check showed `OpenClaw 2026.6.11` as the latest stable candidate and
  `2026.7.1-beta.2` as a pre-release candidate; both slim image manifests were available.

Decision:

- Do not upgrade production during this pass.
- Do not deploy the `2026.7.1-beta.2` pre-release to production.
- Treat `2026.6.11-slim` as the next stable candidate only after building the derived `iproute2` image
  and validating fresh Telegram UI ingress plus outbound replies, because the current production image
  carries the local `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0` hotfix.

## 53. LadyTraderVIP source deployment and OpenClaw 2026.6.11 canary rollback

Date: `2026-07-10`

Actions:

- Resolved exactly one authorised Telethon dialog for the new private market source and added it only
  to ignored signals runtime configuration. The rule reuses the existing no-author FX/Si vocabulary
  and begins with a 15-minute bootstrap window.
- Built a derived `OpenClaw 2026.6.11` image with `iproute2` and the Telegram isolated-ingress kill
  switch. Image version, config validation, Gateway health, Telegram channel probe, and direct
  DeepSeek reserve smoke all passed.
- Sent a marked MTProto message from the owner session to a registered topic. It produced neither an
  inbound Gateway event nor a bot reply on the candidate; the same scripted route could not prove
  ingress after restoring the previous image either. The Gateway was therefore restored
  conservatively to `openclaw-with-iproute2:20260624-slim-2026.6.9-telegram-polling-hotfix`; this is
  a missing manual UI release proof, not a confirmed `2026.6.11` regression.
- Deployed the private signals configuration only after the rollback health gate. The restart exposed
  a stale Redis `ruleset` lock from the interrupted run, so the bridge now releases only configured
  ruleset locks at startup; a subsequent source-only run completed successfully.

Validation:

- The restored Gateway returned `OpenClaw 2026.6.9`, `/healthz` live status, and a healthy Telegram
  polling probe.
- The new source-only signals run scanned `76` messages, matched `0`, posted `0`, and returned bridge
  health `ok=true` with no source errors.

## 54. OpenClaw version compatibility ledger

Date: `2026-07-10`

Decision:

- Treat the derived Gateway image and its local adaptations as versioned compatibility knowledge,
  not as isolated one-off fixes.
- Establish `docs/22-openclaw-version-compatibility-ledger.md` as the canonical pre-upgrade record;
  image history remains in the installation document and detailed chronology remains in this log.

Recorded active findings:

- the derived image must continue to provide `iproute2` for the selected Gateway network mode;
- the current production image retains the Telegram isolated-ingress kill switch until a candidate
  proves the real UI path without it;
- auth-store/provider transport and direct reserve-model behavior require version-specific probes
  after upgrades;
- the 2026.6.11 candidate is held because the available scripted MTProto smoke cannot prove the
  Telegram UI path on either candidate or baseline, not because an upstream regression is confirmed.
- every retained image version now has an explicit ledger entry, including releases with no
  version-specific incompatibility in the retained evidence.

Process:

- every candidate now starts with a ledger record naming its known-good rollback image and required
  gates;
- active workarounds are carried deliberately and can be removed only with the record's stated proof;
- promotion requires generic health/config/model checks plus a fresh manual Telegram UI inbound event
  and outbound reply whenever OpenClaw or its Telegram implementation changes;
- an incomplete or failed gate requires rollback to the known-good image and a `held` or
  `rolled-back` ledger status with sanitized evidence.

## 55. Signals Russian-yuan inflection repair

Date: `2026-07-13`

Problem:

- A valid FX signal from a configured private Telegram source used the Russian form `юане` and did
  not reach the `signals` topic.
- The source and no-author `content_keywords` rule were enabled, but the deterministic matcher only
  recognized the base form `юань` and a few trading-slang aliases. Its whole-word guard correctly
  prevented partial matches, but also excluded the standard inflection.

Actions:

- Added the complete standard Russian yuan word forms to the alias set used by canonical `юань`,
  `cny`, and `yuan` keywords. The existing whole-word guard remains in place, so unrelated longer
  words are not accepted.
- Added regression coverage for the exact missed wording and for the private-source `content_keywords`
  rule shape.
- Rebuilt and recreated the live `signals-bridge`, then enqueued one source-only 60-minute repair
  run to catch up the missed message without reprocessing unrelated sources.

Validation:

- The local real-rule check matches the previously missed message after the fix.
- Full signals suite: `90` tests passed; `compileall` and `git diff --check` passed.
- The live repair run scanned `76` source messages, matched and posted `1` fresh event, relayed its
  original source content, and reported zero source errors, drops, or duplicates.
