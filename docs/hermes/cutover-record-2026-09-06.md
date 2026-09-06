# Production cutover record — 2026-09-06

**Status: `ACTIVE_ON_HERMES`.** This record supersedes the earlier candidate-only status in the
planning documents. The owner explicitly started the cutover; it was not triggered by elapsed time.

## Result

- A fresh cold snapshot was created and SHA-256-verified directly on VPS Hermes. No production archive
  was placed on Mac.
- Hermes imported the reviewed OpenClaw user data with the native importer, then applied the Benka
  profiles, private manifests, model routes, delivery receipts, workers and schedules.
- The production stack now owns one Telegram polling connection, Redis, OmniRoute, LightRAG, wiki,
  dashboard and six workers (two mailboxes, Telegram Digest, Signals, Last30Days and maintenance).
- Caddy remains on the established Reddit Compass panel host at its separate port. It requires mTLS and
  Hermes dashboard authentication; adjacent DNS, Caddy and application containers were not modified.
- Twenty-three native Hermes cron jobs are enabled. They enqueue into Redis; cron itself does not deliver
  messages.
- A new ChatGPT Codex OAuth session is held only in the private Hermes auth store. The model ladder is
  `gpt-5.6-luna` for auxiliary work, `gpt-5.6-terra` for ordinary dialogue and one bounded
  `gpt-5.6-sol` subagent for complex multi-step work; Qwen and DeepSeek are fallback-only.
- All Docker containers on the former OpenClaw VPS were stopped after Hermes validation. Its data, images,
  stopped containers and disabled legacy cron files remain in place for rollback.

## Verification performed on VPS Hermes

- Production Compose validates and every Hermes production container is running.
- Gateway health is `healthy` and its one Telegram polling adapter connected successfully.
- Redis `PING`, wiki health endpoint, LightRAG health endpoint and a real Hermes model response succeeded.
- Dashboard is reachable through the operator client certificate; a request without that certificate is
  rejected.
- A native cron smoke job executed inside the running Gateway and completed after enqueueing a safe wiki
  maintenance task. Worker processes remained stable.
- Direct OAuth-backed requests to all three GPT-5.6 model tiers and a bounded Sol delegation succeeded.

## Observation and rollback

The 48-hour observation period starts from this cutover. Confirm actual Telegram inbound/reply routing,
both mailbox poll/digest cycles, Telegram Digest, Signals/Last30Days, LightRAG indexing and the daily
scheduled jobs as they occur. Record only sanitized outcomes in [acceptance.md](acceptance.md).

Do not restart OpenClaw automatically. For a rollback, first stop Hermes polling/workers and preserve its
current state; then follow [cutover-rollback.md](cutover-rollback.md) to reconcile newer artifacts,
deliveries, cursors and pending Redis work before restoring the stopped source runtime.
