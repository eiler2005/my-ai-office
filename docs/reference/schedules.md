# Schedules reference

[Documentation map](../README.md) · [Workflows](../workflows.md) ·
[Reliability](../reliability.md)

Every recurring job in one table. All times are **`Europe/Moscow`**.

> [!IMPORTANT]
> The confirmed server-side registry is the operational source of truth for which jobs are enabled
> and at what minute. This page describes the **shape** of the schedule, not the switch. Never
> enable something here that is disabled there.

## The rhythm

| Workflow | Cadence | What starts | Lands in |
| --- | --- | --- | --- |
| Benka conversation | Every trusted owner request | Interactive session with the routed profile, permitted context, native tools, and configured model tier | The same conversation |
| Mailbox polling | Every 5 min, both inboxes | Independent polling jobs with separate streams, cursors, and consumer groups | Queue only |
| Signals | Every 5 min | Rule evaluation over enabled mail and Telegram sources | `signals` |
| Signals retention | Hourly | Cleanup of old Signals events | Internal |
| Last30Days | 07:00 | The enabled research preset; the second stays available on request | `last30daysTrend` |
| Personal mail briefing | 08:00, 13:00, 16:00, 20:00 | Morning / interval / editorial summaries | `inbox-email` |
| Telegram Digest | 08:00, 11:00, 14:00, 17:00, 21:00 | A digest run with its slot and `digest_type` preserved | `telegram-digest` |
| Work mail briefing | 8 slots, 08:30–19:00 | Work-only summaries with forwarded-sender resolution and triage | `work-email` |
| LightRAG refresh | Every 30 min | Indexing of the explicitly allowed knowledge roots | Retrieval index |
| Wiki daily | 05:45 | `dry_run`, `report` — reports without changing anything | Wiki reports |
| Wiki weekly | Sun 06:15 | `apply` — report, archive, refresh topics, refresh overview | Wiki |

Intermediate minutes for the work-mail slots come from the actual private config, not from this
page.

## A day, in order

```text
05:45  wiki daily report (dry run)
07:00  Last30Days — Personal Feed
08:00  personal mail briefing · Telegram Digest
08:30  work mail briefing begins
11:00  Telegram Digest
13:00  personal mail briefing
14:00  Telegram Digest
16:00  personal mail briefing
17:00  Telegram Digest
19:00  work mail briefing ends
20:00  personal mail briefing
21:00  Telegram Digest

every  5 min  — mailbox polling · Signals
every 30 min  — LightRAG refresh
every  60 min — Signals retention
Sun 06:15     — wiki weekly maintenance (apply)
```

## How a schedule becomes a job

```text
reviewed-schedules.json   (private, server_verified: true)
        │
        ▼  benka jobs-prepare
job-registry.json
        │
        ▼  benka cron-prepare
native Hermes cron jobs — created PAUSED
        no_agent=true · deliver=local · failure_deliver=local
```

Jobs are created **paused**. Re-running preparation updates them by stable name, and removed jobs
stay paused rather than disappearing.

`deliver=local` is the supported Hermes way of *not* sending a job's output to a channel — only the
shared sender publishes results, so delivery goes through the receipt path
([reliability](../reliability.md)) rather than around it.

The cron script reads `cron_connection_file` for `redis_url`, because Hermes clears the environment
of script-only jobs.

> [!WARNING]
> Do not run the `cron-prepare` CLI with a `HERMES_HOME` different from the home passed to it.

### The reviewed source JSON

`jobs-prepare` consumes a private reviewed file containing:

- `timezone: Europe/Moscow`, and `server_verified: true` after live reconciliation
- `email.personal` / `email.work` — `enabled`, `stream`, `group`, `inbox_ref`, `poll_schedule`, and
  `slots` with `time` and `digest_type`
- `telegram` — `enabled`, `domain`, `slots`
- `signals` — list of `enabled`, `domain`, `ruleset_id`, `schedule`
- `last30days` — list of `enabled`, `domain`, `preset_id`, `schedule`
- `maintenance` — list of `enabled`, `domain`, `action` (`wiki-daily` / `wiki-weekly` / `rag-scan`),
  `schedule`
- `signals_cleanup` — `enabled`, `schedule`

> [!IMPORTANT]
> `signals.rule_files` is part of the production configuration, not a convenience. The finalizer
> expands these reviewed fragments relative to `integrations/signals/`. Reading only the inline
> `rule_sets` creates **no** Signals or Last30Days jobs even when rules and state are fully intact —
> this was a real cause of silently missing releases.

## Fixing a schedule after cutover

When a registry-only gap appears after the switch, do **not** repeat the whole import and finalize.
Use the verified source snapshot and the active state directory:

```bash
benka production-schedules-refresh /private/verified-source /private/production-state
benka cron-sync-production /state/hermes /state/hermes/benka/schedules.json
```

`production-schedules-refresh` changes only the schedule manifest and its hash-bound receipt.
`cron-sync-production` then idempotently adds or updates the reviewed jobs, enables the required
ones, and pauses obsolete jobs. It validates the production receipt and refuses to run against a
candidate or rehearsal.

## Related

- [Operations — schedules and queues](../hermes/operations.md#schedules-and-queues)
- [Workflows](../workflows.md) — what each job actually does
- [Services](services.md) — which container runs it
