"""
Config loader and validator for the signals bridge.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from last30days_presets import (
    DEFAULT_PERSONAL_FEED_QUERY_BUNDLE,
    ensure_last30days_presets,
)


CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.json"))
VALID_SOURCE_TYPES = {"email", "telegram", "web"}
VALID_TELEGRAM_RULE_KINDS = {"hashtag", "author_keywords", "content_keywords"}
VALID_EMAIL_RULE_KINDS = {"tradingview_user"}


def load_config() -> dict:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return normalize_config(data, base_path=CONFIG_PATH.parent)


def normalize_config(data: dict, *, base_path: Path | None = None) -> dict:
    data = _with_external_rule_files(data, base_path=base_path)
    data.setdefault("timezone", "Europe/Moscow")
    data.setdefault("scheduler", {})
    data["scheduler"].setdefault("tick_seconds", 300)
    data["scheduler"].setdefault("cleanup_interval_seconds", 3600)
    data.setdefault("default_poll_interval_seconds", 300)
    data.setdefault("event_retention_days", 14)
    data.setdefault("delivery", {})
    data["delivery"].setdefault("topic_name", "signals")
    data["delivery"].setdefault("mode", "mini_batch")
    data.setdefault("last30days", {})
    data["last30days"].setdefault("enabled", False)
    data["last30days"].setdefault("schedule_expr", "0 7 * * *")
    data["last30days"].setdefault("timezone", data.get("timezone", "Europe/Moscow"))
    data["last30days"].setdefault("mode", "compact")
    data["last30days"].setdefault("max_items", 10)
    data["last30days"].setdefault("query_bundle", list(DEFAULT_PERSONAL_FEED_QUERY_BUNDLE))
    data["last30days"].setdefault("telegram", {})
    data["last30days"]["telegram"].setdefault("topic_name", "last30daysTrend")
    data["last30days"]["telegram"].setdefault("topic_id", 0)
    data["last30days"].setdefault("obsidian", {})
    data["last30days"]["obsidian"].setdefault("root", "Last30Days")
    data["last30days"] = ensure_last30days_presets(data["last30days"])
    data.setdefault("sources", {})
    for key in VALID_SOURCE_TYPES:
        data["sources"].setdefault(key, [])
    data.setdefault("rule_sets", [])
    validate_config(data)
    return data


def _with_external_rule_files(data: dict, *, base_path: Path | None) -> dict:
    result = dict(data)
    result.setdefault("rule_files", [])
    merged_rulesets = list(result.get("rule_sets", []) or [])
    if base_path is None:
        result["rule_sets"] = merged_rulesets
        return result

    for pattern in result.get("rule_files", []) or []:
        for path in sorted(base_path.glob(pattern)):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "rule_sets" in payload:
                merged_rulesets.extend(list(payload.get("rule_sets", []) or []))
            elif isinstance(payload, list):
                merged_rulesets.extend(payload)
            elif isinstance(payload, dict):
                merged_rulesets.append(payload)
    result["rule_sets"] = merged_rulesets
    return result


def validate_config(data: dict) -> None:
    sources = data.get("sources", {})
    source_index: dict[tuple[str, str], dict] = {}
    for source_type, items in sources.items():
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"invalid source kind section: {source_type}")
        for item in items:
            if item.get("kind") != source_type:
                raise ValueError(f"invalid source kind for {item.get('id')}: {item.get('kind')}")
            source_id = str(item.get("id", "")).strip()
            if not source_id:
                raise ValueError(f"missing source id in {source_type}")
            source_index[(source_type, source_id)] = item
            if source_type == "telegram" and not str(item.get("chat_id", "")).strip():
                raise ValueError(f"telegram source {source_id} missing chat_id")

    seen_ruleset_ids: set[str] = set()
    for ruleset in data.get("rule_sets", []):
        ruleset_id = str(ruleset.get("id", "")).strip()
        if not ruleset_id:
            raise ValueError("ruleset missing id")
        if ruleset_id in seen_ruleset_ids:
            raise ValueError(f"duplicate ruleset id: {ruleset_id}")
        seen_ruleset_ids.add(ruleset_id)
        for rule in ruleset.get("rules", []):
            source_type = str(rule.get("source_type", "")).strip()
            source_id = str(rule.get("source_id", "")).strip()
            if not source_type or not source_id:
                raise ValueError(f"rule {rule.get('id')} missing source ref")
            if (source_type, source_id) not in source_index:
                raise ValueError(f"rule {rule.get('id')} references unknown source {source_type}:{source_id}")
            if source_type == "telegram":
                _validate_telegram_rule(rule, source_index[(source_type, source_id)])
            elif source_type == "email":
                _validate_email_rule(rule)
            elif source_type == "web" and sources.get("web"):
                continue

    _validate_last30days(data.get("last30days", {}))


def _validate_telegram_rule(rule: dict, source: dict) -> None:
    kind = str(rule.get("kind", "")).strip()
    if kind not in VALID_TELEGRAM_RULE_KINDS:
        raise ValueError(f"invalid telegram rule kind for {rule.get('id')}: {kind}")
    if not source.get("chat_id"):
        raise ValueError(f"telegram rule {rule.get('id')} requires stable chat_id")
    if kind == "hashtag" and not rule.get("hashtags"):
        raise ValueError(f"telegram hashtag rule {rule.get('id')} missing hashtags")
    if kind == "author_keywords":
        if not rule.get("sender_ids"):
            raise ValueError(f"telegram rule {rule.get('id')} missing sender_ids")
        if not rule.get("keywords"):
            raise ValueError(f"telegram rule {rule.get('id')} missing keywords")
    if kind == "content_keywords":
        if not rule.get("keywords"):
            raise ValueError(f"telegram content rule {rule.get('id')} missing keywords")


def _validate_email_rule(rule: dict) -> None:
    kind = str(rule.get("kind", "")).strip()
    if kind not in VALID_EMAIL_RULE_KINDS:
        raise ValueError(f"invalid email rule kind for {rule.get('id')}: {kind}")
    if not str(rule.get("from_email", "")).strip():
        raise ValueError(f"email rule {rule.get('id')} missing from_email")
    if not rule.get("tradingview_usernames"):
        raise ValueError(f"email rule {rule.get('id')} missing tradingview_usernames")


def _validate_last30days(data: dict) -> None:
    current = dict(data or {})
    current = ensure_last30days_presets(current)
    current.setdefault("mode", "compact")
    current.setdefault("schedule_expr", "0 7 * * *")
    current.setdefault("query_bundle", list(DEFAULT_PERSONAL_FEED_QUERY_BUNDLE))
    current.setdefault("telegram", {})
    current["telegram"].setdefault("topic_id", 0)
    if str(current.get("mode", "compact")).strip() != "compact":
        raise ValueError("last30days.mode must currently be compact")
    expr = str(current.get("schedule_expr", "")).strip()
    if len(expr.split()) != 5:
        raise ValueError("last30days.schedule_expr must be a 5-part cron expression")
    query_bundle = [str(item).strip() for item in current.get("query_bundle", []) if str(item).strip()]
    if not query_bundle:
        raise ValueError("last30days.query_bundle must not be empty")
    topic_id = current.get("telegram", {}).get("topic_id", 0)
    try:
        int(topic_id or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("last30days.telegram.topic_id must be an integer") from exc

    for preset_id, preset in dict(current.get("presets", {}) or {}).items():
        _validate_last30days_preset(preset_id, dict(preset or {}))


def _validate_last30days_preset(preset_id: str, preset: dict) -> None:
    mode = str(preset.get("mode", "compact")).strip()
    if mode != "compact":
        raise ValueError(f"last30days preset {preset_id}.mode must currently be compact")
    topic_id = preset.get("telegram", {}).get("topic_id", 0)
    try:
        int(topic_id or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"last30days preset {preset_id}.telegram.topic_id must be an integer") from exc
    query_bundle = [str(item).strip() for item in preset.get("query_bundle", []) if str(item).strip()]
    if not query_bundle:
        raise ValueError(f"last30days preset {preset_id}.query_bundle must not be empty")


def get_ruleset(config: dict, ruleset_id: str) -> dict:
    for ruleset in config.get("rule_sets", []):
        if ruleset.get("id") == ruleset_id:
            return ruleset
    raise KeyError(f"ruleset not found: {ruleset_id}")


def index_sources(config: dict) -> dict[tuple[str, str], dict]:
    result: dict[tuple[str, str], dict] = {}
    for source_type, items in config.get("sources", {}).items():
        for item in items:
            result[(source_type, item["id"])] = item
    return result
