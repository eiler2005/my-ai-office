# Telegram Historical Ingest

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This page documents the repo-approved way to import historical Telegram posts into LLM-Wiki and how the current Denis batch was laid down.

Recommended background reading:
- memory model -> `docs/archive/openclaw/19-llm-wiki-memory-explained.md`
- behavior contract -> `docs/archive/openclaw/17-knowledge-management.md`
- storage model -> `docs/archive/openclaw/16-llm-wiki-storage-model.md`

---

## Non-Negotiable Rules

Historical Telegram import must follow the same invariants as every other explicit save:

1. `wiki/research/**` is the first visible proof of save.
2. `LightRAG` is a derived index, not the source of truth.
3. `raw/articles/**` and `raw/documents/**` are preserved input, not proof of memory.
4. No `raw -> LightRAG direct ingest`.
5. Bulk historical import should default to `capture_mode=ideas`, not mass canonical promotion.

Short version:

```text
Telegram history -> wiki-import -> wiki/research/** -> optional canonical enrichment -> LightRAG
```

---

## How To Load Historical Posts

Use [scripts/backfill-denis-sources-to-wiki.sh](../../../scripts/backfill-denis-sources-to-wiki.sh).

### 1. Dry-run first

This builds the candidate set, applies dedupe, and shows what would be imported after `resume` skips.

```bash
OPENCLAW_HOST='deploy@<server-host>' \
EXCLUDE_SOURCE_TITLES='Denis_Faang' \
BATCH_SIZE=3 \
MESSAGE_LIMIT=0 \
RESUME_IMPORTED=1 \
IMPORT_RETRY_COUNT=5 \
IMPORT_RETRY_DELAY=3 \
bash scripts/backfill-denis-sources-to-wiki.sh --dry-run
```

What this does:
- scans configured Telegram sources through server-side Telethon
- dedupes by normalized URL and normalized text hash
- skips already materialized `wiki/research/**` pages
- skips already logged titles from `wiki/LOG.md` and `IMPORT-QUEUE.md`

### 2. Apply the import

For large historical batches on the current 4 GB host, prefer small batches.

```bash
OPENCLAW_HOST='deploy@<server-host>' \
EXCLUDE_SOURCE_TITLES='Denis_Faang' \
BATCH_SIZE=3 \
MESSAGE_LIMIT=0 \
RESUME_IMPORTED=1 \
IMPORT_RETRY_COUNT=5 \
IMPORT_RETRY_DELAY=3 \
bash scripts/backfill-denis-sources-to-wiki.sh --apply
```

Recommended knobs:
- `BATCH_SIZE=3..5` for fragile hosts
- `MESSAGE_LIMIT=0` for full history
- `MESSAGE_LIMIT=50` or `100` for incremental refreshes
- `RESUME_IMPORTED=1` always on for repeat runs
- `EXCLUDE_SOURCE_TITLES='Name A,Name B'` when some sources must be skipped

### 3. Verify completion

The strongest check is another `dry-run`.

If import is complete for the chosen scope, the dry-run should show:

```json
{
  "candidates": 0
}
```

This is stronger than counting files because multiple candidates can legitimately collapse into the same research slug.

---

## How Incremental Updates Should Work

For periodic top-ups, use the same script with a small `MESSAGE_LIMIT`.

Example:

```bash
OPENCLAW_HOST='deploy@<server-host>' \
EXCLUDE_SOURCE_TITLES='Denis_Faang' \
BATCH_SIZE=3 \
MESSAGE_LIMIT=100 \
RESUME_IMPORTED=1 \
IMPORT_RETRY_COUNT=5 \
IMPORT_RETRY_DELAY=3 \
bash scripts/backfill-denis-sources-to-wiki.sh --apply
```

Why this is low-friction:
- only the latest window per source is scanned
- already materialized items are skipped
- same source can be re-run safely
- broken URL imports fall back to wiki-first provenance pages instead of stalling the whole batch

Recommended workflow:

1. Run `--dry-run`.
2. Check `candidates`.
3. Run `--apply`.
4. Run `--dry-run` again.
5. If `candidates: 0`, the incremental update is done.

---

## Current Denis Batch

This section records how the Denis historical Telegram import was laid down.

### Scope

Included:
- `Denis_AI`
- `Denis_ToolsForLife`
- `Denis_interesting`
- `Saved Messages`

Excluded:
- `Denis_Faang`

### Final completion check

Authoritative completion signal for this scope:

```json
{
  "candidates": 0,
  "resume_skipped": 1203
}
```

Meaning:
- the selected scope contained `1203` deduped import candidates
- after final resume-aware verification, no candidates remained unmaterialized

### Final layout in wiki

Materialized research pages by prefix:
- `denis-ai-*`: `356`
- `denis-toolsforlife-*`: `254`
- `denis-interesting-*`: `220`
- `saved-messages-*`: `371`

Total materialized pages in the chosen scope: `1201`

Why this is not `1203`:
- `1203` is the candidate count after dedupe
- `1201` is the final research page count
- two candidates collapsed into already existing research slugs, which is acceptable and expected

### How we handled the stubborn tail

The final unresolved tail was not “normal text posts”.
It was a set of `23` URL candidates that repeatedly failed direct URL import.

To finish the batch safely:
- we kept `wiki-first`
- we kept `capture_mode=ideas`
- we added URL fallback materialization

Fallback behavior:
- if `wiki-import(url)` failed
- the script retried as `wiki-import(text)`
- the fallback page preserved:
  - original URL
  - Telegram provenance
  - post date
  - fallback reason

This produced valid `wiki/research/**` artifacts instead of dropping the posts or sending them directly into LightRAG.

Result for the stubborn tail:
- `23` processed
- `23` `partial_success`
- `0` failures

`partial_success` here means:
- wiki artifact exists
- `rag_status` may still be `delayed`
- source-of-truth requirement is satisfied

---

## Audit Ledger

For future imports, the script writes an audit ledger here:

```text
/opt/obsidian-vault/.ingest-ledgers/telegram-post-imports.jsonl
```

This ledger is not the source of truth.
It is an operational audit trail for repeat imports.

Each successful ledger entry stores:
- `source_title`
- `source_kind`
- `source_chat_id`
- `message_id`
- `post_date_utc`
- `source_type`
- `title`
- `research_path`
- `wiki_page_paths`
- `canonical_pages_updated`
- `rag_status`
- `status`
- `capture_mode`
- `auto_promote`

Important:
- the ledger was added after this historical migration had already started
- because of that, it is complete for future runs, but only partial for the early phase of this batch

### Retro rebuild

To reconstruct missing early ledger entries from already materialized `wiki/research/**` pages:

```bash
OPENCLAW_HOST='deploy@<server-host>' \
bash scripts/rebuild-telegram-import-ledger.sh --dry-run

OPENCLAW_HOST='deploy@<server-host>' \
bash scripts/rebuild-telegram-import-ledger.sh --apply
```

What it does:
- scans `wiki/research/*.md`
- looks for `## Telegram Provenance`
- rebuilds ledger rows from saved provenance fields
- merges only missing ledger keys into the canonical ledger

Limitations of rebuild:
- it can reliably recover `source_title`, `source_chat_id`, `message_id`, `post_date_utc`, `research_path`
- it cannot fully reconstruct original runtime-only details for old rows, so rebuilt entries use:
  - `status: rebuilt`
  - `rag_status: unknown`
  - `canonical_pages_updated: []`

---

## Practical Finish Criteria

A Telegram backfill can be considered done when all of these are true:

1. `--dry-run` returns `candidates: 0` for the chosen scope.
2. Expected `wiki/research/**` pages exist.
3. `wiki/LOG.md` contains the final materialization events.
4. No unresolved direct-ingest dependence on LightRAG remains.

If these are true, the batch is done even if some `rag_status` values are still `delayed`.

The wiki artifact is the proof of completion.
