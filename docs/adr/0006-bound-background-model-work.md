# ADR-0006: Run background model work in a fresh bounded subprocess

- **Status:** Accepted
- **Date:** 2026-08-22
- **Context:** [`model_child.py`](../../src/benka_integrations/model_child.py) ·
  [`models.py`](../../src/benka_integrations/models.py) ·
  [Engineering case study §3](../engineering-case-study.md)

## Context

Background workflows need a model, but they need very little from it: summarise these twelve
threads, classify this email as actionable or informational, title this cluster. Small, bounded,
structured tasks.

Reusing the interactive assistant for that work is the path of least resistance and is wrong in
three ways.

It leaks context. The assistant carries the owner's personal memory and profile; a mail digest
worker has no business reading them, and anything it emits could carry them outward.

It leaks capability. The interactive agent has tools. A summarisation task that can reach a
filesystem or a shell has a far larger blast radius than the task warrants.

And it has no natural stopping point. A conversational agent is built to keep going — retry,
elaborate, try another approach. A cron job that keeps going is a cron job burning tokens and
overrunning its slot.

There was also a concrete trigger: the whole background path previously ran through
`docker exec ... openclaw agent`, which coupled every scheduled job to the interactive runtime's
process, environment, and lifecycle.

## Decision

Every background model call runs as a **separate process with an empty temporary agent home**:

- **No tools.** Not a restricted set — none.
- **No inherited memory or context files.** No personal memory, no profile, no session history.
- **No session persistence.** Nothing survives the call.
- **Explicit limits** on turns, tokens, and wall-clock time.
- **Strict JSON output**, validated before use.
- **A per-workload provider chain**, and a deterministic non-model fallback where the task allows
  one.

Failure is a first-class outcome. When every provider fails or the output does not validate, the
worker uses its deterministic path — rule-based titles on the signals route, for example — rather
than failing the run.

## Alternatives considered

**Reuse the interactive agent session.** Free to build. Rejected for the three reasons above; the
memory leak alone disqualifies it.

**One long-lived worker agent, reset between jobs.** Cheaper per call, no process startup. Rejected
because "reset" is a claim that has to hold on every path, including the error paths. A fresh
process makes isolation structural rather than a property of correct cleanup code.

**Call the provider HTTP API directly, no agent at all.** The most bounded option, and genuinely
tempting. Rejected because the fallback chain, auth handling, and streaming would then be
reimplemented per workload; the runtime already does this correctly.

**No limits, just monitoring.** Rejected: an overrun is discovered after the tokens are spent and
after the slot is missed.

## Consequences

A compromised or confused background call has almost nothing to reach: no tools, no memory, no
persistence, and a hard time limit.

Cost and latency are bounded per job rather than per incident.

Behaviour is **testable without a provider**. The native model tests use the pinned agent with a
local HTTP/SSE fixture and verify the things that matter — absence of tools, absence of inherited
memory, `401` → fallback, termination on timeout. They deliberately do not claim to prove real
provider accounts are reachable.

A failed model does not mean a failed workflow, because the deterministic path still produces
something useful.

**The costs are real.** Process startup per job, which is acceptable at this cadence. Prompts must
be self-contained, since there is no conversation to lean on. And every workload needs its own
validator and its own fallback — the work this decision moves onto the author of each worker.
