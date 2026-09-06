"""Durable delivery journal. Unknown outcomes require human reconciliation."""
from __future__ import annotations

import hashlib
import json
import subprocess

from .config import require_active


class UncertainDelivery(RuntimeError):
    pass


def send(client, config, *, delivery_id: str, target: str, text: str, runner=subprocess.run):
    require_active(config, "send")
    if target not in config.get("delivery_targets", []):
        raise PermissionError("Destination is not in this domain's allowlist")
    key = "benka:delivery:" + hashlib.sha256(delivery_id.encode()).hexdigest()
    fingerprint = hashlib.sha256((target + "\0" + text).encode()).hexdigest()
    claim = json.dumps({"status": "sending", "fingerprint": fingerprint})
    if not client.set(key, claim, nx=True):
        previous = json.loads(client.get(key))
        if previous.get("fingerprint") != fingerprint:
            raise ValueError("Delivery identifier reused for different content")
        if previous.get("status") == "confirmed":
            return previous
        raise UncertainDelivery("Delivery already attempted; inspect journal before retrying")
    try:
        result = runner(["hermes", "send", "--to", target, "--file", "-", "--json"],
                        input=text, text=True, capture_output=True, timeout=90, check=False)
        payload = json.loads(result.stdout)
        message_id = payload.get("message_id")
        if result.returncode or payload.get("success") is not True or payload.get("skipped") or not message_id:
            raise ValueError("No confirmed message identifier")
    except Exception:
        client.set(key, json.dumps({"status": "uncertain", "fingerprint": fingerprint}))
        raise UncertainDelivery("Delivery outcome unknown; automatic resend is disabled") from None
    receipt = {"status": "confirmed", "fingerprint": fingerprint,
               "message_id": str(message_id), "target": target}
    client.set(key, json.dumps(receipt))
    return receipt
