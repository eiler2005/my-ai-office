# Transfer inventory

Snapshot: 2026-09-06. Status: `MIGRATION_IN_PROGRESS`. Addresses and secrets live in the private
deployment manifest, never here.

## Source set

The candidate was created as a separate clone, `openclaw_firststeps`, from
`1d7ffedd7a6fcb6ef10dba5d7ed52e48417f2279`.

The target also retains the four original My AI Office commits carrying the overview, architecture,
ignore rules, and MIT license. The source's active branches are published under their previous
`agent/...` names; the source `main` is available as `legacy/openclaw-main`. Migration code is
published to `main` and `migration/hermes-native`. The histories are merged without force pushes.

The source working directory contains uncommitted OpenClaw 2026.9.1 preparation and other edits.
They were **not** copied over the verified runtime automatically: their reconciliation against the
server is tracked in the [drift log](drift-log.md).

Historical branches are kept locally. The `backup/pre-scrub-20260411-144635` backup is not intended
for publication without a separate review of why the history was scrubbed.

At the first read-only probe the live Gateway used image ID
`sha256:b4419b44f35397314015301ea5a248eb31037f05b2c82a777f12ad67d0fb5b97`, and the container was
healthy. This is a recorded starting point, not an instruction to upgrade OpenClaw.

## The Hermes VPS and its neighbours

Details were found in `reddit-compass/docs/HOSTING.md`,
`reddit-compass/deploy/hostkey/README.md`, this project's Compose files, and
`vps_management/docs/ownership-matrix.md` plus `docs/containers.md`. Access goes through the
`vps-hostkey-hermes` alias and `vps_management/ansible/scripts/ssh-vps.sh`; secrets are read via
the standard encrypted Ansible vault mechanism.

| Property | Verified read-only, 2026-09-06 |
|---|---|
| Target CPU / RAM | 8 CPU / 15,955 MiB RAM; roughly 13.4 GiB available |
| Target disk `/opt` | Roughly 113 GiB free, 25% used |
| Existing Compose projects | `reddit-compass`, `moex-futoi`, `cheap-intelligence`, `stealth` |
| Ports | 80, 443, 8450 occupied; 8451 and 9119 were free |
| Hermes Agent / directory | The Hermes command and `/opt/benka-hermes` were both absent at the initial check |
| Source CPU / RAM | 2 CPU / 3,819 MiB RAM; roughly 1.1 GiB available |
| Source disk | 87% used; roughly 4.7 GiB free |

Ports 80/443 and SNI routing belong to existing infrastructure. Reddit Compass already uses 8450.
The candidate receives its own Compose project `benka-hermes-candidate`, the `/opt/benka-hermes`
directory, and Caddy on 8451; 9119 is reachable only inside the container network. The required SNI
route on 443 is a separate infrastructure change made after the domain is chosen.

During the transfer, a blanket `docker compose down`, `docker system prune`, or a restart of
another project's proxy must never be run.

Inventory is repeatable: `scripts/inventory-hermes-host.py --role source|target`. The script only
reads state; it prints variable names without values and emits neither SSH addresses nor cron
command bodies. Detailed JSON reports are stored outside Git. Sizes that cannot be read are marked
`unverified` rather than zero.

A repeat source probe at 10:03 UTC showed roughly 3.57 GiB free space, `config` at roughly
4.72 GiB, LightRAG at roughly 1.05 GiB, and the vault at roughly 56 MiB. The Signals size was not
confirmed because of permissions or a timeout.

An additional OpenClaw candidate was found outside Compose: the production image was unchanged, and
the candidate is not admitted to the baseline. An automated search for OpenClaw cron entries in
`config` produced no confirmed registry; the absence of a result does not mean the absence of jobs.

Recorded live image IDs of the dependent services: LightRAG
`sha256:baf0d07eaa73d2e0fa044fdab76767c69480737368a3fd88ffc86af1290f5259`, OmniRoute
`sha256:a70d7cb45db50d409b75c7a69b0255d856098abbc8ed6da48930a308a1953aa8`, Redis
`sha256:8b81dd37ff027bec4e516d41acfbe9fe2460070dc6d4a4570a2ac5b9d59df065`. The transfer needs either
an export/load of these images or confirmed registry digests; **an image ID is not a registry pull
URL.**

## Functions and data

| Function | Hermes code | State to transfer | Acceptance |
|---|---|---|---|
| Identity and memory | curated `claw-layout`, native importer, domain profiles | SOUL/IDENTITY/USER/MEMORY, reviewed skills | Style and stable facts; new sessions |
| Old conversations and diaries | `archive.py`, SQLite FTS5 | JSONL, Markdown, source and line number | Search, re-indexing, gap report |
| Telegram ingress / topics | Native Gateway, `profiles.py` | Trusted numeric IDs, topics, update watermark | Real inbound, follow-up, negative ACL tests |
| Personal / work mail | `pipelines.py` → `agentmail-email` | Inbox configs, cursors, dedupe, pending, and triage | Both mailboxes, forwards, actionable/informational, no duplicates |
| Telegram Digest | `pipelines.py` → `telethon-digest` | Telethon session, folders/channels, cursors, persisted releases | Sources, category balance, correct links |
| Signals | `pipelines.py` → `signals-bridge` | Rulesets, event streams, locks, source refs, dedupe | Partial source failure, delivery of source material |
| Last30Days | The same native worker and pinned skill | Both presets, source settings, repeat history | `personal-feed` / `platform-pulse`, degradation of individual sources |
| Wiki / Ideas | `wiki.py`, native plugin, the previous `wiki-import` | Vault, fingerprint, lifecycle metadata, ingest receipts | Capture, promotion without duplicates, `обсуди:` without saving |
| LightRAG | `maintenance.py`, the previous embedding endpoint | Graph, KV/vector data, dimension 3072, model identity | Control queries; "upload accepted" recorded separately from "indexed" |
| Redis | `queue.py`, `delivery.py` | RDB/AOF, streams/groups/pending, dedupe, deliveries | One slot, repeated run, reconciliation of uncertain sends |
| OmniRoute | Retained service, model configurations | SQLite/OAuth/routes and provider credentials | Every primary/reserve, failure timing, full fallback |
| Syncthing | Separate service with a new device identity | Vault and a verified folder map | Mac/target reconciliation with no unexpected deletions |
| Web panel / CLI | Native Hermes, separate dashboard, Caddy | Configuration, scoped sessions, auth | Login, chat, WebSocket, settings, refusal for outsiders |

The existing Redis field formats and the wiki `source_type`, `source`, `capture_mode`,
`promote_fingerprint`, `wiki_page_paths`, `raw_path`, and `rag_status` keys are preserved. New keys
are prefixed `benka:`.

Full email bodies are not included in RAG by default. Only a given domain's own data is imported
into that domain's archive.

## Schedules

The confirmed server-side registry is the final source of truth. This table is a reconciliation
aid, never a reason to enable something that is disabled.

| Workflow | Europe/Moscow | Notes |
|---|---|---|
| Telegram Digest | 08, 11, 14, 17, 21 | Preserve `digest_type` and slot; the current source uses host cron |
| Personal mail | 08, 13, 16, 20 | Separate morning / interval / editorial |
| Work mail | 8 slots from 08:30 to 19:00 | Take the intermediate minutes from the actual config |
| Polling of both mailboxes | Every 5 minutes | Separate streams / groups / inbox refs |
| Signals | Every 5 minutes | Enabled rulesets only |
| Signals retention | Hourly, via the source's internal scheduler | Moves to an explicit Hermes cron job after reconciliation |
| Last30Days | 07:00 | Only the preset actually enabled; the second is available on request |
| LightRAG | Every 30 minutes | An explicit list of permitted roots, not the whole filesystem |
| Wiki daily | 05:45 | `dry_run`, `report` |
| Wiki weekly | Sun 06:15 | `apply`: report, archive, refresh_topics, refresh_overview |

`benka jobs-prepare` turns the reviewed JSON registry into job and worker definitions;
`benka cron-prepare` creates native **paused** jobs with `no_agent=true`, `deliver=local`, and
`failure_deliver=local`. `local` is the supported Hermes way of not sending output to a channel.
Only the shared sender publishes results.

## Secrets by purpose

| Purpose | Storage / transfer |
|---|---|
| SSH | The existing Ansible vault, not this project's Git |
| Telegram Bot API | A separate test token for the rehearsal; production only at the switch |
| Telethon | API ID/hash and `.session`, on a private volume with the correct owner |
| The two mailboxes | API/OAuth held separately per domain, with the source inbox refs |
| LLM | Private model-providers JSON or standard Hermes auth; keys never in prompts or cron |
| Redis | ACL/URL; separate scoped credentials and stream permissions |
| Wiki / LightRAG | Separate tokens and URLs per domain |
| OmniRoute | SQLite holding OAuth and keys, taken as a consistent cold copy |
| Dashboard | Username, password hash, stable auth secret; Caddy server cert/key and client CA |
| Syncthing | A new target identity; pairing with the Mac after the data is reconciled |

`READY_NOT_ACTIVE` additionally requires: finishing the server-files ↔ Git mapping, collecting exact
sizes for every volume, enumerating cron at all levels, recording routes and ACLs, pinning the live
digests for LightRAG / OmniRoute / Syncthing, and verifying that they restore.
