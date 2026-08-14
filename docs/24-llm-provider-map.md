# LLM Provider Map and Migration Rule

## Purpose and status

This is the canonical inventory for every LLM boundary in this repository. It
exists so that a provider or model can be changed deliberately when price,
availability, privacy, or quality changes.

The Qwen-first rollout was applied in stages on **2026-08-14**. OmniRoute
`light`, Signals Bridge, and Telethon Digest are running with Qwen first and
DeepSeek retained as their final LLM reserve. The Qwen secret was transferred
only between ignored server-side environments; no tracked file contains it.

The OpenClaw Gateway configuration uses the same direct fallback order. Its
expected derived image was rebuilt locally on the host from the pinned upstream
base and the tracked compatibility Dockerfile, then the Gateway passed health,
configuration, and controlled Qwen text-route checks. A manual Telegram UI
media retest remains a separate acceptance gate. LightRAG remains on its
direct-DeepSeek runtime route pending a separate extraction smoke.

Do not store a real API key, tokenised URL, or live provider response in this
file. Tracked examples contain placeholders only; live values stay in the
gitignored deployment secret store.

## Project rule for any LLM change

Before merging or deploying a provider/model change:

1. Update this map, the relevant sanitized environment example, route tests,
   and the changelog.
2. Record the workload, endpoint family, exact model identifier, fallback
   order, output limits, and owner. Do not describe a provider as a fallback
   unless the code can actually reach it.
3. Keep deterministic validation and delivery available when all LLM calls
   fail. An LLM may enrich or summarize; it must not become the only safe
   delivery path.
4. Test with a non-production fixture first, then use an explicit, reversible
   deployment and inspect provider usage after the first scheduled run.
5. Recheck live pricing and model availability in the provider console on the
   day of a migration. This document deliberately contains no static prices.

## LLM routes

| Workload | Code/config owner | Intended / effective primary chain | Final non-LLM outcome |
|---|---|---|---|
| Interactive OpenClaw Gateway | artifacts/openclaw/openclaw.json and scripts/deploy-qwen-gateway-config.sh | OpenAI gpt-5.5 -> Qwen qwen3.7-flash -> DeepSeek deepseek-v4-flash | Gateway error handling; no implicit fourth remote provider |
| Signals Bridge enrichment after deterministic rule match | artifacts/signals-bridge/omniroute_client.py | OpenClaw/OpenAI -> OmniRoute light -> Qwen qwen3.7-flash -> DeepSeek deepseek-v4-flash | Rule-based title/body result; the signal can still be delivered |
| Telethon Digest summarization | artifacts/telethon-digest/omniroute_client.py | OpenClaw/OpenAI -> OmniRoute light -> Qwen qwen3.7-flash -> DeepSeek deepseek-v4-flash | Local deterministic digest fallback |
| AgentMail inbox/work digest and candidate review | artifacts/agentmail-email/agent_runner.py and cron_bridge.py | Invokes the OpenClaw Gateway, therefore inherits its Gateway route | Direct email rendering when LLM review is disabled, unnecessary, or fails |
| OmniRoute light tier | scripts/sync-omniroute-qwen-provider.sh | Qwen qwen3.7-flash -> DeepSeek deepseek-v4-flash | The calling bridge uses its local fallback |
| LightRAG extraction/summarization | scripts/lightrag.env.template and create-lightrag-env.sh | OmniRoute light, therefore Qwen then DeepSeek | Retrieval still has local wiki-import embeddings; DeepSeek is not an embedding provider |
| Last30Days collection/ranking | artifacts/signals-bridge/last30days_runner.py -> pinned upstream last30days skill | Provider/model configuration is owned by the upstream skill runtime, not this repository | Separate route; inspect and document that upstream runtime before changing its provider |
| OpenClaw inbound image, audio, and video auto-understanding | artifacts/openclaw/openclaw.json `tools.media` | Disabled for this text-only fallback policy | Do not generate a synthetic media description through Qwen/DeepSeek; ask for text or restore a supported vision route |

## 2026-08-14 rollout evidence and remaining gate

- OmniRoute `light` now selects Qwen `qwen3.7-flash` before
  DeepSeek `deepseek-v4-flash`; a controlled internal request returned the
  expected Qwen-only marker.
- Signals Bridge was recreated, has both Qwen and DeepSeek reserve variables,
  and its health and status endpoints passed. Telethon Digest was recreated
  with the same two provider variables and its internal `/health` endpoint
  passed. Its bridge port is intentionally not published to the host.
- Gateway configuration now persists the Qwen-then-DeepSeek direct fallback
  order, with dated backups made before replacement. The expected derived image
  was rebuilt from its pinned base and compatibility Dockerfile, and the
  recreated Gateway passed `/healthz`, config validation, and a controlled Qwen
  text smoke. A fresh manual Telegram UI media retest is still required before
  claiming a visual-input route is accepted.
- Pulsar Trader Lab has a separate deployment record in its provider map. Its
  read-only Qwen smoke passed after the bot was recreated.
- Do not repoint LightRAG merely because OmniRoute is healthy. Its extraction
  route requires a dedicated, non-production extraction smoke before changing
  the live direct-DeepSeek configuration.
- Automatic image, audio, and video understanding is disabled in the Gateway.
  This prevents the text-only Qwen reserve from receiving an auto-generated
  `Image: Analyze ...` task after a primary vision failure. It does not claim
  vision support for either Qwen or DeepSeek; a media task needs a working
  vision-capable primary route or a text-only clarification.

OpenClaw and OmniRoute routes have distinct owners. Changing the Gateway model
does not change a bridge that calls OmniRoute, and changing OmniRoute does not
change the direct Qwen/DeepSeek reserve in a bridge.

## Credentials and non-secret configuration

| Variable or secret | Used by | Meaning and safe location |
|---|---|---|
| DASHSCOPE_API_KEY | Gateway, OmniRoute, Signals Bridge, Telethon Digest | Qwen DashScope international compatible API. Store only in the live secret environment; its placeholder is in env.redacted.example and service env examples. |
| DEEPSEEK_API_KEY | Gateway, OmniRoute, Signals Bridge, Telethon Digest | DeepSeek reserve API. Keep provisioned and tested, but do not use it as the normal route. |
| OPENAI_API_KEY or Gateway OAuth credential | OpenClaw Gateway and optional bridge first hop | Existing OpenAI route. Follow the current OpenClaw credential mechanism; do not duplicate a live credential into this repository. |
| OMNIROUTE_API_KEY | Signals Bridge, Telethon Digest, LightRAG | Authentication for the local OmniRoute service, not a Qwen key. |
| OPENROUTER_API_KEY | Any configured OmniRoute OpenRouter route | Separate provider credential; review it independently during a cost migration. |
| QWEN_URL, QWEN_MODEL, QWEN_TIMEOUT_SECONDS | Signals Bridge and Telethon Digest | Direct Qwen reserve/primary settings. Defaults are the DashScope international chat-completions endpoint and qwen3.7-flash. |
| DEEPSEEK_URL, DEEPSEEK_MODEL, DEEPSEEK_TIMEOUT_SECONDS | Signals Bridge and Telethon Digest | Last-reserve DeepSeek settings. |
| OMNIROUTE_MODEL, OMNIROUTE_MAX_TOKENS, OMNIROUTE_TEMPERATURE | Bridge route | Controls the local tier and bounded enrichment payload; keep these small for batch work. |
| OPENCLAW_AGENT_ID, OPENCLAW_AGENT_THINKING, OPENCLAW_AGENT_TIMEOUT_SECONDS | AgentMail bridge | Selects the OpenClaw agent and bounded invocation; it is not another provider credential. |
| AGENTMAIL_POLL_LLM_ENABLED and AGENTMAIL_MAX_LLM_* | AgentMail bridge | Opt-in candidate review and prompt-size bounds. Keep disabled/strict until its cost and quality are measured. |

Sanitized source files are artifacts/openclaw/env.redacted.example,
artifacts/omniroute/omniroute.env.example,
artifacts/signals-bridge/signals.env.example, and
artifacts/telethon-digest/telethon.env.example. They document names only, not
live values.

## Cost and operational controls

- Signals run deterministic matching before any LLM call, so irrelevant input
  should not consume provider tokens.
- The bridge settings bound the light-tier output and timeouts. Keep a model
  change within the same or stricter limits until usage is measured.
- There is no repository-wide token ledger or hard spending cap for these
  services today. Review each provider dashboard and configure account-level
  quota/budget alerts before enabling a high-volume route.
- Treat provider pricing pages, quota grants, and model deprecations as
  external mutable state. Capture the verification date and source in the
  deployment record, not in a long-lived code default.

## Safe migration procedure

1. Inventory callers with a search for the current provider names and API-key
   variables. Include the Gateway, both bridges, OmniRoute, LightRAG, and any
   scheduled job.
2. Add the new provider as a named adapter/configuration. Preserve the old
   provider as the last tested reserve until the new route has real production
   evidence.
3. Put only placeholder variable names in tracked files. Add the live key in
   the server secret environment during the explicitly approved deployment.
4. Run JSON validation, Python unit tests for both bridges, and shell syntax
   checks for provisioning/sync scripts. Validate request format, model name,
   timeout, and structured output with a controlled smoke request.
5. Deploy one route at a time. Check service logs, Telegram output quality,
   latency, error/fallback rate, and provider usage after the next scheduled
   execution.
6. If quality, spend, or availability regresses, restore the prior route order
   or disable the LLM feature. The local deterministic fallbacks remain the
   immediate safety path.
7. Update this map and the operational changelog with the effective date,
   verified model/endpoint, evidence, and rollback result.

## Change checklist

- Which user-visible workload calls the LLM?
- Which code file owns its primary route and its fallback route?
- Which secret names are required, and where is the sanitized template?
- Are output limits, timeouts, and deterministic validation preserved?
- Does the model change invalidate prompts, caches, or quality expectations?
- Where will spend, quota, errors, and fallback rate be observed?
- What exact rollback restores known-good behaviour?
