# LLM-Wiki Storage Model

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

This document is a **reference-only storage rules file**.

It is no longer part of the primary learning path for the memory stack.

Use it only when you need exact answers to questions like:
- page naming
- canonical slug collisions
- typed folders vs themes
- storage constraints for archive placement and topic maps

Use it when the question is:

- "How should pages be named?"
- "Where do themes live?"
- "What is canonical and what is derived?"
- "Why do we keep typed folders and `TOPICS.md` at the same time?"

Read first before this file:
- human explanation -> `docs/archive/openclaw/19-llm-wiki-memory-explained.md`
- technical memory model -> `docs/archive/openclaw/10-memory-architecture.md`
- runtime query path -> `docs/archive/openclaw/15-llm-wiki-query-flow.md`
- exact machine rules -> `artifacts/llm-wiki/SCHEMA.md`

---

## 1. Storage Layers

This section is intentionally brief because the architecture-level explanation now lives in `docs/10`.

There are three distinct layers:

- `raw/` — immutable source evidence
- `wiki/` — curated markdown knowledge base
- `LightRAG` — derived retrieval index on top of selected markdown

Important operating rule:

- passive scheduled feeds may remain outside `wiki/`
- every explicit user save must materialize a visible wiki artifact immediately

Inside `wiki/`, typed folders are still the primary storage structure:

- `entities/`
- `concepts/`
- `decisions/`
- `research/`
- `sessions/`

Themes are a secondary navigation layer added through frontmatter and `TOPICS.md`.

---

## 2. Canonical Identity

`wiki/CANONICALS.yaml` is the registry for core entities and controlled anchor pages.

Each canonical record defines:

- `slug`
- `type`
- `subtype`
- `name`
- `aliases`
- `tags`
- `themes`
- `preferred_folder`

Resolution order in importer:

1. exact slug
2. exact alias
3. normalized alias
4. existing page aliases
5. heuristic fallback

The goal is simple: if the source mentions `OpenClaw`, `OpenClaw runtime`, or `openclaw`, they
should all land on `entities/openclaw.md`.

---

## 3. Naming Rules

Global invariant:

- file basename must be unique across the entire wiki

That means this is not allowed:

- `entities/openclaw.md`
- `concepts/openclaw.md`
- `research/openclaw.md`

Instead:

- canonical entity page keeps `openclaw.md`
- colliding concept becomes `openclaw-concept.md`
- colliding research page becomes `openclaw-research.md`

Additional rules:

- no duplicate-token slugs like `openclaw-openclaw`
- do not create entity pages from source-title artifacts like `README` or `Setup and Operations`
- decision slugs should be ADR-like, not `imported-*`

---

## 4. Typed Pages vs Themes

Why keep both?

- typed folders answer "what kind of page is this?"
- themes answer "what topic area does this belong to?"

This is a better fit for Obsidian and for Karpathy-style LLM-Wiki maintenance than deep domain
folder trees.

Each non-session page gets `themes: [...]` from a controlled vocabulary:

- `runtime`
- `memory`
- `wiki`
- `retrieval`
- `signals`
- `routing`
- `sync`
- `security`
- `operations`

`TOPICS.md` is rebuilt from these themes and shows:

- anchor entities
- core concepts
- active decisions
- research / synthesis pages

So:

- typed folders remain stable and predictable
- `TOPICS.md` gives fast thematic browsing
- `OVERVIEW.md` remains the cold-start summary

---

## 5. Page Roles

Canonical entity pages:

- stable anchor nodes
- accumulate aliases, tags, themes, and source references
- should improve over time instead of multiplying

Concept pages:

- describe reusable ideas and patterns
- should not duplicate canonical entity identity

Research pages:

- source-centric or synthesis-centric
- can connect multiple entities and themes
- are the right place for import-specific or question-specific synthesis
- are the mandatory landing pages for explicit saves from `Knowledgebase`, `Ideas`, and promotions

Decision pages:

- only for explicit ADR-like signal
- not for every imported source

---

## 6. Repair Policy

`wiki_lint(repair=true)` is the one-time or maintenance repair path.

It may:

- merge duplicate canonical entities into the canonical slug
- move old names into `aliases`
- rename colliding concept/research pages
- remove low-signal auto-generated decisions
- normalize missing themes and aliases
- rebuild `INDEX.md`, `OVERVIEW.md`, and `TOPICS.md`

This is how the wiki stays readable even after early heuristic imports produced noisy pages.

---

## 7. Practical Navigation

When reading as a human:

- start at `OVERVIEW.md` for a quick snapshot
- use `TOPICS.md` to browse by topic
- use `INDEX.md` for the full registry
- open canonical entity pages for stable anchors
- open research pages for source-specific or synthesis-heavy detail

When importing:

- explicit saves create the research page first
- canonical entities update only when confidence is sufficient
- concepts are added only when they are real concepts
- themes and links keep the graph coherent
