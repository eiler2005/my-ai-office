# ADR-0004: Keep orchestration separate from domain logic

- **Status:** Accepted
- **Date:** 2026-08-20
- **Context:** [`src/benka_integrations/`](../../src/benka_integrations) ·
  [Engineering case study §1](../engineering-case-study.md) ·
  [Architecture — layered system view](../architecture.md#layered-system-view)

## Context

The tempting way to build an agent system is to put the rules in the prompt. Which channels matter,
how to weight a story, when a work email is actionable rather than informational, how to detect a
duplicate — all of it expressed as instructions to the model.

It reads well and it is fast to change. It is also unreviewable, untestable, and non-deterministic:
the same input produces different scoring on different days, and there is nothing to diff when the
digest suddenly looks wrong.

The forcing question was concrete. The office had accumulated real domain logic — Telegram channel
scoring with category balancing, forwarded-sender resolution inside work email, Reddit's JSON/RSS
hybrid discovery path, per-source ranking caps for the research feed. A runtime change was already
being considered. If that logic lived inside the agent runtime, changing runtimes would mean
rewriting and re-validating all of it.

## Decision

The agent runtime owns **orchestration only**: interfaces, session handling, profile routing, tool
registration, model selection, and cron.

Everything source-specific lives in an ordinary Python package,
[`benka_integrations`](../../src/benka_integrations), and in the per-source modules under
[`artifacts/`](../../artifacts). Parsers, scorers, deduplication, renderers, cursors, and validation
are plain code with plain unit tests.

The model is invoked where **language judgment** genuinely helps — summarising, classifying,
phrasing — and nowhere else. Deterministic rules run first and, on the signals path, decide whether
a model is called at all.

## Alternatives considered

**Rules in the system prompt, model does the work.** Fast to iterate and needs no code. Rejected: it
cannot be unit-tested, it cannot be diffed in review, and it re-derives the same decision on every
invocation at token cost. Scoring rules that drift silently are worse than scoring rules that are
wrong consistently.

**A runtime-native plugin framework holding the domain logic.** Better than prompts, and idiomatic.
Rejected because it binds business rules to a runtime's plugin API — the exact coupling that would
have made the migration a rewrite.

**A separate microservice per source with an HTTP contract.** Stronger isolation. Rejected as
over-built for one host: the previous architecture did work this way, with HTTP bridges per source,
and replacing them with in-process workers removed a whole class of "is the bridge up" failure
without losing any isolation that mattered.

## Consequences

**The decision was tested by the event it was made for.** The runtime was replaced — OpenClaw to
Hermes ([ADR-0009](0009-migrate-runtime-to-hermes.md)) — and the business algorithms moved across
essentially intact. The [drift log](../hermes/drift-log.md) tracks behavioural differences, and it
is short.

Domain logic is reviewable and testable as ordinary code: 21 test modules, 209 checks in the
verification run.

Model spend follows from structure rather than discipline: the signals path runs deterministic
matching first and calls a model only when a rule actually fires.

**The cost is indirection.** Understanding one digest means reading the schedule, the worker, and the
source module rather than one prompt — which is why [workflows](../workflows.md) traces the paths
end to end.

**The boundary needs maintaining.** "Just add it to the prompt" is always the cheaper next step, and
nothing in the code enforces the line. It holds by review.
