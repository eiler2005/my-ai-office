# ADR-0007: Confirm delivery by receipt; reconcile instead of retrying

- **Status:** Accepted
- **Date:** 2026-08-25
- **Context:** [`delivery.py`](../../src/benka_integrations/delivery.py) ·
  [Reliability](../reliability.md) ·
  [Acceptance record](../hermes/acceptance.md)

## Context

Sending a Telegram message can fail in three ways, and only two of them are safe.

It can fail before anything left the process — nothing happened, retry freely. It can succeed —
done. Or the call can error *after* the message was accepted but before the confirmation came back.
In that third case the local state says "failed" and the owner's phone says otherwise.

The default behaviour of every queue and every HTTP client is to retry. Applied to the third case,
that posts the digest twice. For a system whose entire purpose is reducing noise, duplicate
briefings are a serious defect — and they erode trust faster than a missing one, because the owner
starts checking whether each message is real.

Redis makes the internal handoff durable, but it cannot observe a remote side effect. No amount of
queue reliability answers "did Telegram accept this".

## Decision

**A delivery is confirmed only by a receipt**, and a receipt requires a response carrying `success`
and a `message_id`, with no `skipped` flag. A successful exit code is explicitly not sufficient.

Outcomes map to three states:

| State | Meaning | Action |
|---|---|---|
| `confirmed` | `success` + `message_id` returned | Record the receipt, advance the cursor |
| `failed` | Provably nothing was sent | Safe to retry |
| `uncertain` | Outcome unknown | Nothing automatic — to `benka:reconcile` |

An `uncertain` outcome is **never** retried automatically. It goes to the reconciliation queue with
its original payload, and a human checks the target topic before deciding. That decision is recorded
in the private operations log.

Recovery is deliberately narrow. For a confirmed single miss, the operator may enqueue a
source-scoped job carrying `source_id` and `target_message_id`; it reads only that one item and goes
through the normal matching, dedupe, receipt, and delivery path. Such a job is refused without
`source_id`, so it cannot become a replay of an accumulated feed.

## Alternatives considered

**Retry with exponential backoff.** The standard answer. Rejected because it is exactly wrong for
the ambiguous case, which is the only case that needs a policy.

**Idempotency keys on the send.** The correct general solution — if the transport supports it. The
Telegram Bot API does not offer a client-supplied deduplication key for this path, so it was not
available.

**Read back the chat history to check before retrying.** Considered seriously, and it is what the
operator does manually. Rejected as an automatic step: it needs read access to the target, it races
with concurrent posts, and a wrong automated conclusion produces the duplicate anyway. As a human
step with a recorded decision, it works.

**Accept duplicates as harmless.** Rejected: in a briefing system, duplicates are the failure mode
that makes the owner stop trusting the feed.

## Consequences

**The system never silently duplicates a briefing**, which is the property the whole design is
protecting.

Uncertainty is a state rather than an error, so interrupted work is inspectable instead of lost.

**The cost is human work.** Reconciliation is manual and has no automatic cleanup; queue age and
depth must be monitored. That is a deliberate trade of operator time for delivery integrity.

**This has been exercised in production, twice.** On 2026-09-06 the 17:00 MSK digest failed because
the worker could not find `hermes send` on its `PATH`. The failure occurred before a `message_id`
came back, was stored as `uncertain`, and nothing was resent. A read-only check of the target topic
confirmed no message existed for 16:55–17:10, one controlled run then produced the release, and an
independent re-check found both parts. The design held: the fix was a `PATH` bug, not a lost or
duplicated digest.

A later Signals miss used the source-scoped recovery path: one post, normal matching, confirmed
receipts, no replay, and the original `uncertain` receipts retained for manual review rather than
resent.
