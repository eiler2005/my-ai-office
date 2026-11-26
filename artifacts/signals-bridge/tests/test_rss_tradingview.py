import asyncio
import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from unittest.mock import AsyncMock

import fakeredis
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tradingview_adapter as tv
from config_store import normalize_config
from benka_integrations import legacy_delivery
from benka_integrations.delivery import _journal_key


RULE = {"kind": "author_futures", "author": "vesperfin", "exchange": "RUS", "families": ["Si", "CR"]}
SOURCE = {"id": "vesperfin", "author": "vesperfin", "locale": "ru", "delivery_mode": "full"}
NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
TARGET = "telegram:-100123:123"
CHART = "https://s3.tradingview.com/a/AbCd1234_mid.png"


def feed(symbol="RUS:CRZ2026", author="Vesperfin", body="First paragraph\n\nLast paragraph"):
    link = "https://ru.tradingview.com/chart/CRZ2026/AbCd1234-post/"
    return f"""<rss><channel><item>
    <title>Idea</title><link>{link}</link><description>{escape(body)}</description>
    <pubDate>Thu, 26 Nov 2026 06:42:15 +0000</pubDate>
    <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[
    <div class="avatar"><img src="https://s3.tradingview.com/userpics/avatar.png"></div>
    <div class="chart-author"><a>{author}</a></div>
    <span class="symbol-descr">{symbol}</span>
    <a href="{link}"><img src="{CHART}"></a>
    ]]></content:encoded></item></channel></rss>""".encode()


@pytest.mark.parametrize(("symbol", "family"), [
    ("RUS:CRZ2026", "CR"), ("RUS:SiH7", "Si"), ("RUS:CRM27", "CR"), ("RUS:SIU2027", "Si"),
    ("RUS:SI1!", "Si"), ("RUS:CR22!", "CR"), ("RUS:CRX2026", None),
    ("OTHER:SIZ2026", None), ("RUS:CRZ2026EXTRA", None), ("RUS:CNYRUB", None), ("RUS:CR", None),
])
def test_quarterly_and_continuous_families(symbol, family):
    assert tv.family_for(symbol, RULE) == family


def test_rss_author_image_and_untruncated_text():
    body = "One < two\n\n" + "🧭" * 8000 + "\nLast line"
    [idea] = tv.parse_feed(feed(body=body), "vesperfin")
    assert idea["id"] == "AbCd1234"
    assert idea["chart"] == CHART
    assert idea["body"] == body
    assert tv.parse_feed(feed(author="vesperfin_other"), "vesperfin") == []
    header, parts = tv.message_parts(dict(idea, family="CR"), mode="full", tz="Europe/Moscow")
    assert "🧭 Vesperfin · CR · RUS:CRZ2026" in header
    assert "".join(parts) == body
    assert all(len(part.encode("utf-16-le")) <= 7600 for part in parts)
    with pytest.raises(ValueError, match="declaration"):
        tv.parse_feed(b"<!DOCTYPE rss><rss/>", "vesperfin")


def test_reviewed_rule_configuration():
    fragment = json.loads((Path(tv.__file__).parent / "rules/tradingview.vesperfin.json").read_text())
    config = normalize_config({
        "sources": {"tradingview_rss": [fragment["source"]]},
        "rule_sets": [{"id": "trading-si-watch", "rules": [fragment["rule"]]}],
    })
    assert config["rule_sets"][0]["rules"][0]["families"] == ["Si", "CR"]


def test_bootstrap_before_backfill_and_restart_without_duplicate(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(tv, "fetch_ideas", lambda _: tv.parse_feed(feed(), "vesperfin"))
    poll = dict(now=NOW, target=TARGET, tz="Europe/Moscow")
    assert tv.poll(client, SOURCE, [RULE], **poll) == ["tradingview_queued=0"]
    backfill = dict(SOURCE, id="initial-review", start_at="2026-11-24T12:00:00Z")
    assert tv.poll(client, backfill, [RULE, RULE], **poll) == ["tradingview_queued=1"]
    assert tv.poll(client, backfill, [RULE], **poll) == ["tradingview_queued=0"]

    photo = AsyncMock()
    body = AsyncMock(side_effect=[RuntimeError("interrupted"), True])
    monkeypatch.setattr(legacy_delivery, "post_media", photo)
    monkeypatch.setattr(legacy_delivery, "post_text", body)
    monkeypatch.setattr(tv, "_fetch", lambda *a, **kw: b"\x89PNG\r\n\x1a\n")

    def deliver():
        return asyncio.run(tv.deliver_pending(client, chat=-100123, topic=123, holder="job"))

    assert deliver() == (0, 1)
    photo_id = photo.call_args.kwargs["delivery_id"]
    client.set(_journal_key(photo_id), json.dumps({"status": "confirmed"}))
    assert deliver() == (1, 0)
    assert deliver() == (0, 0)
    photo.assert_awaited_once()
    assert body.call_args_list[0].kwargs["delivery_id"] == body.call_args_list[1].kwargs["delivery_id"]
