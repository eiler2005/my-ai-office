"""Immutable, verified imports from an explicitly quiesced source directory."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

from .config import digest

COMPONENTS = {"openclaw", "workspace", "vault", "integrations", "redis", "lightrag", "omniroute", "config", "secrets"}


def private_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise PermissionError("Migration directory must be private (0700) and not a symlink")


def snapshot(source: Path, output: Path, *, cold_receipt: Path) -> dict:
    """The caller must stop writers; this function never stops production itself."""
    source, output = source.resolve(strict=True), output.absolute()
    if output.is_relative_to(source):
        raise ValueError("Snapshot output must be outside the source")
    private_directory(output)
    receipt = json.loads(cold_receipt.read_text())
    if receipt.get("writers_stopped") is not True or receipt.get("syncthing_paused") is not True:
        raise ValueError("A cold snapshot receipt is required")
    if set(receipt.get("components", [])) != COMPONENTS:
        raise ValueError("Cold receipt must account for all components, including absent ones")
    files, skipped = {}, []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source).as_posix()
        if path.is_symlink():
            raise ValueError("Source contains a symlink; materialize and review it before export")
        if path.parts[len(source.parts)] not in COMPONENTS:
            skipped.append(rel)
        elif path.is_file():
            files[rel] = {"sha256": digest(path), "size": path.stat().st_size}
        elif not path.is_dir():
            raise ValueError("Source contains a non-regular file")
    if not files or skipped:
        raise ValueError(f"Snapshot incomplete: files={len(files)}, unclassified={len(skipped)}")
    manifest = {"schema": 1, "kind": "cold", "files": files,
                "absent_components": sorted(COMPONENTS - {p.split('/')[0] for p in files}),
                "receipt": receipt, "skipped": skipped}
    final = output / "snapshot.tar"
    if final.exists() or (output / "manifest.json").exists():
        raise FileExistsError("Use a new export directory for every snapshot")
    with tempfile.NamedTemporaryFile(dir=output, prefix=".archive-", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with tarfile.open(temporary, "w") as archive:
            for rel in files:
                archive.add(source / rel, arcname=rel, recursive=False)
        # Detect changes during packing. The receipt is not a substitute for this.
        for rel, spec in files.items():
            if digest(source / rel) != spec["sha256"]:
                raise ValueError("Source changed during export")
        manifest["archive_sha256"] = digest(temporary)
        verify(temporary, manifest)
        temporary.rename(final)
        manifest_path = output / "manifest.json"
        with manifest_path.open("x") as stream:
            os.chmod(manifest_path, 0o600)
            json.dump(manifest, stream, indent=2)
        return {"files": len(files), "archive_sha256": manifest["archive_sha256"], "skipped": 0}
    finally:
        temporary.unlink(missing_ok=True)


def verify(archive_path: Path, manifest: dict, *, max_bytes: int = 500 * 1024**3):
    import hashlib
    if manifest.get("schema") != 1 or manifest.get("kind") != "cold" or manifest.get("skipped"):
        raise ValueError("Unsupported or incomplete snapshot manifest")
    if digest(archive_path) != manifest.get("archive_sha256"):
        raise ValueError("Archive checksum mismatch")
    seen, total = set(), 0
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or not path.parts or path.parts[0] not in COMPONENTS
                    or str(path) != member.name or member.name in seen):
                raise ValueError("Unsafe or duplicate archive member")
            spec = manifest["files"].get(member.name)
            total += member.size
            if not spec or member.size != spec["size"] or total > max_bytes:
                raise ValueError("Unexpected archive member or size limit")
            h = hashlib.sha256()
            with archive.extractfile(member) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != spec["sha256"]:
                raise ValueError("Member checksum mismatch")
            seen.add(member.name)
    if seen != set(manifest["files"]):
        raise ValueError("Snapshot is missing files")


def restore(archive_path: Path, manifest_path: Path, destination: Path, *, dry_run: bool = True):
    manifest = json.loads(manifest_path.read_text())
    verify(archive_path, manifest)
    key = manifest["archive_sha256"]
    result = {"snapshot_sha256": key, "files": len(manifest["files"]), "skipped": 0, "dry_run": dry_run}
    if dry_run:
        return result
    private_directory(destination)
    final = destination / key
    if final.exists():
        if final.is_symlink():
            raise ValueError("Existing import must not be a symlink")
        # Re-running never silently accepts a modified prior import.
        for rel, spec in manifest["files"].items():
            target = final / rel
            if (not target.resolve().is_relative_to(final.resolve()) or target.is_symlink()
                    or not target.is_file() or digest(target) != spec["sha256"]):
                raise ValueError("Existing import differs from this snapshot")
        result["already_imported"] = True
        return result
    available = shutil.disk_usage(destination).free
    if available < sum(f["size"] for f in manifest["files"].values()) * 1.1:
        raise OSError("Insufficient disk space for import")
    staging = Path(tempfile.mkdtemp(prefix=".import-", dir=destination))
    try:
        with tarfile.open(archive_path, "r:") as archive:
            for member in archive:
                relative = PurePosixPath(member.name)
                if (not member.isfile() or relative.is_absolute() or ".." in relative.parts
                        or member.name not in manifest["files"]):
                    raise ValueError("Archive changed after verification")
                target = staging / member.name
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(member) as src, target.open("xb") as dst:
                    os.chmod(target, 0o600)
                    shutil.copyfileobj(src, dst)
                if digest(target) != manifest["files"][member.name]["sha256"]:
                    raise ValueError("Restored member checksum mismatch")
        (staging / "IMPORT_RECEIPT.json").write_text(json.dumps(result, indent=2))
        os.chmod(staging / "IMPORT_RECEIPT.json", 0o600)
        staging.rename(final)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return result


def prepare_claw_layout(config_root: Path, curated_workspace: Path, destination: Path):
    """Only an explicitly curated workspace is eligible for the native importer.

    Complete journals and sessions belong in the searchable archive, not memory.
    Config (including credentials) is not copied to the user-data import staging.
    """
    if destination.exists():
        raise FileExistsError("Use an empty layout directory")
    for name, limit in (("MEMORY.md", 2200), ("USER.md", 1375)):
        path = curated_workspace / name
        if path.exists() and len(path.read_text()) > limit:
            raise ValueError(f"Curate {name} to {limit} characters before import")
    if (curated_workspace / "memory").exists():
        raise ValueError("Daily memory journals must go into the archive")
    private_directory(destination)
    workspace = destination / "workspace"
    workspace.mkdir(mode=0o700)
    copied = []
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md", "AGENTS.md"):
        src = curated_workspace / name
        if src.exists():
            if src.is_symlink() or not src.is_file():
                raise ValueError("Only regular curated files are accepted")
            shutil.copyfile(src, workspace / name)
            os.chmod(workspace / name, 0o600)
            copied.append(name)
    # Native user-data import discovers workspace relative to the source config.
    (destination / "openclaw.json").write_text(json.dumps({"agents": {"defaults": {"workspace": str(workspace)}}}))
    os.chmod(destination / "openclaw.json", 0o600)
    return {"copied": copied, "skills_require_review": True, "source_config_present": config_root.is_dir()}


def rollback_delta(baseline: Path, current: Path, old_runtime: Path) -> dict:
    """Three-way file comparison before reverse transfer; never overwrites data.

    Only portable vault artifacts are eligible for this report. Redis state and
    deliveries need semantic reconciliation; copying an RDB backwards loses new
    pending/confirmed states and is deliberately not provided as a merge.
    """
    def inventory(root):
        result = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Rollback roots may not contain symlinks")
            if path.is_file():
                result[path.relative_to(root).as_posix()] = digest(path)
        return result
    base, new, old = map(inventory, (baseline, current, old_runtime))
    result = {"copy_from_hermes": [], "already_equal": [], "conflicts": [], "deletions_require_review": []}
    for path in sorted(set(base) | set(new)):
        if new.get(path) == base.get(path):
            continue
        if path not in new:
            result["deletions_require_review"].append(path)
        elif new.get(path) == old.get(path):
            result["already_equal"].append(path)
        elif old.get(path) == base.get(path):
            result["copy_from_hermes"].append(path)
        else:
            result["conflicts"].append(path)
    return result
