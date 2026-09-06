# ADR-0002: Use Telegram forum topics as the primary operating surface

- **Status:** Accepted
- **Date:** 2026-06-14
- **Context:** [README — Telegram surfaces](../../README.md#telegram-surfaces) ·
  [Archived Telegram topology](../archive/openclaw/12-telegram-channel-architecture.md)

## Context

An assistant that only answers when opened is an assistant that gets forgotten. The office is
built to push — briefings, alerts, digests — which means it needs a surface the owner already has
open, on every device, without a login step.

Telegram was already where the source material lived: the channels being digested, the chats being
watched for signals, and the owner's own daily messaging. A separate interface would have added a
place to check rather than removing one.

The obvious risk with a push system is that everything lands in one stream. Five workflows on
different cadences — a five-minute signals tick, five daily digests, eight work-mail slots — merged
into a single chat produce a feed nobody reads.

## Decision

Use a private Telegram forum supergroup, where **each workflow publishes to its own topic**, plus
the owner's direct message with the bot for conversation.

A worker's destination is configuration, never inference: each one may publish only to its
configured allowlisted route and cannot select a chat or thread from the content it processed.

Inbound is routed the other way: the Gateway maps the sender and route to a `personal`, `work`,
`family`, or `sandbox` profile *before* any tool sees the request, and an unmatched route gets no
tools at all.

## Alternatives considered

**A web dashboard as the primary surface.** Richer rendering and full control of the UI. Rejected
as primary because it is a place to go rather than a place already open, and push notifications
would have meant rebuilding what Telegram already does well. It exists as a secondary operator
surface behind Caddy ([ADR-0010](0010-single-public-listener-with-mtls.md)).

**Email digests.** Universal and needs no client. Rejected because the office's job is to *reduce*
what arrives in the mailbox; adding to it would work against the point.

**One Telegram chat with formatted message headers.** Simplest to build. Rejected on cadence: at
five-minute signals plus five digests a day, headers do not survive scrolling, and there is no way
to mute one workflow without muting all of them.

**Slack or Discord.** Better threading primitives than a Telegram forum. Rejected because the source
material is in Telegram, and a second messenger is a second place to check.

## Consequences

Each stream is independently readable, mutable, and searchable. A topic can be muted without losing
the others — the practical difference between a system that gets read and one that gets ignored.

Because a route is configuration rather than a model decision, **a compromised or confused model
cannot redirect output**: the worst case is a message in the wrong topic of a private group, not a
message to an unintended recipient.

**Telegram's operational limits are now the office's limits.** Unprocessed Bot API updates are
retained for at most 24 hours, which is why the
[migration plan](../hermes/migration-plan.md#5-rollback-and-completion) treats extended downtime as
unacceptable and budgets the cutover window in hours.

**Exactly one process may own polling.** Two pollers means duplicated or lost updates, so "confirm
the single polling owner" appears in the cutover, rollback, and acceptance procedures.

The home channel is deliberately constrained: the finalizer will bind it only to the personal DM of
a single trusted owner, and leaves it unset rather than guessing if that is ambiguous. `/sethome`
inside a forum topic would silently redirect notifications for the whole Gateway, so
[operations](../hermes/operations.md#profiles-and-telegram) calls it out explicitly.
