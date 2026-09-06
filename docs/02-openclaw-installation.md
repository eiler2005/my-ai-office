# OpenClaw Installation

> Историческая справка исходного OpenClaw. Для Hermes используйте [реестр](hermes/inventory.md), [эксплуатацию](hermes/operations.md) и [переключение/откат](hermes/cutover-rollback.md). Production остаётся на OpenClaw; эти старые команды не развёртывают Hermes.

## Goals

The deployment was designed around four constraints:

1. avoid disrupting the existing production container
2. avoid a host-wide Node/OpenClaw install
3. keep sensitive access material out of Git
4. expose OpenClaw publicly only through a hardened reverse proxy path

## Chosen deployment shape

OpenClaw was deployed as a separate Docker Compose project under `/opt/openclaw`.

Why this was chosen:

- clean isolation from the pre-existing app
- easy rollback by removing one project directory
- explicit config and workspace paths
- predictable Docker-only lifecycle
- easy capture of redacted artifacts for documentation

## Runtime boundary policy

OpenClaw is a Dockerized workload on the Hetzner server. Treat the container runtime as the application environment.

Policy:

- if a tool is needed by OpenClaw, its agents, or gateway-executed workflows, install it into the derived OpenClaw image or invoke it with `docker compose exec`
- do not install OpenClaw-adjacent runtime packages on the host OS unless the requirement is explicitly host-administrative
- when debugging command availability, verify both contexts:
  - host OS
  - `openclaw-gateway` container

This rule exists because a host-only install can appear successful while remaining invisible to the actual OpenClaw runtime.

## What differed from the upstream happy path

The real deployment did not follow the simplest upstream path end to end.

### 1. Compose and image behavior had to be aligned

The upstream Compose material and the pulled image behavior did not line up cleanly, so the local Compose file was adapted to the actual image entrypoint behavior.

### 2. OAuth bootstrap was done through a temporary local-auth transfer

To materialize a working OpenClaw auth profile in a headless server environment:

1. a local Codex auth file was copied to the server temporarily
2. OpenClaw was allowed to materialize its own provider profile
3. the temporary copied auth file was deleted again
4. the temporary mount was removed from the deployment

Result:

- OpenClaw now has its own auth profile on the server
- the temporary bootstrap file is no longer part of the live deployment

### 3. Public access evolved through several iterations

The public access path changed during debugging:

- localhost-only access over SSH tunnel
- reverse proxy experiments
- early public access protected by HTTP auth
- final public access protected by `mTLS`

The final path is the one documented here. Earlier iterations are intentionally not treated as the target architecture.

### 4. A derived runtime image became necessary

The final deployment uses a small derived image instead of the raw upstream image because `iproute2` was missing and the chosen network mode required it.

Derived image:

- `openclaw-with-iproute2:20260405`

Upgrade history:

This is an image timeline only. The authoritative record of version-specific defects, local
workarounds, and promotion/rollback gates is the
[OpenClaw Version Compatibility Ledger](22-openclaw-version-compatibility-ledger.md). A newer tag in
this list is not implicitly approved for deployment.

- `openclaw-with-iproute2:20260405` (`OpenClaw 2026.4.2`) — first stable derived image
- `openclaw-with-iproute2:20260406/07` (`OpenClaw 2026.4.5`) — startup instability; blocked
- `openclaw-with-iproute2:20260408` (`OpenClaw 2026.4.8`) — stable Whisper-enabled image used during earlier experiments
- `openclaw-with-iproute2:20260412-slim` (`OpenClaw 2026.4.8`) — intermediate slim image with Whisper removed
- `openclaw-with-iproute2:20260412-slim-2026.4.11` (`OpenClaw 2026.4.11`) — previous production; slim image retained, base OpenClaw updated
- `openclaw-with-iproute2:20260516-slim-2026.5.12` (`OpenClaw 2026.5.12`) — previous production; latest stable release verified from GitHub/GHCR and live-confirmed on `/opt/openclaw`
- `openclaw-with-iproute2:20260528-slim-2026.5.26` (`OpenClaw 2026.5.26`) — previous production; latest stable release verified from GitHub/GHCR and live-confirmed on `/opt/openclaw`
- `openclaw-with-iproute2:20260528-slim-2026.5.27` (`OpenClaw 2026.5.27`) — previous production; latest stable release verified from GitHub and live-confirmed on `/opt/openclaw`
- `openclaw-with-iproute2:20260606-slim-2026.6.1` (`OpenClaw 2026.6.1`) — previous production; latest stable release verified from GitHub/GHCR and live-confirmed on `/opt/openclaw`
- `openclaw-with-iproute2:20260619-slim-2026.6.8` (`OpenClaw 2026.6.8`) — previous production; latest stable release verified from GitHub/GHCR and live-confirmed on `/opt/openclaw`
- `openclaw-with-iproute2:20260624-slim-2026.6.9` (`OpenClaw 2026.6.9`) — previous production; latest stable release verified from GitHub/GHCR, but UI Telegram ingress required the hotfix below
- `openclaw-with-iproute2:20260624-slim-2026.6.9-telegram-polling-hotfix` (`OpenClaw 2026.6.9`) — current production; disables isolated Telegram ingress with `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0` while retaining the 2026.6.9 OpenAI/fallback repairs
- `ghcr.io/openclaw/openclaw:2026.6.11-slim` (`OpenClaw 2026.6.11`) — derived-image canary built on 2026-07-10, but the automated MTProto smoke could not establish UI ingress on either the candidate or restored image. The candidate was rolled back to `2026.6.9-telegram-polling-hotfix`; require a manual UI ingress/outbound smoke before retrying.

## Final deployed shape

### OpenClaw runtime

- gateway bind mode: `lan`
- gateway auth mode: `token`
- trusted proxies: localhost and Docker bridge
- builtin memorySearch: disabled while external embedding limits are unstable; retrieval should use LightRAG once its embedding provider is healthy
- model routing: active Gateway config uses `openai/gpt-5.5` primary with `qwen-direct/qwen3.7-flash` then `deepseek-direct/deepseek-chat` as direct fallbacks. On 2026-08-14 the exact derived image was rebuilt from its pinned base and compatibility Dockerfile; Gateway health, configuration validation, and controlled Qwen text smoke passed. Automatic image/audio/video understanding is disabled for the text-only reserves; a manual Telegram UI media retest remains separate. The
  OpenAI provider remains pinned to ChatGPT/Codex OAuth transport
  (`https://chatgpt.com/backend-api/codex`, `openai-chatgpt-responses`) so `gpt-5.5` uses the
  restored OAuth profile instead of the direct OpenAI Platform API-key path.
- Telegram Bot API ingress: isolated polling is disabled in the derived hotfix image with
  `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0`; do not confuse this path with Telethon digest jobs.
- host publish:
  - `127.0.0.1:18789:18789`
  - `127.0.0.1:18790:18790`

### Public access layer

- reverse proxy: `Caddy`
- public ports:
  - `80/tcp`
  - `443/tcp`
- access control:
  - TLS server certificate
  - mandatory client certificate for browser access
- traffic model:
  - full HTTP + WebSocket reverse proxy to `127.0.0.1:18789`
  - OpenClaw gateway serves both Control UI and backend

### Token handling

- WebSocket auth remains token-based inside OpenClaw
- routine graphical browser access uses an SSH tunnel to `http://127.0.0.1:18789/`
- old tokenized/public browser URLs are not the current operational entrypoint and must never be committed to Git

## Server-side files of interest

- `/opt/openclaw/docker-compose.yml`
- `/opt/openclaw/.env`
- `/opt/openclaw/config/openclaw.json`
- `/opt/openclaw/config/agents/main/agent/auth-profiles.json`
- `/opt/openclaw/Dockerfile.iproute2`
- `/etc/caddy/Caddyfile`
- `/etc/caddy/certs/`

## Voice transcription (currently disabled)

Assumption: `OPENCLAW_HOST` is set as described in `docs/03-operations.md`.

Current policy:

- Whisper is **not** installed on the host OS
- Whisper is **not** installed in the current OpenClaw gateway image
- the current derived image keeps only `iproute2`, which is operationally required for `bind=lan`
- the current live image tag is `openclaw-with-iproute2:20260624-slim-2026.6.9-telegram-polling-hotfix`

### Verify current absence

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    command -v whisper || echo container_whisper_absent
    command -v ffmpeg || echo container_ffmpeg_absent
    command -v ffprobe || echo container_ffprobe_absent
  "
'
```

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  command -v whisper || echo host_whisper_absent
  command -v ffmpeg || echo host_ffmpeg_absent
  command -v ffprobe || echo host_ffprobe_absent
'
```

### Future option

If voice transcription becomes important later, reintroduce it intentionally rather than by default.
Prefer one of these paths:

- a lighter CPU-first stack such as `faster-whisper`
- an external transcription API
- a separate opt-in derived image specifically for audio workflows

## Redacted artifacts in this folder

- [`../artifacts/openclaw/docker-compose.redacted.yml`](../artifacts/openclaw/docker-compose.redacted.yml)
- [`../artifacts/openclaw/caddy.redacted.Caddyfile`](../artifacts/openclaw/caddy.redacted.Caddyfile)
- [`../artifacts/openclaw/openclaw.json`](../artifacts/openclaw/openclaw.json)
- [`../artifacts/openclaw/env.redacted.example`](../artifacts/openclaw/env.redacted.example)
- [`../artifacts/openclaw/auth-profile.redacted.json`](../artifacts/openclaw/auth-profile.redacted.json)
