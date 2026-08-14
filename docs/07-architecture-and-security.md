# Architecture And Security

## Architecture overview

This deployment intentionally separates public access, application runtime, and unrelated workloads.

```text
Browser
  -> TLS + client certificate
  -> Caddy (80/443)
     -> reverse proxy (HTTP + WebSocket) to 127.0.0.1:18789
        -> OpenClaw gateway container (single UI + API source)
           -> provider auth profiles
           -> workspace and task state
           -> upstream model/provider access

Existing app (deploy-bridge-1)
  -> separate project
  -> unchanged
```

## Main components

### Caddy

Role:

- public TLS termination
- mandatory client certificate validation
- reverse proxy for full OpenClaw traffic (HTTP + WebSocket)

Why it matters:

- keeps the OpenClaw gateway off the public internet
- gives one clean trust boundary at the edge

### OpenClaw gateway

Role:

- application backend
- websocket endpoint
- auth profile usage
- agent/runtime orchestration

The active Gateway model-policy boundary is OpenAI primary, DashScope Qwen as
first direct reserve, and DeepSeek as final LLM-only reserve. The expected
derived image was rebuilt from its pinned source on 2026-08-14; health,
configuration, and controlled Qwen text-route checks passed. Automatic media
understanding is disabled for this text-only reserve policy. Both provider keys
remain env SecretRefs; neither is a retrieval-embeddings key.

Current auth mode:

- token auth at the gateway layer

### Host OS boundary

Role:

- Docker host
- reverse-proxy host
- SSH/admin surface

Intentional non-role:

- not the place for OpenClaw runtime add-ons such as `whisper`, `ffmpeg`, or other agent-facing toolchains

Why it matters:

- avoids "installed on the server but missing in the app runtime" confusion
- keeps operational drift smaller
- makes runtime verification deterministic

### Derived OpenClaw image

Role:

- same upstream runtime, plus deployment-required runtime dependencies

Why it exists:

- the selected network mode required the `ip` binary at runtime
- the upstream image did not provide it
- OpenClaw-adjacent tools such as `ffmpeg` and `whisper` must live where OpenClaw actually executes commands

### Version compatibility ledger

The derived image is a controlled compatibility layer, not an untracked collection of fixes. The
[OpenClaw Version Compatibility Ledger](22-openclaw-version-compatibility-ledger.md) records every
active local adaptation, failure signature, required release gate, and rollback relationship. This
keeps upstream upgrades reproducible: a candidate must deliberately carry or revalidate each
adaptation, rather than silently dropping a patch because its base image changed.

### Control UI delivery strategy

Current strategy:

- Control UI is delivered by OpenClaw gateway itself
- `Caddy` forwards all browser traffic to the gateway instead of serving a host-side UI copy

Why it matters:

- avoids UI/backend version drift between copied static assets and running OpenClaw build
- keeps runtime behavior deterministic during upgrades and rollbacks

## Security model

## Edge protection

- only `80/443` are publicly exposed for the application
- SSH remains administrative only
- direct OpenClaw ports stay bound to host loopback

## Client authentication

Primary public access control:

- `mTLS`

Effect:

- a browser without the trusted client certificate should not obtain usable access

## Application authentication

Inside the trusted edge:

- OpenClaw still requires its own gateway token for websocket access

This creates layered access control:

1. edge trust via client certificate
2. application trust via OpenClaw token/auth flow

## Secret handling

Sensitive items intentionally kept out of tracked docs:

- server access details
- raw `.env`
- provider auth profiles
- client certificates
- client certificate passwords
- tokenized browser URLs
- reverse proxy private keys

Storage approach:

- local-only files under `secrets/`
- local-only server notes under `LOCAL_ACCESS.md`
- redacted copies only under `artifacts/`

## Trust boundaries

### Public internet to edge

Trusted only after:

- valid TLS
- valid client certificate

### Edge to OpenClaw

Trusted path:

- localhost proxy hop only

### Host OS to container runtime

Operational rule:

- host-level package installs do not count as OpenClaw runtime installs
- if a binary must be visible to OpenClaw, it must exist in the derived image or in a container-mounted path intentionally consumed by the runtime

### OpenClaw to model/provider layer

Trusted by:

- server-resident OpenClaw auth profile

## Operational risks and trade-offs

### Upstream image assumptions

The deployment depends on behavior not fully captured by the upstream image defaults. That is why the derived image exists.

### Startup convergence window

A strict readiness probe (`/healthz`) can report `starting` or `unhealthy` during cold boot and internal gateway restarts before converging to `healthy`.

### Short-lived proxy errors during restart

If the gateway restarts (for example after config changes), the edge proxy can briefly return `502` until the backend is listening again.

### Shared VPS failure boundary

This application shares host resources with other workloads, but it does not
own their routing/edge data-plane. A Docker/resolver `systemd` ordering cycle
can keep an edge component from starting after boot; OOM/CPU pressure is a
separate capacity signal unless evidence proves otherwise. The cross-project
contract deliberately forbids broad Docker restart loops, volume cleanup and
unscoped firewall changes during diagnosis. See
[Shared VPS incident contract](23-shared-vps-incident-contract.md).

## Applied OpenClaw security settings

Reference: [docs.openclaw.ai/gateway/security](https://docs.openclaw.ai/gateway/security)

These settings are applied in `/opt/openclaw/config/openclaw.json` on the server.
The redacted copy lives in `artifacts/openclaw/openclaw.json`.

### Gateway hardening

| Setting | Value | Reason |
|---|---|---|
| `gateway.auth.allowTailscale` | `false` | Tailscale not used; disable identity header acceptance |
| `gateway.auth.rateLimit` | `{}` (defaults) | Enable brute-force protection on auth endpoints |
| `gateway.trustedProxies` | `[<docker-bridge-gateway-ip>]` | Trust Caddy's forwarded headers for client IP; actual IP in `LOCAL_ACCESS.md` |
| `gateway.allowRealIpFallback` | `false` | Prefer `X-Forwarded-For` only; no `X-Real-IP` fallback |

### Tool execution policy

| Setting | Value | Reason |
|---|---|---|
| `tools.profile` | `"coding"` | OpenClaw stays focused on orchestration and LLM work; source-specific I/O (like AgentMail) lives in dedicated bridges |
| `tools.exec.security` | `"deny"` | No host shell execution from agents |
| `tools.exec.ask` | `"always"` | Approval prompts for any exec attempt |
| `tools.fs.workspaceOnly` | `true` | Filesystem tools limited to mounted workspace |
| `tools.elevated.enabled` | `false` | No privileged execution mode |

Note: the stack now uses `tools.profile: "coding"` because the email ingestion pipeline no longer depends on MCP-delivered AgentMail tools. Safety still relies on `tools.exec.security: "deny"`, `tools.exec.ask: "always"`, `tools.fs.workspaceOnly: true`, and controlled bridge-side automation.

### Operational note: gateway startup time

With these security settings applied, gateway startup time increased to ~2 minutes (vs ~30s before). This is expected — additional config validation and plugin initialisation at boot. The Compose `healthcheck.start_period` (10s) is shorter than the actual startup, so the container briefly reports `unhealthy` before converging to `healthy`. End-user impact: none (Caddy returns 502 only during the ~2 minute window after a `docker compose restart`).

### Logging

| Setting | Value | Reason |
|---|---|---|
| `logging.redactSensitive` | `"tools"` | Redact secrets from tool output (note: `"all"` is not supported in 2026.4.2; allowed values: `"off"`, `"tools"`) |

### Network and discovery

| Setting | Value | Reason |
|---|---|---|
| `discovery.mdns.mode` | `"off"` | No LAN discovery needed on VPS; reduce attack surface |
| `session.dmScope` | `"per-channel-peer"` | Session isolation between peers (safe default even with no DM channels) |

### Browser / SSRF policy

| Setting | Value | Reason |
|---|---|---|
| `browser.ssrfPolicy.dangerouslyAllowPrivateNetwork` | `false` | Block agents from reaching internal/private network destinations |

If agents need to browse specific internal hosts, add them to `browser.ssrfPolicy.allowedHostnames`.

### Caddy: HSTS

| Setting | Before | After | Reason |
|---|---|---|---|
| `Strict-Transport-Security max-age` | `300` | `31536000` | 300s was development-safe; 1 year is the production standard |

### Telegram channel access control

Telegram is configured with layered access control:

| Setting | Value | Reason |
|---|---|---|
| `channels.telegram.dmPolicy` | `"allowlist"` | DMs only from explicitly listed user IDs |
| `channels.telegram.allowFrom` | `[<owner-id>]` | Only owner can DM the bot; actual ID in `LOCAL_ACCESS.md` |
| `channels.telegram.groupAllowFrom` | `[<owner-id>]` | Explicit user allowlist for group triggers |
| `channels.telegram.groups."*".requireMention` | `true` | All groups require @mention by default |
| `channels.telegram.groups.<ops-supergroup-id>.requireMention` | `false` | Operational forum hub can run without mentions, with topic-level runtime policy |
| `channels.telegram.groups.<ops-supergroup-id>.groupPolicy` | `"open"` | Any member of the ops hub can trigger the bot inside approved operational topics |
| `channels.telegram.groups.<family-chat-id>.requireMention` | `true` | Family domain stays conservative by default |
| `channels.telegram.groups.<sandbox-chat-id>.requireMention` | `false` | Sandbox can be relaxed because production memory writes are disabled there |

Real chat IDs and topic IDs are kept in `LOCAL_ACCESS.md` (not committed). The full Telegram
surface policy lives in `docs/12-telegram-channel-architecture.md`; the redacted implementation
draft lives in `artifacts/openclaw/telegram-surfaces.redacted.json`.

Bot prerequisites: admin role in groups that need posting/topic access. If the ops supergroup must
work without mentions, Telegram BotFather privacy mode has to be disabled for the bot; because that
setting is bot-wide, OpenClaw group allowlists and runtime chat/topic filters are mandatory.

### Settings NOT applied

| Setting | Reason |
|---|---|
| `sandbox.*` | Docker-in-Docker not set up on this VPS |
| `plugins.allowlist` | No plugins configured |
| `hooks.*` | No webhooks configured |
| `gateway.auth.trustedProxy.userHeader` | Not using trusted-proxy auth mode |
| `controlUi.allowedOrigins` | Redundant — mTLS already enforces client identity at the edge |

### Dangerous flags confirmed absent

These flags are explicitly not set, confirming no security downgrades:

- `gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback`
- `gateway.controlUi.dangerouslyDisableDeviceAuth`
- `browser.ssrfPolicy.dangerouslyAllowPrivateNetwork` (set to `false`)
- `tools.exec.applyPatch.workspaceOnly` (not set to `false`)

## Signals Bridge & Last30Days Architecture

### signals-bridge

Standalone Python service (`/opt/signals-bridge/`, port 8093). Runs an internal 5-minute scheduler
independent of OpenClaw Cron Jobs. Two responsibilities:

1. **Signal routing** — polls allowlisted email (AgentMail) + Telegram sources, applies
   deterministic matching (keyword/hashtag/author rules) before any LLM call, enriches matches
   via OmniRoute `light` tier only (or local fallback), posts to `signals` Telegram topic.

   Ruleset IDs are a globally unique scheduler namespace, including ignored rule fragments. The
   bridge rejects duplicate IDs at config load so `get_ruleset`, Redis cursors, and next-due state
   cannot select a different ruleset than the scheduler enqueued. Telethon polling, source relay, and
   interactive session auth take a shared lock beside the SQLite session; transient lock contention is
   retried, while unrecovered errors become source-level health state rather than a hidden partial run.

2. **Last30Days presets** — `signals-bridge` now supports two digest modes:
   `personal-feed` (query-driven focused radar) and `platform-pulse`
   (platform-first storylines grouped by source). The scheduled daily run remains the
   personal feed at 07:00 MSK: it executes 8 thematic composite queries + 7 short
   HN-companion queries (parallel `ThreadPoolExecutor`) against the external
   `last30days.py` script, merges results, applies diversified ranking with per-source caps,
   and posts top themes to the `last30daysTrend` Telegram topic.

**Provider configuration (signals.env):**

| Env var | Value | Purpose |
|---------|-------|---------|
| `OPENROUTER_API_KEY` | `sk-or-v1-...` | Enables LLM planning/reranking in external script |
| `LAST30DAYS_PLANNER_MODEL` | `google/gemini-2.5-flash-lite` | Overrides default (invalid) model ID |
| `LAST30DAYS_RERANK_MODEL` | `google/gemini-2.5-flash-lite` | Same override for rerank step |
| `OMNIROUTE_API_KEY` | `sk-...` | Signals enrichment via internal OmniRoute |

**Source priority** (highest to lowest): `hn → web → reddit → youtube → bluesky → github → polymarket → x`

**Per-source caps:** `hn:5, web:5, reddit:5, youtube:4, bluesky:3, github:4, polymarket:2, x:2`

### YouTube source status

YouTube is architecturally supported in the external last30days script (`lib/youtube_yt.py`, yt-dlp
fallback). **Currently frozen** — yt-dlp is blocked by YouTube bot-detection on server IPs without
browser cookies; full support requires `SCRAPECREATORS_API_KEY` (paid service). The integration
point is preserved; enable by adding the key to `signals.env`.

Reddit is now free by default via a native hybrid path: `old.reddit.com` JSON for
search plus RSS fallback (`search.rss`, subreddit `search.rss`, thread
`comments.rss`). `SCRAPECREATORS_API_KEY` remains an optional tertiary backup.

### Reddit hybrid retrieval path

The production image patches the pinned upstream `last30days-skill` checkout during Docker build.
That patch injects a dedicated Reddit adapter and keeps all changes inside the same container.
There is no sidecar service, no local proxy, and no extra port to manage.

Runtime retrieval order:

1. `old.reddit.com/search.json`
2. `old.reddit.com/r/<subreddit>/search.json` for configured subreddit feeds
3. native RSS fallback:
   - global `search.rss`
   - subreddit `search.rss`
   - thread `comments.rss`
4. `SCRAPECREATORS_API_KEY` only if explicitly configured

Why this is implemented with `curl`: on the current server/runtime, Python HTTP clients were
blocked by Reddit on the JSON endpoints while `curl` returned valid responses. The adapter therefore
uses `curl` subprocess transport for Reddit JSON and RSS requests.

### Reddit feed configuration

`signals-bridge` passes subreddit hints through `last30days.platform_sources.reddit.feeds`, which
becomes `--subreddits` in the external CLI.

Recommended baseline for `personal-feed-v1`:

```json
"platform_sources": {
  "search": "x,reddit,youtube,hackernews,github,bluesky,polymarket",
  "reddit": {
    "feeds": [
      "worldnews",
      "technology",
      "science",
      "Futurology",
      "economics",
      "geopolitics",
      "artificial",
      "MachineLearning",
      "OutOfTheLoop"
    ]
  }
}
```

These feeds were chosen to balance broad personal-feed coverage:
- macro and policy: `worldnews`, `economics`, `geopolitics`
- AI and frontier tech: `technology`, `science`, `Futurology`, `artificial`, `MachineLearning`
- internet narrative spikes: `OutOfTheLoop`

### Runtime behavior and diagnostics

- JSON-backed Reddit items preserve real `score` and `num_comments`
- RSS-only items remain eligible for ranking, but carry lower-confidence transport metadata
- thread enrichment is best-effort through `comments.rss`
- failure to enrich comments does not drop the Reddit candidate
- source-level Reddit failures are no longer silently suppressed in the poster layer

Operationally, a healthy run should show:
- `last30days.source_counts.reddit > 0`
- `last30days.errors_by_source.reddit` absent or empty

Verified production result on `2026-04-14` after the hybrid patch rollout:

```json
{
  "preset_id": "personal-feed-v1",
  "source_counts": {
    "reddit": 43,
    "x": 31
  },
  "errors_by_source": {}
}
```

### wiki-import bridge

Standalone internal Python service (`/opt/wiki-import/`, port `8095`). It is the **single writer**
for curated imports into the Obsidian vault:

- saves normalized sources into `/opt/obsidian-vault/raw/articles` or `/opt/obsidian-vault/raw/documents`
- updates `/opt/obsidian-vault/wiki/**/*`
- regenerates `OVERVIEW.md`, `INDEX.md`, and `IMPORT-QUEUE.md`
- enqueues touched `wiki/**/*.md` pages into LightRAG only after the wiki write succeeds
- returns lint/import status over internal HTTP only

Why this exists:
- OpenClaw keeps `tools.fs.workspaceOnly = true`
- the bot should orchestrate imports, not gain direct RW access to the vault
- vault writes stay in a narrow operational boundary with explicit logging and queue state

Internal API:
- `GET /health`
- `GET /status`
- `POST /trigger`
- `POST /lint`
- `POST /maintain`

LightRAG ingest remains read-only and narrowed to curated wiki pages plus `raw/signals`.
Direct `POST /documents/upload` from interactive Knowledgebase/Ideas save flows is out of policy;
the only valid path is through `wiki-import`.

Operational upkeep is split from ingest:
- daily dry-run maintenance reports can surface lifecycle candidates without mutating pages
- weekly apply maintenance may archive low-signal `research/**` pages into `wiki/archive/research/**`
- archived research pages remain searchable because they still live under `wiki/**`

---

## Recommended long-term hardening

- pin the exact base image digest
- rotate client certificates on a schedule
- move from ad hoc local secrets to a formal secret manager if the project grows
- replace ad hoc tokenized browser URLs with a documented issuance flow
- keep readiness checks aligned with `/healthz` and gateway startup characteristics
- automate derived-image rebuilds so runtime dependency changes are always traceable
- if agents need shell access, re-enable `tools.exec.security: "ask"` with `tools.exec.safeBins` allowlist instead of full deny
