---
name: benka-scenarios
description: Trigger and inspect Benka's approved background scenarios.
---

Use `benka_status` to inspect the candidate mode. Standby means OpenClaw still
owns production. Waiting two weeks never authorizes activation.

Use `benka_run` only for a scenario in the deployment's approved job registry.
Use a stable `request_id` for retries of the same request. Queue acceptance is
not proof of completion or delivery. An uncertain delivery requires operator
reconciliation; do not submit the same publication with a new identifier.

Do not create overlapping Hermes cron jobs, OS cron entries or internal timers.
The operator prepares the sole application schedule registry through
`benka cron-prepare`; its native script jobs remain paused until activation.
