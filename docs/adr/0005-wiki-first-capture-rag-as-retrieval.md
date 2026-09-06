# ADR-0005: Capture into the wiki first; treat retrieval as a derived index

- **Status:** Accepted
- **Date:** 2026-07-18
- **Context:** [Knowledge](../knowledge.md) ·
  [Engineering case study §4](../engineering-case-study.md) ·
  [Archived memory architecture](../archive/openclaw/10-memory-architecture.md)

## Context

The default design for agent memory is to index everything and trust retrieval: dump mail, chat
history, and documents into a vector store and let similarity search sort it out.

Two problems showed up quickly. First, an index is not a store you can read — when the owner asked
"did you save that?", the honest answer was "something similar comes back when I search", which is
not the same thing and is not verifiable. Second, indexing everything indexes the noise too, and
retrieval quality falls as the corpus grows: a mailbox is mostly receipts and notifications.

There was also an ownership question. Notes the owner writes about his own business should remain
his in a form he can open, edit, and keep — not rows in a database whose schema belongs to a
retrieval library.

## Decision

**The Markdown wiki is the store. Retrieval is an index built from it.**

An explicit save creates a source-backed Markdown artifact under `wiki/**` **first**, with its
provenance metadata (`source_type`, `source`, `capture_mode`, `promote_fingerprint`). Only then is
the touched page enqueued for indexing. The wiki page — not a successful upload response — is the
proof of storage.

Indexing is scoped to an explicit allowlist of roots, not the filesystem. Raw material such as
`raw/articles/` and `raw/documents/` is stored but stays **out** of retrieval until curated import
promotes it into a visible wiki page.

Whole mailboxes and ordinary conversation are not indexed. Capture is an explicit act, and
`обсуди:` ("discuss") marks a message as conversation so it is not saved.

The wiki is Obsidian-compatible plain Markdown, synced to the owner's machine.

## Alternatives considered

**Index everything; retrieval is the memory.** The conventional RAG design and the least work.
Rejected on both counts above: unverifiable storage, and quality degrading as volume grows.

**A database as the store, with Markdown exported for reading.** Cleaner queries and real schema
enforcement. Rejected because the exported copy is then a second-class artifact — editing it does
not change anything — which defeats the point of the owner keeping his notes.

**Wiki only, no retrieval index.** Simple and fully verifiable. Rejected because grep does not
answer "what did I conclude about this last spring"; graph-assisted retrieval genuinely finds things
a filename search does not.

**Automatic capture of anything that looks important.** Rejected as unpredictable: a system that
sometimes saves and sometimes does not, on criteria the owner cannot see, is worse than one that
always requires a word.

## Consequences

"Did you save that?" has a checkable answer: a file exists, with its source recorded. If indexing
later fails, the knowledge is still there — the index can be rebuilt from the store, never the other
way round.

Retrieval stays on curated material, so it does not degrade as raw volume grows.

The knowledge base is **portable**: plain Markdown in Obsidian, readable and editable without this
system running. That is also the exit path if the office is ever retired.

**The cost is friction.** Capture requires an explicit act, so things the owner does not save are
genuinely not saved — accepted as the price of a knowledge base he can explain.

Two states must be reported separately, because conflating them is exactly the bug this prevents:
*upload accepted* is not *indexed*, and only the second makes something findable.

The embedding model identity and its 3072 dimension are pinned. Repointing the graph at an
incompatible model would silently invalidate the index, so
[operations](../hermes/operations.md#wiki-and-lightrag) forbids it.
