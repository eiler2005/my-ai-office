# Rollback And Backup

## Rollback goals

Rollback should preserve two invariants:

1. the pre-existing `deploy-bridge-1` service must remain untouched
2. OpenClaw changes must be reversible without requiring a full host rebuild

## Simple rollback

Stop OpenClaw only:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose down
'
```

If you only need to disable public access temporarily:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo systemctl stop caddy
'
```

## Config rollback

Relevant rollback points were stored on the server under:

- `/opt/openclaw/backups/`
- `/etc/caddy/Caddyfile.pre-*`

Typical rollback path:

1. restore the previous `docker-compose.yml`
2. restore the previous `openclaw.json`
3. restore the previous `Caddyfile`
4. recreate the gateway container
5. reload `Caddy`

## Versioned Gateway image rollback

For every OpenClaw candidate, start from the
[OpenClaw Version Compatibility Ledger](22-openclaw-version-compatibility-ledger.md) and record the
current derived image as the known-good parent before switching the Gateway. Back up the image
reference, Gateway configuration, and the auth state relevant to the candidate; do not rely on a
floating upstream tag as a rollback target.

If any generic or version-specific release gate fails, restore that known-good image reference,
recreate only `openclaw-gateway`, and repeat the restored-image health, configuration, model, and
Telegram checks. Then mark the candidate `held` or `rolled-back` in the ledger with the observable
failure and the evidence that the restore succeeded. Keep the known-good image available until a
later candidate is marked `production-verified`.

## Hard rollback

If OpenClaw must be removed entirely:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose down || true &&
  sudo rm -rf /opt/openclaw
'
```

If public access should be removed as well:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo systemctl stop caddy
'
```

## Minimum backup set

- `/opt/openclaw/.env`
- `/opt/openclaw/docker-compose.yml`
- `/opt/openclaw/config/openclaw.json`
- `/opt/openclaw/config/agents/main/agent/auth-profiles.json`
- `/etc/caddy/Caddyfile`

## Sensitive backup set

These are operationally important but must never go to Git:

- client certificate materials
- access CA materials
- tokenized browser URLs
- any real server access notes

Keep them only in local password managers, secure file storage, or explicitly private backup locations.
