from __future__ import annotations

import asyncio
from contextlib import nullcontext
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("SIGNALS_SUPERGROUP_ID", "-100123")
os.environ.setdefault("SIGNALS_TOPIC_ID", "414")
os.environ.setdefault("SIGNALS_TELETHON_SESSION_PATH", str(Path(tempfile.gettempdir()) / "signals-bridge-test"))

if "aiohttp" not in sys.modules:
    sys.modules["aiohttp"] = types.SimpleNamespace(ClientSession=object, ClientTimeout=lambda total=None: None)
if "redis" not in sys.modules:
    redis_error = type("RedisError", (Exception,), {})
    response_error = type("ResponseError", (redis_error,), {})
    sys.modules["redis"] = types.SimpleNamespace(
        Redis=object,
        from_url=lambda *args, **kwargs: None,
        exceptions=types.SimpleNamespace(RedisError=redis_error, ResponseError=response_error),
    )
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("SIGNALS_SUPERGROUP_ID", "-1001")

from config_store import normalize_config, validate_config
from cron_bridge import _deliver_source_contexts, _recover_interrupted_ruleset_locks, _relay_telegram_event_via_telethon, _run_telegram_source, _source_health
from email_adapter import _window_messages, resolve_email_window
from event_store import append_events, append_new_events
from last30days_persistence import _render_expanded_markdown
from last30days_runner import build_digest, write_signal_digest
from matching import build_telegram_message_link, extract_tradingview_username, keyword_matches, local_event_from_candidate, match_email_rule, match_telegram_rule
from models import Last30DaysCategorySection, Last30DaysDigest, Last30DaysPlatformSection, Last30DaysTheme, ModelMeta, SignalEvent
from omniroute_client import _local_fallback_batch
from poster import render_batch, render_last30days_digest
from telegram_adapter import collect_telegram_candidates, resolve_telegram_window
import state_store


class FakeRedis:
    def __init__(self) -> None:
        self.kv = {}
        self.stream = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    def get(self, key):
        return self.kv.get(key)

    def delete(self, key):
        if key not in self.kv:
            return 0
        del self.kv[key]
        return 1

    def xadd(self, name, fields):
        self.stream.append((name, fields))
        return f"{len(self.stream)}-0"

    def xrange(self, name, min="-", max="+", count=200):
        return []

    def xdel(self, name, *ids):
        return len(ids)


def sample_config() -> dict:
    return {
        "timezone": "Europe/Moscow",
        "scheduler": {"tick_seconds": 300, "cleanup_interval_seconds": 3600},
        "default_poll_interval_seconds": 300,
        "event_retention_days": 14,
        "delivery": {"topic_name": "signals", "mode": "mini_batch"},
        "sources": {
            "email": [
                {"id": "email-tradingview", "kind": "email", "enabled": True, "inbox_ref": "test@example.com"}
            ],
            "telegram": [
                {"id": "telegram-trader-speki", "kind": "telegram", "enabled": True, "chat_id": -1001, "chat_name": "Трейдер"}
            ],
            "web": [],
        },
        "rule_sets": [
            {
                "id": "trading",
                "title": "Trading",
                "enabled": True,
                "poll_interval_seconds": 300,
                "rules": [
                    {
                        "id": "market-alert-user",
                        "source_type": "email",
                        "source_id": "email-tradingview",
                        "enabled": True,
                        "kind": "tradingview_user",
                        "from_email": "noreply@tradingview.com",
                        "tradingview_usernames": ["AnalystA"],
                    },
                    {
                        "id": "telegram-si",
                        "source_type": "telegram",
                        "source_id": "telegram-trader-speki",
                        "enabled": True,
                        "kind": "hashtag",
                        "hashtags": ["#si"],
                    },
                ],
            }
        ],
    }


def last30days_payload(
    *,
    title: str,
    query_source: str = "x",
    candidate_id: str = "cand-1",
    url: str | None = None,
    snippet: str = "Compact summary with enough context to avoid penalties.",
    score: float = 95.0,
    sources: list[str] | None = None,
    source_titles: list[str] | None = None,
    clusters: list[dict] | None = None,
    ranked_candidates: list[dict] | None = None,
    items_by_source: dict | None = None,
) -> dict:
    resolved_url = url or f"https://example.com/{candidate_id}"
    if clusters is None:
        clusters = [
            {
                "cluster_id": f"cluster-{candidate_id}",
                "title": title,
                "candidate_ids": [candidate_id],
                "representative_ids": [candidate_id],
                "sources": sources or [query_source],
                "score": score,
            }
        ]
    if ranked_candidates is None:
        ranked_candidates = [
            {
                "candidate_id": candidate_id,
                "item_id": f"item-{candidate_id}",
                "source": query_source,
                "title": title,
                "url": resolved_url,
                "snippet": snippet,
                "sources": sources or [query_source],
                "source_items": [{"title": item, "url": resolved_url} for item in (source_titles or ["Reference 1"])],
                "final_score": score,
                "cluster_id": f"cluster-{candidate_id}",
            }
        ]
    return {
        "provider_runtime": {
            "reasoning_provider": "local",
            "planner_model": "deterministic",
            "rerank_model": "deterministic",
        },
        "clusters": clusters,
        "ranked_candidates": ranked_candidates,
        "items_by_source": items_by_source or {query_source: [{"item_id": f"item-{candidate_id}"}]},
        "errors_by_source": {},
        "warnings": [],
    }


class ConfigValidationTests(unittest.TestCase):
    def test_invalid_source_kind_raises(self) -> None:
        config = sample_config()
        config["sources"]["email"][0]["kind"] = "imap"
        with self.assertRaisesRegex(ValueError, "invalid source kind"):
            validate_config(config)

    def test_rule_without_source_ref_raises(self) -> None:
        config = sample_config()
        config["rule_sets"][0]["rules"][0]["source_id"] = ""
        with self.assertRaisesRegex(ValueError, "missing source ref"):
            validate_config(config)

    def test_duplicate_ruleset_id_raises(self) -> None:
        config = sample_config()
        config["rule_sets"].append({"id": "trading", "title": "Duplicate", "rules": []})
        with self.assertRaisesRegex(ValueError, "duplicate ruleset id: trading"):
            validate_config(config)

    def test_telegram_rule_without_stable_ids_raises(self) -> None:
        config = sample_config()
        config["sources"]["telegram"][0]["chat_id"] = ""
        with self.assertRaisesRegex(ValueError, "missing chat_id"):
            validate_config(config)

    def test_normalize_sets_five_minute_scheduler_default(self) -> None:
        config = sample_config()
        del config["scheduler"]["tick_seconds"]
        normalized = normalize_config(config)
        self.assertEqual(normalized["scheduler"]["tick_seconds"], 300)

    def test_external_rule_files_are_merged(self) -> None:
        config = sample_config()
        config["rule_sets"] = []
        config["rule_files"] = ["rules/*.json"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rules_dir = base / "rules"
            rules_dir.mkdir()
            (rules_dir / "trading.json").write_text(
                '{"rule_sets":[{"id":"market-watch","title":"Market Watch","enabled":true,"rules":[{"id":"r1","source_type":"email","source_id":"email-tradingview","enabled":true,"kind":"tradingview_user","from_email":"noreply@tradingview.com","tradingview_usernames":["AnalystA"]}]}]}',
                encoding="utf-8",
            )
            normalized = normalize_config(config, base_path=base)
        self.assertEqual(len(normalized["rule_sets"]), 1)
        self.assertEqual(normalized["rule_sets"][0]["id"], "market-watch")

    def test_external_rule_file_duplicate_ruleset_id_raises(self) -> None:
        config = sample_config()
        config["rule_files"] = ["rules/*.json"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rules_dir = base / "rules"
            rules_dir.mkdir()
            (rules_dir / "duplicate.json").write_text(
                '{"rule_sets":[{"id":"trading","title":"Duplicate","enabled":true,"rules":[]}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate ruleset id: trading"):
                normalize_config(config, base_path=base)

    def test_normalize_sets_last30days_defaults(self) -> None:
        normalized = normalize_config(sample_config())
        self.assertEqual(normalized["last30days"]["mode"], "compact")
        self.assertEqual(normalized["last30days"]["preset_id"], "world-radar-v1")
        self.assertEqual(normalized["last30days"]["max_items"], 10)
        self.assertEqual(len(normalized["last30days"]["query_bundle"]), 8)
        self.assertIn("personal-feed-v1", normalized["last30days"]["presets"])
        self.assertIn("platform-pulse-v1", normalized["last30days"]["presets"])

    def test_invalid_last30days_mode_raises(self) -> None:
        config = sample_config()
        config["last30days"] = {
            "mode": "deep",
            "schedule_expr": "0 7 * * *",
            "query_bundle": ["topic"],
            "telegram": {"topic_id": 0},
        }
        with self.assertRaisesRegex(ValueError, "last30days.mode"):
            validate_config(config)


class StartupLockRecoveryTests(unittest.TestCase):
    def test_interrupted_ruleset_locks_are_released_on_startup(self) -> None:
        redis = FakeRedis()
        redis.set("lock:signals:ruleset:trading-si", "interrupted-run")
        redis.set("lock:signals:last30days:personal-feed-v1", "keep")

        released = _recover_interrupted_ruleset_locks(
            redis,
            {"rule_sets": [{"id": "trading-si"}, {"id": "other"}]},
        )

        self.assertEqual(released, 1)
        self.assertIsNone(redis.get("lock:signals:ruleset:trading-si"))
        self.assertEqual(redis.get("lock:signals:last30days:personal-feed-v1"), "keep")


class SourceHealthTests(unittest.TestCase):
    def test_source_health_reports_stale_error_then_recovery(self) -> None:
        redis = FakeRedis()
        config = sample_config()
        source_id = "telegram-trader-speki"
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        stale_at = now - timedelta(minutes=20)
        state_store.set_dt(redis, state_store.source_last_success_key(source_id), stale_at)
        state_store.set_source_status(
            redis,
            source_id,
            {
                "ok": True,
                "last_attempt_at": stale_at.isoformat(),
                "last_error": None,
                "last_success_at": stale_at.isoformat(),
            },
        )

        health = _source_health(config, redis, now=now)
        self.assertFalse(health["ok"])
        self.assertEqual(health["sources"][source_id]["state"], "stale")

        state_store.set_dt(redis, state_store.source_last_success_key(source_id), now)
        state_store.set_source_status(
            redis,
            source_id,
            {
                "ok": True,
                "last_attempt_at": now.isoformat(),
                "last_error": None,
                "last_success_at": now.isoformat(),
            },
        )
        health = _source_health(config, redis, now=now)
        self.assertTrue(health["ok"])
        self.assertEqual(health["sources"][source_id]["state"], "healthy")

        state_store.set_source_status(
            redis,
            source_id,
            {
                "ok": False,
                "last_attempt_at": now.isoformat(),
                "last_error": "telethon_session_locked",
                "last_success_at": now.isoformat(),
            },
        )
        health = _source_health(config, redis, now=now)
        self.assertFalse(health["ok"])
        self.assertEqual(health["sources"][source_id]["state"], "error")


class TelethonSessionRetryTests(unittest.TestCase):
    def test_telegram_source_retries_database_lock_then_records_success(self) -> None:
        redis = FakeRedis()
        source = {"id": "telegram-trader-speki", "chat_id": -1001}
        ruleset = {"id": "trading"}
        client = Mock()
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.is_user_authorized = AsyncMock(return_value=True)
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)

        with patch("cron_bridge.build_telethon_client", return_value=client), patch(
            "cron_bridge.collect_telegram_candidates",
            new=AsyncMock(side_effect=[sqlite3.OperationalError("database is locked"), ([], ["matched=0"], 7)]),
        ) as collect_mock, patch("cron_bridge.telethon_session_lock", side_effect=lambda: nullcontext()), patch(
            "cron_bridge.time.sleep"
        ) as sleep_mock:
            candidates, tail = _run_telegram_source(
                r=redis,
                source=source,
                ruleset=ruleset,
                rules=[],
                lookback_minutes=None,
                now=now,
            )

        self.assertEqual(candidates, [])
        self.assertEqual(tail, ["matched=0"])
        self.assertEqual(collect_mock.await_count, 2)
        sleep_mock.assert_called_once_with(1)
        self.assertEqual(redis.get(state_store.source_cursor_key(source["id"])), "7")
        self.assertEqual(state_store.get_source_status(redis, source["id"])["last_error"], None)


class TelegramLookbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_lookback_excludes_old_messages_after_stalled_cursor(self) -> None:
        class FakeMessage:
            def __init__(self, message_id: int, text: str, date: datetime) -> None:
                self.id = message_id
                self.message = text
                self.date = date
                self.sender_id = 0
                self.post_author = ""
                self.sender = None
                self.video = None

        now = datetime(2026, 7, 14, 19, 0, tzinfo=timezone.utc)
        stale_but_unseen = FakeMessage(199, "старый #si", now - timedelta(hours=13))
        in_window = FakeMessage(200, "свежий #si", now - timedelta(hours=1))
        client = Mock()
        client.get_messages = AsyncMock(return_value=[in_window, stale_but_unseen])
        fake_types = types.SimpleNamespace(Message=FakeMessage)

        with patch.dict(sys.modules, {"telethon.tl.types": fake_types}):
            candidates, _, max_seen_id = await collect_telegram_candidates(
                client=client,
                source={"id": "telegram-trader-speki", "chat_id": -1001, "message_limit": 80},
                ruleset_id="trading",
                ruleset_title="Trading",
                rules=[{"id": "si", "kind": "hashtag", "hashtags": ["#si"]}],
                cursor=100,
                last_success=now - timedelta(days=4),
                lookback_minutes=12 * 60,
                now=now,
            )

        self.assertEqual([candidate.external_ref for candidate in candidates], ["-1001:200"])
        self.assertEqual(max_seen_id, 200)


class MatchingTests(unittest.TestCase):
    def test_extract_tradingview_username(self) -> None:
        self.assertEqual(extract_tradingview_username("Idea by @AnalystA"), "AnalystA")

    def test_extract_tradingview_username_from_russian_subject(self) -> None:
        self.assertEqual(
            extract_tradingview_username("Смотрите, новое мнение от Mamontiara"),
            "Mamontiara",
        )

    def test_extract_tradingview_username_from_russian_body(self) -> None:
        self.assertEqual(
            extract_tradingview_username(
                "TradingView\n\nMamontiara\n\nна которого вы подписаны, опубликовал(-а) новое мнение\n\nCNYRUB_TOM"
            ),
            "Mamontiara",
        )

    def test_email_tradingview_known_user_matches(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "New idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        self.assertIsNotNone(candidate)

    def test_email_tradingview_russian_subject_matches(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        rule["tradingview_usernames"] = ["Mamontiara"]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-ru-1",
                "timestamp": "2026-04-13T07:37:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Смотрите, новое мнение от Mamontiara",
                "preview": "",
                "text_excerpt": "CNYRUB_TOM",
            },
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.metadata["resolved_username"], "Mamontiara")

    def test_email_tradingview_russian_body_matches(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        rule["tradingview_usernames"] = ["Mamontiara"]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-ru-2",
                "timestamp": "2026-04-13T07:37:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Смотрите, новое мнение",
                "preview": "",
                "text_excerpt": "TradingView\n\nMamontiara\n\nна которого вы подписаны, опубликовал(-а) новое мнение\n\nCNYRUB_TOM",
            },
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.metadata["resolved_username"], "Mamontiara")

    def test_email_tradingview_unknown_user_ignored(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "New idea by @unknownauthor",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        self.assertIsNone(candidate)

    def test_email_tradingview_without_visible_username_ignored(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        rule["tradingview_usernames"] = ["Mamontiara", "vesperfin"]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-no-user",
                "timestamp": "2026-04-13T09:00:01+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Si 30m bullish RYGEL",
                "preview": "",
                "text_excerpt": "Si 30m bullish RYGEL 2026-04-13T09:00:01Z",
            },
        )
        self.assertIsNone(candidate)

    def test_non_tradingview_sender_ignored(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "Other",
                "from_email": "test@example.com",
                "sender_domain": "example.com",
                "subject": "New idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        self.assertIsNone(candidate)

    def test_email_window_prefers_extracted_body_over_preview(self) -> None:
        messages = _window_messages(
            thread={
                "subject": "Смотрите, новое мнение от Mamontiara",
                "preview": "Смотрите, новое мнение от Mamontiara",
                "messages": [
                    {
                        "message_id": "msg-body",
                        "thread_id": "thread-1",
                        "timestamp": "2026-04-14T14:01:00+00:00",
                        "from": "TradingView <noreply@tradingview.com>",
                        "subject": "Смотрите, новое мнение от Mamontiara",
                        "preview": "Смотрите, новое мнение от Mamontiara",
                        "extracted_text": "Фьючерс SI тестирует зону выноса. Сценарий: откат к 114000, затем продолжение.",
                    }
                ],
            },
            since_dt=datetime(2026, 4, 14, 13, 55, tzinfo=timezone.utc),
            until_dt=datetime(2026, 4, 14, 14, 5, tzinfo=timezone.utc),
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0]["text_excerpt"],
            "Фьючерс SI тестирует зону выноса. Сценарий: откат к 114000, затем продолжение.",
        )

    def test_email_window_extracts_tradingview_html_body_when_plain_text_missing(self) -> None:
        messages = _window_messages(
            thread={
                "subject": "Смотрите, новое мнение от Mamontiara",
                "preview": "Смотрите, новое мнение от Mamontiara",
                "messages": [
                    {
                        "message_id": "msg-html",
                        "thread_id": "thread-html",
                        "timestamp": "2026-04-16T13:57:00+00:00",
                        "from": "TradingView <noreply@tradingview.com>",
                        "subject": "Смотрите, новое мнение от Mamontiara",
                        "preview": "Смотрите, новое мнение от Mamontiara",
                        "content": {
                            "html": """
                                <div>TradingView</div>
                                <div>Mamontiara</div>
                                <div>на которого вы подписаны, опубликовал(-а) новое мнение</div>
                                <div>SBER</div>
                                <div>$SBER по феншую, индекс должен протестировать 2600-2650, а значит - рост могут притормозить.</div>
                                <button>Открыть мнение</button>
                            """
                        },
                    }
                ],
            },
            since_dt=datetime(2026, 4, 16, 13, 55, tzinfo=timezone.utc),
            until_dt=datetime(2026, 4, 16, 14, 5, tzinfo=timezone.utc),
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0]["text_excerpt"],
            "SBER\n$SBER по феншую, индекс должен протестировать 2600-2650, а значит - рост могут притормозить.",
        )
        self.assertEqual(messages[0]["delivery_text"], messages[0]["text_excerpt"])

    def test_telegram_hashtag_match(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][1]
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Трейдер",
                "message_id": 1,
                "sender_id": 10,
                "author": "Trader",
                "text": "Сегодня #si выглядит интересно",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_missing_hashtag_ignored(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][1]
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Трейдер",
                "message_id": 1,
                "sender_id": 10,
                "author": "Trader",
                "text": "Сегодня рынок выглядит интересно",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNone(candidate)

    def test_telegram_author_keywords_match(self) -> None:
        rule = {
            "id": "telegram-gukov-fx",
            "source_id": "telegram-trader-speki",
            "kind": "author_keywords",
            "sender_ids": [777],
            "keywords": ["юань", "валюта"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Example Trader Chat",
                "message_id": 2,
                "sender_id": 777,
                "author": "Example Author",
                "text": "По паре юань и валюте вижу интересный сетап",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_media_caption_hashtag_match(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][1]
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Трейдер",
                "message_id": 2,
                "sender_id": 10,
                "author": "Trader",
                "text": "Подпись к графику #si",
                "has_video": False,
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_author_keywords_match_sleng_si_and_yuashka_forms(self) -> None:
        rule = {
            "id": "telegram-gukov-fx",
            "source_id": "telegram-trader-speki",
            "kind": "author_keywords",
            "sender_ids": [777],
            "keywords": ["си", "юань", "cny"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Example Trader Chat",
                "message_id": 2,
                "sender_id": 777,
                "author": "Евгений Гуков",
                "text": "сиху чуть взял на отскок, юашку пока не трогал",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_author_keywords_other_author_ignored(self) -> None:
        rule = {
            "id": "telegram-gukov-fx",
            "source_id": "telegram-trader-speki",
            "kind": "author_keywords",
            "sender_ids": [777],
            "keywords": ["юань", "валюта"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Example Trader Chat",
                "message_id": 2,
                "sender_id": 778,
                "author": "Другой автор",
                "text": "По паре юань и валюте вижу интересный сетап",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNone(candidate)

    def test_telegram_content_keywords_video_match(self) -> None:
        rule = {
            "id": "bogdanoff-morning-evening-video",
            "source_id": "telegram-bogdanoff-invest",
            "kind": "content_keywords",
            "require_video": True,
            "keywords": ["утрен", "вечерн", "обзор"],
            "tags": ["video"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000001,
                "chat_name": "Example Market Channel",
                "message_id": 10,
                "sender_id": -1003000000001,
                "author": "Example Market Channel",
                "text": "Утренний обзор рынка",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": True,
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_content_keywords_require_video_ignored_without_video(self) -> None:
        rule = {
            "id": "bogdanoff-morning-evening-video",
            "source_id": "telegram-bogdanoff-invest",
            "kind": "content_keywords",
            "require_video": True,
            "keywords": ["утрен", "вечерн", "обзор"],
            "tags": ["video"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000001,
                "chat_name": "Example Market Channel",
                "message_id": 10,
                "sender_id": -1003000000001,
                "author": "Example Market Channel",
                "text": "Утренний обзор рынка",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": False,
            },
        )
        self.assertIsNone(candidate)

    def test_telegram_content_keywords_fx_match(self) -> None:
        rule = {
            "id": "artem-bendak-fx-cny-rub",
            "source_id": "telegram-artem-bendak-channel",
            "kind": "content_keywords",
            "keywords": ["юань", "cny", "рубл", "usd", "валют"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000002,
                "chat_name": "Example FX Channel",
                "message_id": 20,
                "sender_id": -1003000000002,
                "author": "Example FX Channel",
                "text": "Разбор пары юань-рубль и валютного рынка",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": False,
            },
        )
        self.assertIsNotNone(candidate)

    def test_keyword_matches_respects_word_boundaries_for_short_words(self) -> None:
        self.assertFalse(keyword_matches("Моя теория гласит, что рынок жив.", "си"))
        self.assertFalse(keyword_matches("Сейчас и мысли совсем о другом.", "си"))
        self.assertTrue(keyword_matches("По СИ вижу интересный сценарий.", "си"))
        self.assertTrue(keyword_matches("Сишка смотрится бодро.", "сишка"))
        self.assertTrue(keyword_matches("сиху чуть взял на отскок.", "си"))
        self.assertTrue(keyword_matches("юашку пока не трогал.", "юань"))

    def test_keyword_matches_yuan_inflections_without_partial_stem_match(self) -> None:
        text = "Откупила позу в юане по 11,500. Стоп под 11,276."
        for keyword in ("юань", "cny", "yuan"):
            self.assertTrue(keyword_matches(text, keyword))
        self.assertFalse(keyword_matches("Юанист обсуждает историю Китая.", "юань"))

    def test_telegram_content_keywords_short_word_inside_longer_word_ignored(self) -> None:
        rule = {
            "id": "artem-bendak-fx-cny-rub",
            "source_id": "telegram-artem-bendak-channel",
            "kind": "content_keywords",
            "keywords": ["си", "сишка"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000002,
                "chat_name": "Example FX Channel",
                "message_id": 21,
                "sender_id": -1003000000002,
                "author": "Example FX Channel",
                "text": "Моя теория гласит, что сейчас мысли про акции важнее.",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": False,
            },
        )
        self.assertIsNone(candidate)

    def test_ladytrader_fx_si_rule_matches_without_author_filter(self) -> None:
        rule = {
            "id": "ladytrader-vip-fx-si",
            "source_type": "telegram",
            "source_id": "telegram-ladytrader-vip",
            "enabled": True,
            "kind": "content_keywords",
            "keywords": ["си", "юань", "cnyrub", "usd/rub"],
            "tags": ["trading", "fx", "ladytrader"],
        }
        message = {
            "chat_id": -1003000000003,
            "chat_name": "LadyTraderVIP",
            "message_id": 22,
            "sender_id": 0,
            "author": "LadyTraderVIP",
            "text": "CNYRUB сохраняет ключевой уровень.",
            "timestamp": "2026-04-12T12:00:00+00:00",
            "has_video": False,
        }

        candidate = match_telegram_rule(
            ruleset_id="trading-si",
            ruleset_title="Trading Si",
            rule=rule,
            message=message,
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.rule_id, "ladytrader-vip-fx-si")
        self.assertEqual(candidate.tags, ["trading", "fx", "ladytrader"])

        message["text"] = "Откупила позу в юане по 11,500. Стоп под 11,276. Не ИИР."
        self.assertIsNotNone(
            match_telegram_rule(
                ruleset_id="trading-si",
                ruleset_title="Trading Si",
                rule=rule,
                message=message,
            )
        )

        message["text"] = "Обзор рынка акций без валютных инструментов."
        self.assertIsNone(
            match_telegram_rule(
                ruleset_id="trading-si",
                ruleset_title="Trading Si",
                rule=rule,
                message=message,
            )
        )

    def test_build_telegram_message_link_for_private_chat(self) -> None:
        self.assertEqual(
            build_telegram_message_link(chat_id=-1003000123456, message_id=1999),
            "https://t.me/c/3000123456/1999",
        )


class DeliveryAndStateTests(unittest.TestCase):
    def test_two_matches_fall_into_one_batch(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate1 = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        candidate2 = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-2",
                "timestamp": "2026-04-12T12:01:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Second chart update",
            },
        )
        batch = _local_fallback_batch(candidates=[candidate1, candidate2], topic_name="signals")
        self.assertEqual(len(batch.events), 2)

    def test_email_and_telegram_same_story_stay_separate(self) -> None:
        email_rule = sample_config()["rule_sets"][0]["rules"][0]
        tg_rule = sample_config()["rule_sets"][0]["rules"][1]
        email_candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=email_rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Про SI",
            },
        )
        tg_candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=tg_rule,
            message={
                "chat_id": -1001,
                "chat_name": "Трейдер",
                "message_id": 5,
                "sender_id": 99,
                "author": "Trader",
                "text": "Похожий взгляд на #si",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        batch = _local_fallback_batch(candidates=[email_candidate, tg_candidate], topic_name="signals")
        self.assertEqual([event.source_type for event in batch.events], ["email", "telegram"])

    def test_no_matches_means_no_events(self) -> None:
        batch = _local_fallback_batch(candidates=[], topic_name="signals")
        self.assertEqual(batch.events, [])

    def test_exact_dedup_blocks_duplicate_external_ref(self) -> None:
        r = FakeRedis()
        events = [
            SignalEvent(
                event_id="1",
                ruleset_id="trading",
                rule_id="rule",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:00+00:00",
                captured_at="2026-04-12T12:00:00+00:00",
                author="A",
                title="T1",
                summary="S1",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
            SignalEvent(
                event_id="2",
                ruleset_id="trading",
                rule_id="rule",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:01+00:00",
                captured_at="2026-04-12T12:00:01+00:00",
                author="A",
                title="T1",
                summary="S1",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
        ]
        ids = append_events(r, events, retention_days=14)
        self.assertEqual(len(ids), 1)

    def test_append_new_events_skips_existing_and_same_batch_duplicates(self) -> None:
        r = FakeRedis()
        events = [
            SignalEvent(
                event_id="1",
                ruleset_id="trading",
                rule_id="rule-a",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:00+00:00",
                captured_at="2026-04-12T12:00:00+00:00",
                author="A",
                title="T1",
                summary="S1",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
            SignalEvent(
                event_id="2",
                ruleset_id="trading",
                rule_id="rule-b",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:01+00:00",
                captured_at="2026-04-12T12:00:01+00:00",
                author="A",
                title="T1 duplicate",
                summary="S1 duplicate",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
            SignalEvent(
                event_id="3",
                ruleset_id="trading",
                rule_id="rule-c",
                source_type="telegram",
                source_id="source",
                external_ref="chat:2",
                occurred_at="2026-04-12T12:01:00+00:00",
                captured_at="2026-04-12T12:01:00+00:00",
                author="B",
                title="T2",
                summary="S2",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
        ]

        ids, appended, skipped = append_new_events(r, events, retention_days=14)
        self.assertEqual(len(ids), 2)
        self.assertEqual([event.external_ref for event in appended], ["chat:1", "chat:2"])
        self.assertEqual([event.external_ref for event in skipped], ["chat:1"])

        ids, appended, skipped = append_new_events(r, events, retention_days=14)
        self.assertEqual(ids, [])
        self.assertEqual(appended, [])
        self.assertEqual([event.external_ref for event in skipped], ["chat:1", "chat:1", "chat:2"])

    def test_overlap_window_uses_last_success_minus_grace(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        last_success = now - timedelta(minutes=5)
        since = resolve_telegram_window(
            source={"overlap_grace_minutes": 15},
            cursor=20,
            last_success=last_success,
            lookback_minutes=None,
            now=now,
        )
        self.assertEqual(since, last_success - timedelta(minutes=15))

    def test_stale_automatic_windows_do_not_backfill_history(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        stale_success = now - timedelta(hours=4)

        telegram_since = resolve_telegram_window(
            source={"overlap_grace_minutes": 15, "stale_after_minutes": 15},
            cursor=20,
            last_success=stale_success,
            lookback_minutes=None,
            now=now,
        )
        email_since, email_until = resolve_email_window(
            source={"lag_grace_minutes": 15, "stale_after_minutes": 15},
            last_success=stale_success,
            lookback_minutes=None,
            now=now,
        )

        self.assertEqual(telegram_since, now - timedelta(minutes=15))
        self.assertEqual(email_since, now - timedelta(minutes=15))
        self.assertEqual(email_until, now)

    def test_local_batch_preserves_telegram_link_and_email_excerpt(self) -> None:
        email_rule = sample_config()["rule_sets"][0]["rules"][0]
        tg_rule = sample_config()["rule_sets"][0]["rules"][1]
        email_candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=email_rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Full email excerpt about SI and setup",
            },
        )
        tg_candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=tg_rule,
            message={
                "chat_id": -1001,
                "chat_name": "Example Trader Chat",
                "message_id": 5,
                "sender_id": 99,
                "author": "Trader",
                "text": "Похожий взгляд на #si",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        batch = _local_fallback_batch(candidates=[email_candidate, tg_candidate], topic_name="signals")
        self.assertEqual(batch.events[0].source_excerpt, "Full email excerpt about SI and setup")
        self.assertEqual(batch.events[0].delivery_text, "Full email excerpt about SI and setup")
        self.assertEqual(batch.events[1].source_link, "https://t.me/c/1/5")
        self.assertEqual(batch.events[1].source_chat_id, -1001)
        self.assertEqual(batch.events[1].source_message_id, 5)
        self.assertEqual(batch.events[1].delivery_text, "Похожий взгляд на #si")

    def test_deliver_source_contexts_relays_telegram_and_email(self) -> None:
        telegram_event = SignalEvent(
            event_id="tg-1",
            ruleset_id="trading",
            rule_id="telegram-rule",
            source_type="telegram",
            source_id="telegram-trader-speki",
            external_ref="chat:5",
            occurred_at="2026-04-15T10:17:00+00:00",
            captured_at="2026-04-15T10:18:00+00:00",
            author="Trader",
            title="SI intraday update",
            summary="Short summary",
            source_link="https://t.me/c/1/5",
            source_excerpt="Короткий excerpt",
            delivery_text="Полный текст из Telegram",
            source_chat_id=-1001,
            source_message_id=5,
            tags=["si"],
            confidence=0.76,
        )
        email_event = SignalEvent(
            event_id="email-1",
            ruleset_id="trading",
            rule_id="email-rule",
            source_type="email",
            source_id="email-tradingview",
            external_ref="msg-1",
            occurred_at="2026-04-15T10:14:00+00:00",
            captured_at="2026-04-15T10:15:00+00:00",
            author="TradingView",
            title="Mamontiara",
            summary="Short summary",
            source_excerpt="Короткий excerpt",
            delivery_text="Полный текст письма",
            tags=["si"],
            confidence=0.76,
        )

        with patch("cron_bridge._relay_telegram_event", new=AsyncMock(return_value=True)) as telegram_mock, patch(
            "cron_bridge._relay_email_event",
            new=AsyncMock(return_value=True),
        ) as email_mock:
            delivered, attempted = asyncio.run(_deliver_source_contexts([telegram_event, email_event]))

        self.assertEqual((delivered, attempted), (2, 2))
        telegram_mock.assert_awaited_once_with(telegram_event)
        email_mock.assert_awaited_once_with(email_event)

    def test_relay_telegram_event_via_telethon_forwards_into_topic(self) -> None:
        class FakeForwardMessagesRequest:
            def __init__(self, **kwargs) -> None:
                self.from_peer = kwargs["from_peer"]
                self.id = kwargs["id"]
                self.to_peer = kwargs["to_peer"]
                self.top_msg_id = kwargs.get("top_msg_id")

        telegram_event = SignalEvent(
            event_id="tg-1",
            ruleset_id="trading",
            rule_id="telegram-rule",
            source_type="telegram",
            source_id="telegram-trader-speki",
            external_ref="chat:5",
            occurred_at="2026-04-15T10:17:00+00:00",
            captured_at="2026-04-15T10:18:00+00:00",
            author="Trader",
            title="SI intraday update",
            summary="Short summary",
            source_link="https://t.me/c/1/5",
            source_excerpt="Короткий excerpt",
            delivery_text="Полный текст из Telegram",
            source_chat_id=-1001,
            source_message_id=5,
            tags=["si"],
            confidence=0.76,
        )
        client = AsyncMock()
        client.connect = AsyncMock()
        client.is_user_authorized = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.get_messages = AsyncMock()
        client.send_message = AsyncMock()
        fake_telethon = types.SimpleNamespace(
            functions=types.SimpleNamespace(
                messages=types.SimpleNamespace(ForwardMessagesRequest=FakeForwardMessagesRequest)
            )
        )

        with patch("cron_bridge.build_telethon_client", return_value=client), patch("cron_bridge.SUPERGROUP_ID", -100555), patch(
            "cron_bridge.TOPIC_ID",
            414,
        ), patch.dict(sys.modules, {"telethon": fake_telethon}):
            delivered = asyncio.run(_relay_telegram_event_via_telethon(telegram_event))

        self.assertTrue(delivered)
        client.assert_awaited_once()
        request = client.await_args.args[0]
        self.assertEqual(request.from_peer, -1001)
        self.assertEqual(request.id, [5])
        self.assertEqual(request.to_peer, -100555)
        self.assertEqual(request.top_msg_id, 414)
        client.get_messages.assert_not_awaited()
        client.send_message.assert_not_awaited()
        client.disconnect.assert_awaited_once()

    def test_relay_telegram_event_via_telethon_resends_message_object_when_forward_fails(self) -> None:
        class FakeForwardMessagesRequest:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        telegram_event = SignalEvent(
            event_id="tg-1",
            ruleset_id="trading",
            rule_id="telegram-rule",
            source_type="telegram",
            source_id="telegram-trader-speki",
            external_ref="chat:5",
            occurred_at="2026-04-15T10:17:00+00:00",
            captured_at="2026-04-15T10:18:00+00:00",
            author="Trader",
            title="SI intraday update",
            summary="Short summary",
            source_link="https://t.me/c/1/5",
            source_excerpt="Короткий excerpt",
            delivery_text="Полный текст из Telegram",
            source_chat_id=-1001,
            source_message_id=5,
            tags=["si"],
            confidence=0.76,
        )
        source_message = types.SimpleNamespace(id=5, message="Полный текст из Telegram", entities=["keep-links"], media=object())
        client = AsyncMock(side_effect=RuntimeError("copy blocked"))
        client.connect = AsyncMock()
        client.is_user_authorized = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        client.get_messages = AsyncMock(return_value=source_message)
        client.send_message = AsyncMock(return_value=object())
        fake_telethon = types.SimpleNamespace(
            functions=types.SimpleNamespace(
                messages=types.SimpleNamespace(ForwardMessagesRequest=FakeForwardMessagesRequest)
            )
        )

        with patch("cron_bridge.build_telethon_client", return_value=client), patch("cron_bridge.SUPERGROUP_ID", -100555), patch(
            "cron_bridge.TOPIC_ID",
            414,
        ), patch.dict(sys.modules, {"telethon": fake_telethon}), patch(
            "cron_bridge.post_plain_text_message",
            new=AsyncMock(return_value=True),
        ) as plain_mock:
            delivered = asyncio.run(_relay_telegram_event_via_telethon(telegram_event))

        self.assertTrue(delivered)
        client.get_messages.assert_awaited_once_with(-1001, ids=5)
        client.send_message.assert_awaited_once_with(-100555, source_message, reply_to=414)
        plain_mock.assert_not_awaited()
        client.disconnect.assert_awaited_once()

    def test_render_batch_prefers_source_text_for_email_and_telegram(self) -> None:
        text = render_batch(
            ruleset_title="Trading SI",
            model_meta=ModelMeta(model_id="local", tier="light"),
            events=[
                SignalEvent(
                    event_id="email-1",
                    ruleset_id="trading-si",
                    rule_id="email-rule",
                    source_type="email",
                    source_id="email-tradingview",
                    external_ref="msg-1",
                    occurred_at="2026-04-13T07:37:00+00:00",
                    captured_at="2026-04-13T07:38:00+00:00",
                    author="TradingView",
                    title="Mamontiara SI Trend Analysis",
                    summary="TradingView signal about SI trend reversal detected",
                    source_excerpt="CNYRUB_TOM\nMamontiara ожидает разворот тренда по SI.",
                    tags=["si", "fx"],
                    confidence=0.8,
                ),
                SignalEvent(
                    event_id="tg-1",
                    ruleset_id="trading-si",
                    rule_id="telegram-rule",
                    source_type="telegram",
                    source_id="telegram-trader-speki",
                    external_ref="chat:5",
                    occurred_at="2026-04-13T07:40:00+00:00",
                    captured_at="2026-04-13T07:41:00+00:00",
                    author="Trader",
                    title="SI intraday update",
                    summary="Short AI summary should not be primary",
                    source_excerpt="Сам текст сигнала по #si с уровнями и сценарием.",
                    source_link="https://t.me/c/1/5",
                    tags=["si"],
                    confidence=0.76,
                ),
            ],
        )

        self.assertIn("Mamontiara ожидает разворот тренда по SI.", text)
        self.assertIn("Сам текст сигнала по #si с уровнями и сценарием.", text)
        self.assertNotIn("Текст письма:", text)
        self.assertNotIn("Short AI summary should not be primary", text)
        self.assertIn("https://t.me/c/1/5", text)


class Last30DaysDigestTests(unittest.TestCase):
    @patch("last30days_runner.subprocess.run")
    def test_build_digest_merges_queries_and_keeps_partial_failures(self, mock_run) -> None:
        payload = last30days_payload(
            title="Theme 1",
            query_source="x",
            sources=["reddit", "x"],
            source_titles=["Reference 1"],
        )
        payload["items_by_source"] = {"reddit": [{"item_id": "item-1"}], "x": [{"item_id": "item-2"}]}
        payload["errors_by_source"] = {"youtube": "timeout"}

        success = Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        failure = Mock(returncode=1, stdout="", stderr="provider error")
        empty_hn = Mock(returncode=0, stdout=json.dumps({"clusters": [], "ranked_candidates": [], "items_by_source": {}, "errors_by_source": {}}), stderr="")
        # 4 main queries + 7 HN companion queries (parallel, any order)
        mock_run.side_effect = [success, failure, success, success, *([empty_hn] * 7)]

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = ["topic-1", "topic-2", "topic-3", "topic-4"]
        digest = build_digest(
            config,
            preset_id="world-radar-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(digest.total_queries, 4)
        self.assertEqual(digest.successful_queries, 3)
        self.assertEqual(digest.status, "partial")
        self.assertEqual(digest.profile, "personal-feed")
        self.assertEqual(digest.canonical_preset_id, "personal-feed-v1")
        self.assertTrue(digest.themes)
        self.assertTrue(digest.global_themes)
        self.assertTrue(digest.category_sections)
        self.assertIn("youtube", digest.errors_by_source)
        self.assertEqual(digest.themes[0].title, "Theme 1")

    @patch("last30days_runner.subprocess.run")
    def test_build_digest_uses_rescue_queries_after_empty_composite_result(self, mock_run) -> None:
        empty = {
            "provider_runtime": {
                "reasoning_provider": "local",
                "planner_model": "deterministic",
                "rerank_model": "deterministic",
            },
            "clusters": [],
            "ranked_candidates": [],
            "items_by_source": {"reddit": [], "hackernews": []},
            "errors_by_source": {},
            "warnings": ["No candidates survived retrieval and ranking."],
        }
        rescue = last30days_payload(
            title="OpenAI ships a new frontier model",
            query_source="hackernews",
            candidate_id="openai-1",
            url="https://example.com/openai-launch",
            snippet="OpenAI ships a new frontier model and pushes pricing changes across the market.",
            sources=["hackernews"],
            source_titles=["HN reference"],
        )

        def fake_run(cmd, **kwargs):
            query = cmd[2]
            payload = rescue if query == "OpenAI" else empty
            return Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        mock_run.side_effect = fake_run

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = ["OpenAI Anthropic Google DeepMind xAI Nvidia Apple Microsoft product launches AI research breakthroughs"]
        digest = build_digest(
            config,
            preset_id="world-radar-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(digest.status, "ok")
        self.assertTrue(digest.themes)
        self.assertEqual(digest.themes[0].title, "OpenAI ships a new frontier model")
        self.assertEqual(digest.themes[0].category, "Big Tech & AI")
        self.assertGreaterEqual(digest.source_counts["hn"], 1)
        first_report = digest.reports[0]
        self.assertIn("rescue_queries", first_report)
        self.assertIn("OpenAI", first_report["rescue_queries"])

    @patch("last30days_runner.subprocess.run")
    def test_build_digest_passes_github_repo_hints_for_top_queries(self, mock_run) -> None:
        payload = last30days_payload(title="MCP ecosystem accelerates")
        payload["clusters"] = []
        payload["ranked_candidates"] = []
        payload["items_by_source"] = {}
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = ["open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks"]
        digest = build_digest(
            config,
            preset_id="world-radar-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(digest.total_queries, 1)
        repo_args = []
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            if "--github-repo" in cmd:
                idx = cmd.index("--github-repo")
                repo_args.append(cmd[idx + 1])
        self.assertTrue(repo_args)
        self.assertTrue(any("openclaw/openclaw" in arg for arg in repo_args))
        self.assertTrue(any("modelcontextprotocol/servers" in arg for arg in repo_args))

    @patch("last30days_runner.subprocess.run")
    def test_build_digest_applies_source_and_category_caps(self, mock_run) -> None:
        big_tech_clusters = []
        big_tech_candidates = []
        for index in range(5):
            candidate_id = f"bigtech-{index}"
            big_tech_clusters.append(
                {
                    "cluster_id": f"cluster-{candidate_id}",
                    "title": f"OpenAI headline {index}",
                    "candidate_ids": [candidate_id],
                    "representative_ids": [candidate_id],
                    "sources": ["x"],
                    "score": 99.0 - index,
                }
            )
            big_tech_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "item_id": f"item-{candidate_id}",
                    "source": "x",
                    "title": f"OpenAI headline {index}",
                    "url": f"https://example.com/openai-{index}",
                    "snippet": "OpenAI changes the market with a meaningful product move and broad ecosystem impact.",
                    "sources": ["x"],
                    "source_items": [{"title": f"Reference {index}", "url": f"https://example.com/openai-{index}"}],
                    "final_score": 99.0 - index,
                    "cluster_id": f"cluster-{candidate_id}",
                }
            )
        consumer_payload = last30days_payload(
            title="TikTok changes ranking logic",
            query_source="x",
            candidate_id="consumer-1",
            snippet="TikTok ships a major ranking change that affects creators and consumer behavior globally.",
        )
        creator_payload = last30days_payload(
            title="Runway expands creator workflow stack",
            query_source="youtube",
            candidate_id="creator-1",
            snippet="Runway expands creator workflow stack with new video-generation and editing capabilities.",
            sources=["youtube"],
            source_titles=["Creator reference"],
        )

        def fake_run(cmd, **kwargs):
            query = cmd[2]
            if query == "OpenAI Anthropic Google Meta xAI Nvidia Apple Microsoft Amazon launches product roadmap":
                payload = last30days_payload(
                    title="unused",
                    clusters=big_tech_clusters,
                    ranked_candidates=big_tech_candidates,
                    items_by_source={"x": [{"item_id": item["item_id"]} for item in big_tech_candidates]},
                )
                return Mock(returncode=0, stdout=json.dumps(payload), stderr="")
            if query == "X TikTok YouTube Instagram Reddit Bluesky consumer apps platform changes viral products":
                return Mock(returncode=0, stdout=json.dumps(consumer_payload), stderr="")
            if query == "creator economy Veo Runway Pika Sora Midjourney YouTube media workflows":
                return Mock(returncode=0, stdout=json.dumps(creator_payload), stderr="")
            empty = last30days_payload(title="unused")
            empty["clusters"] = []
            empty["ranked_candidates"] = []
            empty["items_by_source"] = {}
            return Mock(returncode=0, stdout=json.dumps(empty), stderr="")

        mock_run.side_effect = fake_run

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = [
            "OpenAI Anthropic Google Meta xAI Nvidia Apple Microsoft Amazon launches product roadmap",
            "X TikTok YouTube Instagram Reddit Bluesky consumer apps platform changes viral products",
            "creator economy Veo Runway Pika Sora Midjourney YouTube media workflows",
        ]
        digest = build_digest(
            config,
            preset_id="world-radar-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )

        x_count = len([theme for theme in digest.themes if theme.primary_source == "x"])
        big_tech_count = len([theme for theme in digest.themes if theme.category == "Big Tech & AI"])
        self.assertLessEqual(x_count, 4)
        self.assertLessEqual(big_tech_count, 3)
        self.assertTrue(any(section.category == "Creator / Media" for section in digest.category_sections))

    def test_renderers_output_world_radar_sections(self) -> None:
        theme = Last30DaysTheme(
            theme_id="theme-1",
            title="OpenAI launches new model",
            snippet="OpenAI launches a new model and resets pricing expectations across the market.",
            url="https://example.com/openai",
            sources=["x"],
            queries=["OpenAI Anthropic Google Meta xAI Nvidia Apple Microsoft Amazon launches product roadmap"],
            score=95.0,
            source_titles=["Reference 1"],
            category="Big Tech & AI",
            primary_source="x",
            global_score=110.0,
            global_rank=1,
            category_rank=1,
        )
        digest = Last30DaysDigest(
            preset_id="world-radar-v1",
            mode="compact",
            generated_at="2026-04-12T04:00:00+00:00",
            topic_name="last30daysTrend",
            topic_id=414,
            query_bundle=["topic"],
            themes=[theme],
            global_themes=[theme],
            category_sections=[Last30DaysCategorySection(category="Big Tech & AI", themes=[theme])],
            source_counts={"x": 5},
            successful_queries=8,
            total_queries=8,
        )

        telegram_text = render_last30days_digest(digest)
        markdown_text = _render_expanded_markdown(digest, datetime(2026, 4, 12, 7, 0, tzinfo=timezone.utc))

        self.assertIn("Personal Feed", telegram_text)
        self.assertIn("🤖", telegram_text)
        self.assertIn("Big Tech &amp; AI", telegram_text)
        self.assertIn("OpenAI launches new model", telegram_text)
        self.assertIn("## Global Top Themes", markdown_text)
        self.assertIn("## Category Sections", markdown_text)


class RadarRedesignTests(unittest.TestCase):
    """Tests for the radar redesign: source priority, quality bonuses, per-source caps, platform_sources."""

    # ── _build_platform_args ──────────────────────────────────────────────────

    def test_build_platform_args_includes_search_flag(self) -> None:
        from last30days_runner import _build_platform_args, _DEFAULT_SEARCH_SOURCES

        # --search is always emitted (enables all sources, not just X)
        args = _build_platform_args({})
        self.assertIn("--search", args)
        idx = args.index("--search")
        self.assertEqual(args[idx + 1], _DEFAULT_SEARCH_SOURCES)

    def test_build_platform_args_custom_search(self) -> None:
        from last30days_runner import _build_platform_args

        args = _build_platform_args({"search": "x,reddit,youtube"})
        idx = args.index("--search")
        self.assertEqual(args[idx + 1], "x,reddit,youtube")

    def test_build_platform_args_reddit_subreddits(self) -> None:
        from last30days_runner import _build_platform_args

        # Correct flag is --subreddits (not --reddit-sub)
        args = _build_platform_args({"reddit": {"feeds": ["worldnews", "technology"]}})
        self.assertIn("--subreddits", args)
        idx = args.index("--subreddits")
        self.assertIn("worldnews", args[idx + 1])
        self.assertIn("technology", args[idx + 1])

    def test_build_platform_args_does_not_include_github(self) -> None:
        from last30days_runner import _build_platform_args

        args = _build_platform_args({"github": {"repos": ["owner/repo"], "trending": True}})
        self.assertNotIn("--github-repo", args)

    def test_build_platform_args_no_unsupported_flags(self) -> None:
        from last30days_runner import _build_platform_args

        # These flags don't exist in the external script
        args = _build_platform_args({"hn": {"feeds": ["frontpage"]}, "youtube": {"search_terms": ["AI"]}, "bluesky": {"starter_packs": ["x"]}})
        self.assertNotIn("--hn-feed", args)
        self.assertNotIn("--youtube-search", args)
        self.assertNotIn("--bluesky-pack", args)

    # ── _build_github_repos ───────────────────────────────────────────────────

    def test_build_github_repos_merges_hints_and_platform_sources(self) -> None:
        from last30days_runner import _build_github_repos

        platform = {"github": {"repos": ["new-org/new-repo"], "trending": False}}
        repos = _build_github_repos(
            "open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks",
            platform,
        )
        self.assertIn("openclaw/openclaw", repos)          # from GITHUB_REPO_HINTS
        self.assertIn("modelcontextprotocol/servers", repos)
        self.assertIn("new-org/new-repo", repos)            # from platform_sources

    def test_build_github_repos_deduplicates(self) -> None:
        from last30days_runner import _build_github_repos

        platform = {"github": {"repos": ["openclaw/openclaw"], "trending": False}}
        repos = _build_github_repos(
            "open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks",
            platform,
        )
        self.assertEqual(repos.count("openclaw/openclaw"), 1)

    def test_build_github_repos_trending_flag(self) -> None:
        from last30days_runner import _build_github_repos

        repos = _build_github_repos("some query", {"github": {"repos": [], "trending": True}})
        self.assertIn("trending", repos)

    def test_build_github_repos_no_platform_sources(self) -> None:
        from last30days_runner import _build_github_repos

        repos = _build_github_repos(
            "open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks",
            {},
        )
        self.assertIn("openclaw/openclaw", repos)

    # ── Source priority (hn > web > reddit > ... > x) ────────────────────────

    def test_primary_source_prefers_hn_over_x(self) -> None:
        from last30days_runner import _primary_source

        theme = {"sources": ["x", "hn", "web"]}
        self.assertEqual(_primary_source(theme), "hn")

    def test_primary_source_prefers_web_over_x(self) -> None:
        from last30days_runner import _primary_source

        theme = {"sources": ["x", "web"]}
        self.assertEqual(_primary_source(theme), "web")

    def test_primary_source_prefers_reddit_over_x(self) -> None:
        from last30days_runner import _primary_source

        theme = {"sources": ["x", "reddit"]}
        self.assertEqual(_primary_source(theme), "reddit")

    def test_primary_source_x_only(self) -> None:
        from last30days_runner import _primary_source

        theme = {"sources": ["x"]}
        self.assertEqual(_primary_source(theme), "x")

    # ── Quality bonus in _world_score ─────────────────────────────────────────

    def test_world_score_quality_bonus_for_hn(self) -> None:
        from last30days_runner import _world_score

        hn_theme = {
            "score": 80.0,
            "sources": ["hn"],
            "queries": ["q1"],
            "category": "Big Tech & AI",
            "primary_source": "hn",
            "source_titles": ["HN ref"],
            "title": "Some HN title",
            "snippet": "A solid long snippet that exceeds 40 characters easily.",
            "url": "https://example.com/hn",
        }
        x_theme = dict(hn_theme)
        x_theme["sources"] = ["x"]
        x_theme["primary_source"] = "x"
        x_theme["title"] = "@SomeTweet with short text"

        hn_score = _world_score(hn_theme)
        x_score = _world_score(x_theme)
        self.assertGreater(hn_score, x_score)

    def test_world_score_multi_quality_bonus(self) -> None:
        from last30days_runner import _world_score

        multi = {
            "score": 80.0,
            "sources": ["hn", "web", "youtube"],
            "queries": ["q1"],
            "category": "Big Tech & AI",
            "primary_source": "hn",
            "source_titles": ["ref"],
            "title": "Multi-source story",
            "snippet": "Snippet long enough to not get penalized at all here.",
            "url": "https://example.com/multi",
        }
        single = dict(multi)
        single["sources"] = ["hn"]

        self.assertGreater(_world_score(multi), _world_score(single))

    # ── Context penalties ─────────────────────────────────────────────────────

    def test_context_penalty_tweet_title(self) -> None:
        from last30days_runner import _context_penalty

        tweet = {"title": "@SomeUser This is a tweet", "url": "https://x.com/user/status/1", "sources": ["x"], "source_titles": [], "snippet": "Short."}
        normal = {"title": "A proper article headline", "url": "https://example.com/article", "sources": ["web"], "source_titles": ["ref"], "snippet": "A snippet that is long enough."}
        self.assertGreater(_context_penalty(tweet), _context_penalty(normal))

    def test_context_penalty_no_url(self) -> None:
        from last30days_runner import _context_penalty

        no_url = {"title": "Some title", "url": "", "sources": ["hn"], "source_titles": ["ref"], "snippet": "A nice snippet that is long enough."}
        with_url = dict(no_url)
        with_url["url"] = "https://example.com"
        self.assertGreater(_context_penalty(no_url), _context_penalty(with_url))

    def test_context_penalty_short_snippet(self) -> None:
        from last30days_runner import _context_penalty

        short = {"title": "Some title", "url": "https://example.com", "sources": ["web"], "source_titles": ["ref"], "snippet": "Too short"}
        long = dict(short)
        long["snippet"] = "This is a proper snippet with enough characters to avoid the short penalty."
        self.assertGreater(_context_penalty(short), _context_penalty(long))

    # ── Per-source caps (_SOURCE_CAPS) ────────────────────────────────────────

    def test_x_source_cap_is_two(self) -> None:
        from last30days_runner import _SOURCE_CAPS
        self.assertEqual(_SOURCE_CAPS["x"], 2)

    def test_hn_source_cap_is_five(self) -> None:
        from last30days_runner import _SOURCE_CAPS
        self.assertEqual(_SOURCE_CAPS["hn"], 5)

    @patch("last30days_runner.subprocess.run")
    def test_x_capped_at_two_in_digest(self, mock_run) -> None:
        """x-sourced themes must not exceed _SOURCE_CAPS["x"] = 2 in global themes."""
        clusters = []
        candidates = []
        for i in range(6):
            cid = f"x-theme-{i}"
            clusters.append({"cluster_id": f"c-{cid}", "title": f"X headline {i}", "candidate_ids": [cid], "representative_ids": [cid], "sources": ["x"], "score": 90.0 - i})
            candidates.append({"candidate_id": cid, "item_id": f"item-{cid}", "source": "x", "title": f"X headline {i}", "url": f"https://x.com/{i}", "snippet": "Some tweet content that might be a bit short.", "sources": ["x"], "source_items": [{"title": f"Ref {i}", "url": f"https://x.com/{i}"}], "final_score": 90.0 - i, "cluster_id": f"c-{cid}"})

        payload = last30days_payload(title="unused", clusters=clusters, ranked_candidates=candidates, items_by_source={"x": [{"item_id": c["item_id"]} for c in candidates]})
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = ["some query"]
        digest = build_digest(config, preset_id="world-radar-v1", now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc))

        x_count = sum(1 for t in digest.global_themes if t.primary_source == "x")
        self.assertLessEqual(x_count, 2)

    # ── platform_sources passed to subprocess ─────────────────────────────────

    @patch("last30days_runner.subprocess.run")
    def test_platform_sources_reddit_rss_passed_to_subprocess(self, mock_run) -> None:
        payload = last30days_payload(title="World event")
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = ["world news query"]
        config["last30days"]["platform_sources"] = {
            "reddit": {"feeds": ["worldnews", "geopolitics"]}
        }
        build_digest(config, preset_id="world-radar-v1", now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc))

        all_cmds = [call[0][0] for call in mock_run.call_args_list]
        # --search should always be present
        self.assertTrue(any("--search" in cmd for cmd in all_cmds), "Expected --search in subprocess calls")
        # --subreddits (correct flag, not --reddit-sub)
        reddit_args = [cmd[cmd.index("--subreddits") + 1] for cmd in all_cmds if "--subreddits" in cmd]
        self.assertTrue(reddit_args, "Expected --subreddits in subprocess calls")
        self.assertTrue(any("worldnews" in arg for arg in reddit_args))
        self.assertTrue(any("geopolitics" in arg for arg in reddit_args))

    @patch("last30days_runner.subprocess.run")
    def test_platform_sources_github_merged_with_hints(self, mock_run) -> None:
        payload = last30days_payload(title="OSS story")
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = ["open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks"]
        config["last30days"]["platform_sources"] = {
            "github": {"repos": ["extra-org/extra-repo"], "trending": False}
        }
        build_digest(config, preset_id="world-radar-v1", now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc))

        all_cmds = [call[0][0] for call in mock_run.call_args_list]
        repo_args = [cmd[cmd.index("--github-repo") + 1] for cmd in all_cmds if "--github-repo" in cmd]
        self.assertTrue(repo_args)
        # Both GITHUB_REPO_HINTS and platform_sources repos should appear
        combined = ",".join(repo_args)
        self.assertIn("openclaw/openclaw", combined)
        self.assertIn("extra-org/extra-repo", combined)

    # ── Telegram render (new radar format) ────────────────────────────────────

    def test_render_shows_radar_header_with_date(self) -> None:
        theme = Last30DaysTheme(theme_id="t1", title="AI story", snippet="Good snippet about AI topic.", url="https://example.com", sources=["hn"], queries=["q"], score=90.0, category="Big Tech & AI", primary_source="hn", global_score=100.0, global_rank=1, category_rank=1)
        digest = Last30DaysDigest(preset_id="world-radar-v1", mode="compact", generated_at="2026-04-13T04:00:00+00:00", topic_name="last30daysTrend", topic_id=1, query_bundle=["q"], themes=[theme], global_themes=[theme], category_sections=[Last30DaysCategorySection(category="Big Tech & AI", themes=[theme])], source_counts={"hn": 10}, successful_queries=8, total_queries=8)
        text = render_last30days_digest(digest)
        self.assertIn("🌍", text)
        self.assertIn("Personal Feed", text)
        self.assertIn("<code>personal-feed</code>", text)
        self.assertIn("13", text)  # day in date

    def test_render_category_emoji_present(self) -> None:
        theme = Last30DaysTheme(theme_id="t1", title="Market move", snippet="Markets react to Fed decision.", url="https://example.com", sources=["web"], queries=["q"], score=90.0, category="Markets / Regulation / Geopolitics", primary_source="web", global_score=100.0, global_rank=1, category_rank=1)
        digest = Last30DaysDigest(preset_id="world-radar-v1", mode="compact", generated_at="2026-04-13T04:00:00+00:00", topic_name="last30daysTrend", topic_id=1, query_bundle=["q"], themes=[theme], global_themes=[theme], category_sections=[Last30DaysCategorySection(category="Markets / Regulation / Geopolitics", themes=[theme])], source_counts={"web": 5}, successful_queries=8, total_queries=8)
        text = render_last30days_digest(digest)
        self.assertIn("📈", text)

    def test_render_shows_reddit_errors(self) -> None:
        theme = Last30DaysTheme(theme_id="t1", title="Story", snippet="Some story snippet here.", url="https://example.com", sources=["hn"], queries=["q"], score=90.0, category="Big Tech & AI", primary_source="hn", global_score=100.0, global_rank=1, category_rank=1)
        digest = Last30DaysDigest(preset_id="world-radar-v1", mode="compact", generated_at="2026-04-13T04:00:00+00:00", topic_name="last30daysTrend", topic_id=1, query_bundle=["q"], themes=[theme], global_themes=[theme], category_sections=[Last30DaysCategorySection(category="Big Tech & AI", themes=[theme])], source_counts={"hn": 5}, errors_by_source={"reddit": "API access denied", "youtube": "rate limited"}, successful_queries=8, total_queries=8)
        text = render_last30days_digest(digest)
        self.assertIn("reddit", text)
        self.assertIn("youtube", text)

    def test_render_shows_source_badge(self) -> None:
        theme = Last30DaysTheme(theme_id="t1", title="HN story", snippet="A good long snippet that should appear.", url="https://example.com", sources=["hn", "web"], queries=["q"], score=90.0, category="Open Source / Builders", primary_source="hn", global_score=100.0, global_rank=1, category_rank=1)
        digest = Last30DaysDigest(preset_id="world-radar-v1", mode="compact", generated_at="2026-04-13T04:00:00+00:00", topic_name="last30daysTrend", topic_id=1, query_bundle=["q"], themes=[theme], global_themes=[theme], category_sections=[Last30DaysCategorySection(category="Open Source / Builders", themes=[theme])], source_counts={"hn": 5}, successful_queries=8, total_queries=8)
        text = render_last30days_digest(digest)
        self.assertIn("[hn · web]", text)

    def test_render_up_to_four_themes_per_category(self) -> None:
        themes = [Last30DaysTheme(theme_id=f"t{i}", title=f"Story {i}", snippet="A proper snippet for this story.", url=f"https://example.com/{i}", sources=["hn"], queries=["q"], score=90.0 - i, category="Big Tech & AI", primary_source="hn", global_score=100.0 - i, global_rank=i + 1, category_rank=i + 1) for i in range(6)]
        digest = Last30DaysDigest(preset_id="world-radar-v1", mode="compact", generated_at="2026-04-13T04:00:00+00:00", topic_name="last30daysTrend", topic_id=1, query_bundle=["q"], themes=themes[:4], global_themes=themes, category_sections=[Last30DaysCategorySection(category="Big Tech & AI", themes=themes)], source_counts={"hn": 20}, successful_queries=8, total_queries=8)
        text = render_last30days_digest(digest)
        self.assertIn("4.", text)
        self.assertNotIn("5.", text)

    def test_render_platform_pulse_groups_by_platform(self) -> None:
        reddit_theme = Last30DaysTheme(
            theme_id="r1",
            title="Humanoid robot half-marathon in China",
            snippet="Reddit discusses the coming humanoid robot half-marathon and how autonomous the field really is.",
            url="https://reddit.example/1",
            sources=["reddit"],
            queries=["robotics"],
            score=90.0,
            category="Science / Hardware",
            primary_source="reddit",
            global_score=100.0,
            global_rank=1,
        )
        x_theme = Last30DaysTheme(
            theme_id="x1",
            title="Meta ramps AI spending again",
            snippet="X is full of posts about Meta spending aggressively to catch OpenAI and Google.",
            url="https://x.example/1",
            sources=["x"],
            queries=["ai labs"],
            score=88.0,
            category="Big Tech & AI",
            primary_source="x",
            global_score=98.0,
            global_rank=2,
        )
        digest = Last30DaysDigest(
            preset_id="platform-pulse-v1",
            canonical_preset_id="platform-pulse-v1",
            profile="platform-pulse",
            display_name="Platform Pulse",
            mode="compact",
            generated_at="2026-04-13T04:00:00+00:00",
            topic_name="platformPulse",
            topic_id=1,
            query_bundle=["ai labs", "robotics"],
            core_sources=["reddit", "x"],
            experimental_sources=["github"],
            themes=[reddit_theme, x_theme],
            global_themes=[reddit_theme, x_theme],
            platform_sections=[
                Last30DaysPlatformSection(platform="reddit", post_count=12, themes=[reddit_theme]),
                Last30DaysPlatformSection(platform="x", post_count=9, themes=[x_theme]),
            ],
            source_counts={"reddit": 12, "x": 9},
            successful_queries=2,
            total_queries=2,
        )
        text = render_last30days_digest(digest)
        markdown_text = _render_expanded_markdown(digest, datetime(2026, 4, 13, 7, 0, tzinfo=timezone.utc))
        self.assertIn("Platform Pulse", text)
        self.assertIn("<code>platform-pulse</code>", text)
        self.assertIn("Reddit", text)
        self.assertIn("(12 posts)", text)
        self.assertIn("Humanoid robot half-marathon in China", text)
        self.assertIn("https://reddit.example/1", text)
        self.assertIn("## Platform Sections", markdown_text)
        self.assertIn("### reddit (12 posts)", markdown_text)

    @patch("last30days_runner.subprocess.run")
    def test_platform_pulse_renders_all_platform_sections_and_normalizes_hn(self, mock_run) -> None:
        reddit_payload = last30days_payload(
            title="Humanoid robot half-marathon in China",
            query_source="reddit",
            candidate_id="reddit-1",
            url="https://reddit.example/1",
            snippet="Reddit discusses the coming humanoid robot half-marathon and how autonomous the field really is.",
            sources=["reddit"],
            source_titles=["Reddit ref"],
        )
        x_payload = last30days_payload(
            title="Meta ramps AI spending again",
            query_source="x",
            candidate_id="x-1",
            url="https://x.example/1",
            snippet="X is full of posts about Meta spending aggressively to catch OpenAI and Google.",
            sources=["x"],
            source_titles=["X ref"],
        )

        def fake_run(cmd, **kwargs):
            query = cmd[2]
            if query == "ai labs":
                return Mock(returncode=0, stdout=json.dumps(reddit_payload), stderr="")
            if query == "robotics":
                return Mock(returncode=0, stdout=json.dumps(x_payload), stderr="")
            return Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "provider_runtime": {
                            "reasoning_provider": "local",
                            "planner_model": "deterministic",
                            "rerank_model": "deterministic",
                        },
                        "clusters": [],
                        "ranked_candidates": [],
                        "items_by_source": {"hackernews": [], "bluesky": [], "github": [], "youtube": [], "polymarket": []},
                        "errors_by_source": {},
                        "warnings": [],
                    }
                ),
                stderr="",
            )

        mock_run.side_effect = fake_run

        config = normalize_config(sample_config())
        config["last30days"]["presets"]["platform-pulse-v1"] = {
            "profile": "platform-pulse",
            "display_name": "Platform Pulse",
            "mode": "compact",
            "telegram": {"topic_name": "last30daysTrend", "topic_id": 414},
            "max_items": 12,
            "query_bundle": ["ai labs", "robotics"],
            "core_sources": ["reddit", "hackernews", "x", "bluesky"],
            "experimental_sources": ["github", "youtube", "polymarket"],
            "platform_sources": {
                "search": "reddit,hackernews,x,bluesky,github,youtube,polymarket",
            },
        }

        digest = build_digest(
            config,
            preset_id="platform-pulse-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )
        text = render_last30days_digest(digest)
        markdown_text = _render_expanded_markdown(digest, datetime(2026, 4, 12, 7, 0, tzinfo=timezone.utc))

        self.assertEqual(
            [section.platform for section in digest.platform_sections],
            ["reddit", "hn", "x", "bluesky", "github", "youtube", "polymarket"],
        )
        self.assertIn("Core: Reddit, Hacker News, X, Bluesky", text)
        self.assertIn("Experimental: GitHub, YouTube, Polymarket", text)
        self.assertIn("🟠 <b>Hacker News</b>  <i>(0 posts)</i>", text)
        self.assertIn("🦋 <b>Bluesky</b>  <i>(0 posts)</i>", text)
        self.assertIn("🐙 <b>GitHub</b>  <i>(0 posts)</i>", text)
        self.assertIn("▶️ <b>YouTube</b>  <i>(0 posts)</i>", text)
        self.assertIn("📊 <b>Polymarket</b>  <i>(0 posts)</i>", text)
        self.assertGreaterEqual(text.count("No surfaced stories in this run."), 5)
        self.assertIn("### hn (0 posts)", markdown_text)
        self.assertIn("- No surfaced stories in this run.", markdown_text)

    @patch("last30days_runner.subprocess.run")
    def test_platform_pulse_shows_all_ranked_posts_without_four_post_cap(self, mock_run) -> None:
        clusters = []
        candidates = []
        items = []
        for idx in range(6):
            cid = f"reddit-{idx}"
            clusters.append(
                {
                    "cluster_id": f"cluster-{cid}",
                    "title": f"Reddit story {idx}",
                    "candidate_ids": [cid],
                    "representative_ids": [cid],
                    "sources": ["reddit"],
                    "score": 95.0 - idx,
                }
            )
            candidates.append(
                {
                    "candidate_id": cid,
                    "item_id": f"item-{cid}",
                    "source": "reddit",
                    "title": f"Reddit story {idx}",
                    "url": f"https://reddit.example/{idx}",
                    "snippet": f"Detailed Reddit snippet {idx} with enough context to exceed the minimum length requirement.",
                    "sources": ["reddit"],
                    "source_items": [{"title": f"Reddit ref {idx}", "url": f"https://reddit.example/{idx}"}],
                    "final_score": 95.0 - idx,
                    "cluster_id": f"cluster-{cid}",
                }
            )
            items.append({"item_id": f"item-{cid}"})

        payload = last30days_payload(
            title="unused",
            clusters=clusters,
            ranked_candidates=candidates,
            items_by_source={"reddit": items},
        )
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["presets"]["platform-pulse-v1"] = {
            "profile": "platform-pulse",
            "display_name": "Platform Pulse",
            "mode": "compact",
            "telegram": {"topic_name": "last30daysTrend", "topic_id": 414},
            "max_items": 12,
            "query_bundle": ["ai labs"],
            "core_sources": ["reddit"],
            "experimental_sources": [],
            "platform_sources": {"search": "reddit"},
        }

        digest = build_digest(config, preset_id="platform-pulse-v1", now=datetime(2026, 4, 14, 4, 0, tzinfo=timezone.utc))
        reddit_section = next(section for section in digest.platform_sections if section.platform == "reddit")

        self.assertEqual(reddit_section.post_count, 6)
        self.assertEqual(reddit_section.raw_post_count, 6)
        self.assertEqual(reddit_section.repeat_filtered_count, 0)
        self.assertEqual(len(reddit_section.themes), 6)
        self.assertEqual(len(digest.themes), 6)

    @patch("last30days_runner.subprocess.run")
    def test_platform_pulse_filters_posts_seen_in_prior_week(self, mock_run) -> None:
        clusters = []
        candidates = []
        for idx, url in enumerate(["https://reddit.example/repeat", "https://reddit.example/new"]):
            cid = f"reddit-{idx}"
            clusters.append(
                {
                    "cluster_id": f"cluster-{cid}",
                    "title": f"Reddit story {idx}",
                    "candidate_ids": [cid],
                    "representative_ids": [cid],
                    "sources": ["reddit"],
                    "score": 90.0 - idx,
                }
            )
            candidates.append(
                {
                    "candidate_id": cid,
                    "item_id": f"item-{cid}",
                    "source": "reddit",
                    "title": f"Reddit story {idx}",
                    "url": url,
                    "snippet": f"Detailed Reddit snippet {idx} with enough context to exceed the minimum length requirement.",
                    "sources": ["reddit"],
                    "source_items": [{"title": f"Reddit ref {idx}", "url": url}],
                    "final_score": 90.0 - idx,
                    "cluster_id": f"cluster-{cid}",
                }
            )

        payload = last30days_payload(
            title="unused",
            clusters=clusters,
            ranked_candidates=candidates,
            items_by_source={"reddit": [{"item_id": "item-reddit-0"}, {"item_id": "item-reddit-1"}]},
        )
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["presets"]["platform-pulse-v1"] = {
            "profile": "platform-pulse",
            "display_name": "Platform Pulse",
            "mode": "compact",
            "telegram": {"topic_name": "last30daysTrend", "topic_id": 414},
            "max_items": 12,
            "query_bundle": ["ai labs"],
            "core_sources": ["reddit"],
            "experimental_sources": [],
            "obsidian": {"root": "PlatformPulse"},
            "platform_sources": {"search": "reddit"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            history_dir = Path(tmp) / "PlatformPulse" / "Derived" / "2026-04-13"
            history_dir.mkdir(parents=True)
            history_payload = {
                "platform_sections": [
                    {
                        "platform": "reddit",
                        "themes": [
                            {
                                "title": "Yesterday repeated Reddit story",
                                "url": "https://reddit.example/repeat",
                            }
                        ],
                    }
                ],
                "reports": [],
                "global_themes": [],
            }
            (history_dir / "0700-compact.json").write_text(json.dumps(history_payload), encoding="utf-8")
            with patch("last30days_runner.LAST30DAYS_OBSIDIAN_ROOT", Path(tmp)):
                digest = build_digest(
                    config,
                    preset_id="platform-pulse-v1",
                    now=datetime(2026, 4, 14, 4, 0, tzinfo=timezone.utc),
                )

        reddit_section = next(section for section in digest.platform_sections if section.platform == "reddit")
        text = render_last30days_digest(digest)

        self.assertEqual(reddit_section.raw_post_count, 2)
        self.assertEqual(reddit_section.repeat_filtered_count, 1)
        self.assertEqual(reddit_section.post_count, 1)
        self.assertEqual(len(reddit_section.themes), 1)
        self.assertEqual(reddit_section.themes[0].url, "https://reddit.example/new")
        self.assertIn("1 repeats hidden from the prior 7 days.", text)

    @patch("last30days_runner.subprocess.run")
    def test_platform_pulse_filters_fuzzy_title_repeats_from_prior_week(self, mock_run) -> None:
        candidates = [
            {
                "candidate_id": "reddit-fuzzy",
                "item_id": "item-reddit-fuzzy",
                "source": "reddit",
                "title": "China humanoid robot half marathon draws more than 70 teams with autonomous navigation",
                "url": "https://reddit.example/fuzzy-new",
                "snippet": "A long Reddit snippet about the China humanoid half marathon and the growing number of autonomous teams.",
                "sources": ["reddit"],
                "source_items": [{"title": "Reddit ref fuzzy", "url": "https://reddit.example/fuzzy-new"}],
                "final_score": 91.0,
                "cluster_id": "cluster-reddit-fuzzy",
            },
            {
                "candidate_id": "reddit-fresh",
                "item_id": "item-reddit-fresh",
                "source": "reddit",
                "title": "Anthropic delays wider release of its cyber model",
                "url": "https://reddit.example/fresh",
                "snippet": "A long Reddit snippet about Anthropic keeping its cyber model under tighter commercial controls.",
                "sources": ["reddit"],
                "source_items": [{"title": "Reddit ref fresh", "url": "https://reddit.example/fresh"}],
                "final_score": 88.0,
                "cluster_id": "cluster-reddit-fresh",
            },
        ]
        payload = last30days_payload(
            title="unused",
            ranked_candidates=candidates,
            clusters=[
                {
                    "cluster_id": "cluster-reddit-fuzzy",
                    "title": candidates[0]["title"],
                    "candidate_ids": ["reddit-fuzzy"],
                    "representative_ids": ["reddit-fuzzy"],
                    "sources": ["reddit"],
                    "score": 91.0,
                },
                {
                    "cluster_id": "cluster-reddit-fresh",
                    "title": candidates[1]["title"],
                    "candidate_ids": ["reddit-fresh"],
                    "representative_ids": ["reddit-fresh"],
                    "sources": ["reddit"],
                    "score": 88.0,
                },
            ],
            items_by_source={"reddit": [{"item_id": "item-reddit-fuzzy"}, {"item_id": "item-reddit-fresh"}]},
        )
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["presets"]["platform-pulse-v1"] = {
            "profile": "platform-pulse",
            "display_name": "Platform Pulse",
            "mode": "compact",
            "telegram": {"topic_name": "last30daysTrend", "topic_id": 414},
            "max_items": 12,
            "query_bundle": ["robotics"],
            "core_sources": ["reddit"],
            "experimental_sources": [],
            "obsidian": {"root": "PlatformPulse"},
            "platform_sources": {"search": "reddit"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            history_dir = Path(tmp) / "PlatformPulse" / "Derived" / "2026-04-13"
            history_dir.mkdir(parents=True)
            history_payload = {
                "platform_sections": [
                    {
                        "platform": "reddit",
                        "themes": [
                            {
                                "title": "More than 70 robot teams are gearing up for China's humanoid robot half-marathon with autonomous navigation",
                                "url": "https://reddit.example/fuzzy-old",
                            }
                        ],
                    }
                ],
                "reports": [],
                "global_themes": [],
            }
            (history_dir / "0700-compact.json").write_text(json.dumps(history_payload), encoding="utf-8")
            with patch("last30days_runner.LAST30DAYS_OBSIDIAN_ROOT", Path(tmp)):
                digest = build_digest(
                    config,
                    preset_id="platform-pulse-v1",
                    now=datetime(2026, 4, 14, 4, 0, tzinfo=timezone.utc),
                )

        reddit_section = next(section for section in digest.platform_sections if section.platform == "reddit")

        self.assertEqual(reddit_section.raw_post_count, 2)
        self.assertEqual(reddit_section.repeat_filtered_count, 1)
        self.assertEqual(reddit_section.post_count, 1)
        self.assertEqual(reddit_section.themes[0].url, "https://reddit.example/fresh")

    @patch("last30days_runner.subprocess.run")
    def test_platform_pulse_keeps_same_title_on_different_platform(self, mock_run) -> None:
        payload = last30days_payload(
            title="unused",
            ranked_candidates=[
                {
                    "candidate_id": "x-1",
                    "item_id": "item-x-1",
                    "source": "x",
                    "title": "Humanoid robot half marathon in China draws 70 teams",
                    "url": "https://x.example/1",
                    "snippet": "A long X snippet about the same robotics story, but on a different platform.",
                    "sources": ["x"],
                    "source_items": [{"title": "X ref", "url": "https://x.example/1"}],
                    "final_score": 87.0,
                    "cluster_id": "cluster-x-1",
                }
            ],
            clusters=[
                {
                    "cluster_id": "cluster-x-1",
                    "title": "Humanoid robot half marathon in China draws 70 teams",
                    "candidate_ids": ["x-1"],
                    "representative_ids": ["x-1"],
                    "sources": ["x"],
                    "score": 87.0,
                }
            ],
            items_by_source={"x": [{"item_id": "item-x-1"}]},
        )
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["presets"]["platform-pulse-v1"] = {
            "profile": "platform-pulse",
            "display_name": "Platform Pulse",
            "mode": "compact",
            "telegram": {"topic_name": "last30daysTrend", "topic_id": 414},
            "max_items": 12,
            "query_bundle": ["robotics"],
            "core_sources": ["x"],
            "experimental_sources": [],
            "obsidian": {"root": "PlatformPulse"},
            "platform_sources": {"search": "x"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            history_dir = Path(tmp) / "PlatformPulse" / "Derived" / "2026-04-13"
            history_dir.mkdir(parents=True)
            history_payload = {
                "platform_sections": [
                    {
                        "platform": "reddit",
                        "themes": [
                            {
                                "title": "Humanoid robot half marathon in China draws 70 teams",
                                "url": "https://reddit.example/old",
                            }
                        ],
                    }
                ],
                "reports": [],
                "global_themes": [],
            }
            (history_dir / "0700-compact.json").write_text(json.dumps(history_payload), encoding="utf-8")
            with patch("last30days_runner.LAST30DAYS_OBSIDIAN_ROOT", Path(tmp)):
                digest = build_digest(
                    config,
                    preset_id="platform-pulse-v1",
                    now=datetime(2026, 4, 14, 4, 0, tzinfo=timezone.utc),
                )

        x_section = next(section for section in digest.platform_sections if section.platform == "x")

        self.assertEqual(x_section.raw_post_count, 1)
        self.assertEqual(x_section.repeat_filtered_count, 0)
        self.assertEqual(x_section.post_count, 1)
        self.assertEqual(x_section.themes[0].url, "https://x.example/1")

    def test_write_signal_digest_persists_daily_markdown(self) -> None:
        theme = Last30DaysTheme(
            theme_id="t1",
            title="OpenAI launches new model",
            snippet="OpenAI launches a new model and shifts expectations for the rest of the market.",
            url="https://example.com/openai",
            sources=["hn", "reddit"],
            queries=["openai"],
            score=92.0,
            category="Big Tech & AI",
            primary_source="hn",
            global_score=101.0,
            global_rank=1,
        )
        digest = Last30DaysDigest(
            preset_id="world-radar-v1",
            canonical_preset_id="personal-feed-v1",
            profile="personal-feed",
            display_name="Personal Feed",
            mode="compact",
            generated_at="2026-04-14T04:00:00+00:00",
            topic_name="last30daysTrend",
            topic_id=1,
            query_bundle=["openai"],
            themes=[theme],
            global_themes=[theme],
            category_sections=[Last30DaysCategorySection(category="Big Tech & AI", themes=[theme])],
            source_counts={"hn": 3, "reddit": 2},
            successful_queries=1,
            total_queries=1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = write_signal_digest(digest, obsidian_vault_path=Path(tmp))
            text = path.read_text(encoding="utf-8")

        self.assertEqual(path.name, "2026-04-14.md")
        self.assertIn("type: signal-digest", text)
        self.assertIn("preset_id: personal-feed-v1", text)
        self.assertIn("OpenAI launches new model", text)
        self.assertIn("[hn · reddit](https://example.com/openai)", text)
        self.assertIn("## Source Coverage", text)


if __name__ == "__main__":
    unittest.main()
