#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
EXCLUDE_SOURCE_TITLES="${EXCLUDE_SOURCE_TITLES:-Denis_Faang}"
SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-15}"
  -o ConnectionAttempts=1
)

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: export OPENCLAW_HOST=deploy@<server-host>" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "python3 -" > "${TMP_DIR}/remote.json" <<'PY'
import json
from pathlib import Path

vault_root = Path("/opt/obsidian-vault")
research_root = vault_root / "wiki" / "research"
log_path = vault_root / "wiki" / "LOG.md"
queue_path = vault_root / "wiki" / "IMPORT-QUEUE.md"


def count_prefix(prefix: str) -> int:
    return len(list(research_root.glob(f"{prefix}*.md")))


def read_preview(path: Path, max_lines: int = 10) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lines:]


result = {
    "research_page_total": len(list(research_root.glob("*.md"))),
    "research_prefix_counts": {
        "denis_ai": count_prefix("denis-ai-"),
        "denis_toolsforlife": count_prefix("denis-toolsforlife-"),
        "denis_interesting": count_prefix("denis-interesting-"),
        "saved_messages": count_prefix("saved-messages-"),
        "denis_faang": count_prefix("denis-faang-"),
    },
    "wiki_log_tail": read_preview(log_path),
    "import_queue_tail": read_preview(queue_path),
}

print(json.dumps(result, ensure_ascii=False))
PY

EXCLUDE_SOURCE_TITLES="${EXCLUDE_SOURCE_TITLES}" \
OPENCLAW_HOST="${OPENCLAW_HOST}" \
SSH_KEY="${SSH_KEY}" \
bash "${ROOT_DIR}/scripts/backfill-denis-sources-to-wiki.sh" --dry-run > "${TMP_DIR}/backfill.txt"

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "curl -sf http://127.0.0.1:8020/health && echo && curl -sf http://127.0.0.1:8020/documents/status_counts" \
  > "${TMP_DIR}/lightrag-health.txt"

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "python3 - <<'PY'
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


VAULT_ROOT = Path('/opt/obsidian-vault')
RESEARCH_ROOT = VAULT_ROOT / 'wiki' / 'research'
LEDGER_PATH = VAULT_ROOT / '.ingest-ledgers' / 'telegram-post-imports.jsonl'


def telegram_deeplink(chat_id, message_id):
    chat = str(chat_id or '').strip()
    msg = str(message_id or '').strip()
    if not chat or not msg or chat == 'me':
        return None
    if chat.startswith('-100') and msg.isdigit():
        return f'https://t.me/c/{chat[4:]}/{msg}'
    return None


def load_ledger():
    records = {}
    if not LEDGER_PATH.exists():
        return records
    for line in LEDGER_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        research_path = str(payload.get('research_path') or '').strip()
        if research_path:
            records[Path(research_path).name] = payload
    return records


def parse_source_links(file_path, ledger):
    result = {
        'wiki': file_path,
        'source_links': [],
        'source_provenance': {},
    }
    page = RESEARCH_ROOT / file_path
    ledger_row = ledger.get(Path(file_path).name)
    if ledger_row:
        canonical = str(ledger_row.get('source') or '').strip()
        if canonical.startswith('http://') or canonical.startswith('https://'):
            result['source_links'].append(canonical)
        tg = telegram_deeplink(ledger_row.get('source_chat_id'), ledger_row.get('message_id'))
        if tg:
            result['source_links'].append(tg)
        result['source_provenance'] = {
            'source_title': ledger_row.get('source_title'),
            'message_id': ledger_row.get('message_id'),
            'post_date_utc': ledger_row.get('post_date_utc'),
        }
        return result

    if not page.exists():
        return result

    text = page.read_text(encoding='utf-8', errors='ignore')
    url_match = re.search(r'^source:\s*(https?://\S+)\s*$', text, flags=re.MULTILINE)
    if url_match:
        result['source_links'].append(url_match.group(1).strip())

    q_match = re.search(r'from ([A-Za-z0-9_ ]+) message (\d+) dated ([0-9T:+-]+)', text)
    if q_match:
        result['source_provenance'] = {
            'source_title': q_match.group(1).strip(),
            'message_id': int(q_match.group(2)),
            'post_date_utc': q_match.group(3).strip(),
        }
    return result


ledger = load_ledger()

query_specs = [
    {
        'query': 'life principles',
        'kind': 'thematic',
        'hl_keywords': ['life principles', 'personal philosophy', 'guiding values'],
        'll_keywords': ['life principles', 'honesty', 'integrity', 'values'],
        'expected_ref_substrings': [
            'denis-interesting-2024-08-13-102',
            'denis-toolsforlife-2025-05-09-160',
        ],
    },
    {
        'query': 'Claude code best practices',
        'kind': 'factual',
        'hl_keywords': ['Claude Code', 'AI coding', 'best practices'],
        'll_keywords': ['Claude code best practices', 'Claude Code', 'coding agent'],
        'expected_ref_substrings': [
            'denis-ai-2025-05-15-claude-code-best-practices',
            '2026-04-21-claude-code-guide',
            'denis-ai-2025-07-01-158-claude-code',
        ],
    },
    {
        'query': 'NOCONCEPT',
        'kind': 'entity_topic',
        'hl_keywords': ['NOCONCEPT'],
        'll_keywords': ['NOCONCEPT'],
        'expected_ref_substrings': [
            'noconcept',
            'denis-interesting',
            'denis-ai',
        ],
    },
]
results = []
for spec in query_specs:
    query = spec['query']
    request_payload = {
        'query': query,
        'mode': 'hybrid',
        'hl_keywords': spec['hl_keywords'],
        'll_keywords': spec['ll_keywords'],
        'top_k': 20,
        'chunk_top_k': 10,
        'max_entity_tokens': 3000,
        'max_relation_tokens': 3000,
        'max_total_tokens': 10000,
        'enable_rerank': False,
    }
    req = urllib.request.Request(
        'http://127.0.0.1:8020/query/data',
        data=json.dumps(request_payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    query_error = None
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        try:
            parsed_error = json.loads(body)
        except json.JSONDecodeError:
            parsed_error = {'raw': body[:500]}
        payload = {}
        query_error = {
            'http_status': exc.code,
            'error': parsed_error,
        }
    data = payload.get('data') or {}
    refs = data.get('references') or []
    ref_paths = [
        str(item.get('file_path') or item.get('path') or '')
        for item in refs
        if isinstance(item, dict)
    ]
    source_meta = [
        parse_source_links(path, ledger)
        for path in ref_paths[:5]
        if path
    ]
    results.append(
        {
            'query': query,
            'kind': spec['kind'],
            'references': len(refs),
            'response_preview': str(payload.get('message') or '')[:240],
            'reference_preview': refs[:3],
            'all_reference_paths': ref_paths[:10],
            'source_link_preview': source_meta[:3],
            'expected_ref_substrings': spec['expected_ref_substrings'],
            'query_error': query_error,
        }
    )
print(json.dumps(results, ensure_ascii=False))
PY" > "${TMP_DIR}/queries.json"

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "python3 - <<'PY'
import json
import urllib.error
import urllib.request
from pathlib import Path


def read_env(path):
    result = {}
    for line in Path(path).read_text(encoding='utf-8', errors='ignore').splitlines():
        if not line or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        result[key.strip()] = value.strip()
    return result


env = read_env('/opt/lightrag/.env')
api_key = env.get('LLM_BINDING_API_KEY') or env.get('EMBEDDING_BINDING_API_KEY') or ''
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + api_key,
}

routes = {}

chat_payload = {
    'model': 'light',
    'messages': [{'role': 'user', 'content': 'Reply exactly: OK_RAG_LLM_RESERVE'}],
    'max_tokens': 32,
    'temperature': 0,
}
chat_req = urllib.request.Request(
    'http://127.0.0.1:20129/v1/chat/completions',
    data=json.dumps(chat_payload).encode('utf-8'),
    headers=headers,
    method='POST',
)
try:
    with urllib.request.urlopen(chat_req, timeout=90) as response:
        payload = json.loads(response.read().decode('utf-8'))
        text = (((payload.get('choices') or [{}])[0].get('message') or {}).get('content') or '')
        routes['omniroute_light_llm'] = {
            'ok': 'OK_RAG_LLM_RESERVE' in text,
            'http_status': response.status,
            'resolved_model': payload.get('model'),
            'response_preview': text[:80],
        }
except urllib.error.HTTPError as exc:
    routes['omniroute_light_llm'] = {
        'ok': False,
        'http_status': exc.code,
        'error_preview': exc.read(300).decode('utf-8', errors='ignore'),
    }
except Exception as exc:
    routes['omniroute_light_llm'] = {
        'ok': False,
        'error_type': type(exc).__name__,
        'error_preview': str(exc)[:300],
    }

embedding_payload = {
    'model': 'deepseek/deepseek-chat',
    'input': 'ping',
}
embedding_req = urllib.request.Request(
    'http://127.0.0.1:20129/v1/embeddings',
    data=json.dumps(embedding_payload).encode('utf-8'),
    headers=headers,
    method='POST',
)
try:
    with urllib.request.urlopen(embedding_req, timeout=30) as response:
        routes['deepseek_embeddings'] = {
            'supported': True,
            'http_status': response.status,
        }
except urllib.error.HTTPError as exc:
    error_preview = exc.read(300).decode('utf-8', errors='ignore')
    if not error_preview and exc.code == 400:
        error_preview = 'DeepSeek is not an embeddings provider in OmniRoute.'
    routes['deepseek_embeddings'] = {
        'supported': False,
        'http_status': exc.code,
        'error_preview': error_preview,
    }
except Exception as exc:
    routes['deepseek_embeddings'] = {
        'supported': False,
        'error_type': type(exc).__name__,
        'error_preview': str(exc)[:300],
    }

print(json.dumps(routes, ensure_ascii=False))
PY" > "${TMP_DIR}/routing.json"

python3 - <<'PY' "${TMP_DIR}/remote.json" "${TMP_DIR}/backfill.txt" "${TMP_DIR}/lightrag-health.txt" "${TMP_DIR}/queries.json" "${TMP_DIR}/routing.json"
import json
import re
import sys
from pathlib import Path

remote = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
backfill_text = Path(sys.argv[2]).read_text(encoding="utf-8", errors="ignore")
health_lines = [line for line in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines() if line.strip()]
queries = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
routing = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))

candidates_match = re.search(r'"candidates"\s*:\s*(\d+)', backfill_text)
resume_match = re.search(r'"resume_skipped"\s*:\s*(\d+)', backfill_text)
dedupe_match = re.search(r'"dedupe_skipped"\s*:\s*(\d+)', backfill_text)

health = json.loads(health_lines[0]) if health_lines else {}
status_counts = json.loads(health_lines[1]).get("status_counts", {}) if len(health_lines) > 1 else {}

degraded_markers = (
    "do not have enough information",
    "cannot answer your question",
    "too broad",
    "does not contain information",
    "lightRAG unavailable".lower(),
)

for item in queries:
    preview = str(item.get("response_preview", "")).lower()
    refs = int(item.get("references", 0) or 0)
    ref_paths = [str(path).lower() for path in item.get("all_reference_paths", [])]
    expected = [str(marker).lower() for marker in item.get("expected_ref_substrings", [])]
    source_links = [
        link
        for entry in item.get("source_link_preview", [])
        for link in entry.get("source_links", [])
    ]
    expected_ref_hit = any(
        marker in path
        for marker in expected
        for path in ref_paths
    )
    item["quality_flags"] = {
        "has_refs": refs > 0,
        "query_ok": item.get("query_error") is None,
        "degraded_answer": any(marker in preview for marker in degraded_markers),
        "expected_ref_hit": expected_ref_hit,
        "has_source_links": len(source_links) > 0,
        "targeted_factual_pass": (
            item.get("kind") != "factual"
            or (
                refs > 0
                and expected_ref_hit
                and len(source_links) > 0
                and not any(marker in preview for marker in degraded_markers)
            )
        ),
    }

quality_summary = {
    "targeted_factual_queries": [
        item["query"] for item in queries if item.get("kind") == "factual"
    ],
    "targeted_factual_pass": all(
        item["quality_flags"]["targeted_factual_pass"]
        for item in queries
        if item.get("kind") == "factual"
    ),
    "degraded_queries": [
        item["query"] for item in queries if item["quality_flags"]["degraded_answer"]
    ],
    "query_errors": [
        {"query": item["query"], "error": item.get("query_error")}
        for item in queries
        if item.get("query_error") is not None
    ],
}

embedding_unavailable_markers = (
    "no credentials for embedding provider",
    "monthly spending cap",
    "resource_exhausted",
    "insufficient_quota",
    "credits_exhausted",
)
embedding_paywall_errors = [
    err
    for err in quality_summary["query_errors"]
    if any(marker in json.dumps(err, ensure_ascii=False).lower() for marker in embedding_unavailable_markers)
]
deprecated_retrieval = (
    bool(quality_summary["query_errors"])
    and len(embedding_paywall_errors) == len(quality_summary["query_errors"])
)

quality_summary["retrieval_status"] = "deprecated_external_embeddings_unavailable" if deprecated_retrieval else "active"
quality_summary["deprecated_reason"] = (
    "LightRAG retrieval requires a funded Gemini/OpenRouter/OpenAI API embeddings route. "
    "Current external embedding providers are missing credentials, out of quota, or blocked by spending caps. "
    "DeepSeek is validated as an LLM reserve behind OmniRoute light, but it is not an embeddings provider."
    if deprecated_retrieval
    else None
)

summary = {
    "wiki": {
        "research_page_total": remote["research_page_total"],
        "research_prefix_counts": remote["research_prefix_counts"],
        "dry_run": {
            "candidates": int(candidates_match.group(1)) if candidates_match else None,
            "resume_skipped": int(resume_match.group(1)) if resume_match else None,
            "dedupe_skipped": int(dedupe_match.group(1)) if dedupe_match else None,
        },
        "wiki_log_tail": remote["wiki_log_tail"][-5:],
        "import_queue_tail": remote["import_queue_tail"][-5:],
    },
    "lightrag": {
        "status": health.get("status"),
        "pipeline_busy": health.get("pipeline_busy"),
        "status_counts": status_counts,
        "model_routes": routing,
        "queries": queries,
        "quality_summary": quality_summary,
    },
}

print(json.dumps(summary, ensure_ascii=False, indent=2))
if deprecated_retrieval:
    print(
        "LightRAG retrieval is deprecated for this deployment until a funded embeddings route is restored.",
        file=sys.stderr,
    )
    sys.exit(0)
if quality_summary["query_errors"] or not quality_summary["targeted_factual_pass"]:
    sys.exit(1)
PY
