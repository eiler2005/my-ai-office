"""Compatible Redis stream envelopes with atomic slot de-duplication."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import time

import redis

from .config import credential, require_active

ENQUEUE = """
local prior = redis.call('GET', KEYS[2])
if prior then return prior end
local id = redis.call('XADD', KEYS[1], '*', unpack(ARGV, 2))
redis.call('SET', KEYS[2], id, 'EX', ARGV[1])
return id
"""


def connection(config):
    return redis.Redis.from_url(credential(config, "redis", "REDIS_URL"), decode_responses=True)


def enqueue(client, config, job: str, slot: str, fields: dict | None = None):
    require_active(config, "enqueue")
    spec = config["jobs"][job]
    payload = dict(spec.get("payload", {}))
    if fields:
        # User-supplied values cannot change a route or source identity.
        if set(fields) - set(spec.get("allowed_fields", [])):
            raise ValueError("Job payload contains unapproved fields")
        payload.update(fields)
    slot_key = hashlib.sha256(f"{job}\0{slot}".encode()).hexdigest()
    payload.update(run_id=f"hermes-{slot_key[:24]}", requested_at=str(int(time.time())), requested_by="hermes")
    args = [str(spec.get("dedupe_seconds", 90 * 86400))]
    for key, value in payload.items():
        args.extend((key, str(value)))
    return client.eval(ENQUEUE, 2, spec["stream"], f"benka:slot:{slot_key}", *args)


def consume_one(client, config, handler, *, consumer=None, reclaim_ms=6_000_000):
    """A failed or recovered side-effecting job goes to reconciliation, never blind replay.

    Existing business pipelines combine cursor mutation and remote delivery. Until
    a recovered job is inspected, replay could skip or duplicate a publication.
    """
    require_active(config, "worker")
    spec = config["worker"]
    stream, group = spec["stream"], spec["group"]
    consumer = consumer or f"{socket.gethostname()}-{os.getpid()}"
    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    cursor_key = f"benka:reclaim-cursor:{stream}:{group}:{consumer}"
    cursor = client.get(cursor_key) or "0-0"
    claimed = client.xautoclaim(stream, group, consumer, reclaim_ms, cursor, count=1)
    client.set(cursor_key, claimed[0], ex=86400)
    recovered = claimed[1]
    entries = recovered
    if not entries:
        result = client.xreadgroup(group, consumer, {stream: ">"}, count=1, block=1000)
        entries = result[0][1] if result else []
    if not entries:
        return False
    entry_id, data = entries[0]
    data.setdefault("run_id", "hermes-import-" + hashlib.sha256(f"{stream}:{entry_id}".encode()).hexdigest()[:24])
    status_key = f"benka:job:{stream}:{entry_id}"
    if client.hget(status_key, "status") == "completed":
        client.xack(stream, group, entry_id)
        return True
    try:
        if recovered:
            raise RuntimeError("recovered_pending_requires_reconciliation")
        client.hset(status_key, mapping={"status": "running", "run_id": data.get("run_id", entry_id)})
        result = handler(data)
        if isinstance(result, dict) and result.get("ok") is False:
            raise RuntimeError("pipeline_reported_failure")
        client.hset(status_key, mapping={"status": "completed", "finished_at": str(int(time.time()))})
    except Exception as exc:
        # Don't include exception text: provider failures can contain credentials.
        reason = "pending_recovered" if recovered else type(exc).__name__
        with client.pipeline(transaction=True) as pipe:
            pipe.xadd("benka:reconcile", {"stream": stream, "entry_id": entry_id, "group": group,
                                       "reason": reason, "payload": json.dumps(data)})
            pipe.hset(status_key, mapping={"status": "reconcile", "reason": reason})
            pipe.xack(stream, group, entry_id)
            pipe.execute()
        return True
    client.xack(stream, group, entry_id)
    return True
