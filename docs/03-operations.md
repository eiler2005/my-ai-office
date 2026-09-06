# Operations

> Историческая справка исходного OpenClaw. Для Hermes используйте [реестр](hermes/inventory.md), [эксплуатацию](hermes/operations.md) и [переключение/откат](hermes/cutover-rollback.md). Production остаётся на OpenClaw; эти старые команды не развёртывают Hermes.

## SSH convention

Use a placeholder in committed docs and keep the real value only in `LOCAL_ACCESS.md`.

```bash
export OPENCLAW_HOST="deploy@<server-host>"
```

For the intuitive memory overview, read `docs/19-llm-wiki-memory-explained.md`. For the
LLM-oriented doc map, read `docs/20-llm-project-orientation.md`.

## Container-only operational rule

For this deployment, OpenClaw runtime changes happen in Docker, not on the host OS.

Use the host OS for:

- Docker and Compose management
- `Caddy`
- SSH and general system administration

Use the container runtime for:

- OpenClaw CLI checks
- runtime dependency verification
- tool execution that agents depend on

If a new OpenClaw feature requires a binary or Python package, update `/opt/openclaw/Dockerfile.iproute2`, rebuild the image, and recreate `openclaw-gateway` instead of installing the package directly on Ubuntu. Keep the sanitized template in `artifacts/openclaw/Dockerfile.iproute2` aligned with the server copy.

## Move to the OpenClaw project

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && pwd'
```

## Core runtime checks

Show Compose state:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose ps
'
```

Show Docker state:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"
'
```

Gateway logs:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose logs --tail=200 openclaw-gateway
'
```

Follow gateway logs:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose logs -f openclaw-gateway
'
```

## Voice transcription status

Voice transcription is intentionally disabled in the current production image. The VPS keeps only the runtime dependency that is operationally required for `bind=lan`:

- `iproute2` in the container image
- no `whisper`
- no `ffmpeg`
- no `ffprobe`

Verify the current absence in the same runtime context where OpenClaw actually runs:

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

And verify the host stays clean too:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  command -v whisper || echo host_whisper_absent
  command -v ffmpeg || echo host_ffmpeg_absent
  command -v ffprobe || echo host_ffprobe_absent
'
```

If voice workflows become important later, add them back intentionally via a lighter CPU-first stack or an external API rather than by default in the main runtime image.

## Restart paths

Restart OpenClaw only:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose restart openclaw-gateway
'
```

## Host clock guard for Telegram bridges

Telethon is sensitive to host clock drift. If logs show `Server sent a very new message` or
`Too many messages had to be ignored consecutively`, check server time against an HTTPS `Date`
header before debugging Telegram credentials.

On 2026-05-28, UDP NTP replies were timing out from the host, so a small systemd timer was installed
as a guard:

```bash
systemctl status openclaw-https-time-sync.timer
journalctl -t openclaw-https-time-sync -n 20 --no-pager
```

The guard reads HTTPS `Date` headers from public endpoints, corrects only small clock drift, writes
RTC, and logs the correction. It is a fallback for this VPS; normal NTP should still be preferred
when UDP/123 is available again.

## OpenAI Codex auth recovery

Current intended policy is OpenAI via OpenClaw as the normal route, then
`qwen-direct/qwen3.7-flash`, then `deepseek-direct/deepseek-chat`. The server
config was updated to that order on 2026-08-14 using the DashScope
OpenAI-compatible endpoint and `DASHSCOPE_API_KEY` env SecretRef. Gateway
was rebuilt from its pinned compatibility Dockerfile, then passed `/healthz`,
config validation, and an explicit Qwen text-route smoke. Automatic
image/audio/video understanding is disabled for the text-only Qwen/DeepSeek
reserves. A manual Telegram UI media retest remains separate from these
non-delivery checks.

Do not switch the global primary route to DeepSeek as a cooldown workaround. If OpenAI reports a
Codex subscription cooldown such as `You've reached your Codex subscription usage limit`, the intended
behavior is still `openai/gpt-5.5` primary with Qwen then DeepSeek handling a failed turn. Changing
`agents.defaults.model.primary` masks the fallback defect and makes later default-route smokes less
useful.

Do not put `omniroute/light` in the interactive Gateway fallback chain: after the 2026.6.1 upgrade it
could return `Cannot continue from message role: assistant` after compaction retries, while DeepSeek
completed the same Telegram smoke directly. Also do not use the built-in `deepseek/deepseek-v4-flash`
route as the current interactive reserve on OpenClaw 2026.6.9; the live probe failed with an unknown
model response, while the direct DeepSeek-compatible `deepseek-chat` route succeeded.

OpenClaw 2026.6.9 uses the canonical `openai/*` model route plus `openai:*` auth profiles in the
per-agent SQLite auth store. Avoid new `openai-codex:*` entries in `auth.order.openai`; they can
leave `openclaw models status --probe` with every usable OpenAI OAuth profile marked
`Excluded by auth.order for this provider`.

The OpenAI provider must stay pinned to ChatGPT/Codex OAuth transport:

```json
{
  "baseUrl": "https://chatgpt.com/backend-api/codex",
  "auth": "oauth",
  "api": "openai-chatgpt-responses",
  "models": []
}
```

Without that provider transport, `openai/gpt-5.5` can resolve to the direct OpenAI Platform
`openai-responses` path, where OAuth is rejected and the agent falls back with
`No API key found for provider "openai"`.

Symptom in Telegram:

```text
No API key found for provider "openai"
You are authenticated with OpenAI ChatGPT/Codex OAuth
Excluded by auth.order for this provider
Cannot continue from message role: assistant
```

Confirm the cause in gateway logs:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose logs --tail=250 openclaw-gateway |
    grep -E "No API key found|Excluded by auth.order|Cannot continue|model fallback|auto-compaction"
'
```

If `openclaw models auth list --provider openai --json` returns no profiles after an upgrade but
legacy `auth-profiles.json` still exists, import it into the SQLite store with the OpenClaw runtime
migration. Do not run broad `openclaw doctor --fix` unless you are ready to accept unrelated doctor
repairs such as skill toggles or session-state migrations.

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose exec -T openclaw-gateway node --input-type=module -e "
    import fs from 'node:fs';
    import { n as migrate } from '/app/dist/doctor-auth-flat-profiles-ojJQmduz.js';
    const cfg = JSON.parse(fs.readFileSync('/home/node/.openclaw/openclaw.json', 'utf8'));
    const prompter = { confirmAutoFix: async function () { return true; } };
    const result = await migrate({ cfg, env: process.env, prompter, now: function () { return Date.now(); } });
    console.log(JSON.stringify({
      detected: result.detected.length,
      changes: result.changes,
      warnings: result.warnings
    }, null, 2));
  "
'
```

Then pin the provider transport and make both auth-order layers point at the canonical `openai:*`
profile ids. The first command updates `openclaw.json`; the second updates the agent-scoped override:

```bash
ssh -tt -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose exec openclaw-gateway sh -lc "
    openclaw config set models.providers.openai \
      '\''{\"auth\":\"oauth\",\"baseUrl\":\"https://chatgpt.com/backend-api/codex\",\"api\":\"openai-chatgpt-responses\",\"models\":[]}'\'' --strict-json &&
    openclaw config set auth.order.openai \
      '\''[\"openai:default\"]'\'' --strict-json &&
    openclaw models auth order set --provider openai \
      openai:default
  "
'
```

Use the actual profile ids shown by:

```bash
openclaw models auth list --provider openai
```

Do not print token values in logs or committed docs. If no usable `openai:*` OAuth profile exists
after SQLite import, re-auth from the gateway container with
`openclaw models auth login --provider openai`.

Then restart the gateway so the running service drops the old token state:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose up -d --force-recreate openclaw-gateway
'
```

Verify the primary route and reserve route:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose exec -T openclaw-gateway sh -lc "
    openclaw models status --probe --probe-provider openai &&
    openclaw models status --probe --probe-provider qwen-direct &&
    openclaw models status --probe --probe-provider deepseek-direct &&
    openclaw config get agents.defaults.model --json
  "
'
```

Expected essentials:

```text
Auth probes
- openai/gpt-5.5 ... openai:default ... ok
- qwen-direct/qwen3.7-flash ... ok
- deepseek-direct/deepseek-chat ... ok

Model policy
- primary: openai/gpt-5.5
- fallback: qwen-direct/qwen3.7-flash
- final reserve: deepseek-direct/deepseek-chat
```

Finish with a real default-route agent smoke and require `fallbackAttempts=0` before treating the
primary route as healthy.

During an OpenAI cooldown incident, run an explicit reserve smoke as well, but leave the model policy
unchanged:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose exec -T openclaw-gateway sh -lc "
    openclaw agent --agent main --model deepseek-direct/deepseek-chat \
      --message OK_DEEPSEEK_RESERVE_SMOKE --json
  "
'
```

If the default route surfaces `FailoverError` instead of answering through the reserve, keep the
primary as OpenAI, capture the failing transcript/log lines, then recreate only `openclaw-gateway` and
repeat both the default-route and explicit-reserve smokes.

Important: if the Telegram topic still posts an auto-compaction warning after auth is fixed, reset
only the affected `sessions.json` mappings (`agent:main:main` and the topic session key), preserve
their transcript files under `sessions/reset-backups/<incident-id>/`, recreate the Gateway, and send
a short `обсуди:` smoke in the affected topic.

## OpenClaw auto-compaction reserve

If Telegram or Gateway sessions show:

```text
Auto-compaction could not recover this turn
increase your compaction buffer by setting agents.defaults.compaction.reserveTokensFloor
```

confirm the live value:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose exec -T openclaw-gateway \
    openclaw config get agents.defaults.compaction.reserveTokensFloor
'
```

As of 2026-05-28, the live Gateway is set to `20000`. The value was applied with
`openclaw config set agents.defaults.compaction.reserveTokensFloor 20000 --strict-json`, followed
by a Gateway restart. A default agent smoke then returned through `openai/gpt-5.5`.

If the value is already correct but a Telegram topic still posts the recovery warning, inspect stale
session mappings. A long transcript can keep failing with `already_compacted_recently` even after the
global reserve is fixed. The safe recovery is:

1. Back up `/opt/openclaw/config/agents/main/sessions/sessions.json`.
2. Back up the session files referenced by the affected keys.
3. Remove only the stale keys from `sessions.json`.
4. Recreate `openclaw-gateway` so the in-memory mapping cache is cleared.
5. Send a short Telegram smoke in the affected topic and verify a fresh session is created.

For the `Knowledgebase` topic this was done on 2026-05-31 for:

```text
agent:main:telegram:group:<ops-supergroup-chat-id>:topic:232
agent:main:main
```

The removed records were copied to
`/opt/openclaw/config/agents/main/sessions/reset-backups/knowledgebase-compaction-<timestamp>/`
before the Gateway restart.

## Telegram ingress spool recovery

OpenClaw Telegram isolated polling writes incoming updates to
`/home/node/.openclaw/telegram/ingress-spool-default` inside the Gateway container. A Gateway
recreate can leave old `.json.processing` claims behind. If the new container reuses the same PID,
OpenClaw may treat those old claims as live and stop draining the lane even though Bot API polling
still receives updates.

Separate inbound failures from manual delivery checks. A successful
`openclaw agent --session-key ... --deliver` proves model execution and Telegram outbound delivery,
but it does not prove that a fresh user message from the Telegram UI was received by isolated polling.
For no-reply incidents, verify the affected topic session timestamp changes after a new UI message,
or capture the missing update as an ingress defect.

Symptoms:

- Gateway `/healthz` is OK.
- Telegram logs show `isolated polling ingress started`.
- New user messages get no reply.
- The spool has `.json` or `.json.processing` files that do not drain.
- Manual `--deliver` smokes can still post into the topic.

Check the spool:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker exec openclaw-openclaw-gateway-1 sh -lc '"'"'
    d=/home/node/.openclaw/telegram/ingress-spool-default
    printf "pending=%s processing=%s failed=%s\n" \
      "$(find "$d" -maxdepth 1 -name "*.json" | wc -l)" \
      "$(find "$d" -maxdepth 1 -name "*.processing" | wc -l)" \
      "$(find "$d" -maxdepth 1 -name "*.failed" | wc -l)"
  '"'"'
'
```

Safe recovery guard:

```bash
export OPENCLAW_HOST="deploy@<server-host>"
scripts/recover-telegram-ingress-spool.sh
```

The script requeues only `.json.processing` files whose claim timestamp is older than the current
`openclaw-gateway` container start time. It does not touch active in-process updates from the current
container.

Install the live cron guard:

```bash
export OPENCLAW_HOST="deploy@<server-host>"
scripts/recover-telegram-ingress-spool.sh --install-cron
```

This installs `/usr/local/sbin/openclaw-telegram-spool-guard` and
`/etc/cron.d/openclaw-telegram-spool-guard`. The cron runs once per minute and logs only when it
actually requeues or drops stale duplicate processing files.

## OpenClaw version compatibility ledger

Before any OpenClaw image update, read the
[OpenClaw Version Compatibility Ledger](22-openclaw-version-compatibility-ledger.md). It is the
release decision record for local image adaptations, blocked versions, historical symptoms, required
validation, and the known-good rollback target.

Use this order for every candidate:

1. Create or update the candidate record, name the known-good parent image, and back up the current
   image reference and Gateway configuration.
2. Carry all active workarounds into the derived image; verify the expected source/compiled patch
   rather than relying on a filename or a release note.
3. Run image version, configuration, `/healthz`, primary and reserve-model, and Telegram channel
   probes.
4. Run every version-specific gate named by the active ledger records.
5. Send a fresh manual Telegram UI prompt and require both an inbound Gateway event and an outbound
   reply before promotion. Channel probes and `openclaw agent --deliver` do not prove this path.
6. On any failed or incomplete gate, restore the ledger's known-good image, recreate the Gateway,
   validate the restored service, and mark the candidate `held` or `rolled-back` with the evidence.

Do not retire a local workaround without the exact removal proof specified in its ledger record.

## Telegram isolated polling kill switch

OpenClaw 2026.6.9 can run Telegram Bot API ingress through a separate isolated polling worker. If
the Gateway is healthy, Telegram status reports `mode:polling`, outbound Telegram sends work, but a
fresh message from the Telegram UI does not log `Inbound message telegram:...`, treat this as an
ingress defect rather than a model fallback defect. Telethon upgrades do not affect this path:
Telethon is used by digest/MTProto jobs, while the interactive OpenClaw bot receives messages through
Telegram Bot API polling.

The derived OpenClaw image carries a local kill switch:

```bash
OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0
```

With the switch set, the Telegram plugin uses the regular polling handler instead of the isolated
worker/spool path. Keep `openai/gpt-5.5` as the primary route and
`deepseek-direct/deepseek-chat` as the reserve fallback; do not make DeepSeek the global primary just
to work around an OpenAI cooldown or an ingress outage.

The `2026.6.11` derived-image canary confirmed that a green `/healthz`, `openclaw config validate`,
reserve-model smoke, and `openclaw channels status telegram --probe` do **not** prove Telegram UI
ingress. A scripted MTProto message produced neither an inbound event nor a bot reply on the
candidate or restored image, so it cannot diagnose an upstream regression. Retain a manual UI
inbound/outbound smoke as the release gate before retrying the candidate.

Validation after enabling the switch:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose up -d --no-deps --force-recreate openclaw-gateway &&
  sudo docker exec openclaw-openclaw-gateway-1 sh -lc '"'"'
    openclaw channels status telegram --probe
    tail -n 500 /tmp/openclaw/openclaw-$(date +%F).log |
      grep -Ei "telegram ingress|Inbound message|telegram outbound send ok|isolated polling"
  '"'"'
'
```

For a real smoke, send a fresh message from the Telegram UI and require both an inbound line and a
final outbound line. `openclaw agent --deliver` is still useful, but it only proves model execution
and outbound delivery; it does not prove the Telegram UI ingress path.

## Docker resource guardrails

The live `CX23` currently exposes `2 vCPU` and about `3.7GiB` RAM. Keep roughly 20-25% CPU headroom
for SSH, Docker, Redis, Caddy/networking, and lightweight bridge services. The active caps are:

```text
openclaw-gateway  0.90 CPU  1224m RAM / no swap  256 pids  restart on-failure:5  logs 10m x3  Node heap 768m
omniroute         0.25 CPU   512m RAM / no swap  128 pids
lightrag          0.45 CPU  2304m RAM / 2816m swap  128 pids
```

The combined CPU cap for the main AI path is `1.60` out of `2.00` vCPU. Do not reduce LightRAG
memory below `2304m` without rebuilding/pruning its graph: the current graph is about `20k` nodes /
`26k` edges, and a `1536m` cap caused `Exit 137` during cold start.

These are active Compose settings, not advisory examples. OpenClaw Gateway's app-level defaults live
in `/opt/openclaw/docker-compose.yml`; host guardrails from `vps_management` are persisted in
`/opt/openclaw/docker-compose.override.local.yml`. LightRAG limits live in
`/opt/lightrag/docker-compose.override.local.yml`.

`openclaw-gateway` intentionally uses `restart: on-failure:5`. If it stops after exhausting that
budget, inspect OOM/restart evidence before starting it again; do not change it back to
`unless-stopped` to hide a resource storm.

Check applied limits, not only YAML:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  for c in openclaw-openclaw-gateway-1 omniroute lightrag-lightrag-1; do
    sudo docker inspect "$c" \
      --format "$c NanoCpus={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}} PidsLimit={{.HostConfig.PidsLimit}} Restart={{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}} Log={{.HostConfig.LogConfig.Type}}"
  done
'
```

### Shared VPS incident boundary

A routing managed-egress outage, a Docker boot-order warning and OpenClaw OOM
evidence are separate signals until the respective data-plane, unit-graph and
resource checks prove a link. Do not turn the bounded restart policy into an
unlimited restart loop or restart the full Docker stack as a first response.
Use [Shared VPS incident contract](23-shared-vps-incident-contract.md) for the
owner split, safe read-only evidence and closure criteria.

## LightRAG embedding-provider recovery

Current live status after the 2026-05-31 recovery:

- LightRAG health and document status endpoints are live.
- LightRAG retrieval is active through `wiki-import` local embeddings.
- `wiki-import` normally has an empty `WIKI_IMPORT_RAG_DEGRADED_REASON`, so explicit Telegram saves
  enqueue their touched wiki pages to LightRAG instead of stopping at wiki-save.
- The embedding model is `local/hash-embedding-3072` through `http://wiki-import:8095/v1`, with
  `EMBEDDING_DIM=3072`.
- LightRAG LLM extraction currently uses direct DeepSeek (`deepseek-chat`) because OmniRoute `light`
  returned `api_bridge_timeout` during document extraction. OmniRoute `light` was switched to Qwen
  first with DeepSeek final reserve on 2026-08-14, but LightRAG itself remains direct DeepSeek until
  a dedicated Qwen-first extraction smoke passes.
- The Codex/OpenAI subscription fallback works for Gateway chat responses, but it does not provide a
  usable API embeddings route for LightRAG. DeepSeek is an LLM reserve only.

If Telegram shows `LightRAG: degraded`, first verify the local endpoint from the LightRAG container:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag
  docker compose -f docker-compose.yml -f docker-compose.override.yml exec -T lightrag python - <<'"'"'PY'"'"'
import json, os, urllib.request
payload = json.dumps({"model": "local/hash-embedding-3072", "input": ["smoke"], "dimensions": 3072}).encode()
req = urllib.request.Request(
    "http://wiki-import:8095/v1/embeddings",
    data=payload,
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["EMBEDDING_BINDING_API_KEY"]},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode())
print(len(data["data"][0]["embedding"]))
PY
'
```

Then restart LightRAG if the env changed and requeue pending/failed documents:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag
  docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --force-recreate lightrag
  curl -sf -X POST http://127.0.0.1:8020/documents/reprocess_failed
'
```

Only use degraded mode as a temporary pressure valve:

```bash
WIKI_IMPORT_RAG_DEGRADED_REASON="LightRAG indexing paused: embeddings route is degraded; wiki save is complete and indexing will resume after embeddings quota/credentials are restored."
```

That keeps `raw/**` and `wiki/research/**` writes successful while embedding/indexing is being
repaired. Clear the variable again once `/v1/embeddings` from the LightRAG container succeeds.

If a paid OpenRouter embeddings route is restored, `scripts/sync-omniroute-openrouter-provider.sh`
can refresh OmniRoute's encrypted provider record. Changing embedding providers without changing
`EMBEDDING_DIM=3072` avoids immediate crashes, but old vectors and new vectors are not semantically
identical. Plan a backed-up full rebuild of `/opt/lightrag/data/` after any provider switch.

If Telegram shows the same "Model login failed" text but the session JSONL contains an error such
as `You have hit your ChatGPT usage limit (...) Try again in ~N min.`, the OAuth profile is not the
root cause. That is a primary-model usage-limit failure. The live gateway was patched on
2026-04-26 so embedded-agent `stopReason=error` results are rethrown into `runWithModelFallback`
and can attempt the configured fallback chain. The same live patch also
adds a user-facing usage-limit message before OAuth/login classification, so Telegram should say
that OpenAI Codex hit a temporary ChatGPT usage limit instead of recommending OAuth re-auth.

Validate the reserve independently before relying on it:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo docker compose exec -T openclaw-gateway sh -lc '"'"'
    KEY=$(node -e "const fs=require(\"fs\"); const c=JSON.parse(fs.readFileSync(\"/home/node/.openclaw/openclaw.json\",\"utf8\")); process.stdout.write(c.models?.providers?.omniroute?.apiKey || \"\")")
    curl -sS -m 60 -o /tmp/omni-smoke.json -w "http=%{http_code}\n" \
      -H "Authorization: Bearer $KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"light\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply exactly OK\"}],\"max_tokens\":8}" \
      http://omniroute:20129/v1/chat/completions
  '"'"'
'
```

`http=503` with `all upstream accounts are inactive` means OpenClaw will try the reserve, but
OmniRoute cannot currently answer until its upstream provider quotas/credits/spending caps are
restored.

Recreate OpenClaw:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose up -d --force-recreate openclaw-gateway
'
```

Reload `Caddy`:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo caddy validate --config /etc/caddy/Caddyfile &&
  sudo systemctl reload caddy
'
```

## Connecting to the OpenClaw web UI

The graphical OpenClaw UI is opened through an SSH tunnel. Do not use the old
public sslip.io URL for normal browser access.

### Step 1 - Open the UI tunnel

Keep this command running in a terminal:

```bash
ssh -N -L 18789:127.0.0.1:18789 \
  -o ProxyCommand='ssh admin@192.168.50.1 nc -w 120 %h %p' \
  deploy@204.168.239.217
```

Or use the helper script:

```bash
./scripts/openclaw-ui-tunnel.sh
```

### Step 2 - Open the local browser URL

Open:

```text
http://127.0.0.1:18789/
```

If local port `18789` is busy, use another local port:

```bash
ssh -N -L 18790:127.0.0.1:18789 \
  -o ProxyCommand='ssh admin@192.168.50.1 nc -w 120 %h %p' \
  deploy@204.168.239.217
```

Then open:

```text
http://127.0.0.1:18790/
```

The helper script supports the same fallback:

```bash
LOCAL_PORT=18790 ./scripts/openclaw-ui-tunnel.sh
```

### Step 3 - Start a session

The Control UI opens in a ready state. To begin a conversation:

- type a message and press Enter
- the bot loads workspace files at the start of each new session

**Starting a fresh session** (reloads all workspace files):

```
/new
```

Use `/new` after deploying updated workspace files, or when switching context to avoid token waste from a long previous session.

### Troubleshooting connection issues

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `bind: Address already in use` | Local port `18789` is occupied | Use `18790` locally: `LOCAL_PORT=18790 ./scripts/openclaw-ui-tunnel.sh` |
| Browser cannot connect to `127.0.0.1:18789` | Tunnel is not running or exited | Restart the tunnel and keep the terminal open |
| SSH fails at the bastion hop | ProxyCommand path failed | Verify `ssh admin@192.168.50.1` works from the current network |
| Page loads but bot does not respond | Gateway may be restarting | Wait ~90s after a restart, then reload |
| SSH times out before banner | Hetzner Firewall may have narrowed | Open Hetzner Console, verify `22/tcp` is allowed from your IP |

## Workspace management

Workspace files define the bot's identity, behaviour, and long-term memory.

### View current workspace files on server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "ls -la /home/node/.openclaw/workspace/"'
```

### Read a specific workspace file

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/MEMORY.md"'
```

### Deploy updated workspace templates from git

```bash
export OPENCLAW_HOST="deploy@<server-host>"
./scripts/deploy-workspace.sh
```

Then start a new session in the bot (`/new`) to reload the files.

### Read today's daily memory log

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/memory/$(date +%Y-%m-%d).md 2>/dev/null || echo no-log-yet"'
```

### Edit a workspace file directly on server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'sudo nano /opt/openclaw/workspace/MEMORY.md'
```

Note: changes take effect on the next bot session start (`/new`). If you edit directly, sync changes back to `workspace/` in git to keep templates current.

## Files worth backing up

### OpenClaw

- `/opt/openclaw/.env`
- `/opt/openclaw/docker-compose.yml`
- `/opt/openclaw/config/openclaw.json`
- `/opt/openclaw/config/agents/main/agent/auth-profiles.json`
- `/opt/openclaw/Dockerfile.iproute2`

### Reverse proxy and certificates

- `/etc/caddy/Caddyfile`
- `/etc/caddy/certs/`

### Existing application

- `/opt/maxtg-bridge/`

## Security verification

### Confirm active tools profile

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    grep -A2 profile /home/node/.openclaw/openclaw.json 2>/dev/null || echo no-override
  "
'
```

### Verify mDNS is off

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    ss -ulnp | grep -E \"5353|mdns\" || echo mdns-absent
  "
'
```

### Verify exec security mode

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    grep -A2 exec /home/node/.openclaw/openclaw.json 2>/dev/null || echo using-config-file
  "
'
```

### Check HSTS header value

```bash
curl -skI --cert-type P12 \
  --cert /path/to/client.p12:<password> \
  https://<public-host>/ | grep -i strict-transport
# Expected: max-age=31536000
```

### Verify no private network SSRF

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    grep -A3 ssrfPolicy /home/node/.openclaw/openclaw.json 2>/dev/null || echo check-config
  "
'
```

## Run openclaw doctor

After any upgrade or config change, run doctor inside the container to catch issues early:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway openclaw doctor
'
```

No errors = config is valid. Warnings about startup optimization and `bind=lan` are expected in this deployment.

## Known operational nuances

### Startup time

Gateway takes ~90 seconds to converge from `starting` → `healthy` after a `force-recreate`. This is normal — the Compose healthcheck start period (10s) is shorter than the actual boot time, so `unhealthy` is briefly reported before the probe succeeds. Real user impact: Caddy returns `502` only during this ~90s window.

Do not confuse `unhealthy` with a broken deployment — always check `/healthz` directly:

```bash
curl -sf http://127.0.0.1:18789/healthz  # inside server
```

If this returns `{"ok":true,"status":"live"}` but Compose shows `unhealthy`, the service is fine and will flip to `healthy` on the next probe cycle.

### Startup environment variables

These are set in `/opt/openclaw/.env` to reduce startup overhead on this VPS:

```
OPENCLAW_NODE_OPTIONS=--max-old-space-size=768
NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache
OPENCLAW_NO_RESPAWN=1
```

`OPENCLAW_NODE_OPTIONS` keeps the Node heap below the Docker cgroup ceiling so the Gateway fails
inside its own budget instead of dragging the host into swap pressure.

The cache directory must exist on the host (mounted into the container):

```bash
sudo mkdir -p /var/tmp/openclaw-compile-cache
```

### bind=lan warning from doctor

`openclaw doctor` warns that `bind=lan` (0.0.0.0) is network-accessible. This is intentional: Caddy handles all public exposure via mTLS. The gateway port is only published to `127.0.0.1:18789` on the host — not externally reachable. The warning can be ignored in this architecture.

## Memory management

### Memory system overview

The bot uses a three-layer memory system. See `docs/10-memory-architecture.md` for full details.

```
LIVE > RAW > DERIVED
```

Quick rule: current-state questions → always live-check. Never answer from memory files.

LightRAG is the retrieval layer over the markdown memory corpus. It indexes workspace files and the
curated LLM-Wiki layer plus raw signal digests, then lets OpenClaw ask narrow historical questions
without loading archives into the conversation. It is useful for "what do we know about X?" and
"why did we decide Y?", but it is not authoritative for live service state.

Builtin OpenClaw `memorySearch` is the lighter local recall layer. It indexes `MEMORY.md`,
`memory/**/*.md`, and `/opt/obsidian-vault/wiki/**/*.md` directly inside the gateway using Gemini
embeddings. It intentionally does not index `raw/signals`, `raw/articles`, `raw/documents`, or
legacy vault trees; those stay on the LightRAG / curated-import side of the boundary.

On this `CX23` VPS, builtin memory is tuned conservatively: Gemini provider-side batch mode is
enabled with `concurrency=1`, the hybrid candidate pool is reduced to `2`, and MMR reranking is
disabled. This keeps future reindex runs and recall queries gentler on the host.

Data flow:

```text
workspace/*.md + workspace/memory/*.md + workspace/raw/*.md
Obsidian vault via Syncthing
  ├─ wiki/**/*.md
  └─ raw/signals/**/*.md
        ↓
/opt/lightrag/scripts/lightrag-ingest.sh
        ↓
POST /documents/upload + POST /documents/reprocess_failed
        ↓
chunks + entities + relationships + vectors
        ↓
OpenClaw lightrag_query → http://lightrag:9621/query
        ↓
Knowledge channel (Telegram) → plain-text message → search results with citations
```

### Search via Telegram Knowledge channel

Post any plain-text message in the Knowledge channel — bot responds with top results from all knowledge sources.

**Test flow:**
```
1. Write in Knowledge channel: "почему выбрали LightRAG?"
   → Bot responds with cited snippets from wiki + workspace + signals

2. Forward a post, paste a link, or write any text to save
   → Bot auto-extracts title/domain/source/date/summary and saves to wiki (✅ Сохранено: ...)
   Forwarded posts, explicit save commands, URLs, and long multiline notes must prefer ingest over conversational reply.

3. Write: "xyzzy крокодил абракадабра"
   → Bot responds: "Ничего не найдено. Попробуй другие ключевые слова."
```

**If bot doesn't respond:** check that Knowledgebase topic_id=232 is registered in `telegram-topic-map.json` and workspace is deployed.

For any forum topic where the bot should answer without an explicit mention, first verify that the
topic is registered in the live server `telegram-topic-map.json`. Unlisted topics can look like model
failures from the UI because Bot API polling may consume the update without creating an agent inbound
log. The live `football` topic is registered as `message_thread_id=11`.

If a registered forum topic still does not answer, inspect the matching session key in
`~/.openclaw/agents/main/sessions/sessions.json`, for example
`agent:main:telegram:group:<chat-id>:topic:11`. A stale or very heavy topic session can be backed up
under `sessions/reset-backups/<incident-id>/` and removed from `sessions.json` so the next inbound
creates a clean topic session. Validate with an `openclaw agent --session-key ... --deliver` smoke to
the same Telegram `topic:<id>` target. During OpenAI Codex usage cooldown, expect the clean default
route to fall back to `deepseek-direct/deepseek-chat`; the OpenAI provider probe will show the
cooldown explicitly.

### Ideas capture workflow

Forward any Telegram post, paste a link, or write any thought into the `💡 Ideas` topic (topic_id=639) — no formatting required.

**What the bot does automatically:**
1. Reads the content (forwarded post, URL, free text)
2. Extracts the essence and assigns tags (domain, source_type)
3. Scores importance; silently ignores if score < 0.35
4. Creates `raw/**` + light-curated `wiki/research/**`
5. Enqueues the touched wiki pages to LightRAG
6. Replies with a wiki-first confirmation

**Promoting to Knowledgebase:**
```
Бенька, промоутни лучшее из Ideas за эту неделю
Бенька, добавь последний пост в базу знаний
```
Bot shows the list and asks for confirmation before writing to wiki.

**Ideas now create a visible wiki research page immediately**, but promotion is still explicit for
deeper canonical enrichment.

**If bot doesn't respond to Ideas:** check that topic_id=639 is in `telegram-topic-map.json` and workspace is deployed.

### Check LightRAG health

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/health | jq .
'
```

### Check LightRAG indexing status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/documents/status_counts | jq .
'
```

Healthy indexing should converge to `failed=0`. Upload success alone is not enough: documents can
be accepted by `/documents/upload` and still fail later during LLM extraction.

For interactive explicit saves, do not use `uploaded` as the primary success criterion. First check
that a `wiki/research/**` page exists for the saved item; only then inspect LightRAG freshness.

For LLM-Wiki rollout v2, `documents/status_counts` should not suddenly jump because of legacy vault
folders or bulk `raw/articles` imports. If it does, the ingest boundary has drifted.

### View LightRAG logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag && docker compose -f docker-compose.yml -f docker-compose.override.yml logs --tail=100 lightrag
'
```

### Trigger LightRAG re-index (after bulk workspace or Obsidian changes)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  /opt/lightrag/scripts/lightrag-ingest.sh
'
```

### Check curated import bridge

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  token="$(sudo awk -F= "/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}" /opt/wiki-import/wiki-import.env | tail -n1)"
  curl -sf http://127.0.0.1:8095/health && echo
  curl -sf http://127.0.0.1:8095/status -H "Authorization: Bearer ${token}" | jq .
'
```

### Trigger curated wiki import manually

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  token="$(sudo awk -F= "/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}" /opt/wiki-import/wiki-import.env | tail -n1)"
  curl -sf -X POST http://127.0.0.1:8095/trigger \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    -d "{\"source_type\":\"url\",\"source\":\"https://example.com/article\",\"target_kind\":\"auto\",\"capture_mode\":\"knowledgebase\"}" | jq .
'
```

### Check Gateway-side wiki import wrapper

The Telegram agent does not always receive `wiki_ingest` as a native OpenClaw tool. In that case it
must use the narrow wrapper deployed into the Gateway workspace:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw
  sudo docker compose exec -T openclaw-gateway \
    python3 /home/node/.openclaw/workspace/bin/wiki_import_tool.py status | jq .
'
```

The wrapper reads the internal token from `/run/secrets/wiki_import_token`. Do not echo the token in
logs. For a manual save smoke, pass a JSON payload to `trigger` and confirm `wiki_page_paths`,
`raw_path`, and `rag_status` in the response.

### Run wiki lifecycle maintenance manually

Dry-run report:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  token="$(sudo awk -F= "/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}" /opt/wiki-import/wiki-import.env | tail -n1)"
  curl -sf -X POST http://127.0.0.1:8095/maintain \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    -d "{\"mode\":\"dry_run\",\"actions\":[\"report\"]}" | jq .
'
```

Apply safe archive + bot-managed refresh:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  token="$(sudo awk -F= "/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}" /opt/wiki-import/wiki-import.env | tail -n1)"
  curl -sf -X POST http://127.0.0.1:8095/maintain \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    -d "{\"mode\":\"apply\",\"actions\":[\"report\",\"archive\",\"refresh_topics\",\"refresh_overview\"]}" | jq .
'
```

`wiki-import` now ships with an OpenClaw cron-store sync helper:
- daily dry-run lifecycle report
- weekly safe archive + overview/topics refresh

### Backfill historical `Knowledgebase` posts into wiki

Use this when old `Knowledgebase` saves were handled as `raw/RAG-first` and need to be
materialized into real `wiki/research/**` pages.

```bash
OPENCLAW_HOST="deploy@<server-host>" bash scripts/backfill-knowledgebase-to-wiki.sh --dry-run
OPENCLAW_HOST="deploy@<server-host>" bash scripts/backfill-knowledgebase-to-wiki.sh --apply
```

The script reads only the `📚 Knowledgebase` forum topic, skips bot/service chatter and short
question-like search messages, and replays the remaining human content through `wiki-import` in two
steps: first a source-centric `ideas` capture to guarantee `wiki/research/**`, then an immediate
`promotion` pass only for high-signal materials. This keeps historical saves visible in the wiki
without reintroducing broad ontology explosion.

### Query LightRAG directly (for debugging)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf -X POST http://127.0.0.1:8020/query \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"test query\", \"mode\": \"hybrid\"}" | jq .
'
```

### Query LightRAG as OpenClaw sees it

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    node -e \"fetch(\\\"http://lightrag:9621/query\\\", {
      method: \\\"POST\\\",
      headers: {\\\"Content-Type\\\": \\\"application/json\\\"},
      body: JSON.stringify({query: \\\"test query\\\", mode: \\\"hybrid\\\"})
    }).then(r => r.text()).then(t => console.log(t.slice(0, 1000)))\"
  "
'
```

### Read today's memory index

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/memory/INDEX.md 2>/dev/null || echo no-index-yet"'
```

### Check builtin OpenClaw memorySearch status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway openclaw memory status --deep
'
```

### Rebuild builtin OpenClaw memorySearch index

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway openclaw memory index --force
'
```

For this server, prefer running a forced rebuild off-hours and avoid launching multiple
`openclaw memory ...` commands in parallel; the first large backfill can temporarily spike load.

### Smoke-test builtin OpenClaw memorySearch

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway openclaw memory search "LightRAG"
'
```

### Read workspace master index

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "cat /home/node/.openclaw/workspace/INDEX.md"'
```

### Weekly memory maintenance (manual)

Run when HEARTBEAT prompts or weekly:

1. Move daily notes older than 14 days to `memory/archive/`
2. Update `memory/INDEX.md` — remove stale entries
3. Trigger LightRAG re-index
4. Scan for contradictions between `MEMORY.md` and recent raw/ entries

```bash
# Example: archive old daily note
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw/workspace &&
  mv memory/2026-04-08.md memory/archive/ 2>/dev/null || echo "file not found"
'
```

After archiving, deploy updated `memory/INDEX.md` and trigger `/new` in the bot.

### Obsidian vault sync — Syncthing setup (bidirectional)

The vault syncs **bidirectionally** between Mac (iCloud) and server via Syncthing.
Changes on either side propagate automatically within seconds.

**Current state (already configured):**

| Parameter | Mac | Server |
|---|---|---|
| Device ID | `EJ6FHJG` | `6JODYFX` |
| Config dir | `~/Library/Application Support/Syncthing/` | `~/.config/syncthing/` |
| Vault path | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/DenisJournals` | `/opt/obsidian-vault` |
| Service | `homebrew.mxcl.syncthing` (launchd) | `syncthing@deploy` (systemd) |
| Folder ID | `obsidian-vault` | `obsidian-vault` |
| Connection | via global relay (Hetzner cloud firewall blocks port 22000 externally) | |

**GUI access:**

| Side | URL | Notes |
|---|---|---|
| Mac | `http://127.0.0.1:8384` | open directly in browser |
| Server | `http://127.0.0.1:8384` (on server) | access via SSH tunnel: `ssh -i ~/.ssh/id_rsa -L 8385:127.0.0.1:8384 deploy@<server-host>` → `http://127.0.0.1:8385` |

Folder shows **"Up to Date"** when in sync. Remote device shows **"Up to Date"** when peer is connected and synced.

**Check sync status (Mac):**

```bash
# Via Syncthing API
curl -s -H "X-API-Key: $(grep -o '<apikey>[^<]*' ~/Library/Application\ Support/Syncthing/config.xml | cut -d'>' -f2)" \
  http://127.0.0.1:8384/rest/system/connections | python3 -c "
import json,sys; d=json.load(sys.stdin)
for k,v in d.get('connections',{}).items():
    if k!='total': print(k[:16],'connected:',v.get('connected'),'addr:',v.get('address','-'))
"
```

Or open `http://127.0.0.1:8384` in browser — folder shows **Up to Date** when in sync.

**Restart Syncthing if disconnected:**

```bash
# Mac
brew services restart syncthing

# Server
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo systemctl restart syncthing@deploy'
```

**If devices show "Disconnected (Inactive)" — force reconnect:**

```bash
API_KEY=$(grep -o '<apikey>[^<]*' ~/Library/Application\ Support/Syncthing/config.xml | cut -d'>' -f2)
SRV_ID="6JODYFX-EEYVQQA-VRWGIUE-OAKH3DA-5LAMQYZ-3FR5HEN-GK7JWU5-DH24MAD"
# Pause then unpause to force retry
curl -s -X PATCH -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"deviceID\":\"$SRV_ID\",\"paused\":true}" http://127.0.0.1:8384/rest/config/devices/$SRV_ID
sleep 2
curl -s -X PATCH -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"deviceID\":\"$SRV_ID\",\"paused\":false}" http://127.0.0.1:8384/rest/config/devices/$SRV_ID
```

**Fresh install on a new Mac:**

1. Install Syncthing: `brew install syncthing && brew services start syncthing`
2. Open `http://127.0.0.1:8384` → Actions → Show ID — note the device ID
3. Add the device ID to server config via server's Syncthing GUI (via SSH tunnel: `ssh -L 8385:127.0.0.1:8384 deploy@<server-host>`, then open `http://127.0.0.1:8385`)
4. Share folder `obsidian-vault` with the new device on both sides
5. Create `.stfolder` marker: `touch ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/DenisJournals/.stfolder`

---

### Obsidian vault sync check

```bash
# Curated wiki tree on server
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" "find /opt/obsidian-vault/wiki -name '*.md' | wc -l"
# Expected: > 0 and growing via curated import

# Server Syncthing status
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  "curl -s -H 'X-API-Key: \$(grep -o \"<apikey>[^<]*\" ~/.config/syncthing/config.xml | cut -d\">\" -f2)' \
  http://127.0.0.1:8384/rest/db/status?folder=obsidian-vault" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('state:',d.get('state'),'files:',d.get('globalFiles'),'needFiles:',d.get('needFiles'))"
```

**Trigger LightRAG re-index after bulk Obsidian changes:**

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '/opt/lightrag/scripts/lightrag-ingest.sh'
```

---

### Legacy rsync sync (deprecated)

The old one-way rsync agent (`com.openclaw.obsidian-sync`) is still installed at
`~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist` but is superseded by Syncthing.
It can be left in place (it runs but finds nothing to sync since Syncthing handles it),
or unloaded:

```bash
launchctl unload ~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist
```

## Telethon Digest

Telethon Digest reads Denis's Telegram subscriptions via Telethon and posts structured
digests to the configured supergroup topic using the OpenClaw Telegram bot token.
LLM summarization and dedup use OpenClaw/OpenAI first, then OmniRoute
(`http://omniroute:20129/v1`), then Qwen, then DeepSeek as final reserve, before local deterministic
fallback.

**Scheduling:** host cron triggers one-shot runs at
`08:00, 11:00, 14:00, 17:00, 21:00 MSK` through
`/bin/bash /opt/telethon-digest/trigger-digest.sh`. This keeps delivery independent
of the script executable bit. No long-running digest worker daemon.
The always-on `telethon-digest-cron-bridge` consumes the Redis job and runs the
worker. OpenClaw Telethon agent-turn cron jobs are disabled on the live server
because the 2026.5.x lightweight cron context can report `ok` while refusing the
shell tool needed to call the bridge.

**Digest types (auto-selected by hour):**

| Hour | Type | Format |
|------|------|--------|
| 08:00 | morning | Compact snapshot, 1-2 messages |
| 11/14/17 | interval | Per-folder Tier A detail + Tier B summary |
| 21:00 | editorial | Full editorial: summary → themes → must-read → low signal → watchpoints |

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-telethon-digest.sh
```

The script: rsyncs source, fills secrets from `/opt/openclaw/.env`, rebuilds image,
stops the old daemon if any, writes `/etc/cron.d/telethon-digest`, and disables
legacy Telethon Digest OpenClaw cron jobs if they are still present.

**Managed host cron slots:**

- `0 5 * * *` UTC → `/bin/bash /opt/telethon-digest/trigger-digest.sh morning 8 0`
- `0 8 * * *` UTC → `/bin/bash /opt/telethon-digest/trigger-digest.sh interval 11 0`
- `0 11 * * *` UTC → `/bin/bash /opt/telethon-digest/trigger-digest.sh interval 14 0`
- `0 14 * * *` UTC → `/bin/bash /opt/telethon-digest/trigger-digest.sh interval 17 0`
- `0 18 * * *` UTC → `/bin/bash /opt/telethon-digest/trigger-digest.sh editorial 21 0`

Each cron slot sends one authenticated HTTP trigger to `telethon-digest-cron-bridge`
from inside the bridge container. The bridge then runs `python digest_worker.py --now`
with an explicit `DIGEST_TYPE_OVERRIDE`, which keeps the run type stable even if a
job is retried later than the scheduled hour. The trigger also passes the nominal
slot (`08:00`, `11:00`, `14:00`, `17:00`, `21:00`) into the worker, so the digest
header keeps the scheduled window label even if Telegram shows the message itself
at `11:05` because rendering/posting finished a few minutes later.
The worker also uses that nominal slot to read and filter the exact source window:
`21:00-08:00`, `08:00-11:00`, `11:00-14:00`, `14:00-17:00`, and `17:00-21:00`.
The overnight window expands `lookahead_hours` for that run, so it does not silently
miss earlier night posts.
Do not replace these lines with `TZ=Europe/Moscow` plus local-hour cron expressions:
the deployed host cron evaluates schedule times in UTC, while `TZ` only changes the
command environment. Using local-hour expressions there causes delayed, stale
window labels such as an `11:00` slot firing at `14:00 MSK`.

The cron sync script also sets a longer OpenClaw run timeout (`1800` seconds by
default) so the cron run can wait for the digest to finish instead of reporting
the bridge as "hung" while the worker is still processing a large window.

**Header counters:** the digest header reports active channels in the exact source
window, then raw messages processed in that window, then posts selected for the
published issue. For example, `7 каналов, обработано 57 сообщений, в выпуске 16
постов` means the reader saw 57 source messages from 7 active channels, and the
score/dedup stage selected 16 direct post links for rendering.

**Bridge status recovery:** on `telethon-digest-cron-bridge` startup, if the
persisted status still says `running=true`, the bridge marks that previous run
as `interrupted`, sets `exit_code=130`, and releases the matching Redis run lock.
This prevents a container restart during `digest_worker.py --now` from leaving a
stale running flag or blocking the next scheduled slot until lock TTL expiry.

**LLM fallback:** summarizer responses wrapped in Markdown JSON fences are parsed
as normal JSON before retry-marker checks. Deterministic local fallback should
therefore mean the model route failed validation after retries, not merely that
the model returned fenced JSON.

On this deployment, `openclaw cron list` may hang even when the gateway itself is
healthy. Because of that, the sync helpers patch the cron store (`jobs.json`)
directly, back it up first, then restart the gateway container so it reloads the
managed jobs.

This workflow is also captured as the repo skill
`skills/openclaw-cron-maintenance/SKILL.md`, so future schedule or cron-store
changes can follow one stable procedure instead of re-discovering the recovery
path each time.

### How `Пульс дня` is selected

`Пульс дня` is no longer a plain "most repeated news" block. The editorial layer now does:

1. take the strong scored post pool after `reader.py` → `scorer.py` → `dedup.py`
2. build pulse candidates from LLM `themes`, local extraction, and fallback storyline lines
3. rank candidates by:
   - repeated / cross-channel signal
   - fit to Denis-interest buckets (`AI`, `Telegram/privacy`, `fintech`, `geopolitics`, `creator`, `product`, `science`)
   - novelty vs recently published pulse lines
   - line quality (prefer storyline/theme, avoid source-like labels)
   - diversity bonus so one category does not flood the block
4. publish one strong line per bucket first, then fill remaining slots with the next best lines

The bucket profile is persisted in `/app/state/pulse-profile.json` inside the shared `telethon-state`
volume. It is updated after each digest from the current strong-post pool and stores:

- bucket momentum from recent windows
- learned bucket terms discovered from recurring posts
- recent pulse signatures to suppress stale repetition

This ranking/profile layer is intentionally generic and can later be reused for `inbox-email` or
`work-email` recaps.

**Important:** the target OpenClaw agent must be allowed to use `exec` and must
have access to `/opt/telethon-digest`. The sync script defaults to agent `main`,
but you can override it with `OPENCLAW_CRON_AGENT=ops` before deploy if your
server uses a dedicated ops agent. The sync script reads existing jobs from
`/opt/openclaw/config/cron/jobs.json` by default; override with
`OPENCLAW_CRON_STORE=...` if your gateway uses a custom cron store path.

**Bridge diagnostics:**

The bridge listens on its container-only `:8091` port; it is not published to
the host. Run the check inside the container instead:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'sudo docker exec telethon-digest-cron-bridge python -c '\''import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8091/health", timeout=5).read().decode())'\'''
```

- `GET /health` — quick liveness + last run snapshot
- `GET /status` — current or last run payload with timestamps, digest type, exit code, and tail
- `POST /trigger` — synchronous run; returns `409 digest_already_running` if another digest is already queued or still in flight

### One-time Telethon authorization

```bash
ssh -t -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python auth.py'
```

### Sync Telegram folders (run after auth, and after folder changes)

```bash
# Dry-run
ssh -t -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python sync_channels.py --dry-run'

# Write config.json (adds position + username per channel)
ssh -t -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python sync_channels.py'
```

Read scope config (`config.json` — not committed):

```json
{
  "read_only": true,
  "require_explicit_allowlist": true,
  "read_broadcast_channels_only": true,
  "allowed_folder_names": ["news", "evolution", "startups", "growth.me", "fintech", "investing", "work", "eb1", "гребенюк", "personal", "faang"],
  "content_mix": {
    "capped_folders": {
      "news": {"target_share": 0.3, "hard_share": 0.35}
    }
  }
}
```

Content mix selection:

- `content_mix.capped_folders.news` is also the code default, so older live `config.json` files start using the rule after deploy even before the key is written into config.
- The rule applies after score/min-score filtering and during the diversity selection passes. It does not remove `news` from the Telethon read allowlist.
- When non-news folders have enough scored candidates, `news` stays around 30% and cannot exceed 35% of the selected source pool.
- When non-news folders are sparse for a slot, the effective cap expands and strong `news` posts fill the remaining `top_posts_for_llm` budget.
- To disable the cap intentionally, set `"content_mix": {"capped_folders": {}}` in `/opt/telethon-digest/config.json`.

### Run digest immediately

```bash
# Auto-detect type by current hour
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo /opt/telethon-digest/cron-digest.sh'

# Force a specific type for testing
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose run --rm \
   -e DIGEST_TYPE_OVERRIDE=morning telethon-digest python digest_worker.py --now'
```

### Watch logs

```bash
# Digest log (one line per run)
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo tail -f /var/log/telethon-digest-cron.log'

# Detailed docker log from last run
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/telethon-digest && sudo docker compose logs --tail=100'
```

### Check OpenClaw cron schedule

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'sudo cat /opt/openclaw/config/cron/jobs.json 2>/dev/null || sudo cat /home/deploy/.openclaw/cron/jobs.json'
```

## AgentMail Inbox Email

AgentMail Inbox Email polls the personal inbox every 5 minutes through a standalone Python
bridge that talks to the AgentMail HTTP API directly, uses an internal 5-minute scheduler for
poll-based state/labeling only, and publishes scheduled recaps to the `inbox-email` topic at
`08:00`, `13:00`, `16:00`, and `20:00` MSK. The 5-minute poll path uses deterministic prefiltering by
default and must not call `openclaw agent` inside the Gateway unless `poll_llm_enabled=true` is set
deliberately for a controlled test. Scheduled digests render directly from the mailbox window so they
always reflect the actual message count and senders.

If a scheduled digest window has no messages, the bridge now still posts a short
"empty window" message to Telegram instead of silently skipping the slot.

Scheduled digest windows are anchored to the fixed Moscow schedule boundaries
(`08:00 → 13:00 → 16:00 → 20:00`) rather than the timestamp of the previous manual run.

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-agentmail-email.sh
```

Local gitignored secret source:

```text
secrets/agentmail-email/email.env
```

Do not place real AgentMail keys in tracked docs, templates, or repo-root shell history. The only
allowed locations are the gitignored local secret file above and `/opt/agentmail-email/email.env`
on the server. The live `work-email` bridge follows the same pattern under
`secrets/agentmail-work-email/email.env` locally and `/opt/agentmail-work-email/email.env` on the server.

Required local keys:

- `AGENTMAIL_API_KEY`
- `AGENTMAIL_INBOX_REF`
- `EMAIL_DIGEST_SUPERGROUP_ID`
- `EMAIL_DIGEST_TOPIC_ID`

The deploy script:

- rsyncs `/opt/agentmail-email`
- hydrates `TELEGRAM_BOT_TOKEN` from `/opt/openclaw/.env`
- keeps `AGENTMAIL_API_KEY` inside `/opt/agentmail-email/email.env`
- removes stale AgentMail-specific coupling from the central OpenClaw config
- rebuilds the lightweight Python `agentmail-email-bridge`
- materializes the real `AGENTMAIL_INBOX_REF` into `/opt/agentmail-email/config.json`
- removes stale `/opt/agentmail-email/openclaw-config` leftovers from the old embedded-runtime design
- prunes dangling Docker image/build artifacts after a successful rebuild
- installs `/etc/cron.d/agentmail-email` so host cron triggers digest delivery directly
- disables legacy `AgentMail Inbox · ...` OpenClaw Cron digest jobs after backing up the cron store
- validates that no 5-minute poll cron job remains

Architecture note:

- `agentmail-email-bridge` no longer carries its own OpenClaw runtime or copied auth store.
- Mailbox access now happens inside the bridge itself via the AgentMail HTTP API.
- The bridge remains responsible for Redis orchestration, Telegram posting, mailbox labels,
  and derived event persistence.
- The shared `openclaw-openclaw-gateway-1` container is used only for LLM steps over prepared
  thread snapshots or derived events.
- The 5-minute poll no longer relies on OpenClaw Cron Jobs; it is scheduled internally by the bridge.
- The scheduled Telegram digests no longer rely on OpenClaw agent-turn Cron Jobs either; host cron
  calls `/opt/agentmail-email/trigger-email-digest.sh` directly to avoid false-positive cron runs
  when the lightweight OpenClaw cron context has no shell tool available.

Current validation snapshot:

- the rebuilt bridge image is about `229 MB` on server (down from the earlier embedded-runtime build)
- direct AgentMail API reads and label updates work from the bridge container
- manual `/trigger` → `poll` enqueue works
- a clean empty-window poll finished with `exit_code=0` on `2026-04-11`
- on `2026-04-12`, a manual `poll lookback=1440` finished with `exit_code=0`, scanned `32` threads,
  produced `1` publishable event, and tolerated one missing message id during label commit
- on `2026-04-12`, a manual `editorial` digest finished with `exit_code=0`, rendered from the
  mailbox window, and applied `benka/digested=1`
- on `2026-04-13`, the internal scheduler successfully self-enqueued a poll after bridge restart,
  the run finished with `exit_code=0`, and `/status` showed the new prefilter diagnostics directly
- on `2026-06-24`, both personal and work 5-minute polls were pinned to `poll_llm_enabled=false`
  after parallel AgentMail `openclaw agent` execs killed `openclaw-gateway` with `exit=137` and caused
  unrelated Telegram topic replies to disappear.
  in `poll summary` (`prefilter_scanned`, `skipped_handled`, `skipped_low_signal`,
  `candidate_threads`, `llm_skipped`)
- on `2026-04-13`, server-side image tests passed: `python -m unittest discover -s /app/tests`
  → `Ran 5 tests ... OK`

### Host cron jobs

Host cron runs in UTC. `/etc/cron.d/agentmail-email` maps to the Moscow digest slots:

- `05:00 UTC` → `08:00 MSK` morning brief
- `10:00 UTC` → `13:00 MSK` regular digest
- `13:00 UTC` → `16:00 MSK` regular digest
- `17:00 UTC` → `20:00 MSK` evening editorial

Legacy `AgentMail Inbox · ...` OpenClaw Cron jobs are disabled in the cron store to prevent duplicate
delivery.

## AgentMail Work Email

AgentMail Work Email is a second live runtime that reuses the same Python bridge codebase but runs
separately from the personal inbox at `/opt/agentmail-work-email`. It talks directly to the
AgentMail HTTP API for `workmail.denny@agentmail.to`, uses its own internal 5-minute scheduler for
poll-based state/labeling with `poll_llm_enabled=false` by default, and publishes scheduled digests to
Telegram topic `work-email` at `08:30`, `10:00`, `11:30`, `13:00`, `14:30`, `16:00`, `17:30`, and
`19:00` MSK.

Unlike the personal `inbox-email` runtime, the work digest can resolve the original sender from
forwarded-message headers inside the email body. This is enabled only for `work-email`, so a mail
forwarded by Denis still renders under the underlying author such as `Elena Zabrodina` when the
message body contains a forwarded header block (`От:` / `From:`).

Scheduled `work-email` digests use a stable three-part layout:

- `Сюжеты` — all visible storylines in the current mailbox window
- `Нужно реагировать` — threads that likely need a reply, status, decision, approval, or problem follow-up
- `Для информации` — FYI/absence/update threads that are useful to keep in mind but do not obviously demand immediate action

Low-signal handling stays unchanged: the digest still counts low-signal mail separately and can add
short background/noise recap lines under the informational part of the message.

Isolation guarantees:

- separate Redis jobs stream: `ingest:jobs:email:work`
- separate derived events stream: `ingest:events:email:work`
- separate DLQ stream: `dlq:failed:email:work`
- separate consumer group: `email-workers-work`
- separate Redis status key: `status:email:work:latest`
- separate labels: `workmail/polled`, `workmail/low-signal`, `workmail/digested`
- separate Docker container / volume / localhost port (`agentmail-work-email-bridge`, `8094`)

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-agentmail-work-email.sh
```

Local gitignored secret source:

```text
secrets/agentmail-work-email/email.env
```

Required local keys:

- `AGENTMAIL_API_KEY`
- `AGENTMAIL_INBOX_REF`
- `EMAIL_DIGEST_SUPERGROUP_ID`
- `EMAIL_DIGEST_TOPIC_ID`

Current validation snapshot:

- on `2026-04-13`, `/opt/agentmail-work-email` deployed successfully with eight managed cron jobs
- `agentmail-work-email-bridge` came up healthy on `127.0.0.1:8094`
- internal scheduler ran a successful poll with `exit_code=0`, scanned `10` threads, emitted `6`
  derived events into `ingest:events:email:work`, and applied `workmail/polled` / `workmail/low-signal`
- server-side image tests passed: `python -m unittest discover -s /app/tests` → `Ran 5 tests ... OK`
- a manual `digest interval lookback=240` trigger finished with `exit_code=0` and applied
  `workmail/digested=1`
- on `2026-04-14`, `scripts/deploy-agentmail-work-email.sh` redeployed the bridge with
  forwarded-sender resolution enabled only for `work-email`; `GET /health` and `GET /status`
  returned `last_exit_code=0`, the internal 5-minute poll completed cleanly after restart, and all
  eight managed cron jobs remained present with `enabled=true`
- on `2026-04-14`, a live mailbox-window check inside the running bridge showed forwarded CNews
  invitations under `Elena Zabrodina` while calendar forwards still rendered as `Яндекс.Календарь`
- on `2026-05-29`, email polling was verified healthy while Telegram digest delivery had stalled
  behind false-positive OpenClaw Cron runs without an exec/shell tool; digest delivery moved to
  `/etc/cron.d/agentmail-work-email`, and the legacy OpenClaw Cron jobs were disabled.
- on `2026-06-24`, `work-email` was redeployed with `poll_llm_enabled=false`; the next scheduled poll
  self-enqueued without creating an `openclaw agent` exec in the Gateway, and `openclaw-gateway`
  remained healthy.
- on `2026-07-06`, scheduled `work-email` Telegram delivery was repaired after host cron showed
  repeated `Permission denied` failures for the trigger script. The live trigger scripts were restored
  to mode `0755`, the deploy helper now writes cron entries through `bash`, and a manual
  `digest interval lookback=240` finished with `exit_code=0`, rendered `3` messages, and applied
  `workmail/digested=3`.

### Host cron jobs

Host cron runs in UTC. `/etc/cron.d/agentmail-work-email` maps to the Moscow digest slots:

- `05:30 UTC` → `08:30 MSK` morning triage
- `07:00 UTC` → `10:00 MSK` regular digest
- `08:30 UTC` → `11:30 MSK` regular digest
- `10:00 UTC` → `13:00 MSK` regular digest
- `11:30 UTC` → `14:30 MSK` regular digest
- `13:00 UTC` → `16:00 MSK` regular digest
- `14:30 UTC` → `17:30 MSK` regular digest
- `16:00 UTC` → `19:00 MSK` end-of-day wrap-up

Legacy `AgentMail Work Email · ...` OpenClaw Cron jobs are disabled in the cron store to prevent
duplicate delivery.

Cron entries intentionally invoke `bash /opt/agentmail-work-email/trigger-email-digest.sh ...` rather
than executing the script path directly. This keeps scheduled delivery working if rsync or manual file
maintenance drops the trigger script executable bit.

### Bridge diagnostics

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8094/health && echo && curl -s http://127.0.0.1:8094/status'
```

### Integration bus checks

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email:work
  docker exec integration-bus-redis redis-cli XLEN ingest:events:email:work
  docker exec integration-bus-redis redis-cli GET status:email:work:latest
'
```

### Bridge diagnostics

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8092/health && echo && curl -s http://127.0.0.1:8092/status'
```

- `GET /health` — quick liveness + last poll/digest snapshot
- `GET /status` — current or last run payload with timestamps, job type, exit code, and tail
- `POST /trigger` — enqueue `poll` or `digest` into `ingest:jobs:email`
- Optional trigger override: `lookback_minutes` for manual catch-up/backfill without editing Redis state

### Integration bus checks

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email
  docker exec integration-bus-redis redis-cli XLEN ingest:events:email
  docker exec integration-bus-redis redis-cli XPENDING ingest:jobs:email email-workers - + 10
  docker exec integration-bus-redis redis-cli XLEN dlq:failed
'
```

### Manual enqueue examples

```bash
# Poll now
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:email "*" \
    run_id manual-poll \
    job_type poll \
    inbox_ref <agentmail-inbox-ref> \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'

# Poll now with a wider catch-up window
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:email "*" \
    run_id manual-poll-backfill \
    job_type poll \
    lookback_minutes 1440 \
    inbox_ref <agentmail-inbox-ref> \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'

# Digest now
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:email "*" \
    run_id manual-digest \
    job_type digest \
    digest_type interval \
    inbox_ref <agentmail-inbox-ref> \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'
```

### Watch logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/agentmail-email && sudo docker compose logs --tail=100 agentmail-email-bridge'
```

### Cleanup old install leftovers

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo rm -rf /opt/agentmail-email/openclaw-config
  sudo docker image prune -af
  sudo docker builder prune -af
'
```

Use this after migrating away from the old embedded-runtime design or after repeated failed image builds.

## Signals Bridge

Signals Bridge polls allowlisted email + Telegram sources every 5 minutes through its own internal
Python scheduler and publishes compact mini-batches into the `signals` topic. This service does not
use OpenClaw Cron Jobs. LLM enrichment uses OpenClaw/OpenAI first, then cheap `OmniRoute light`,
then Qwen, then DeepSeek as final reserve, with local rule-based summaries only after all model routes fail.

Delivery format:

- Telegram-derived signal items include a direct source link to the originating post when one can be constructed.
- Email-derived signal items retain a compact excerpt in the rendered batch so the operator can read the core message without opening the raw mailbox.
- Telegram keyword matching stays deterministic, but now includes a small alias layer for recurring
  trading slang and standard yuan inflections. Canonical rules such as `си` / `юань` / `cny` catch
  narrow forms such as `сиху` and `юашку` plus `юане` without widening into generic FX chatter or
  accepting a partial stem inside another word.

### Deploy

```bash
export OPENCLAW_HOST="deploy@<server-host>"
bash scripts/deploy-signals-bridge.sh
```

Local gitignored secret source:

```text
secrets/signals-bridge/signals.env
secrets/signals-bridge/config.json
secrets/signals-bridge/rules/*.json
```

Required local keys:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_PHONE`
- `SIGNALS_SUPERGROUP_ID`
- `SIGNALS_TOPIC_ID`
- `AGENTMAIL_API_KEY`

Recommended local keys:

- `OMNIROUTE_API_KEY`
- `DASHSCOPE_API_KEY` (Qwen direct reserve)
- `TELEGRAM_BOT_TOKEN` if you do not want the deploy script to hydrate it from `/opt/openclaw/.env`

The deploy script:

- rsyncs `/opt/signals-bridge`
- preserves `/opt/signals-bridge/backups/` while syncing the application payload
- syncs local `secrets/signals-bridge/config.json`
- syncs local `secrets/signals-bridge/rules/*.json`
- hydrates `TELEGRAM_BOT_TOKEN` from `/opt/openclaw/.env` when missing
- hydrates `OMNIROUTE_API_KEY` from `/opt/openclaw/.env` when missing
- hydrates `DASHSCOPE_API_KEY` from `/opt/openclaw/.env` when missing
- generates `SIGNALS_BRIDGE_TOKEN` when missing
- keeps the bridge standalone; there is no OpenClaw cron-store sync step
- rebuilds the lightweight Python `signals-bridge`
- starts `signals-bridge` and validates `GET /health`

Architecture note:

- polling cadence is every 5 minutes, not every 30 seconds
- scheduling is internal to `signals-bridge`
- public docs/templates stay generic; real local rules live in separate JSON files under `secrets/signals-bridge/rules/`
- add a private Telegram source only after resolving one stable `chat_id` through the authorised
  Telethon session; use an explicit bootstrap window and validate it with a source-only run
- startup releases stale locks only for configured signals rulesets, so an interrupted bridge run
  cannot block the next run for the full lock TTL
- every enabled `rule_sets.id` must be globally unique, including IDs loaded through `rule_files`;
  config validation rejects a duplicate rather than allowing the scheduler to shadow a ruleset
- polling, relay, and interactive Telethon auth share one session lock; a transient SQLite session
  lock retries with bounded backoff before the source is marked failed
- a stale source resumes automatically only over its normal overlap window; any wider recovery is an
  explicit source-only run with `lookback_minutes`, preventing an outage restart from replaying history
- AgentMail and Telethon reads happen inside the bridge itself
- LLM enrichment for already matched candidates is `OpenClaw/OpenAI -> OmniRoute light -> Qwen -> DeepSeek`
- if all model routes are unavailable, the bridge falls back to local rule-based summaries and can still post

### Bridge diagnostics

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8093/health && echo && curl -s http://127.0.0.1:8093/status'
```

- `GET /health` — quick liveness + last signals run summary and per-source health; it becomes
  `ok=false` for a source with an unresolved error or a prior successful poll older than three poll
  intervals (minimum 15 minutes)
- `GET /status` — current or last run payload with ruleset id, posted count, tail, and source-level
  `healthy` / `stale` / `error` / `unknown` state
- `POST /trigger` — enqueue a manual ruleset run into `ingest:jobs:signals`
- Optional trigger overrides:
  - `lookback_minutes` for manual catch-up/backfill; it is a strict lower timestamp bound even when a source cursor is stale. Automatic polls never expand a stale source into a historical backfill.
  - `source_id` to limit a manual run to one configured source

### Integration bus checks

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:signals
  docker exec integration-bus-redis redis-cli XLEN ingest:events:signals
  docker exec integration-bus-redis redis-cli XPENDING ingest:jobs:signals signals-workers - + 10
  docker exec integration-bus-redis redis-cli XLEN dlq:failed
'
```

### Manual enqueue examples

```bash
# Run one configured ruleset now
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:signals "*" \
    run_id manual-signals \
    ruleset_id <ruleset-id> \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'

# Run one source with a wider lookback
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:signals "*" \
    run_id manual-signals-backfill \
    ruleset_id <ruleset-id> \
    source_id <source-id> \
    lookback_minutes 60 \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'
```

### Watch logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'cd /opt/signals-bridge && sudo docker compose logs --tail=100 signals-bridge'
```

## If SSH times out during banner exchange

This indicates a host-level access problem before shell login. Use Hetzner Console for recovery checks:

1. verify server power state and load
2. verify Hetzner Firewall still allows `22/tcp` from your current client IP
3. verify `sshd` is active (`systemctl status ssh`)
4. if the host is overloaded, restart only `openclaw-gateway` first, then re-test SSH

## OmniRoute operations

OmniRoute runs as an additional service inside the OpenClaw Docker Compose project (`docker-compose.override.yml`).

### Start / stop

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose up -d omniroute'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose stop omniroute'
```

### Status and logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose ps'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose logs --tail=100 omniroute'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && sudo docker compose logs -f omniroute'
```

### Access dashboard via SSH tunnel

```bash
ssh -i ~/.ssh/id_rsa -L 20128:localhost:20128 "$OPENCLAW_HOST" -N &
# Open http://localhost:20128 in browser
# Password: see /opt/openclaw/client-secrets/omniroute-password.txt on server
kill %1   # close tunnel when done
```

### Test API from server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:20129/v1/models \
    -H "Authorization: Bearer $(grep ^OMNIROUTE_API_KEY /opt/openclaw/.env | cut -d= -f2)"
'
```

### Bootstrap providers (one-time, via SSH tunnel)

Open dashboard via SSH tunnel (see above), then:

1. **OpenRouter** — auto-connects from `OPENROUTER_API_KEY` in `omniroute.env` (check green in Dashboard → Providers)
2. **Codex CLI** — Dashboard → Providers → Codex CLI → Connect → OpenAI OAuth (same credentials as OpenClaw)
3. **Kiro** — Dashboard → Providers → Kiro → Connect → AWS Builder ID OAuth
4. **Qoder** — Dashboard → Providers → Qoder → Connect → OAuth (gives Kimi, Qwen, DeepSeek)
5. **Gemini CLI** — Dashboard → Providers → Gemini CLI → Connect → Google OAuth (same Google account)

After auth, tokens persist in the `omniroute-data` volume and auto-refresh.

### Create routing tiers (one-time, via dashboard)

Dashboard → Combos → Create New:

| Combo name | Strategy | Chain |
|---|---|---|
| `smart` | priority | Kiro/claude-sonnet → OpenRouter/claude-3.5-sonnet → Qoder/kimi-k2 |
| `medium` | priority | Codex/gpt-4o-mini → Kiro/claude-haiku → Qoder/kimi → Qoder/qwen3 |
| `light` | priority | Gemini CLI/gemini-2.0-flash → Qoder/qwen3-coder → Kiro/claude-haiku |

After creating combos: Dashboard → API Manager → Create Key → copy bearer token.

### Generate OmniRoute API key (one-time)

1. Open dashboard
2. Go to API Manager → Create Key
3. Copy bearer token
4. Add to `/opt/openclaw/.env`: `OMNIROUTE_API_KEY=<token>`
5. Re-create openclaw-gateway: `sudo docker compose up -d --force-recreate openclaw-gateway`

### Upgrade OmniRoute

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  TARGET_TAG=v3.6.3
  cd /opt/openclaw/omniroute-src &&
  sudo git fetch --tags origin &&
  sudo git checkout -B "deploy/${TARGET_TAG#v}" "$TARGET_TAG"
  cd /opt/openclaw && sudo docker compose build --no-cache omniroute
  sudo docker compose up -d --force-recreate omniroute
'
```

The `omniroute-data` volume persists auth tokens and settings across rebuilds.

---

## Integration Bus (Redis Streams)

Redis runs as a standalone Docker Compose project at `/opt/integration-bus/`.

### Start / status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/integration-bus && sudo docker compose ps
'
```

### Deploy (first time or after config change)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/integration-bus && sudo docker compose up -d
'
```

### Ping Redis

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli ping
'
```

### Check stream lengths

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XLEN ingest:jobs:telegram
  docker exec integration-bus-redis redis-cli XLEN dlq:failed
'
```

### Check pending (jobs in-flight)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli \
    XPENDING ingest:jobs:telegram digest-workers - + 10
'
```

### Inspect dead letter queue

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli \
    XRANGE dlq:failed - + COUNT 20
'
```

### Manually enqueue a digest job (bypass cron_bridge)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:jobs:telegram "*" \
    run_id manual-test \
    digest_type interval \
    requested_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    requested_by manual
'
```

### Trim stream (keep last 1000 entries)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XTRIM ingest:jobs:telegram MAXLEN 1000
'
```

### Check ingest:rag:queue (LightRAG upload queue)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  echo "=== RAG queue total ==="
  docker exec integration-bus-redis redis-cli XLEN ingest:rag:queue
  echo "=== Pending (in-flight) ==="
  docker exec integration-bus-redis redis-cli XPENDING ingest:rag:queue rag-workers - + 10
'
```

### Manually enqueue a file for LightRAG ingest

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker exec integration-bus-redis redis-cli XADD ingest:rag:queue "*" \
    source manual \
    file_path "/app/obsidian/Telegram Digest/Derived/2026-04-11/interval-0800-1200.md" \
    file_name "interval-0800-1200.md" \
    enqueued_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
'
```

### LightRAG WebUI (SSH tunnel)

```bash
ssh -i ~/.ssh/id_rsa -L 9621:127.0.0.1:8020 "$OPENCLAW_HOST" -N &
# → open http://127.0.0.1:9621
kill %1  # close tunnel when done
```

### LightRAG health and document status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/health | python3 -m json.tool
'
```

### Trigger LightRAG reprocess of failed documents

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf -X POST http://127.0.0.1:8020/documents/reprocess_failed
'
```
