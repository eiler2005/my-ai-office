"""Durable delivery journal. Unknown outcomes require human reconciliation."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import require_active


class UncertainDelivery(RuntimeError):
    pass


def _journal_key(delivery_id: str) -> str:
    return "benka:delivery:" + hashlib.sha256(delivery_id.encode()).hexdigest()


def receipt_status(client, delivery_id: str) -> str | None:
    raw = client.get(_journal_key(delivery_id))
    return json.loads(raw)["status"] if raw else None


def send(client, config, *, delivery_id: str, target: str, text: str, runner=subprocess.run):
    require_active(config, "send")
    if target not in config.get("delivery_targets", []):
        raise PermissionError("Destination is not in this domain's allowlist")
    key = _journal_key(delivery_id)
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
        hermes_cli = Path(sys.executable).with_name("hermes")
        command = str(hermes_cli) if hermes_cli.is_file() else "hermes"
        source_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().absolute()
        # Workers mount the gateway's Hermes home read-only. The CLI still needs
        # a writable runtime area for bootstrap state during standalone delivery.
        with tempfile.TemporaryDirectory(prefix="benka-delivery-") as temporary:
            home = Path(temporary)
            for name in (".env", "config.yaml"):
                source = source_home / name
                if source.is_file():
                    (home / name).symlink_to(source)
            environment = dict(os.environ, HERMES_HOME=str(home), HERMES_DISABLE_LAZY_INSTALLS="1")
            environment.pop("HERMES_PROFILE", None)
            result = runner([command, "send", "--to", target, "--file", "-", "--json"],
                            input=text, text=True, capture_output=True, timeout=90, check=False,
                            env=environment)
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
