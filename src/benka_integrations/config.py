from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

DOMAINS = {"personal", "work", "family", "sandbox"}


class DeploymentError(RuntimeError):
    """A deployment or configuration fault an operator can act on.

    Raised instead of a bare OSError so the tool layer can report *which* file is
    missing and what to check. A tool that can only answer "FileNotFoundError"
    makes every environment fault undiagnosable from the chat surface.

    The message names paths and configuration keys, never credential values.
    """

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        super().__init__(message)
        self.remedy = remedy


def credential(config: dict, name: str, default_env: str) -> str:
    """Profile-scoped secret files avoid process-global env leakage in multiplexing."""
    path = config.get(name + "_file")
    if path:
        try:
            value = Path(path).read_text().strip()
        except FileNotFoundError:
            raise DeploymentError(
                f"Credential file for '{name}' is missing at {path}",
                remedy="Mount this domain's profile-secrets directory read-only into the "
                       "container, or correct the '_file' path in the domain manifest.",
            ) from None
        except PermissionError:
            raise DeploymentError(
                f"Credential file for '{name}' at {path} is not readable by the runtime user",
                remedy="The runtime runs as UID/GID 1000. Fix ownership on the mounted file.",
            ) from None
    else:
        variable = config.get(name + "_env", default_env)
        try:
            value = os.environ[variable]
        except KeyError:
            raise DeploymentError(
                f"Credential for '{name}' is not configured: "
                f"no '{name}_file' in the manifest and no {variable} in the environment",
                remedy="Prefer a profile-scoped '_file' path; process-global environment "
                       "variables leak between multiplexed profiles.",
            ) from None
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
    try:
        raw = path.read_text()
    except FileNotFoundError:
        raise DeploymentError(
            f"Domain manifest not found at {path}",
            remedy="The gateway mounts the private manifest directory read-only as "
                   "/run/benka/profiles/. Check that the mount exists and that the profile's "
                   "manifest_path points at /run/benka/profiles/<domain>.json.",
        ) from None
    except IsADirectoryError:
        raise DeploymentError(
            f"Domain manifest path {path} is a directory, not a file",
            remedy="manifest_path must name one domain's JSON file, "
                   "not the mounted directory.",
        ) from None
    except PermissionError:
        raise DeploymentError(
            f"Domain manifest at {path} is not readable by the runtime user",
            remedy="The runtime runs as UID/GID 1000. Fix ownership on the mounted manifest.",
        ) from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeploymentError(
            f"Domain manifest at {path} is not valid JSON (line {exc.lineno}, column {exc.colno})",
            remedy="Regenerate it with 'benka profiles-prepare' rather than editing by hand.",
        ) from None
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
        try:
            data = json.loads(receipt.read_text())
        except FileNotFoundError:
            raise DeploymentError(
                f"Activation receipt not found at {receipt}",
                remedy="An operator creates the receipt after a separate owner instruction. "
                       "It is an operational interlock, not something to generate to get unblocked.",
            ) from None
        except json.JSONDecodeError:
            raise DeploymentError(
                f"Activation receipt at {receipt} is not valid JSON",
                remedy="Recreate the receipt; do not edit it by hand.",
            ) from None
        expected = digest(Path(config["_manifest_path"]))
        if (data.get("command") != "ACTIVATE_HERMES_BY_DENIS"
                or data.get("manifest_sha256") != expected
                or not data.get("snapshot_sha256")
                or data.get("old_writers_stopped") is not True):
            raise PermissionError("A separate owner activation receipt for this manifest is required")
    else:
        raise PermissionError("This instance is in standby and does not own production")
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
