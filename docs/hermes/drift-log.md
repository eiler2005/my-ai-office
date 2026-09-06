# Drift log: OpenClaw ↔ Hermes

OpenClaw remained production throughout preparation and the roughly two-week waiting period that
followed. Ordinary new messages, mail, notes, and cursors transfer with the final fresh snapshot.
Changes to **behaviour, code, sources, schedules, settings, and secrets** are tracked separately
here, because a snapshot cannot carry them.

| ID / date | Change in the source system | Action required in Hermes | Verification | Status |
|---|---|---|---|---|
| D001 / 2026-09-06 | Source checkout contains uncommitted edits and OpenClaw 2026.9.1 preparation | Map every diff against the live files; port the applicable fixes | File registry and regression run | OPEN |
| D002 / 2026-09-06 | Telegram Digest is started by host cron; the OpenClaw agent-turn job is disabled | Preserve the five slots and digest types in Hermes cron, then stop the host trigger | One run per slot | Code ready; server-side reconciliation OPEN |
| D003 / 2026-09-06 | `config` and `workspace` were split; an additional OpenClaw candidate outside Compose was found on the source host | Record only the actual production baseline; do not treat the candidate as a running version | Re-run inventory immediately before cutover | OPEN |
| D004 / 2026-09-06 | New private remote `my-ai-office`; by the owner's instruction, verification runs on the VPS only | Do not create GitHub Actions or automated deployment | Absence of deployment workflows; VPS protocol | Applied |
| D005 / 2026-09-06 | Denis chose a domain matching or adjacent to Reddit Compass | Same `RC_PUBLIC_HOST`, separate port 8451, own Caddy; no change to the neighbouring project | mTLS, login, WebSocket, and rejection of unauthorised access | PASS on the isolated panel |
| D006 / 2026-09-06 | Denis gave a separate instruction for production cutover and lifted the requirement to keep the snapshot on the Mac | A fresh cold snapshot was created and verified directly on the Hermes VPS; source Docker services were stopped after Hermes started | Gateway, model, Redis, wiki, LightRAG, panel mTLS, and native cron smoke | ACTIVE_ON_HERMES; 48 h observation OPEN |

Add a row for every change to the source system. For rotations, record only the secret name or
purpose and the date; transfer the value through private storage and then verify access on the test
contour by an approved method.

Functional gaps must be closed before `READY_NOT_ACTIVE`. During the waiting period, record the
candidate SHA and repeat the affected checks whenever a fix is ported. Before the switch window,
this table must contain no unresolved behavioural changes. A rehearsal snapshot is never treated as
current production state.

| Checkpoint | Value |
|---|---|
| Source Git baseline | `1d7ffedd7a6fcb6ef10dba5d7ed52e48417f2279` |
| Hermes upstream | `01ae7a5668ce0fa2efca524a4567cacdd0786c95` |
| `READY_NOT_ACTIVE` declared | Skipped by a separate production-cutover instruction |
| Start of the ~two-week waiting period | Ended by a separate instruction from the owner |
| Denis's instruction for production activation | Received 2026-09-06 |
| Final snapshot | Created and verified on the Hermes VPS; private state |
| Start of the 48-hour observation window | 2026-09-06 |
