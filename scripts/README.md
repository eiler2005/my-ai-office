# Scripts

Two eras live in this directory. **Check which one a script belongs to before running it.**

Every predecessor-era script carries a banner in its header saying so. If you see that banner, the
script targets the retired OpenClaw deployment and must not be run against production.

## Current

Used to build, verify, and operate the Hermes system.

| Script | Purpose |
| --- | --- |
| `run-hermes-vps-tests.sh` | Builds the candidate in an isolated Buildx builder and runs the suites in containers with a read-only root, no production secrets, and 2 CPU / 2 GiB limits. **The release gate** ([ADR-0011](../docs/adr/0011-verification-on-the-vps-not-in-ci.md)). |
| `verify-hermes-contract.py` | Native plugin, cron, and AIAgent contract checks. |
| `verify-hermes-panel-vps.py` | Panel checks, negatives first: mTLS refusal, no-session refusal, wrong password, then a successful login, cookies, APIs, WebSocket upgrade, and ticket replay refusal. Reports no endpoint, cookie, or credential. |
| `verify-redis-vps.py` | Redis persistence and recovery against a real instance. |
| `verify-hermes-claw-vps.py` | Native importer rehearsal against synthetic data. |
| `test-hermes.py` | Local contract smoke. |
| `prepare-hermes-panel.py` | Operator-only panel preparation: private directories, certificate copy, client certificate issue. Refuses to repeat initial setup so existing credentials cannot be replaced by accident. |
| `package-hermes-candidate.py` | Builds a candidate export for VPS verification. |
| `prepare-hermes-adapters.py` | Migration tooling: maps predecessor service configuration onto Hermes workers. |
| `inventory-hermes-host.py` | Read-only host inventory for both hosts. Prints variable names without values; emits no SSH addresses or cron bodies. |
| `scan-git-secrets.py` | Walks every reachable Git blob plus the working tree with `detect-secrets --no-verify`. Reports hashes and locations, never plaintext. Run before every push; CI runs it too. |
| `check-docs-links.py` | Resolves every internal Markdown link and heading anchor, offline. |
| `render-diagrams.py` | Generates the light/dark SVG pairs in `docs/assets/`. Edit this, never the `.svg` files. |
| `list-telethon-catalog.py` · `lookup-telegram-ids.py` | Read-only Telegram catalog and identifier helpers. |
| `lightrag.env.template` | Configuration template. |

## Predecessor-era

> [!WARNING]
> These target the retired OpenClaw deployment: `/opt/openclaw`, the `openclaw-gateway` container,
> and the standalone HTTP bridge services. **They do not deploy, configure, or repair the current
> system**, and several would write to paths that no longer exist.
>
> They are retained because [ADR-0009](../docs/adr/0009-migrate-runtime-to-hermes.md) kept rollback
> real rather than theoretical: the source host's services were stopped and preserved, not deleted.
> The retention period is at least 14 days *after* full Hermes acceptance, which is still open.

| Group | Scripts |
| --- | --- |
| Bridge deployment | `deploy-agentmail-email.sh`, `deploy-agentmail-work-email.sh`, `deploy-signals-bridge.sh`, `deploy-telethon-digest.sh`, `deploy-wiki-import.sh`, `deploy-workspace.sh` |
| Knowledge provisioning | `deploy-llm-wiki.sh`, `setup-llm-wiki.sh`, `bootstrap-llm-wiki.sh`, `setup-lightrag.sh`, `create-lightrag-env.sh`, `lightrag-ingest.sh` |
| Backfill and recovery | `backfill-denis-sources-to-wiki.sh`, `backfill-knowledgebase-to-wiki.sh`, `rebuild-telegram-import-ledger.sh`, `recover-telegram-ingress-spool.sh` |
| Model routing | `deploy-qwen-gateway-config.sh`, `sync-omniroute-deepseek-provider.sh`, `sync-omniroute-openrouter-provider.sh`, `sync-omniroute-qwen-provider.sh` |
| Operator access and misc | `openclaw-ui-tunnel.sh`, `post-telegram-pins.sh`, `smoke-check-knowledge.sh`, `sync-obsidian.sh`, `fetch-telethon-catalog.sh`, `com.openclaw.obsidian-sync.plist.template` |

Four more sit next to the code they configured:
`artifacts/{agentmail-email,signals-bridge,telethon-digest,wiki-import}/sync-openclaw-cron-jobs.sh`.

### What replaced them

| Predecessor approach | Now |
| --- | --- |
| A deploy script per bridge service | One Compose project, `deploy/hermes/compose.production.yaml` ([services](../docs/reference/services.md)) |
| `sync-openclaw-cron-jobs.sh` patching a cron store | `benka jobs-prepare` and `benka cron-prepare` ([schedules](../docs/reference/schedules.md)) |
| Host cron and internal schedulers | Native Hermes cron, one owner |
| Standalone HTTP bridges | In-process workers on the Redis bus ([reliability](../docs/reliability.md)) |
| `openclaw-ui-tunnel.sh` over SSH | Caddy with TLS + mTLS ([panel](../docs/hermes/panel.md)) |

## Rules

- **Deploying is a separate, explicit act.** Preparing configuration locally is always fine; running
  anything against the server requires an instruction from the owner.
- **Never run a global `docker compose down`, `docker system prune`, or restart another project's
  proxy.** The VPS is shared with `reddit-compass`, `moex-futoi`, `cheap-intelligence`, and
  `stealth`.
- **No secrets in scripts or their output.** Tokens come from files referenced by environment
  variables and are never printed.
