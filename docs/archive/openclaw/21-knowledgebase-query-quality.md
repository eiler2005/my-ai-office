# Knowledgebase Query Quality

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This file defines the **answer-quality contract** for `📚 Knowledgebase` search.
It does not change the storage architecture:

- `wiki/**` stays the source of truth
- `LightRAG` stays a derived retrieval layer
- search quality is improved at the `retrieval -> source review -> synthesis` step

See also:
- [docs/archive/openclaw/15-llm-wiki-query-flow.md](15-llm-wiki-query-flow.md)
- [docs/archive/openclaw/17-knowledge-management.md](17-knowledge-management.md)
- [scripts/smoke-check-knowledge.sh](../../../scripts/smoke-check-knowledge.sh)

Runtime rollout note:

- on `2026-04-21`, this contract was deployed to the live OpenClaw server by updating
  `/opt/openclaw/workspace`, `/opt/openclaw/config/telegram-surfaces.policy.json`, and the pinned
  `Knowledgebase` topic instructions
- see [docs/archive/openclaw/06-command-log.md](06-command-log.md) for the rollout record

## Target Behavior

For a short question-like query in `Knowledgebase`, the bot should:

1. run `lightrag_query(..., mode="hybrid")`
2. run `memory_search`
3. open `2-5` top `references[].file_path`
4. extract `2-4` supportable facts or short evidence snippets
5. produce a `grounded expanded` answer with source links when available

The answer should be:

- broader than a terse snippet dump, but still directly useful
- anchored in opened refs
- explicit about uncertainty boundaries
- citation-first, not vibes-first
- source-link-aware: include wiki path plus original Telegram/web source when provenance exists
- do not default to raw vault paths when a more human-friendly source link exists

## Grounded Expanded Format

Default answer shape:

```text
🔍 Запрос: «...»

Короткий вывод: {3-6 предложений}

• {supportable fact or short evidence snippet}
Источник: {file_path}

• {supportable fact or short evidence snippet}
Источник: {file_path}

Что это значит:
- {why it matters}

Что может быть полезно тебе:
- {applied suggestion grounded in refs}

Источники:
- Wiki: {file_path}
- Исходник: {canonical_url_if_available}
- Telegram: {t.me/c/... if available}
```

Allowed uncertainty form:

```text
В открытых refs нашлись X и Y, но прямого подтверждения Z нет.
```

## Degraded-Answer Guard

The bot must **not** answer with a generic fallback like:

- "I do not have enough information"
- "I cannot answer your question"
- "The provided context does not contain information"

unless both are true:

1. top references were actually opened
2. no supportable facts were found in them

If refs exist and confirm even part of the answer, the bot should answer with the supported subset.
If original source links are available in the reviewed pages, the bot should include them in the answer rather than only internal wiki refs.
Raw vault paths are acceptable only as a fallback of last resort.

## Regression Smoke Check

Run:

```bash
OPENCLAW_HOST='deploy@<server-host>' bash scripts/smoke-check-knowledge.sh
```

The script verifies:

- wiki dry-run stays at `candidates: 0`
- `LightRAG` is healthy and converged
- fixed `Knowledgebase` queries return refs
- targeted factual queries hit expected wiki-derived refs
- degraded-answer markers are surfaced explicitly
- top refs expose source-linkable provenance when available

Current fixed queries:

- `Claude code best practices`
- `life principles`
- `NOCONCEPT`

Acceptable regression result:

- `has_refs=true` for all core queries
- `targeted_factual_pass=true`
- `has_source_links=true` for targeted factual queries when provenance exists in wiki
- no unexpected rise in `pending/failed`

If thematic or broad queries still show `degraded_answer=true`, that is a quality signal for synthesis tuning, not necessarily a retrieval/storage failure.
