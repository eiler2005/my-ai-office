# ADR-0008: Route model work by tier with explicit provider failover

- **Status:** Accepted
- **Date:** 2026-06-20
- **Context:** [README — model routing](../../README.md#model-routing) ·
  [Operations — models and integrations](../hermes/operations.md#models-and-integrations) ·
  [Archived provider map](../archive/openclaw/24-llm-provider-map.md)

## Context

The office's model work is not one workload. Holding a conversation, deciding whether an email is
actionable, and summarising twelve Telegram threads have different requirements for quality,
latency, and context length — and their volumes differ by orders of magnitude. The classification
path runs every five minutes; the conversation path runs when the owner types.

Sending all of it to the best available model is straightforward and expensive, and most of the
spend buys nothing: a frontier model does not classify a newsletter better than a small one.

Provider availability was the second problem. Every provider used here has failed at some point —
rate limits, auth expiry, a bad deploy, a region outage. A personal office that stops working when
one API returns 429 is not an office.

## Decision

Route by **tier**, and give each tier an explicit ordered provider chain rather than one model.

The current interactive ladder:

| Tier | Model | Used for |
|---|---|---|
| Auxiliary | `gpt-5.6-luna`, minimal/low reasoning | Titles, compression, background review |
| Dialogue | `gpt-5.6-terra`, medium reasoning | Benka's ordinary conversation |
| Complex | one `delegate_task` to `gpt-5.6-sol`, high reasoning, then Terra reviews | Multi-step research, design, verification |
| Fallback | `qwen3.7-flash`, then `deepseek-v4-flash` | Only when the OpenAI route is unavailable |

Escalation to Sol is deliberate, not automatic: simple questions, status checks, and short edits
never create a subagent. The delegated agent gets no terminal, browser, filesystem, personal memory,
or further delegation.

Background workflows do **not** share this ladder. Each has its own bounded chain
([ADR-0006](0006-bound-background-model-work.md)), because a digest summariser and a conversation
are different jobs with different failure modes.

Fallback is fault tolerance and nothing more. Qwen's presence in the chain is not a statement that
Qwen is a chosen model for the work.

## Alternatives considered

**One model for everything.** Simplest, and the least code. Rejected on cost and on latency: paying
frontier prices for five-minute classification ticks, and waiting for a reasoning model to title a
cluster.

**Per-call model choice by the agent.** Flexible, and superficially attractive. Rejected because the
decision then becomes non-deterministic and untraceable — cost varies by mood, and there is nothing
to review when spend changes.

**A single routing proxy for every call.** This is what the predecessor did with OmniRoute as the
universal route. Rejected as universal policy because it made one component a single point of
failure for both conversation and background work, and it hid which provider actually served a
given call. OmniRoute is retained for explicitly assigned workloads rather than as the default path.

**No fallback; fail loudly.** Correct for a system with an operator on call. Rejected here: a
personal office should degrade rather than stop, and the deterministic paths mean degraded output is
still useful.

## Consequences

Cost tracks task complexity rather than volume, and the expensive tier is reached only by an
explicit escalation.

A provider outage degrades the office instead of stopping it, and the degradation is visible in the
chain rather than silent.

**Configuration is the cost.** Every workload needs its provider chain defined, credentials
supplied, and the fallback path actually tested — which is why the acceptance criteria require
verifying each primary, each reserve, timeouts, auth errors, malformed responses, and the
all-providers-fail case.

**Fallbacks must be verified, not assumed.** Automatic image, audio, and video understanding is
disabled specifically so a text-only reserve cannot falsely attempt media analysis — a failure mode
found by testing rather than by reasoning.

Provider-specific constraints leak into the design and have to be documented: LightRAG's extraction
route and its embedding provider are pinned separately from the conversational chain, because an
embedding model is not interchangeable with a chat model
([ADR-0005](0005-wiki-first-capture-rag-as-retrieval.md)).
