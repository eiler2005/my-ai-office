# Next Steps In VS Code

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This is the recommended sequence for continuing work safely.

## 1. Keep the working folder local until the docs are reviewed

Before any Git initialization or remote push:

- verify that `secrets/` stays ignored
- verify that `LOCAL_ACCESS.md` stays ignored
- verify that no raw `.env`, auth profile, certificate, or tokenized URL was copied into tracked docs

## 2. First verification pass

Use the placeholder host pattern from [`03-operations.md`](./03-operations.md).

Run:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && docker compose ps'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo systemctl status caddy --no-pager'
```

Then validate browser access through the OpenClaw UI tunnel:

```bash
./scripts/openclaw-ui-tunnel.sh
```

Open `http://127.0.0.1:18789/` while the tunnel is running.

## 3. Decide whether to keep the derived image local or publish it

Current deployment depends on a small derived image because the upstream image lacked `iproute2`.

Decision to make:

- keep building the image locally on the server
- or publish a pinned custom image to a controlled registry

If this deployment is meant to last, publishing and pinning the image is the cleaner long-term option.

## 4. Normalize health reporting

The built-in container healthcheck is misleading for this deployment.

Recommended future improvement:

- override the healthcheck in Compose with a custom probe that reflects the real readiness contract

## 5. Decide how much of the public architecture should remain

Current public path is strong enough for controlled use:

- `mTLS` at the edge
- local-only gateway publish
- no direct public OpenClaw port

Still worth deciding:

- whether to keep a public `sslip.io` style hostname
- whether to migrate to a real managed domain
- whether to rotate and reissue client certificates on a schedule

## 6. If you turn this into a real repository

Recommended first tracked content:

- `README.md`
- `docs/`
- `artifacts/`
- `.gitignore`

Recommended next tracked additions:

- `LICENSE` if distribution is planned
- `CHANGELOG.md` if this becomes a maintained operations repo
- simple helper scripts or a `Makefile` for repeatable ops

## 7. Useful next engineering tasks

- pin the exact upstream OpenClaw base image digest in the custom Dockerfile
- add a documented smoke test for the browser and WebSocket flow
- add a deterministic script to refresh the copied `control-ui` assets when the image changes
- replace placeholder host instructions with environment-variable driven scripts
- add an async ingestion queue between source readers and downstream processing so long Telegram/email
  reads do not block digest generation or fail on bridge/request timeouts
- keep the queue design boring and standard: producer writes normalized source events, workers consume
  them for enrichment/dedup/summarization, and publishers emit final digests separately
- design it as a shared ingestion layer for Telegram, work email, and future signal feeds instead of
  building one-off retry logic per source

## 8. Delegation brief for another LLM

Use this prompt as-is when delegating the async ingestion work:

```text
Нужно спроектировать и реализовать v1 общего async ingestion слоя для Benka/OpenClaw.

Контекст:
- Сейчас Telegram Digest работает в одном sync path: read -> score -> dedup -> summarize -> publish
- Из-за этого длинные reads и provider timeouts давят на bridge/cron response path
- В будущем такие же проблемы появятся для Work Email и других signal sources

Цель:
- Вынести ingest из sync request path
- Сделать общий pipeline для Telegram, Work Email и будущих signal feeds
- Оставить решение простым и стандартным

Выбранный стек:
- Redis Streams
- Python workers

Архитектура:
- producers enqueue normalized events
- workers consume, enrich, dedup, classify, summarize
- publishers emit digest/messages separately
- cron/bridge в будущем должен enqueue-ить задачу и быстро отвечать, а не ждать весь digest

Минимальная модель события:
- source_type
- source_id
- event_id
- occurred_at
- payload_ref или normalized payload
- dedup_key
- ingestion_state

Нужно продумать:
- idempotency
- checkpointing по источникам
- retry / dead-letter handling
- separation between ingest, summarize, publish
- как без боли подключить Telegram Digest и Work Email первыми

Ограничения:
- не строить тяжёлую платформу
- не делать bespoke retry logic для каждого источника
- prefer boring operations and explicit boundaries

На выходе дай:
- implementation plan
- stream/key naming
- worker responsibilities
- failure/retry model
- rollout steps for Telegram first, then Work Email
```
