# Changelog

All notable changes to this deployment are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Changed

- **Qwen-first staged rollout (2026-08-14):** transferred the DashScope
  credential only between ignored server-side environments, then applied Qwen
  `qwen3.7-flash` before DeepSeek to OmniRoute `light`, Signals Bridge, and
  Telethon Digest. Controlled Qwen smoke requests and the bridge health checks
  passed; DeepSeek remains the final LLM reserve and deterministic fallbacks
  remain intact. No secret value or Telegram message was emitted by the checks.

- **Gateway image recovery and Qwen activation:** rebuilt the expected derived
  Gateway image locally from the pinned upstream base plus the tracked
  compatibility Dockerfile, then recreated only the Gateway. `/healthz`, config
  validation, and a controlled `qwen-direct/qwen3.7-flash` text smoke passed;
  Qwen precedes DeepSeek in the active direct fallback order. A manual Telegram
  UI media retest remains a separate acceptance gate. LightRAG remains on its
  direct-DeepSeek extraction route until a separate extraction smoke passes.

- **Media-safe text fallback:** disabled automatic image, audio, and video
  understanding in Gateway `tools.media`. Qwen and DeepSeek are declared
  text-only reserves, so a primary vision failure cannot create a misleading
  `Image: Analyze ...` request through the Qwen route; the user instead needs a
  working vision primary or a text clarification.

- **LLM provider map:** added docs/24-llm-provider-map.md as the canonical
  inventory of model routes, sanitized credential names, cost controls, and
  a reversible migration procedure for every LLM workload.

- **Shared VPS incident contract**: documented the routing/host/OpenClaw
  ownership boundary, Docker boot-order evidence, OOM separation, safe
  read-only triage and redaction requirements for cross-project incidents.

- **Signals ruleset execution hardening**: `signals-bridge` now rejects duplicate `rule_sets.id`
  values across the base config and ignored rule fragments instead of silently running only the first
  matching ruleset. Telethon session use is serialized across polling, relay, and interactive auth,
  with a bounded retry for transient SQLite `database is locked` errors. `/health` and `/status` now
  expose per-source healthy/stale/error state so a partially stalled signals feed cannot look healthy
  merely because another ruleset is still running. Manual Telegram lookback is a strict timestamp
  boundary even when a source cursor is stale, preventing old retained messages from being replayed
  during recovery; stale automatic sources resume only over the normal overlap and require an explicit
  source-only lookback for wider recovery.
- **Signals Russian yuan inflections**: fixed deterministic FX matching so the canonical `юань` /
  `cny` / `yuan` keywords cover standard Russian inflections while preserving whole-word boundaries.
  A source-only repair run caught up the missed private-channel post and delivered one fresh signal
  without duplicates.
- **OpenClaw version compatibility ledger**: added a dedicated, versioned registry for derived-image
  adaptations, historical failure signatures, release gates, and rollback evidence. Future OpenClaw
  candidates must start from this record, carry active workarounds deliberately, and close the
  required manual Telegram UI gate before promotion. The retained image timeline now has an explicit
  record for every release, including releases with no version-specific incompatibility.
- **Signals market-source extension**: deployed one additional private Telegram source through the
  existing FX/Si deterministic keyword rule with a 15-minute bootstrap. Its source-only validation
  scanned 76 messages, produced zero matches, and left the bridge healthy; real identifiers remain
  only in ignored runtime configuration. Startup now also releases only interrupted configured
  ruleset locks, so a bridge restart cannot suppress the next signals run for the full lock TTL.
- **OpenClaw 2026.6.11 canary rollback**: built the latest stable derived image and passed health,
  config, reserve-model, and channel probes, but the scripted MTProto smoke could not prove UI
  ingress on either the candidate or the restored image. Production was immediately restored to the
  confirmed `2026.6.9-telegram-polling-hotfix` image; `2026.6.11` remains pending a manual UI smoke.
- **AgentMail work-email delivery recovery**: repaired live scheduled Telegram digest delivery after
  host cron was repeatedly failing with `Permission denied` on the work-email trigger script. The
  deploy helper now writes work-email cron entries through `bash /opt/agentmail-work-email/trigger-email-digest.sh`
  so delivery does not depend on the script executable bit; a manual `interval` digest validated the
  live `work-email` topic with `exit_code=0`.
- **OpenClaw upgrade assessment**: documented the `2026.6.11` stable release check and kept production
  pinned to the `2026.6.9` Telegram polling hotfix until a separate derived-image canary proves fresh
  Telegram UI ingress and outbound replies.
- **OpenClaw Gateway resource containment**: bounded the live Gateway restart policy to
  `on-failure:5`, capped Docker json logs at `10m x3`, and added
  `OPENCLAW_NODE_OPTIONS=--max-old-space-size=768` so repeated `exit=137` events stop inside the
  OpenClaw budget instead of causing a host-level outage that can take `maxtg_bridge` down.
- **Football Telegram topic recovery**: registered the live football forum topic, reset its stale
  OpenClaw session state after a missed inbound update, and verified delivered topic smokes after
  restoring the intended `openai/gpt-5.5` primary plus `deepseek-direct/deepseek-chat` reserve policy.
  The temporary DeepSeek-primary recovery attempt was rolled back; OpenAI cooldowns must be handled by
  the configured fallback chain rather than by changing the global primary route.
- **AgentMail poll gateway isolation**: the 5-minute AgentMail `poll` path now skips OpenClaw LLM
  classification by default and uses the deterministic prefilter/label path. This prevents parallel
  personal/work AgentMail poll windows from launching heavy `openclaw agent` execs inside
  `openclaw-gateway` and taking Telegram replies down with `exit=137`.
- **Telegram ingress diagnostics**: after AgentMail containment, a fresh football-topic no-reply was
  narrowed to the Telegram ingress/update path rather than the model route. Live diagnostics were
  enabled with `OPENCLAW_LOG_LEVEL=debug` and `OPENCLAW_DEBUG_TELEGRAM_INGRESS=1`; OpenAI remains the
  primary model and `deepseek-direct/deepseek-chat` remains the reserve.
- **OpenClaw Telegram polling hotfix**: added a derived-image kill switch for the OpenClaw 2026.6.9
  isolated Telegram ingress worker and deployed the live Gateway with
  `OPENCLAW_TELEGRAM_ISOLATED_INGRESS=0`. Fresh Telegram UI messages now reach the regular polling
  handler again; this is separate from Telethon, which is only used by digest/MTProto jobs.
- **OpenClaw OpenAI primary restore**: imported the legacy OpenAI auth profile JSON into the
  `openclaw-agent.sqlite` auth store, set the tracked OpenAI provider to ChatGPT/Codex OAuth
  transport, and revalidated the default Gateway route on `openai/gpt-5.5` without fallback.
- **OpenClaw runtime live upgrade**: upgraded the tracked target for the live derived gateway image
  to `openclaw-with-iproute2:20260624-slim-2026.6.9`, based on the latest stable upstream
  `OpenClaw 2026.6.9` release. The live Gateway upgrade, `deepseek-direct/deepseek-chat` fallback
  repair, and validation are recorded in the command log.
- **Telegram Digest content mix**: `telethon-digest` now caps the `news` folder during source
  selection, targeting about 30% and hard-capping at 35% when other allowlisted folders have enough
  scored candidates. The cap expands automatically when non-news folders are sparse, keeping quiet
  slots populated instead of dropping strong posts.
- **Telegram Digest status and rendering clarity**: the cron bridge now marks an in-flight digest as
  interrupted after a bridge restart instead of leaving `running=true` stale, releases the matching
  Redis run lock on recovery, and the Telegram header now distinguishes processed source messages
  from posts selected for the final issue. LLM summarization now parses fenced JSON before treating
  retry/clarification markers as a failed response, reducing unnecessary deterministic fallback.
- **OpenClaw runtime live upgrade**: upgraded the live derived gateway image to
  `openclaw-with-iproute2:20260619-slim-2026.6.8`, based on the latest stable upstream
  `OpenClaw 2026.6.8` release. The gateway was recreated, and the current service set was
  brought up and revalidated after the recreate. Removed the stale live `telethon-digest`
  service from the OpenClaw compose override so broad OpenClaw compose operations no longer
  create an obsolete digest container.
- **Telegram Digest scheduled channel coverage**: scheduled slot runs now backread by time window
  instead of prefiltering with per-channel cursors, keeping cursor watermarks monotonic while the
  digest header reports channels active inside the exact window. Low-coverage scheduled reads now
  retry once with slower Telethon pacing before scoring.
- **OpenClaw 2026.6.1 auth-order hardening**: aligned the tracked Gateway config with the live
  recovery path: canonical `openai:*` OAuth profiles for `openai/gpt-5.5`, matching
  `models auth order` override guidance, and a direct `deepseek/deepseek-v4-flash` reserve route
  instead of routing interactive Telegram turns through `omniroute/light`.
- **OpenClaw runtime live upgrade**: upgraded the live derived gateway image to
  `openclaw-with-iproute2:20260606-slim-2026.6.1`, based on the latest stable upstream
  `OpenClaw 2026.6.1` release. The gateway returned healthy and `/healthz` returned live status after
  the recreate.
- **Live Docker resource guardrails**: capped the main 2-vCPU AI path with about 20% host headroom:
  `openclaw-gateway` at `0.90 CPU / 1224m`, `omniroute` at `0.25 CPU / 512m`, and `lightrag` at
  `0.45 CPU / 2304m` with `2816m` memory-swap. The LightRAG cap was raised after the current
  graph cold start OOMed at 1536MB.
- **Telegram LLM route order**: `telethon-digest` and `signals-bridge` now use the intended route order for LLM enrichment: OpenClaw `openai/gpt-5.5` primary via the live Gateway, OmniRoute fallback, then optional DeepSeek API fallback. Deterministic local fallback is now last-resort only after all model routes fail.
- **OpenClaw runtime live upgrade**: upgraded the prepared derived gateway image to `openclaw-with-iproute2:20260528-slim-2026.5.27`, based on the latest stable upstream `OpenClaw 2026.5.27` release. Removed the stale managed npm `codex@2026.5.12` plugin install so the live registry uses the bundled `codex` plugin from the current OpenClaw image.
- **OpenAI primary auth refresh**: refreshed the live `openai-codex` token profile used by the `openai/gpt-5.5` primary route. OmniRoute/OpenRouter remain configured as the first fallback route.
- **OpenClaw compaction reserve**: set the live Gateway `agents.defaults.compaction.reserveTokensFloor` to `20000` to avoid over-aggressive auto-compaction recovery after long tool-heavy turns.
- **LightRAG route split**: registered DeepSeek as the final OmniRoute `light` LLM reserve for RAG answer generation, then moved the live LightRAG extraction hop to direct `deepseek-chat` after OmniRoute `light` timed out. Retrieval now uses `wiki-import` local 3072-dimensional embeddings because Gemini/OpenRouter embeddings are blocked by quota/credits. DeepSeek is explicitly documented and smoke-tested as not being an embeddings provider.
- **Telethon Digest scheduler**: moved live digest scheduling from OpenClaw agent-turn Cron Jobs to `/etc/cron.d/telethon-digest`, which calls `/opt/telethon-digest/trigger-digest.sh` directly. This avoids false-positive OpenClaw cron runs when the lightweight cron context has no shell tool available.
- **OpenClaw runtime target**: updated the redacted OpenClaw image template from `openclaw-with-iproute2:20260412-slim-2026.4.11` (`OpenClaw 2026.4.11`) to `openclaw-with-iproute2:20260516-slim-2026.5.12`, based on the GitHub latest stable release and GHCR `latest` image reporting `OpenClaw 2026.5.12`. Added a tracked `artifacts/openclaw/Dockerfile.iproute2` template for rebuilding the minimal derived image with only `iproute2`; the live `/opt/openclaw` gateway now runs this image.
- **OpenClaw model policy**: live Gateway uses `openai/gpt-5.5` as primary and direct DeepSeek as reserve. Builtin `memorySearch` remains disabled while external embedding limits are unstable; LightRAG remains the intended retrieval layer.
- **OpenClaw GPT model ref**: replaced active legacy GPT/OpenAI Codex references with canonical OpenClaw `openai/gpt-5.5` fallback docs and footer labels, matching the current live model catalog and OpenClaw provider docs.
- **OpenClaw Codex catalog hygiene**: disabled live Codex model discovery, pruned older static Codex catalog entries in the derived-image template, and cleaned the deployed `signals` topic session state so stale GPT footer context no longer survives gateway restarts.
- **LightRAG smoke script**: `scripts/smoke-check-knowledge.sh` now uses `/query/data` with explicit keyword hints and no reranker so retrieval checks can validate references and source links without waiting on answer synthesis.
- **LLM-Wiki lifecycle metadata**: wiki pages now distinguish workflow origin (`capture_mode`), curation depth (`curation_level`), and lifecycle stage (`capture_state`). `wiki-import` adds review metadata, lifecycle-aware lint diagnostics, and a new `/maintain` endpoint for safe archive/report refreshes.
- **Research archive policy**: low-signal research pages can now move into `wiki/archive/research/**` while staying inside `wiki/**` for LightRAG recall. `OVERVIEW.md` and `TOPICS.md` now treat archived research as lower-prominence material instead of deleting it from the knowledge graph.
- **wiki-import deployment flow**: `scripts/deploy-wiki-import.sh` now syncs dedicated OpenClaw cron jobs for daily lifecycle dry-run reports and weekly safe archive refreshes.
- **Knowledge capture is now wiki-first by contract**: explicit saves from `📚 Knowledgebase`, `💡 Ideas`, and Ideas promotion are documented and implemented as `raw -> wiki/research -> optional canonical pages -> LightRAG`, instead of treating LightRAG upload as the primary success condition.
- **Ideas capture semantics**: `💡 Ideas` no longer means “outside wiki until promotion”. Explicit captures now create a visible light-curated `wiki/research/**` page immediately; promotion deepens the same artifact chain instead of materializing it from scratch.
- **Telegram save UX**: pinned messages, agent instructions, and knowledge-management docs now describe wiki-first success replies with a concrete `wiki/research/**` page path and separate `LightRAG` freshness status.
- **Knowledgebase historical-save recovery**: documented and operationalized a dedicated backfill path for old `Knowledgebase` posts that were previously handled as `raw/articles + LightRAG` without visible wiki artifacts.

### Added
- **Gateway wiki-import wrapper**: added `workspace/bin/wiki_import_tool.py`, a narrow runtime helper
  that calls the internal `wiki-import` API from the OpenClaw Gateway using a mounted token file. This
  makes `Knowledgebase` saves work even when `wiki_ingest` is only a documented workflow concept and
  not exposed as a native OpenClaw tool.
- **wiki-import local embeddings endpoint**: added authenticated `/v1/embeddings` compatibility with
  deterministic 3072-dimensional vectors so LightRAG can keep indexing when Gemini/OpenRouter
  embeddings are blocked by external quota or credits.
- **Human-first memory explainer**: added `docs/19-llm-wiki-memory-explained.md` with Mermaid diagrams for vault structure, compile flow, explicit save flow, query path, and the role split between `wiki`, `LightRAG`, and OpenClaw.
- **LLM-facing project orientation**: added `docs/20-llm-project-orientation.md` so another model can understand what this repo is, which docs are canonical by topic, and how to navigate the current architecture without scanning the whole tree blindly.
- **wiki-import cron sync helper**: added `artifacts/wiki-import/sync-openclaw-cron-jobs.sh` to patch the OpenClaw cron store with lifecycle maintenance jobs safely and idempotently.
- **`wiki-import` capture modes**: `POST /trigger` now supports `capture_mode` (`knowledgebase` / `ideas` / `promotion`) plus promotion reuse via stable fingerprint, returns `wiki_page_paths`, `canonical_pages_updated`, `rag_enqueued_paths`, `rag_status`, and `status`, and performs immediate non-blocking RAG enqueue only for touched `wiki/**/*.md` pages.
- **Knowledge-capture tests**: added unit coverage for ideas light-curation saves, promotion reuse of existing research pages, wiki-first response payloads, partial success when LightRAG enqueue fails, and explicit rejection of raw-to-LightRAG uploads in interactive save flows.
- **`scripts/backfill-knowledgebase-to-wiki.sh`**: the Knowledgebase backfill helper now runs as a two-stage replay: every historical item is first materialized as a source-centric `ideas` capture, and only high-signal articles are immediately re-run through `promotion` to deepen canonical wiki pages without reviving broad graph noise.
- **Claude/Gemini research prompt for memory lifecycle**: added `docs/18-claude-llm-wiki-memory-lifecycle-prompt.md` so the current LLM-Wiki lifecycle problem can be handed to another model with consistent context, constraints, and evaluation criteria.
- **OmniRoute DeepSeek sync helper**: added `scripts/sync-omniroute-deepseek-provider.sh` to upsert the live DeepSeek key into OmniRoute's encrypted provider store and attach `deepseek/deepseek-chat` as the final `light` combo reserve.
- **OmniRoute OpenRouter sync helper**: added `scripts/sync-omniroute-openrouter-provider.sh` to upsert the live OpenRouter key into OmniRoute's encrypted provider store, clear stale no-credential/quota state, and smoke-test 3072-dimensional embeddings from the LightRAG runtime.

### Fixed
- **LightRAG and wiki boot context recovery**: restored live LightRAG health after `Exit 137` cold
  starts by raising the live memory limit, and synced bot-facing top-level wiki navigation files into
  the OpenClaw workspace so `wiki/OVERVIEW.md` cold-start reads no longer fail with `exit 2`.
- **Telegram forum topic routing**: registered the live `football` forum topic in the server
  `telegram-topic-map.json` after an unlisted topic stopped producing agent inbound logs even though
  OpenAI primary and Telegram Bot API sends were healthy.
- **AgentMail bridge deploy safety**: deploy helpers now propagate `poll_llm_enabled=false` into
  existing live configs and treat a missing legacy OpenClaw cron store as a warning because host cron
  is authoritative for AgentMail digest delivery.
- **Knowledgebase save recovery after 2026.6.1**: recovered a missed `Knowledgebase` save after the
  message reached Telegram ingress but the agent turn failed on the new OpenAI provider-auth regression
  plus a stale compacted topic transcript. Reset only the affected topic/generic session mappings,
  recreated the Gateway, manually imported the missed source into `wiki-import`, and validated a fresh
  topic smoke reply through the configured fallback route.
- **Telegram Digest Telethon session recovery**: upgraded `telethon-digest` from `Telethon 1.36.0` to
  `1.43.2` after the live session database gained the newer `tmp_auth_key` column and the old runtime
  started failing every scheduled digest with `ValueError: too many values to unpack`. A manual interval
  smoke completed with `exit_code=0`, posted three chunks, persisted the derived note, and enqueued RAG.
- **Telegram ingress spool recovery**: added `scripts/recover-telegram-ingress-spool.sh` and installed
  a live cron guard that requeues only `.json.processing` Telegram updates claimed before the current
  `openclaw-gateway` container start. This fixes the no-reaction failure mode where a Gateway recreate
  leaves isolated-polling claims behind and the new container reuses the same PID.
- **Knowledgebase missed-save backfill**: recovered the blocked `Knowledgebase` topic by requeueing
  stale Telegram spool claims, resetting only the stale topic 232 session mapping, then backfilling the
  missed forwarded posts into wiki/LightRAG. A live Knowledgebase smoke returned `Сохранено в wiki` and
  LightRAG showed `busy=false`.
- **LightRAG embeddings recovery**: added a local OpenAI-compatible embeddings endpoint to `wiki-import`, switched live LightRAG embeddings to `local/hash-embedding-3072`, synced the OmniRoute OpenRouter provider store for future paid-route recovery, cleared `WIKI_IMPORT_RAG_DEGRADED_REASON`, and validated that new `Knowledgebase` saves enqueue touched wiki pages instead of returning `LightRAG: degraded`.
- **Knowledgebase save tool availability**: mounted the `wiki-import` token into the Gateway as a
  file-only secret, deployed the workspace wrapper, reset the stale `Knowledgebase` session, and
  validated a real Telegram save. The live reply now confirms `raw/**` + `wiki/**` creation and marks
  LightRAG as degraded instead of saying `wiki_ingest` is unavailable.
- **Knowledgebase forwarded-save stall**: reset a stuck `Knowledgebase` topic session after a long
  forwarded save wandered into broad OpenClaw/source searches and hit an active-model timeout. The
  workspace policy now requires direct `wiki_ingest` for forwarded/long save content and a short
  operator error instead of repo/source diagnostics when ingest is unavailable.
- **Knowledgebase stale session compaction recovery**: reset the live stale `Knowledgebase` topic session mapping and generic `agent:main:main` mapping after `reserveTokensFloor=20000` was already present but the old transcript kept failing with `already_compacted_recently`. Backed up the session records, recreated the Gateway, and validated a fresh Knowledgebase Telegram smoke without auto-compaction errors.
- **Knowledgebase save degraded RAG UX**: `wiki-import` now supports an explicit `WIKI_IMPORT_RAG_DEGRADED_REASON` mode so Knowledgebase saves still materialize `raw/**` and `wiki/research/**` while skipping known-failing LightRAG uploads. Telegram instructions now treat `rag_status=degraded` as a successful wiki-first save and forbid leaking raw infra-debug messages such as `getent hosts ... (agent) failed` after the save.
- **Telegram Digest full-day windows and lead links**: aligned live `telethon-digest` schedule config with the host cron slots (`08:00`, `11:00`, `14:00`, `17:00`, `21:00` MSK), made scheduled runs read/filter exact nominal windows instead of drifting from `last_run`, expanded overnight lookahead for `21:00-08:00`, and made `Главное` bullets render source `→` links like folder items.
- **AgentMail email digest delivery**: moved `inbox-email` and `work-email` scheduled digest delivery from OpenClaw agent-turn Cron Jobs to host cron direct `/trigger` calls. The email pollers were healthy and continued producing Redis events; only Telegram delivery was stalled because OpenClaw Cron reported false-positive `ok` runs without an exec/shell tool.
- **Telegram Digest deterministic fallback path**: fixed the digest service using direct OmniRoute only; it now tries the existing OpenClaw/OpenAI subscription first, then OmniRoute and DeepSeek before rendering `local deterministic fallback · no LLM`.
- **Telegram Digest LLM validation**: fixed `post_url` validation so Telegram URLs are preserved as URLs instead of being stripped by the text cleaner. The live smoke posted a fresh `08:00-08:45` digest with `model: gpt-5.5` and `fallback: false`.
- **Telegram Digest cron windows**: corrected host cron to use explicit UTC schedule times while passing Moscow slot labels as script arguments. This prevents the `11:00` slot from firing at `14:00 MSK` and rendering a stale `09:00-11:00` window.
- **Signals OpenClaw route sessions**: `signals-bridge` now uses short-lived unique OpenClaw route session keys, avoiding stale long Telegram topic sessions and auto-compaction pressure when model routes are unavailable.
- **Telegram bridge recovery after host clock drift**: repaired the live Telegram delivery outage that started after the Sunday runs by correcting host time, adding a small HTTPS Date systemd timer guard, restarting `signals-bridge` and `telethon-digest`, fast-forwarding stale `signals` Redis jobs, and validating fresh bridge runs. `signals` now has zero Redis lag/pending jobs, and `telegram-digest` completed a fresh interval digest with four posted chunks.
- **Live OpenAI token profile**: repaired the OpenAI path by replacing the expired server OAuth refresh path with a short-lived Codex token auth profile. Direct smoke returns `OK` through `openai/gpt-5.5`; OmniRoute and DeepSeek remain reserve routes.
- **OpenClaw auto-compaction recovery**: applied the live compaction reserve floor and validated a post-restart default agent smoke returning `OK_COMPACTION_FALLBACK` through `openai-codex/gpt-5.5`; recent gateway logs no longer show `Missing API key for provider "openai-codex"` or `Auto-compaction could not recover`.
- **Knowledge smoke transport and error semantics**: removed the remote temp-file/`scp` hop from `scripts/smoke-check-knowledge.sh` and made embedding paywall/credential failures produce an explicit deprecated retrieval status.
- **Live Telegram delivery smoke**: validated the deployed `Knowledgebase` topic with the existing Telethon owner session and a strict bot-reply filter; the bot returned an explicit source-style answer after the OmniRoute failure path fell through to OpenAI fallback.
- **OpenClaw usage-limit fallback path**: patched the live gateway runtime so embedded-agent
  `stopReason=error` results from `openai-codex` are rethrown into the model fallback layer instead
  of being surfaced to Telegram as a misleading login failure. This lets temporary ChatGPT usage
  limits attempt the configured OmniRoute fallback chain; OmniRoute still needs live upstream
  quota/credits to answer. The Telegram-facing failure text now reports ChatGPT usage limits
  directly instead of suggesting `openclaw models auth login`.
- **OpenClaw Codex OAuth recovery**: re-authenticated the live `openai-codex` profile after
  `refresh_token_reused` broke GPT-5.5 in Telegram, restarted `openclaw-gateway`, and verified a
  gateway smoke run returns `OK` via `openai/gpt-5.5`. Current policy keeps OpenAI as the
  default route and reserves OmniRoute/OpenRouter plus DeepSeek for fallback.
- **Telethon Digest schedule clarity + duplicate trigger guard**: `telethon-digest-cron-bridge` now rejects repeated triggers with `409 digest_already_running` while a digest is queued/running, instead of allowing tiny follow-up digests like `11:05–11:05`. Scheduled cron slots also pass their nominal hour into `digest_worker`, so the rendered digest window keeps the intended schedule label even when Telegram shows the post a few minutes later because processing finished at `11:05`.
- **Signals trading slang matching**: `signals-bridge` keyword matching now expands a narrow alias set for recurring trading shorthand, so canonical rules like `си` / `юань` / `cny` also match forms such as `сиху` and `юашку`. This fixes dropped Telegram alerts from the allowlisted Евгений Гуков rule without broadening the feed into generic FX noise.
- **Knowledgebase search routing**: clarified that `📚 Knowledgebase` search is local-first (`LightRAG` + builtin memory) and must not auto-fallback to internet `web_search`. Internet lookup is now opt-in only for this topic unless Denis explicitly asks for web/latest/online information or the request inherently depends on fresh external data. This fixes the misleading case where a temporary `web_search fetch failed` looked like a knowledge-base miss instead of a tool failure on an unnecessary route.
- **Knowledgebase pin text**: updated the canonical pinned message so it now states the same rule explicitly for users: short questions use local knowledge search by default, and internet search runs only on an explicit request such as `поищи в интернете`.
- **Telegram fallback order for knowledge workflows**: restored the OpenAI-primary generation chain for Telegram-side capture, save, and promotion flows. LightRAG extraction remains OmniRoute-based, with DeepSeek only as a reserve route behind OmniRoute.
- **Ideas/Knowledgebase direct ingest guidance**: tightened agent instructions so `Ideas` promotion and `Knowledgebase` save prefer direct `wiki_ingest(url)` when a stable source URL already exists, and use `wiki_ingest(text)` only when no reliable URL is available. This reduces unnecessary summarization hops before the canonical wiki write path.
- **Knowledgebase save routing precedence**: narrowed `Knowledgebase` search triggering to short question-like queries only, and made explicit save commands, forwarded posts, URLs, and long multiline notes prefer ingest first. This prevents long-form saved content from being handled as a conversational reply instead of `wiki_ingest`.
- **Telegram pin templates for knowledge UX**: added canonical pinned-message text under `artifacts/openclaw/telegram-pins.redacted.md`. `Knowledgebase` now documents the default “long content = save” behavior and the escape hatch `обсуди:` for discussion without ingest; `Ideas` pin now points users to `Knowledgebase` for direct durable saves.
- **`scripts/post-telegram-pins.sh`**: added a deploy helper that reads the live bot token and topic map on the server, posts fresh pin messages into `Knowledgebase` and `Ideas`, and pins the newly posted messages automatically.
- **Ideas vs Knowledgebase operating principle**: documented the canonical rule that the split is by intent, not by topic: `Ideas` means "capture now, decide later", while `Knowledgebase` means "commit this to durable system knowledge". Added explicit examples based on the recent Sequoia article and the `coding agents` note.
- **Knowledgebase search grounding**: tightened retrieval instructions so a short question in `Knowledgebase` must not stop at LightRAG/memory snippets. The agent now has to open 2–5 top references, inspect real wiki/workspace pages, and only then answer or explicitly say that nothing relevant was found.
- **Telegram retry UX for Knowledgebase saves**: documented that transient `read/edit/write` failures should not leak into Telegram as the main user-visible outcome when a retry succeeds. The agent should prefer full `write` over `edit` for large rewrites, remember the latest tool failure for the next turn, and explain it plainly if Denis asks what went wrong.

### Added
- **Auto-structured ingestion**: removed manual structured post format from Knowledgebase. Bot now auto-extracts title/domain/source/date/summary/sensitivity from any content (forwarded post, URL, plain text). User never fills fields manually. Updated `telegram-surfaces` configs, `workspace/TOOLS.md`, `workspace/TELEGRAM_POLICY.md`, pinned message in Knowledgebase, `docs/17-knowledge-management.md`.

- **💡 Ideas topic created**: new forum topic in Ben'ka_Clawbot_SuperGroup (topic_id=639) for frictionless capture of Telegram posts, links, and thoughts. Bot classifies, tags, and queues items; promotion to Knowledgebase requires explicit approval. Registered in server `telegram-topic-map.json` and `telegram-surfaces.policy.json`; local `telegram-surfaces.redacted.json` updated to `supergroup_topic` type.

- **Knowledgebase topic search**: the `📚 Knowledgebase` topic in Ben'ka_Clawbot_SuperGroup (topic_id=232) is now dual-purpose. Plain-text messages trigger knowledge base search (`lightrag_hybrid` + builtin memory search) and the bot responds with cited snippets. Structured posts (with required fields) continue to be ingested as CURATED/LONG_TERM. Surface type corrected to `supergroup_topic`; `search_mode` config added to `telegram-surfaces.redacted.json` and server `telegram-surfaces.policy.json`; topic registered in server `telegram-topic-map.json`; agent instructions updated in `workspace/TOOLS.md` and `workspace/TELEGRAM_POLICY.md`.

- **OpenClaw builtin memorySearch**: enabled the gateway's builtin hybrid memory layer on top of
  curated sources only — `MEMORY.md`, `memory/*.md`, and `/opt/obsidian-vault/wiki` — using
  Gemini embeddings (`gemini-embedding-001`) with snippet citations and embedding cache. This is a
  fast local recall layer for the agent and does not replace LightRAG.
- **Retrieval profile policy**: documented the canonical indexing boundaries across OpenClaw
  memorySearch, LightRAG, and LLM-Wiki. Raw vault sources (`raw/articles`, `raw/documents`, legacy
  vault trees) remain out of retrieval until curated import promotes them into `wiki/`.
- **Builtin memorySearch post-tuning**: tuned the OpenClaw builtin memory layer for the small
  Hetzner VPS by lowering the hybrid candidate pool (`candidateMultiplier=2`), disabling MMR
  reranking, and enabling provider-side Gemini batch embedding with `concurrency=1` and
  `wait=false` to make future reindex runs gentler on the host.
- **LLM-Wiki canonical registry v1.2**: added bot-maintained `CANONICALS.yaml` and `TOPICS.md`
  plus theme metadata, so importer now resolves core entities canonically before writing pages and
  exposes thematic navigation separately from typed folders.
- **wiki-import repair path**: `wiki_lint(repair=true)` can now merge duplicate canonical entities,
  rename colliding concept/research pages, remove low-signal auto decisions, normalize aliases and
  themes, and rebuild `INDEX.md`, `OVERVIEW.md`, and `TOPICS.md`.
- **LLM-Wiki storage model doc**: added `docs/16-llm-wiki-storage-model.md` to explain canonical
  identity, thematic metadata, topic maps, and the repair policy.
- **LLM-Wiki scaffold v2**: added bot-maintained `OVERVIEW.md` and `IMPORT-QUEUE.md` to
  `artifacts/llm-wiki/`, extending the schema from static templates to a real cold-start and
  curated-import workflow.
- **`wiki-import` bridge**: new internal service under `artifacts/wiki-import/` with `POST /trigger`,
  `POST /lint`, `GET /status`, deterministic source normalization (`url` / `text` / `server_path`),
  bot-owned queue state, and wiki/index/overview regeneration.
- **`scripts/deploy-wiki-import.sh`**: deployment helper for `/opt/wiki-import`; generates an
  internal token on first deploy, builds the service, and validates `GET /health`.
- **`scripts/bootstrap-llm-wiki.sh`**: bootstrap helper that submits the first curated imports from
  repo docs plus the external LLM-Wiki and Graphify references once `wiki-import` is online.
- **`docs/15-llm-wiki-query-flow.md`**: new end-to-end explainer for the LLM-Wiki stack covering
  canonical storage, narrowed ingest, curated import, LightRAG retrieval, and how OpenClaw uses
  retrieved context to assemble answers.
- **Last30Days raw signal export**: `signals-bridge` now writes
  `/opt/obsidian-vault/raw/signals/YYYY-MM-DD.md` after a successful Telegram post, keeping the
  signal digest inside the vault as a first-class raw source.
- **Last30Days preset split**: added `personal-feed-v1` and `platform-pulse-v1` preset structure,
  while keeping `world-radar-v1` as a compatibility alias to `personal-feed-v1`.
- **Platform Pulse renderer**: `signals-bridge` can now render a platform-first digest grouped by
  source with per-platform post counts plus English story titles and direct links.
- **Free Reddit hybrid adapter**: `signals-bridge` now patches the pinned upstream
  `last30days-skill` during Docker build and routes Reddit through `old.reddit.com` JSON first,
  native RSS fallback second, and `SCRAPECREATORS_API_KEY` only as an optional tertiary backup.
- **Reddit build-time patch set**: added
  `artifacts/signals-bridge/last30days_patches/reddit_hybrid.py` and
  `artifacts/signals-bridge/last30days_patches/patch_last30days_skill.py` so the external
  checkout can be upgraded deterministically without forking the whole upstream repo.
- **Reddit adapter tests**: added focused coverage for the patcher and hybrid enrichment path in
  `artifacts/signals-bridge/tests/test_last30days_patches.py`.
- **README redesign**: full rewrite with Mermaid architecture diagram (main graph LR + signals flow TD + Last30Days flow TD), services table, source coverage status table (including YouTube frozen status), model routing table, updated repository structure. Replaces ASCII art with GitHub-renderable diagrams.
- **docs/07-architecture-and-security.md**: added "Signals Bridge & Last30Days Architecture" section — HN companion pass, provider config table, source priority, per-source caps, YouTube frozen status.
- **docs/01-server-state.md**: added Signals Bridge state entry — ports, volumes, env vars, Last30Days metrics.
- **Last30Days HN companion pass**: `_run_hn_companion_themes()` runs 7 short Algolia-friendly queries
  (`OpenAI`, `Anthropic`, `AI regulation`, `startup funding`, `open source`, `robotics`, `cybersecurity`)
  in parallel against HN only, then merges results into the main theme pool before ranking. HN now
  surfaces reliably — verified 5 HN stories in top 10 themes vs 0 before.
- **OpenRouter reasoning provider**: added `OPENROUTER_API_KEY` + `LAST30DAYS_PLANNER_MODEL` /
  `LAST30DAYS_RERANK_MODEL` (`google/gemini-2.5-flash-lite`) to `signals.env` — external last30days
  script now uses LLM planning/reranking instead of deterministic fallback (`local_mode` disabled).
  Model ID `google/gemini-flash-2.0` was invalid on OpenRouter; corrected to `google/gemini-2.5-flash-lite`.


- **`artifacts/signals-bridge/`**: new standalone signals pipeline artifact with internal 5-minute
  scheduler, AgentMail + Telethon adapters, deterministic rule matcher, Redis-backed event/state
  store, cheap OmniRoute-light enrichment path, Telegram poster, config/env templates, auth helper,
  and focused unit tests.
- **`scripts/deploy-signals-bridge.sh`**: deployment helper for `/opt/signals-bridge`; keeps the
  service independent from OpenClaw Cron Jobs, hydrates missing bot/router secrets from the shared
  OpenClaw env when available, and validates `GET /health` after restart.
- **`artifacts/agentmail-email/`**: new AgentMail inbox-email pipeline artifact with standalone
  `docker-compose.yml`, `cron_bridge.py`, `agent_runner.py`, prompt builders, Redis-backed
  derived-event buffer, Telegram poster, config/env templates, and OpenClaw cron sync helper.
- **`artifacts/agentmail-email/agentmail_api.py`**: direct AgentMail HTTP adapter for inbox
  listing, message listing, thread reads, and mailbox label updates.
- **`scripts/deploy-agentmail-email.sh`**: deployment helper for `/opt/agentmail-email`,
  Python-first bridge deployment, central OpenClaw cleanup, cron sync, and post-deploy Docker cleanup.
- **`scripts/deploy-agentmail-work-email.sh`**: deployment helper for `/opt/agentmail-work-email`;
  deploys the live work-email runtime with isolated streams, labels, status key, and work-specific
  digest slots (`08:30` → `19:00` MSK).
- **Telegram topology**: new `inbox-email` topic/surface added to policy/config docs next to
  `work-email` and `telegram-digest`.
- **`skills/`**: repo-managed project skill catalog added, starting with
  `skills/openclaw-cron-maintenance/SKILL.md` as the canonical playbook for OpenClaw cron-store
  maintenance and hanging-CLI recovery.
- **`docs/14-codex-skills.md`**: new catalog for custom Codex skills, their scope boundaries,
  install/sync pattern, and the planned next skill set for this deployment.
- **`README.md` Telegram surfaces overview**: added a Mermaid high-level diagram plus a concise
  `what/why/how it works` section for DM, ops topics, inbox-email, work-email, telegram-digest,
  and signals so the Telegram architecture is understandable directly from the repo front page.

### Changed
- **Signals email body extraction**: `signals-bridge` now falls back through nested email
  `content/body/payload/parts` structures, converts HTML-only message bodies into text, and strips
  TradingView template chrome so alerts like `Mamontiara` keep the actual opinion text instead of
  collapsing back to the subject/preview line.
- **Signals Telegram relay fallback**: when bot-side `copyMessage` is unavailable, `signals-bridge`
  now relays Telegram originals through Telethon first, forwarding into the `signals` topic or
  resending the original `Message` object with its formatting intact instead of reuploading media
  through the Bot API. This preserves linked entities and avoids splitting long relayed posts into
  a second plain-text message in the common fallback path.
- **LLM-Wiki cutover strategy**: rollout is now safe by default — no destructive `rm -rf
  /opt/obsidian-vault/*`; legacy vault content can remain on disk but stays out of the active
  LightRAG ingest boundary.
- **LightRAG ingest boundary**: the tracked `scripts/lightrag-ingest.sh` now indexes only
  workspace markdown, `/opt/obsidian-vault/wiki/**/*.md`, and `/opt/obsidian-vault/raw/signals/**/*.md`.
- **Boot context**: cold start now reads `wiki/OVERVIEW.md` instead of the full `wiki/INDEX.md`,
  keeping startup context compact while preserving `INDEX.md` for maintenance/import logic.
- **Memory and architecture docs**: `README.md`, `docs/07-architecture-and-security.md`,
  `docs/10-memory-architecture.md`, `docs/11-lightrag-setup.md`, `workspace/AGENTS.md`,
  `workspace/MEMORY.md`, and `workspace/TOOLS.md` now describe the LLM-Wiki + wiki-import flow.
- **Last30Days naming model**: `world-radar` is now treated as the legacy name for
  `personal-feed`; docs and config examples now describe the split between `personal-feed`
  (our focused radar) and `platform-pulse` (what platforms are talking about).
- **Live and example config**: `last30days.preset_id` now points to `personal-feed-v1`, and both
  config files carry a `presets` map with core/experimental source layout for `platform-pulse-v1`.
- **Reddit source status**: the live `world-radar-v1` config now includes curated
  `platform_sources.reddit.feeds` subreddit seeds:
  `worldnews`, `technology`, `science`, `Futurology`, `economics`, `geopolitics`,
  `artificial`, `MachineLearning`, `OutOfTheLoop`.
- **Reddit error visibility**: `poster.py` no longer blanket-suppresses Reddit source failures, so
  real source-level issues now surface in digest diagnostics instead of being hidden.
- **README.md / docs/07-architecture-and-security.md / config.example.json**: expanded with the
  new Reddit hybrid retrieval order, curated subreddit configuration, diagnostics guidance, and
  updated repository structure/test counts.
- **Signals architecture**: `signals-bridge` now uses its own internal **5-minute** scheduler
  instead of any 30-second loop or OpenClaw cron job, and the enrichment path is explicitly limited
  to cheap `OmniRoute light` calls with low token settings plus a local fallback; GPT-5.5 is not
  used in the signals ingestion path.
- **Signals batch rendering**: signal mini-batches now retain a compact email excerpt and include a
  direct Telegram source link for Telegram-derived items, making manual review faster inside the
  `signals` topic.
- **Signals source relay**: after each mini-batch post, `signals-bridge` now additionally relays
  the original matched Telegram content into the `signals` topic when possible and posts an
  expanded email-content follow-up for email-derived matches.
- **Signals config layout**: public docs/templates no longer embed Denis-specific signal rules;
  the runtime now supports loading real local rule-sets from separate JSON files via `rule_files`
  (for example `secrets/signals-bridge/rules/*.json`).
- **`README.md` / `docs/03-operations.md` / `docs/13-ai-assistant-architecture.md`**: now document
  the standalone signals service, new Redis streams `ingest:jobs:signals` / `ingest:events:signals`,
  and the low-cost model policy for trading-style signals.
- **`artifacts/agentmail-email/cron_bridge.py`**: scheduled digests no longer disappear when the
  derived-event window is empty; the bridge now posts an explicit empty-window Telegram recap and
  marks the slot as delivered instead of silently skipping it.
- **`artifacts/agentmail-email/cron_bridge.py` / `poster.py`**: 5-minute `poll` runs are now
  internal-only (no Telegram mini-batches in `inbox-email`), while scheduled digests render
  directly from the real mailbox window and include exact message counts, sender counts, and
  per-message subjects for the slot.
- **`artifacts/agentmail-email/cron_bridge.py`**: the inbox-email 5-minute poll now runs from an
  internal scheduler inside the bridge instead of an OpenClaw cron job, and a deterministic
  prefilter skips obvious empty / low-signal windows before any LLM poll analysis.
- **`artifacts/agentmail-email/*`**: the shared AgentMail bridge codebase is now runtime-parameterized
  by env for streams, consumer group, status key, digest display titles, and slot-based schedules,
  which allows personal `inbox-email` and live `work-email` runtimes to coexist cleanly.
- **Work Email**: `work-email` is now live in production as a second standalone AgentMail runtime
  backed by `workmail.denny@agentmail.to`, with its own container `agentmail-work-email-bridge`,
  streams `ingest:jobs:email:work` / `ingest:events:email:work`, labels `workmail/*`, internal
  5-minute scheduler, and eight digest cron jobs from `08:30` to `19:00` Europe/Moscow.
- **`artifacts/agentmail-email/cron_bridge.py` / `scripts/deploy-agentmail-work-email.sh`**:
  `work-email` digests now resolve the original sender from forwarded-message headers (`От:` /
  `From:`) before rendering sender counts and message lines, while personal `inbox-email` keeps the
  previous direct-sender behavior.
- **AgentMail digest windows**: scheduled runs are now anchored to the fixed Moscow schedule
  boundaries (`08:00`, `13:00`, `16:00`, `20:00`) instead of drifting after a manual trigger.
- **`artifacts/telethon-digest/pulse.py`**: `Пульс дня` вынесен в отдельный модуль с общими
  правилами дедупликации по смысловому факту, fallback на реальные storyline из digest-контента,
  и без пустой заглушки про отсутствие сквозных тем.
- **`artifacts/telethon-digest/pulse.py`**: added interest-bucket ranking with persisted profile
  state in `/app/state/pulse-profile.json`; pulse selection now balances repeated signal, Denis-fit
  buckets, novelty, and diversity instead of only repeated news pressure.
- **`artifacts/telethon-digest/sync-openclaw-cron-jobs.sh`** and
  **`artifacts/agentmail-email/sync-openclaw-cron-jobs.sh`**: no longer depend on
  `openclaw cron list/add/remove`; they now patch the gateway cron store directly,
  back it up, and restart the gateway to avoid the hanging CLI path on this server.
- **Telethon Digest schedule**: окна обновлены до `08:00`, `11:00`, `14:00`, `17:00`, `21:00`
  Moscow time across config, cron sync, deploy helper, and ops docs.
- **`README.md`**: repository structure, integration-bus status, quick ops, and feature list now
  include the AgentMail inbox-email pipeline.
- **OpenClaw runtime image**: production first moved from `openclaw-with-iproute2:20260408` to
  a slim image without Whisper, and then to `openclaw-with-iproute2:20260412-slim-2026.4.11`;
  the image still keeps only `iproute2` and no longer bakes in Whisper, ffmpeg, or the extra
  Python venv/toolchain.
- **OmniRoute**: upgraded from `3.5.9` to `3.6.3`, pinned in `/opt/openclaw/omniroute-src`
  on local branch `deploy/v3.6.3`, rebuilt in place with the existing `omniroute-data` volume.
- **`README.md` / `docs/03-operations.md` / `docs/13-ai-assistant-architecture.md`**: now show
  `agentmail-email-bridge` as its own Docker service in the main architecture, document the
  recovery/backfill path via `lookback_minutes`, and describe the Python-first AgentMail flow.
- **`artifacts/agentmail-email/`**: removed embedded OpenClaw runtime path and removed AgentMail MCP
  from the active runtime path; the bridge now reads mailbox data directly over AgentMail HTTP,
  while OpenClaw only handles JSON-only classification and digest generation.
- **`artifacts/agentmail-email/sync-openclaw-cron-jobs.sh`**: the token-spending `*/5` poll cron
  job was removed entirely; OpenClaw now manages only the four digest slots for inbox-email.
- **`artifacts/agentmail-email/cron_bridge.py`**: trigger payload now accepts `lookback_minutes`
  for manual catch-up windows; poll/digest status tails include concise runtime summaries; label
  commit now tolerates per-message `404 NotFoundError` instead of failing the whole run.
- **`artifacts/agentmail-email/prompts.py`**: OpenClaw prompts now operate on pre-fetched
  thread snapshots / derived events only and explicitly disallow mailbox tools.
- **`artifacts/openclaw/openclaw.json`**: removed `mcp.servers.agentmail` and tightened
  `tools.profile` back to `"coding"`.
- **`scripts/deploy-agentmail-email.sh`**: post-deploy validation now checks that the 5-minute
  poll cron job is absent, that the four digest cron jobs remain enabled with next scheduled runs,
  and it still removes stale AgentMail-specific env/config coupling from the shared OpenClaw deployment.
- **Server cleanup**: stale email Redis lock/pending entry removed after embedded-runtime rollback;
  unused Docker build cache cleared and the bridge image size dropped from ~2.78 GB to ~229 MB.
- **`README.md` / `docs/01-server-state.md` / `docs/02-openclaw-installation.md` / `docs/03-operations.md` / `artifacts/openclaw/env.redacted.example`**:
  updated to reflect that voice transcription is disabled in production for now and may return later
  through a lighter CPU-oriented stack or an external API.
- **`docs/01-server-state.md` / `docs/03-operations.md` / `docs/13-ai-assistant-architecture.md`**:
  updated to reflect current OpenClaw `2026.4.11` and OmniRoute `3.6.3` runtime state.
- **`docs/03-operations.md`**: added AgentMail inbox-email deploy/runbook section.
- **`docs/12-telegram-channel-architecture.md`** and **`docs/13-ai-assistant-architecture.md`**:
  added `Inbox Email` surface, bus streams `ingest:jobs:email` / `ingest:events:email`, and
  near-real-time poll + scheduled digest architecture.

### Verified
- `python3 -m unittest discover -s artifacts/signals-bridge/tests -p 'test_*.py'`
- `python3 -m py_compile artifacts/signals-bridge/*.py artifacts/signals-bridge/tests/*.py`
- `bash -n scripts/deploy-signals-bridge.sh`
- `agentmail-email-bridge` now starts as a lightweight Python image (`229 MB` on server after rebuild).
- `/trigger` returns `202` and enqueues `poll` jobs into `ingest:jobs:email`.
- Bridge consumer loop starts successfully and performs direct AgentMail API reads / label updates.
- Manual `poll` finished with `exit_code=0` on `2026-04-11`; the window had no publishable emails, so
  the empty-window path completed without Telegram posting or label mutations.
- Manual `poll lookback=1440` finished with `exit_code=0` on `2026-04-12`; it scanned 32 threads,
  produced 1 publishable event, and applied `benka/polled=23`, `benka/low-signal=6` with one
  missing message id skipped safely.
- Manual `editorial` digest finished with `exit_code=0` on `2026-04-12`; it summarized the
  derived event buffer and applied `benka/digested=1`.

## [2026-04-11c] — Fix sync-openclaw-cron-jobs.sh duplicate prevention

### Fixed
- **`sync-openclaw-cron-jobs.sh`**: `read_existing_job_ids()` now uses `openclaw cron list`
  CLI output instead of reading the JSON file directly. Parses JSON output first, falls back
  to UUID extraction from text table lines. Eliminates silent failures that caused duplicates.
- Removed unused `OPENCLAW_CRON_STORE` variable from the script.

## [2026-04-11b] — Integration bus: async LightRAG ingest via ingest:rag:queue

### Added
- **`ingest:rag:queue` Redis stream**: LightRAG file uploads now go through the bus
  instead of being called synchronously inside the digest pipeline.
- **`rag_consumer_loop()`** in `cron_bridge.py`: second background thread that reads
  from `ingest:rag:queue` (consumer group `rag-workers`), uploads each file to
  `LightRAG /documents/upload`, calls `reprocess_failed`, writes `dlq:failed` on error.
- `_upload_file_to_lightrag_sync()` in `cron_bridge.py`: synchronous httpx upload
  used by the RAG consumer thread (no aiohttp needed in thread context).

### Changed
- **`persistence.py`**: `persist_digest()` now calls `_enqueue_lightrag_uploads()`
  instead of `_upload_paths_to_lightrag()` directly. If `REDIS_URL` is set, file paths
  are pushed to `ingest:rag:queue`; falls back to direct HTTP if Redis unavailable.
- **`cron_bridge.py`**: `main()` starts two background threads — `digest-consumer`
  (unchanged) and new `rag-consumer`.

### Verified
Digest triggered → `persistence.py` pushed `interval-*.md` to `ingest:rag:queue` →
`rag-consumer` uploaded to LightRAG HTTP 200 → `reprocess_failed` called → XPENDING=0, DLQ=0.

## [2026-04-11] — Integration bus v1 (Redis Streams)

### Added
- **`artifacts/integration-bus/docker-compose.yml`**: standalone Redis 7 Alpine Compose project.
  Joins `openclaw_default` network; persistent `integration-bus-redis-data` volume.
  Deploy at `/opt/integration-bus/` on server.
- **Integration bus streams** (naming convention):
  - `ingest:jobs:{source}` — batch job triggers (telegram, email, …)
  - `ingest:events:{source}` — real-time item events (signals, private groups — v2)
  - `ingest:rag:queue` — LightRAG indexer queue (v2)
  - `dlq:failed` — dead letter queue for all sources

### Changed
- **`cron_bridge.py`** refactored to async-first bridge:
  - `POST /trigger` now enqueues to `ingest:jobs:telegram` via Redis XADD and returns HTTP 202
    immediately (previously blocked synchronously for up to 90 min).
  - Redis consumer loop runs as a background thread in the same container; reads from
    `ingest:jobs:telegram` consumer group `digest-workers`, calls `digest_worker.py --now`,
    writes status to `cron-bridge-status.json` (unchanged), pushes failures to `dlq:failed`.
  - Removed `fcntl` file lock (consumer group handles sequential processing).
  - Added graceful Redis reconnect with exponential backoff.
- **`requirements.txt`**: added `redis>=5.0.0`.
- **`docker-compose.yml`** (telethon-digest): added `REDIS_URL` env to `cron-bridge` service.

### Docs
- `docs/13-ai-assistant-architecture.md`: updated Telegram Digest architecture diagram to show
  async bus; replaced backlog section with implemented status + v2 backlog.
- `docs/03-operations.md`: added Integration Bus operations section (deploy, ping, stream
  inspection, DLQ, manual enqueue, trim commands).

## [2026-04-10] — telethon-digest: Telegram channel digest service

### Added
- **`telethon-digest` Docker service**: reads 150–200 Telegram channels via Telethon MTProto,
  scores posts by folder priority × pin boost, summarizes via OmniRoute `medium`, posts 4× daily
  (08:00/12:00/16:00/20:00 МСК) to `telegram-digest` topic in `Benka_Clawbot_SuperGroup`.
- Service files prepared for `/opt/telethon-digest/`:
  `auth.py`, `digest_worker.py`, `reader.py`, `scorer.py`, `link_builder.py`,
  `summarizer.py`, `poster.py`, `state_store.py`, `sync_channels.py`, `Dockerfile`, `requirements.txt`.
- `artifacts/telethon-digest/` added to repo with all Python modules, standalone `docker-compose.yml`,
  `config.example.json`, and `telethon.env.example` (redacted).
- Standalone Compose project uses the external `openclaw_default` network plus `telethon-sessions`
  and `telethon-state` named Docker volumes.
- Local gitignored secret source created at `secrets/telethon-digest/telethon.env`.
- Telethon user session authorized and stored in the `telethon-sessions` Docker volume.
- Telegram folders synced into server `config.json`: 18 folders, 499 dialogs, 426 broadcast channels.
- Read scope locked down with explicit allowlist and `read_broadcast_channels_only=true`.
- Local gitignored catalog copy created at `secrets/telethon-digest/config.local.json`.
- `docs/13-ai-assistant-architecture.md` updated with Telegram Channel Digest section.
- `docs/14-telethon-digest-handoff.md` added as the continuation/runbook source for future LLMs.

### Fixed
- Telethon Digest summarizer now handles OmniRoute `text/event-stream` responses as well as JSON
  chat completions, and falls back locally if the LLM refuses summarization.

### Verified
- Full smoke test read the allowlisted channels, selected top posts, and posted digest chunks to the
  `telegram-digest` topic through the OpenClaw Telegram bot.
- Synthetic OmniRoute summarization smoke test passes after the SSE parser fix.
- Daemon started successfully; APScheduler next run is managed inside the `telethon-digest` container.

## [2026-04-10]

### Fixed
- OpenAI Codex rate-limit failover: added `agents.defaults.model.fallbacks` in `openclaw.json` so
  when Codex hits its usage cap the gateway automatically retries `omniroute/smart` → `omniroute/medium`
  → `omniroute/light` instead of surfacing the error to the user. Config hot-reloaded on the live server.
- OmniRoute combo model IDs corrected: `smart` now uses `kiro/claude-sonnet-4.5` (was `claude-sonnet-4-5`
  with dashes), `medium` and `light` now use `kiro/claude-haiku-4.5` (was `claude-3-5-haiku-20241022`).
  All three tiers verified working.

### Added
- `docs/13-ai-assistant-architecture.md`: comprehensive description of AI assistant design principles,
  model routing (primary + OmniRoute fallback tiers), Telegram surface interaction model, memory
  classes, LightRAG integration rules, approval gates, and anti-patterns.
- AGENTS.md updated on server: model-selection and fallback sections updated; response footer instruction
  added (`_model · ctx% · memory_` at end of every Telegram reply).
- Daily memory file `memory/2026-04-10.md` created on server with today's decisions and open items.

### Added
- Telegram channel architecture policy:
  - final / minimal / safe-first topology for DM, ops supergroup topics, work email, Telegram digest, signals, family, knowledge, ideas, and sandbox
  - least-privilege permission matrix for each Telegram surface
  - OpenClaw behavior modes and approval boundaries
  - conservative memory and RAG/Obsidian ingestion gates
  - redacted implementation draft in `artifacts/openclaw/telegram-surfaces.redacted.json`
  - runtime policy file in `workspace/TELEGRAM_POLICY.md`
- Telegram policy deployed to the live server:
  - `workspace/TELEGRAM_POLICY.md` deployed to `/opt/openclaw/workspace/`
  - ops forum topics created in the live supergroup: `inbox`, `approvals`, `tasks`, `signals`, `system`, `rag-log`, `work-email`, `telegram-digest`
  - server-local topic map written to `/opt/openclaw/config/telegram-topic-map.json`
  - server-local live surface policy written to `/opt/openclaw/config/telegram-surfaces.policy.json`
  - full redacted architecture document copied into server workspace `raw/` for LightRAG indexing

### Fixed
- LightRAG indexing repaired on the live server:
  - attached `lightrag-lightrag-1` to `openclaw_default` with DNS alias `lightrag`
  - replaced public `0.0.0.0:9621` publish with host-local `127.0.0.1:8020`
  - changed healthcheck from missing `curl` to Python `urllib`
  - switched LightRAG extraction from OmniRoute `light` to direct Gemini `gemini-2.5-flash-lite`
  - reprocessed the corpus successfully (`processed=26`, `failed=0`)

### Changed
- Expanded LightRAG documentation across README, memory architecture, setup, operations, and workspace tool docs:
  - why LightRAG exists
  - what data is ingested
  - how cron/upload/reprocess updates the index
  - how OpenClaw queries it
  - when LightRAG results are trustworthy versus when live checks are required

---

## [2026-04-10] — OmniRoute smart model routing layer + Бенька model selection

### Added
- **OmniRoute** deployed as additional service in OpenClaw Docker Compose (via `docker-compose.override.yml`)
  - Source cloned to `/opt/openclaw/omniroute-src`
  - Dashboard: `127.0.0.1:20128` (SSH tunnel access only)
  - API: `127.0.0.1:20129` (OpenAI-compatible `/v1/*`, `REQUIRE_API_KEY=true`)
  - Network: `openclaw_default` (same as openclaw-gateway and lightrag)
  - Providers connected: Kiro (AWS Builder ID OAuth, Claude Sonnet/Haiku, free unlimited), OpenRouter (API key hub — Claude 3.5, Kimi K2, Qwen3), Gemini (API key, Flash)
  - Routing tiers (priority order, auto-fallback):
    - `smart`: Kiro/claude-sonnet-4-5 → OpenRouter/claude-3.5-sonnet → OpenRouter/kimi-k2
    - `medium`: Kiro/claude-3-5-haiku → Gemini/gemini-2.0-flash → OpenRouter/qwen3-30b
    - `light`: Gemini/gemini-2.0-flash → OpenRouter/qwen3-8b → Kiro/claude-3-5-haiku
- **LightRAG LLM** switched from direct Gemini to OmniRoute `light` tier (`LLM_BINDING=openai`, `LLM_BINDING_HOST=http://omniroute:20129/v1`)
- **OpenClaw**: OmniRoute registered as provider in `openclaw.json` (3 virtual models: `smart`, `medium`, `light`); current Gateway policy uses OmniRoute first and keeps Codex/OpenAI as reserve
- **Бенька model selection rules** added to `workspace/AGENTS.md` — rule-based heuristics for choosing routing tier by task complexity (code → smart, chat → medium, LightRAG → light)
- **SSH TCP forwarding** enabled for `deploy` user via `/etc/ssh/sshd_config.d/50-deploy-forwarding.conf` (was blocked by hardening config)
- `artifacts/omniroute/` — redacted compose override and env example added to repo

### Changed
- `docs/01-server-state.md`: OmniRoute service entry, ports 20128/20129, actual providers and tiers
- `docs/03-operations.md`: OmniRoute operations section (start/stop/logs/tunnel/upgrade/bootstrap)
- `README.md`: architecture diagram updated with OmniRoute layer; new "Model Routing" section; tech stack and features updated

---

## [2026-04-09b] — Syncthing bidirectional sync + clawden-ai GitHub release

### Added
- **Syncthing bidirectional vault sync** — replaces one-way rsync
  - Mac (`EJ6FHJG`, homebrew service) ↔ Server (`6JODYFX`, systemd `syncthing@deploy`)
  - Folder ID: `obsidian-vault`, type `sendreceive`, connection via global relay
  - Bot can now write notes directly to vault; changes appear in Obsidian on Mac
- **GitHub repo published**: `eiler2005/clawden-ai` (public, MIT)
  - Sensitive files gitignored: `workspace/USER.md`, `MEMORY.md`, `SOUL.md`, daily notes
- **OpenClaw elevated permissions**: `profile=full`, `exec.security=full`, `elevated.enabled=true`, `fs.workspaceOnly=false`
- **`/opt/obsidian-vault` mounted** into `openclaw-gateway` container with `rw` access

### Changed
- `CLAUDE.md`: added "Commit Permission Rule" — no commit/push without explicit user approval
- `docs/03-operations.md`: Syncthing setup guide added, legacy rsync marked deprecated
- `docs/01-server-state.md`: Obsidian sync method updated to reflect Syncthing
- `README.md`: architecture diagram, tech stack, quick ops updated for Syncthing

---

## [2026-04-09] — Memory system + LightRAG

### Added
- **LightRAG knowledge graph** — deployed at `127.0.0.1:8020`, Docker compose override pattern
  - LLM: `gemini-2.0-flash`, Embedding: `gemini-embedding-001` (one API key)
  - File-based storage: NetworkX + NanoVectorDB + JsonKV (no external DB)
  - Cron: re-index every 30 min via `/opt/lightrag/scripts/lightrag-ingest.sh`
- **Three-layer memory architecture** (Live > Raw > Derived)
  - `workspace/INDEX.md` — master memory catalog
  - `workspace/memory/INDEX.md` — daily note index
  - `workspace/raw/` — verbatim decision threads (redacted, git-tracked)
  - `workspace/memory/archive/` — compressed old daily notes
- **Obsidian vault sync** — one-way rsync from Mac iCloud vault to `/opt/obsidian-vault/`
  - launchd agent on Mac (`com.openclaw.obsidian-sync`), every 15 min
  - `TRIGGER_REINDEX=true` calls LightRAG ingest after sync
- **`lightrag_query` tool** in `workspace/TOOLS.md`
  - endpoint: `POST http://lightrag-lightrag-1:9621/query {"query": "...", "mode": "hybrid"}`
  - replaces bulk-reading archives: 1 query → ~2KB answer
- **`workspace/BOOT.md`** — 8-step session startup checklist
- **`workspace/AGENTS.md`** — memory protocol, promotion criteria for raw/, boot algorithm
- Scripts: `setup-lightrag.sh`, `sync-obsidian.sh`, `create-lightrag-env.sh`

### Fixed
- `exec denied: host=gateway security=deny` — browser plugin now enabled for agent, SSRF private network allowed
- LightRAG unreachable from bot — connected `lightrag_default` → `openclaw_default` Docker network
- Wrong URL `http://lightrag:8020` → `http://lightrag-lightrag-1:9621` (correct Docker DNS)
- Ingestion: switched from `POST /documents/scan` (doesn't recurse) to `POST /documents/upload` file-by-file
- Volume mount path: `/app/inputs/` → `/app/data/inputs/` (LightRAG actual `INPUT_DIR`)
- `memory/2026-04-08.md` — removed duplicate stale bootstrap entries
- `memory/INDEX.md` — updated from `_(none yet)_` to reflect actual state

### Changed
- `openclaw.json`: removed `browser` from agent deny list; `dangerouslyAllowPrivateNetwork: true`
- `workspace/TOOLS.md`: updated LightRAG endpoint URL

---

## [2026-04-08] — Bot personalisation + upgrade

### Added
- Bot identity: **Бенька** 🐾 (цвергшнауцер, anti-sycophancy, direct + light playful tone)
- `workspace/IDENTITY.md`, `workspace/SOUL.md`, `workspace/USER.md`, `workspace/MEMORY.md`
- `workspace/HEARTBEAT.md` — weekly lightweight maintenance tasks
- Telegram group support: bot responds to mentions in group `<telegram-group-id>` without `/start`
- `openai-whisper` + `ffmpeg` baked into derived container image for voice transcription
- `OPENCLAW_NO_RESPAWN=1` + `NODE_COMPILE_CACHE` for faster startup on CX23

### Fixed
- Upgraded from `2026.4.5` (high-CPU spin-loop, port never bound) → `2026.4.8` (stable)
- `iproute2` added to derived image — required for `bind=lan` network mode
- `BOOTSTRAP.md` removed after initial setup completed

### Changed
- Container image: `openclaw-with-iproute2:20260408` (derived from upstream)
- Disk cleanup: removed 4 old `openclaw-with-iproute2` images + build cache (freed ~27 GB, 67% disk free)

---

## [2026-04-04] — Initial deployment

### Added
- Hetzner CX23 provisioned (Ubuntu 24.04)
- OpenClaw deployed under `/opt/openclaw` (Docker Compose)
- Caddy reverse proxy with mTLS — client certificate auth
- Telegram bot connected (`dmPolicy: allowlist`, token auth on WebSocket layer)
- Pre-existing `deploy-bridge-1` service left untouched
- `docs/` ops package: server state, installation, operations, architecture, security, git policy
- `LOCAL_ACCESS.md` + `secrets/` for private access materials (gitignored)
- UFW: only `22/tcp`, `80/tcp`, `443/tcp` open
