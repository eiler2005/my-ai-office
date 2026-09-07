# Glossary

[Documentation map](../README.md)

Terms that mean something specific in this project. Where a word has a general meaning too, the
entry says what is different here.

## The system

**Benka** (Бенька) — the assistant. A miniature schnauzer in persona, concise and deliberately
unsentimental about weak ideas. Runs on Hermes Agent; the office around it is the work in this
repository.

**My AI Office** — the whole system: the agent, the workers, the queue, the knowledge base, and the
operating design. The project and portfolio name.

**Hermes Agent** — the upstream agent runtime, vendored as a pinned submodule. Supplies interfaces,
sessions, profiles, native tools, model selection, and cron. Does **not** contain the office's
business logic ([ADR-0004](../adr/0004-separate-orchestration-from-domain-logic.md)).

**`benka-hermes`** — the production Docker Compose project name. Its 13 services are listed in
[services](services.md).

**`benka_integrations`** — the Python package holding the office's own logic: tools, worker
pipelines, queue and delivery handling, bounded model execution, and migration helpers.

## Execution

**Slot** — one scheduled occurrence of a workflow, e.g. the 17:00 Telegram Digest. A slot yields one
**stable run id**, derived from the slot rather than the clock, so a repeat of the same slot is
refused rather than duplicated.

**Worker** — a dedicated process handling one source family. Has its own manifest, config, cursor,
Redis consumer group, and delivery allowlist.

**Cursor** — a worker's position in its source, advanced only after work is persisted.

**Integration bus** — not a container. It is the `redis` service **plus** the scheduling, queue,
delivery, and worker contracts in `benka_integrations`. There is no service named
`integration-bus` in production.

**Pending list (PEL)** — Redis's record of entries claimed by a consumer but not acknowledged. Where
an interrupted job becomes visible instead of vanishing.

**Receipt** — proof of a delivery. Requires a Hermes response carrying `success` and a `message_id`
with no `skipped` flag. A successful exit code is **not** a receipt.

**`uncertain`** — a delivery whose outcome cannot be determined. A first-class state, never retried
automatically.

**`benka:reconcile`** — the queue where uncertain and recovered-pending work waits for an operator
decision. Has no automatic cleanup.

**Source-scoped job** — a narrow recovery job carrying `source_id` and `target_message_id`. Reads
exactly one item through the normal matching, dedupe, receipt, and delivery path. Refused without
`source_id`, so it cannot become a backlog replay.

**Bounded model call** — a background model invocation in a fresh agent home with no tools, no
inherited memory, no session persistence, and explicit turn, token, and time limits
([ADR-0006](../adr/0006-bound-background-model-work.md)).

**Deterministic fallback** — the non-model output path a worker uses when every provider fails, e.g.
rule-based titles. Degraded, but still delivered.

## Surfaces and workflows

**Domain / profile** — one of `personal`, `work`, `family`, `sandbox`. Each has its own manifest,
paths, memory, tool permissions, credentials, and delivery targets. Resolved before tools are
attached.

**Home channel** — the Telegram destination for cron results and system notifications. Bound only to
the personal DM of a single trusted owner; left unset rather than guessed if that is ambiguous.

**Route / delivery allowlist** — the configured chat and thread a worker may publish to. A worker
cannot choose a destination from content it read.

**Signals** — deterministic rule matching over configured mail and Telegram sources. A model runs
only when a rule fires.

**Last30Days** — the daily research workflow across Reddit, Hacker News, GitHub, X, Bluesky,
YouTube, Polymarket, and web results.

**Personal Feed** — the Last30Days preset for the owner's own themes. Successor to the earlier
`world-radar`; `world-radar-v1` still resolves as an alias to `personal-feed-v1`.

**Platform Pulse** — the Last30Days preset that reports platform by platform: what Reddit, Hacker
News, X, and Bluesky are each discussing.

**Telegram Digest** — the scheduled briefing built from the approved channel catalog, with scoring,
deduplication, and category balancing.

**Triage (actionable / informational)** — the split applied to work mail, preserved through to the
briefing so the owner sees what needs a reply separately from what is context.

**`обсуди:`** — Russian for "discuss". Prefixing a message with it keeps the message in conversation
and prevents automatic capture.

## Knowledge

**Wiki** — the curated Markdown knowledge base. The **store**, and the proof that something was
saved.

**LightRAG** — the graph-assisted retrieval index over allowlisted roots. **Derived** from the wiki
and rebuildable from it.

**Capture** — writing a source-backed wiki artifact. Always precedes indexing.

**Promotion** — deepening an existing idea chain rather than creating a duplicate, matched by
`promote_fingerprint`.

**Archive** — the private SQLite FTS store of imported conversations and diaries. Searched only on an
explicit request.

**Raw evidence** — original sources kept for provenance under `raw/`. Stored, not indexed, until a
curated import promotes them.

## Migration and operations

**OpenClaw** — the predecessor agent runtime, used from the first deployment until the 2026-09-06
cutover. Now frozen at [`eiler2005/clawden-ai`](https://github.com/eiler2005/clawden-ai) and
documented in [`docs/archive/openclaw/`](../archive/openclaw/). Nothing in the current system runs
on it ([ADR-0009](../adr/0009-migrate-runtime-to-hermes.md)).

**Cutover** — the switch of production from the predecessor to Hermes, performed 2026-09-06 after a
separate instruction from the owner.

**Cold snapshot** — a consistent copy taken with writers stopped. Copying a running database with an
ordinary `cp` is not one.

**Drift log** — the record of behavioural changes in the source system during the waiting period.
A snapshot moves data; the drift log moves everything a snapshot cannot.

**`READY_NOT_ACTIVE`** — code, migrators, configuration, and rehearsal complete, with production
connections still disabled.

**`ACTIVE_ON_HERMES`** — the current recorded status. The 48-hour observation window and full
production acceptance remain open.

**Activation receipt** — an operational interlock recording the manifest SHA, the snapshot SHA, and
that old writers stopped. **Not** cryptographic authorisation; only an operator creates one, and
only after an explicit instruction.

**OmniRoute** — a provider-routing service retained for explicitly assigned workloads. Not the
universal route for every model call.

**Neighbouring projects** — `reddit-compass`, `moex-futoi`, `cheap-intelligence`, `stealth`.
Independent Compose projects sharing the host, outside this system's networks and lifecycle
commands.

> [!NOTE]
> **Reddit** and **Reddit Compass** are unrelated. Reddit is an external Last30Days source; Reddit
> Compass is a separate application that happens to share the VPS.
