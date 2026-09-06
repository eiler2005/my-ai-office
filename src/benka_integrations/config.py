from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

DOMAINS = {"personal", "work", "family", "sandbox"}


def credential(config: dict, name: str, default_env: str) -> str:
    """Profile-scoped secret files avoid process-global env leakage in multiplexing."""
    path = config.get(name + "_file")
    value = Path(path).read_text().strip() if path else os.environ[config.get(name + "_env", default_env)]
    if not value:
        raise PermissionError("Required credential is missing")
    return value


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: str | Path | None = None) -> dict:
    path = Path(path or os.environ.get("BENKA_MANIFEST", "/run/benka/manifest.json"))
    data = json.loads(path.read_text())
    if data.get("schema") != 1 or data.get("mode") not in {"standby", "rehearsal", "production"}:
        raise ValueError("Invalid deployment manifest")
    if data.get("domain") not in DOMAINS:
        raise ValueError("A single explicit domain is required per runtime")
    data["_manifest_path"] = str(path.resolve())
    return data


def require_active(config: dict, operation: str) -> None:
    """No date or elapsed-time check can activate the candidate."""
    mode = config.get("mode")
    if mode == "rehearsal":
        if config.get("data_class") != "test" or config.get("production_connections") is not False:
            raise PermissionError("Rehearsal requires isolated test data and connections")
    elif mode == "production":
        receipt = Path(config["activation_receipt"])
        data = json.loads(receipt.read_text())
        expected = digest(Path(config["_manifest_path"]))
        if (data.get("command") != "ACTIVATE_HERMES_BY_DENIS"
                or data.get("manifest_sha256") != expected
                or not data.get("snapshot_sha256")
                or data.get("old_writers_stopped") is not True):
            raise PermissionError("A separate owner activation receipt for this manifest is required")
    else:
        raise PermissionError("Hermes is in standby; production remains on OpenClaw")
    if operation not in config.get("enabled_operations", []):
        raise PermissionError(f"Operation is disabled: {operation}")


def confined(root: str | Path, relative: str, *, must_exist: bool = False) -> Path:
    base = Path(root).resolve(strict=True)
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("Expected a relative path within the domain")
    result = (base / rel).resolve(strict=must_exist)
    if result == base or not result.is_relative_to(base):
        raise PermissionError("Path escapes the domain root")
    return result
