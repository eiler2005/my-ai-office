#!/usr/bin/env python3
"""Run before/after restarting a disposable Redis on an internal Docker network."""
import json
import subprocess
import sys
import time

import redis

from benka_integrations.delivery import send
from benka_integrations.queue import consume_one, enqueue


def main():
    client = redis.Redis(host="redis", decode_responses=True, socket_timeout=3)
    for attempt in range(30):
        try:
            client.ping()
            break
        except redis.ConnectionError:
            time.sleep(1)
    config = {"mode": "rehearsal", "domain": "sandbox", "data_class": "test", "production_connections": False,
              "enabled_operations": ["enqueue", "worker", "send"], "delivery_targets": ["telegram:101"],
              "worker": {"stream": "fixture:jobs", "group": "fixture-workers"},
              "jobs": {"poll": {"stream": "fixture:jobs", "payload": {"job_type": "poll"}}}}
    if sys.argv[1] == "prepare":
        assert client.dbsize() == 0, "Refuse any non-empty Redis; use a fresh disposable volume"
        first = enqueue(client, config, "poll", "fixture-slot")
        client.set("fixture:first", first)
        consume_one(client, config, lambda data: {"ok": True})
        client.xadd("fixture:jobs", {"file_path": "wiki/page.md"})  # Old envelope without run_id.
        client.xreadgroup("fixture-workers", "dead-worker", {"fixture:jobs": ">"})
        reply = subprocess.CompletedProcess([], 0, json.dumps({"success": True, "message_id": "fixture-confirmed"}), "")
        send(client, config, delivery_id="fixture-delivery", target="telegram:101", text="fixture",
             runner=lambda *args, **kwargs: reply)
        assert client.xpending("fixture:jobs", "fixture-workers")["pending"] == 1
    else:
        assert enqueue(client, config, "poll", "fixture-slot") == client.get("fixture:first")
        assert client.xlen("fixture:jobs") == 2
        def forbidden(*args, **kwargs):
            raise AssertionError("A recovered side effect must not be replayed")
        consume_one(client, config, forbidden, reclaim_ms=0)
        assert client.xlen("benka:reconcile") == 1
        assert client.xpending("fixture:jobs", "fixture-workers")["pending"] == 0
        receipt = send(client, config, delivery_id="fixture-delivery", target="telegram:101", text="fixture", runner=forbidden)
        assert receipt["message_id"] == "fixture-confirmed"
    print("PASS: real Redis " + sys.argv[1])


if __name__ == "__main__":
    main()
