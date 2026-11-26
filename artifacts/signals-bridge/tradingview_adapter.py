"""TradingView idea polling and durable Signals delivery."""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

import state_store

FEED_HOSTS = {"en": "www.tradingview.com", "ru": "ru.tradingview.com"}
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
IDEA_PATH = re.compile(r"/chart/[^/]+/([A-Za-z0-9]{8})(?:-[^/]+)?/?")
HANDLE = re.compile(r"[A-Za-z0-9_-]{1,64}")
CHUNK_LIMIT = 3800


def validate_source(source: dict) -> None:
    if source.get("locale") not in FEED_HOSTS or not HANDLE.fullmatch(str(source.get("author", ""))):
        raise ValueError("TradingView source requires a supported locale and author handle")
    if source.get("delivery_mode", "link") not in {"link", "chart", "full"}:
        raise ValueError("Invalid TradingView delivery_mode")
    if source.get("start_at"):
        _start_at(source)


def _start_at(source: dict) -> datetime:
    timestamp = datetime.fromisoformat(source["start_at"])
    if timestamp.tzinfo is None:
        raise ValueError("TradingView start_at requires a timezone")
    return timestamp.astimezone(timezone.utc)


def validate_rule(rule: dict, source: dict) -> None:
    if rule.get("kind") != "author_futures" or str(rule.get("author", "")).lower() != source["author"].lower():
        raise ValueError("TradingView rule must match the source author")
    families = rule.get("families")
    if (not isinstance(families, list) or not families
            or not all(re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,9}", str(item)) for item in families)
            or not re.fullmatch(r"[A-Z0-9]+", str(rule.get("exchange", "")))):
        raise ValueError("TradingView rule requires an exchange and futures families")


def family_for(symbol: str, rule: dict) -> str | None:
    exchange, _, ticker = symbol.upper().partition(":")
    if exchange == rule["exchange"]:
        for family in rule["families"]:
            if re.fullmatch(re.escape(family.upper()) + r"(?:[1-9][0-9]*!|[HMUZ](?:[0-9]{1,2}|20[0-9]{2}))", ticker):
                return family
    return None


def _idea_id(url: str) -> str | None:
    parsed = urlsplit(url)
    match = IDEA_PATH.fullmatch(parsed.path)
    if parsed.scheme == "https" and parsed.netloc in FEED_HOSTS.values() and match:
        return match[1]
    return None


def _chart_url(url: str, idea_id: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc == "s3.tradingview.com"
            and re.fullmatch(rf"/[A-Za-z0-9]/{re.escape(idea_id)}(?:_[a-z]+)?\.png", parsed.path) is not None)


def parse_feed(data: bytes, author: str) -> list[dict]:
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", data, re.IGNORECASE):
        raise ValueError("Unexpected TradingView XML declaration")
    channel = ET.fromstring(data.decode("utf-8-sig")).find("channel")
    if channel is None:
        raise ValueError("TradingView RSS channel is missing")
    ideas = []
    for item in channel.findall("item"):
        link = item.findtext("link", "")
        idea_id = _idea_id(link)
        html = BeautifulSoup(item.findtext(CONTENT, ""), "html.parser")
        publisher = html.select_one(".chart-author a")
        symbol = html.select_one(".symbol-descr")
        if not idea_id or publisher is None or symbol is None:
            raise ValueError("TradingView item metadata is missing")
        if publisher.get_text(strip=True).lower() != author.lower():
            continue
        published = parsedate_to_datetime(item.findtext("pubDate", ""))
        if published.tzinfo is None:
            raise ValueError("TradingView publication timestamp lacks a timezone")
        image = next((image.get("src", "") for anchor in html.find_all("a", href=True)
                      if _idea_id(anchor["href"]) == idea_id
                      for image in anchor.find_all("img", src=True)
                      if _chart_url(image["src"], idea_id)), "")
        ideas.append({
            "id": idea_id, "author": publisher.get_text(strip=True), "link": link,
            "symbol": symbol.get_text(strip=True), "chart": image,
            "published": published.astimezone(timezone.utc).isoformat(),
            "title": item.findtext("title", "").strip(),
            "body": item.findtext("description", "").strip(),
        })
    return sorted(ideas, key=lambda idea: (idea["published"], idea["id"]))


def _fetch(url: str, *, limit: int, params: dict | None = None) -> bytes:
    with httpx.stream("GET", url, params=params, timeout=12, trust_env=False) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("TradingView response exceeds size limit")
        return bytes(data)


def fetch_ideas(source: dict) -> list[dict]:
    url = f"https://{FEED_HOSTS[source['locale']]}/feed/"
    return parse_feed(_fetch(url, params={"username": source["author"]}, limit=2_000_000), source["author"])


def split_body(body: str):
    # Measure UTF-16 conservatively and budget for Hermes directive escaping.
    while len(body.encode("utf-16-le")) > CHUNK_LIMIT * 2:
        end = len(body.encode("utf-16-le")[:CHUNK_LIMIT * 2].decode("utf-16-le", errors="ignore"))
        paragraph = body.rfind("\n\n", 0, end - 1)
        if paragraph >= end // 2:
            end = paragraph + 2
        yield body[:end]
        body = body[end:]
    if body:
        yield body


def message_parts(idea: dict, *, mode: str, tz: str) -> tuple[str, list[str]]:
    published = datetime.fromisoformat(idea["published"]).astimezone(ZoneInfo(tz))
    header = (f"🧭 {idea['author']} · {idea['family']} · {idea['symbol']}\n"
              f"{idea['title'][:250]}\n"
              f"TradingView · {published:%d.%m.%Y %H:%M %Z}\n{idea['link']}")
    if mode != "link" and not idea["chart"]:
        header += "\nГрафик доступен по ссылке."
    if mode != "full":
        return header, []
    body = idea["body"]
    if not body or body.endswith(("…", "...")):
        header += "\nПолная версия текста доступна по ссылке."
    return header, list(split_body(body))


_ACCEPT = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then return 0 end
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('SADD', KEYS[1], ARGV[1])
return 1
"""


def poll(r, source: dict, rules: list[dict], *, now: datetime, target: str, tz: str) -> list[str]:
    ideas = fetch_ideas(source)
    source_id = source["id"]
    baseline = f"state:signals:tradingview:baseline:{source_id}"
    configured_start = _start_at(source) if source.get("start_at") else now
    r.set(baseline, min(now, configured_start).isoformat(), nx=True)
    cutoff = datetime.fromisoformat(r.get(baseline))
    target_key = hashlib.sha256(target.encode()).hexdigest()
    accepted = f"state:signals:tradingview:{target_key}:accepted"
    pending = f"state:signals:tradingview:{target_key}:pending"
    count = 0
    for idea in ideas:
        published = datetime.fromisoformat(idea["published"])
        if not cutoff <= published <= now:
            continue
        family = next((family for rule in rules if (family := family_for(idea["symbol"], rule))), None)
        if not family:
            continue
        mode = source.get("delivery_mode", "link")
        idea["family"] = family
        header, body = message_parts(idea, mode=mode, tz=tz)
        payload = {"header": header, "body": body, "published": idea["published"],
                   "chart": idea["chart"] if mode != "link" else ""}
        count += r.eval(_ACCEPT, 2, accepted, pending, idea["id"], json.dumps(payload, ensure_ascii=False))
    notes = [f"tradingview_queued={count}"]
    previous = state_store.get_dt(r, state_store.source_last_success_key(source_id))
    if ideas and previous and previous < datetime.fromisoformat(ideas[0]["published"]):
        notes.append("tradingview_possible_feed_gap")
    state_store.set_dt(r, state_store.source_last_success_key(source_id), now)
    return notes


async def deliver_pending(r, *, chat: int, topic: int, holder: str) -> tuple[int, int]:
    from benka_integrations.delivery import UncertainDelivery, receipt_status
    from benka_integrations.legacy_delivery import post_media, post_text

    target = f"telegram:{chat}:{topic}"
    target_key = hashlib.sha256(target.encode()).hexdigest()
    pending = f"state:signals:tradingview:{target_key}:pending"
    lock = state_store.lock_key("tradingview", target_key)
    if not state_store.acquire_lock(r, lock, holder, ttl_seconds=600):
        return 0, 0
    delivered = failures = 0
    try:
        plans = [(idea_id, json.loads(raw)) for idea_id, raw in r.hgetall(pending).items()]
        for idea_id, plan in sorted(plans, key=lambda entry: (entry[1]["published"], entry[0])):
            identity = f"tradingview:{target_key}:{idea_id}"
            try:
                if plan["chart"]:
                    chart_id = f"{identity}:chart"
                    status = receipt_status(r, chart_id)
                    if status is None:
                        try:
                            image = _fetch(plan["chart"], limit=9_000_000)
                        except httpx.HTTPStatusError as exc:
                            if exc.response.status_code not in {404, 410}:
                                raise
                            plan["chart"] = ""
                            plan["header"] += "\nГрафик доступен по ссылке."
                            r.hset(pending, idea_id, json.dumps(plan, ensure_ascii=False))
                        else:
                            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                                raise ValueError("TradingView chart is not a PNG")
                            await post_media(image, filename=f"{idea_id}.png", caption=plan["header"],
                                             chat_id=chat, topic_id=topic, document=False, delivery_id=chart_id)
                    elif status != "confirmed":
                        raise UncertainDelivery("TradingView chart requires reconciliation")
                if not plan["chart"]:
                    await post_text(plan["header"], chat_id=chat, topic_id=topic, html=False,
                                    delivery_id=f"{identity}:header")
                for index, chunk in enumerate(plan["body"]):
                    await post_text(chunk, chat_id=chat, topic_id=topic, html=False,
                                    delivery_id=f"{identity}:body:{index}")
            except Exception:
                failures += 1
                continue
            r.hdel(pending, idea_id)
            delivered += 1
    finally:
        state_store.release_lock(r, lock, holder)
    return delivered, failures
