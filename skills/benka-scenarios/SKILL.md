---
name: benka-scenarios
description: Trigger and inspect Benka's approved background scenarios.
---

Use `benka_status` to inspect the runtime mode. Standby means this instance does
not own production and must not act as if it does. Elapsed time never authorizes
activation; only an explicit owner instruction does.

Use `benka_run` only for a scenario in the deployment's approved job registry.
Use a stable `request_id` for retries of the same request. Queue acceptance is
not proof of completion or delivery. An uncertain delivery requires operator
reconciliation; do not submit the same publication with a new identifier.

Do not create overlapping Hermes cron jobs, OS cron entries or internal timers.
The operator prepares the sole application schedule registry through
`benka cron-prepare`; its native script jobs remain paused until activation.
