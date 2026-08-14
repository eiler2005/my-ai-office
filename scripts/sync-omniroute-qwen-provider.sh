#!/usr/bin/env bash
# Register the server-side DashScope API key as Qwen in OmniRoute and make it
# the primary model for the `light` combo. DeepSeek remains the final reserve.

set -euo pipefail

OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-30}"
  -o ConnectionAttempts=1
)

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: export OPENCLAW_HOST=deploy@<server-host>" >&2
  exit 1
fi

echo "Syncing Qwen DashScope provider into OmniRoute on ${OPENCLAW_HOST}..."

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  'sudo docker exec -i omniroute sh -lc "cd /app && node -"' <<'JS'
import Database from "better-sqlite3";
import { randomUUID } from "node:crypto";
import fs from "node:fs";

const { encrypt } = await import("./src/lib/db/encryption.ts");

const key = process.env.DASHSCOPE_API_KEY;
if (!key) {
  throw new Error("DASHSCOPE_API_KEY is not set in the omniroute container env");
}

const dbPath = "/app/data/storage.sqlite";
const backupDir = "/app/data/db_backups";
fs.mkdirSync(backupDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const backupPath = `${backupDir}/db_${stamp}_pre-qwen-provider.sqlite`;
fs.copyFileSync(dbPath, backupPath);

const db = new Database(dbPath);
const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
const encryptedKey = encrypt(key);

const existing = db
  .prepare("select id from provider_connections where provider = ? order by priority limit 1")
  .get("alibaba");

let action = "inserted";
if (existing) {
  db.prepare(`
    update provider_connections
       set api_key = ?,
           auth_type = 'apikey',
           is_active = 1,
           test_status = 'active',
           error_code = null,
           last_error = null,
           last_error_at = null,
           last_error_type = null,
           last_error_source = null,
           rate_limited_until = null,
           updated_at = ?
     where id = ?
  `).run(encryptedKey, now, existing.id);
  action = "updated";
} else {
  db.prepare(`
    insert into provider_connections (
      id, provider, auth_type, name, priority, is_active, test_status,
      api_key, created_at, updated_at
    ) values (?, 'alibaba', 'apikey', 'Qwen DashScope primary', 1, 1, 'active', ?, ?, ?)
  `).run(randomUUID(), encryptedKey, now, now);
}

const combo = db.prepare("select id, data from combos where name = ?").get("light");
let comboUpdated = false;
if (combo) {
  const data = JSON.parse(combo.data || "{}");
  const qwenModel = "alibaba/qwen3.7-flash";
  const deepseekModel = "deepseek/deepseek-chat";
  const models = Array.isArray(data.models) ? data.models : [];
  const reordered = [
    qwenModel,
    ...models.filter((model) => model !== qwenModel && model !== deepseekModel),
    deepseekModel,
  ];
  comboUpdated = JSON.stringify(models) !== JSON.stringify(reordered);
  data.models = reordered;
  data.updatedAt = now;
  db.prepare("update combos set data = ?, updated_at = ? where id = ?").run(
    JSON.stringify(data),
    now,
    combo.id
  );
}

console.log(JSON.stringify({
  ok: true,
  provider: "alibaba",
  action,
  light_combo_qwen_primary: true,
  light_combo_deepseek_reserve: true,
  combo_updated: comboUpdated,
  backup: backupPath.split("/").pop(),
}));
JS

echo "Restarting OmniRoute..."
ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/openclaw
  sudo docker compose up -d --force-recreate omniroute >/dev/null
  for _ in $(seq 1 60); do
    status="$(sudo docker inspect -f "{{.State.Health.Status}}" omniroute 2>/dev/null || echo starting)"
    [[ "$status" == "healthy" ]] && break
    sleep 2
  done
  sudo docker compose ps omniroute
'

echo "Done."
