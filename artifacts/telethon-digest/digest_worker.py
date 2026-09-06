"""
Main digest orchestrator.

Modes:
  python digest_worker.py          — starts APScheduler daemon (local/debug only)
  python digest_worker.py --now    — runs one digest cycle immediately and exits

Environment: loads /app/telethon.env (inside container).
Config: /app/config.json.
"""
import argparse
import asyncio
import copy
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from dotenv import load_dotenv

# Load env before importing modules that reference os.environ
load_dotenv("/app/telethon.env", override=False)

import state_store
from reader import build_client, read_all_channels, update_cursors
from scorer import score_posts
from dedup import deduplicate_posts
from link_builder import attach_links
from summarizer import summarize
from poster import post_digest
from persistence import persist_digest
from models import DigestStats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("digest_worker")

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.json"))
TZ_MSK = pytz.timezone("Europe/Moscow")


def _get_digest_type(config: dict) -> str:
    """Determine digest type by current MSK hour, with env override for testing."""
    override = os.environ.get("DIGEST_TYPE_OVERRIDE", "").strip()
    if override:
        return override
    tz = pytz.timezone(config.get("timezone", "Europe/Moscow"))
    hour = str(datetime.now(tz).hour)
    return config.get("digest_types", {}).get(hour, "interval")


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _as_int_set(values: list[int | str]) -> set[int]:
    return {int(v) for v in values}


def _schedule_slots(config: dict) -> list[tuple[int, int]]:
    raw_slots = list(config.get("schedule_slots", []) or [])
    if raw_slots:
        slots: list[tuple[int, int]] = []
        for raw in raw_slots:
            hour_text, minute_text = str(raw).strip().split(":", 1)
            slots.append((int(hour_text), int(minute_text)))
        return sorted(set(slots))
    return sorted({(int(hour), 0) for hour in config.get("schedule_hours", [8, 11, 14, 17, 21])})


def _scheduled_period_label(config: dict, *, now: datetime) -> str | None:
    bounds = _scheduled_period_bounds(config, now=now)
    if bounds is None:
        return None
    _, _, label = bounds
    return label


def _scheduled_period_bounds(config: dict, *, now: datetime) -> tuple[datetime, datetime, str] | None:
    raw_hour = os.environ.get("DIGEST_SLOT_HOUR", "").strip()
    if not raw_hour:
        return None
    slot_hour = int(raw_hour)
    slot_minute = int(os.environ.get("DIGEST_SLOT_MINUTE", "0").strip() or "0")
    tz = pytz.timezone(str(config.get("timezone", "Europe/Moscow") or "Europe/Moscow"))
    local_now = now.astimezone(tz)
    slots = _schedule_slots(config)
    if (slot_hour, slot_minute) not in slots:
        slots.append((slot_hour, slot_minute))
        slots.sort()

    points: list[datetime] = []
    for day_offset in (-1, 0, 1):
        day = local_now.date().fromordinal(local_now.date().toordinal() + day_offset)
        for hour, minute in slots:
            points.append(tz.localize(datetime(day.year, day.month, day.day, hour, minute)))
    points.sort()

    matching_points = [
        point
        for point in points
        if point.hour == slot_hour and point.minute == slot_minute and point <= local_now
    ]
    if not matching_points:
        return None
    end_local = matching_points[-1]
    start_local = points[points.index(end_local) - 1]
    label = f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), label


def _post_in_period(post, start: datetime, end: datetime) -> bool:
    post_dt = post.date
    if post_dt.tzinfo is None:
        post_dt = post_dt.replace(tzinfo=timezone.utc)
    else:
        post_dt = post_dt.astimezone(timezone.utc)
    return start <= post_dt < end


def _filter_posts_in_period(posts, start: datetime, end: datetime):
    return [post for post in posts if _post_in_period(post, start, end)]


def _active_channel_count(posts) -> int:
    return len({post.channel_id for post in posts})


def _scheduled_retry_floor(config: dict, channels_in_scope: int) -> int:
    configured = config.get("scheduled_min_active_channels")
    if configured is not None:
        return max(0, int(configured))
    return max(12, min(24, int(channels_in_scope * 0.03)))


def _should_retry_scheduled_read(
    config: dict,
    *,
    scheduled: bool,
    channels_in_scope: int,
    posts_in_period,
) -> bool:
    if not scheduled or channels_in_scope < 100:
        return False
    floor = _scheduled_retry_floor(config, channels_in_scope)
    if floor <= 0 or _active_channel_count(posts_in_period) >= floor:
        return False
    return len(posts_in_period) >= max(20, floor * 2)


def _scheduled_retry_config(config: dict) -> dict:
    retry_config = copy.deepcopy(config)
    retry_config["read_batch_size"] = max(
        1,
        min(int(retry_config.get("read_batch_size", 5) or 5), 3),
    )
    retry_config["read_batch_delay_sec"] = max(
        float(retry_config.get("read_batch_delay_sec", 1.5) or 1.5),
        2.0,
    )
    return retry_config


def apply_read_allowlist(config: dict) -> dict:
    """
    Enforce least-privilege reads before Telethon sees the channel list.

    Telegram user sessions do not support API scopes, so the service must
    fail closed at application level: only configured folders/channel IDs are
    read, and only broadcast channels are read by default.
    """
    if config.get("read_only") is not True:
        raise ValueError("Telethon Digest requires read_only=true")

    allowed_folders = set(config.get("allowed_folder_names", []))
    allowed_channel_ids = _as_int_set(config.get("allowed_channel_ids", []))
    excluded_folders = set(config.get("excluded_folder_names", []))
    excluded_channel_ids = _as_int_set(config.get("excluded_channel_ids", []))
    broadcast_only = config.get("read_broadcast_channels_only", True)

    if config.get("require_explicit_allowlist", True) and not (
        allowed_folders or allowed_channel_ids
    ):
        raise ValueError("No allowed folders or channel IDs configured")

    filtered = copy.deepcopy(config)
    filtered_folders = []
    before_channels = sum(len(f.get("channels", [])) for f in config.get("folders", []))

    for folder in config.get("folders", []):
        folder_name = folder.get("name", "")
        if folder_name in excluded_folders:
            continue

        folder_allowed = not allowed_folders or folder_name in allowed_folders
        kept_channels = []
        for channel in folder.get("channels", []):
            channel_id = int(channel["id"])
            if channel_id in excluded_channel_ids:
                continue
            if not (folder_allowed or channel_id in allowed_channel_ids):
                continue
            if broadcast_only and channel.get("broadcast") is not True:
                continue
            kept_channels.append(channel)

        if kept_channels:
            next_folder = copy.deepcopy(folder)
            next_folder["channels"] = kept_channels
            filtered_folders.append(next_folder)

    filtered["folders"] = filtered_folders
    after_channels = sum(len(f.get("channels", [])) for f in filtered_folders)
    logger.info(
        "Read allowlist: %s folders / %s channels selected from %s channels",
        len(filtered_folders),
        after_channels,
        before_channels,
    )
    if after_channels == 0:
        raise ValueError("Read allowlist selected 0 channels")
    return filtered


async def run_digest(config: dict | None = None):
    """Execute one full digest cycle."""
    if config is None:
        config = load_config()

    digest_type = _get_digest_type(config)
    logger.info(f"Digest type: {digest_type}")

    config = apply_read_allowlist(config)
    channels_in_scope = sum(len(folder.get("channels", [])) for folder in config.get("folders", []))

    now_utc = datetime.now(timezone.utc)
    slot_bounds = _scheduled_period_bounds(config, now=now_utc)
    if slot_bounds is not None:
        period_start, period_end, period_label_override = slot_bounds
        config = copy.deepcopy(config)
        window_age_hours = max((now_utc - period_start).total_seconds() / 3600, 0)
        config["lookahead_hours"] = max(float(config.get("lookahead_hours", 4) or 4), window_age_hours + 0.25)
    else:
        period_end = now_utc
        period_start_ts = state_store.get_last_run()
        if period_start_ts == 0:
            # First run: use lookahead_hours as window
            period_start_ts = time.time() - config.get("lookahead_hours", 4) * 3600
        period_start = datetime.fromtimestamp(period_start_ts, tz=timezone.utc)
        period_label_override = None

    logger.info(
        f"Digest cycle: {period_start.isoformat()} → {period_end.isoformat()}"
    )

    client = build_client()
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("Telethon session not authorized. Run auth.py first.")
        await client.disconnect()
        raise RuntimeError("Telethon session is not authorized")

    try:
        # 1. Read channels
        all_posts = await read_all_channels(
            client,
            config,
            use_cursors=slot_bounds is None,
        )
        posts_in_period = _filter_posts_in_period(all_posts, period_start, period_end)
        if _should_retry_scheduled_read(
            config,
            scheduled=slot_bounds is not None,
            channels_in_scope=channels_in_scope,
            posts_in_period=posts_in_period,
        ):
            original_posts = len(posts_in_period)
            original_channels = _active_channel_count(posts_in_period)
            logger.warning(
                "Scheduled read coverage low: %s posts across %s channels; retrying with slower pacing",
                original_posts,
                original_channels,
            )
            retry_all_posts = await read_all_channels(
                client,
                _scheduled_retry_config(config),
                use_cursors=False,
            )
            retry_posts_in_period = _filter_posts_in_period(
                retry_all_posts, period_start, period_end
            )
            retry_channels = _active_channel_count(retry_posts_in_period)
            if retry_channels > original_channels or len(retry_posts_in_period) > original_posts:
                logger.info(
                    "Scheduled read coverage retry improved: %s/%s posts, %s/%s channels",
                    len(retry_posts_in_period),
                    original_posts,
                    retry_channels,
                    original_channels,
                )
                all_posts = retry_all_posts
                posts_in_period = retry_posts_in_period
            else:
                logger.info(
                    "Scheduled read coverage retry did not improve: %s posts, %s channels",
                    len(retry_posts_in_period),
                    retry_channels,
                )
    finally:
        await client.disconnect()

    if len(posts_in_period) != len(all_posts):
        logger.info(
            "Window filter: kept %s/%s posts for %s → %s",
            len(posts_in_period),
            len(all_posts),
            period_start.isoformat(),
            period_end.isoformat(),
        )

    if not posts_in_period:
        logger.info("No new posts — skipping digest")
        state_store.set_last_run()
        return

    # 2. Score & filter
    top_posts = score_posts(posts_in_period, config)

    if not top_posts:
        logger.info("No posts above min_score — skipping digest")
        state_store.set_last_run()
        return

    # 3. LLM dedup (clusters similar posts across channels)
    top_posts = await deduplicate_posts(top_posts, config)

    # 4. Attach links
    attach_links(top_posts)

    stats = DigestStats(
        channels_in_scope=channels_in_scope,
        new_posts_seen=len(posts_in_period),
        posts_selected=len(top_posts),
        active_channels_seen=len({post.channel_id for post in posts_in_period}),
            folder_message_counts=dict(Counter(post.folder_name for post in posts_in_period)),
        folder_channel_counts={
            folder_name: len(channel_ids)
            for folder_name, channel_ids in _folder_channel_sets(posts_in_period).items()
        },
    )

    # 5. Summarize into one structured digest document
    digest_document = await summarize(
        top_posts,
        config=config,
        digest_type=digest_type,
        period_start=period_start,
        period_end=period_end,
        period_label_override=period_label_override,
        stats=stats,
    )

    # 6. Post to Telegram via OpenClaw bot token
    posted = await post_digest(digest_document)
    if not posted:
        logger.error("Digest publication failed — state not advanced")
        raise RuntimeError("Digest publication failed")

    # 7. Persist processed digest after successful Telegram publication
    try:
        await persist_digest(
            digest_document,
            config=config,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:
        logger.error("Digest persistence failed: %s", exc)
        raise

    # 8. Advance watermarks
    update_cursors(posts_in_period)
    state_store.set_last_run()

    logger.info("Digest cycle complete")


def _folder_channel_sets(posts):
    by_folder = defaultdict(set)
    for post in posts:
        by_folder[post.folder_name].add(post.channel_id)
    return by_folder


def _job_listener(event):
    if event.exception:
        logger.error(f"Scheduled job failed: {event.exception}")
    else:
        logger.info("Scheduled job completed successfully")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true", help="Run once immediately")
    args = parser.parse_args()

    config = load_config()
    schedule_hours = config.get("schedule_hours", [8, 11, 14, 17, 21])
    tz = config.get("timezone", "Europe/Moscow")

    if args.now:
        logger.info("Running digest immediately (--now mode)")
        asyncio.run(run_digest(config))
        return

    # Local APScheduler daemon fallback; production scheduling is handled by OpenClaw Cron Jobs.
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    hours_str = ",".join(str(h) for h in schedule_hours)
    scheduler.add_job(
        run_digest,
        trigger="cron",
        hour=hours_str,
        minute=0,
        misfire_grace_time=300,  # skip if container was down; don't catch up
        kwargs={"config": config},
        id="digest",
        name="Telegram Digest",
    )

    scheduler.start()
    logger.info(
        f"APScheduler started. Digest at hours {schedule_hours} ({tz}). "
        f"Next run: {scheduler.get_job('digest').next_run_time}"
    )

    # Keep event loop alive
    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
