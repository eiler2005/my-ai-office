#!/usr/bin/env python3
"""Native OpenClaw importer rehearsal on synthetic data, inside an offline VPS container."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from benka_integrations.migration import prepare_claw_layout


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def main():
    with tempfile.TemporaryDirectory(prefix="benka-native-claw-") as temporary:
        root = Path(temporary)
        source, curated, layout, target = [root / name for name in ("source-config", "curated", "layout", "hermes")]
        source.mkdir()
        curated.mkdir()
        target.mkdir()
        (source / "openclaw.json").write_text(json.dumps({"fixture_private_setting": "not-for-import"}))
        (source / ".env").write_text("FIXTURE=not-for-import\n")
        markers = {"SOUL.md": "BENKA_REHEARSAL_PERSONALITY", "USER.md": "BENKA_REHEARSAL_USER",
                   "MEMORY.md": "BENKA_REHEARSAL_COMPACT_MEMORY"}
        for name, marker in markers.items():
            (curated / name).write_text(marker + "\n")
        prepare_claw_layout(source, curated, layout)
        before = hashes(layout)
        environment = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG"}}
        environment.update({"HERMES_HOME": str(target), "HERMES_DISABLE_UPDATE_CHECK": "1"})
        base = ["hermes", "claw", "migrate", "--source", str(layout), "--preset", "user-data", "--yes"]

        def invoke(*extra):
            result = subprocess.run([*base, *extra], env=environment, cwd=root, capture_output=True, text=True, timeout=90)
            assert result.returncode == 0, "Native importer process failed"
            assert "Migration script not found" not in result.stdout, "Native importer asset is missing"
            return result.stdout

        def imported():
            return {str(path.relative_to(target)): path.read_text() for path in target.rglob("*.md")
                    if path.parent == target or path.parent == target / "memories"}

        invoke("--dry-run")
        assert not any(marker in text for text in imported().values() for marker in markers.values()), "Dry-run imported data"
        # The pinned CLI bootstraps a default SOUL even in dry-run. It refuses
        # the entire apply on that conflict, while still returning exit code 0.
        invoke()
        assert not any(marker in text for text in imported().values() for marker in markers.values())
        invoke("--dry-run", "--overwrite")
        output = invoke("--overwrite")  # Only this new, synthetic target; retain native backup.
        data = imported()
        for marker in markers.values():
            if not any(marker in text for text in data.values()):
                print(output[-6000:])  # This rehearsal contains only synthetic markers.
                raise AssertionError("Native import did not preserve " + marker)
        assert not (target / ".env").exists() or "not-for-import" not in (target / ".env").read_text()
        invoke()
        assert imported() == data, "Repeated native import changed reviewed data"
        assert hashes(layout) == before, "Native importer modified source layout"
        assert list((target / "backups").glob("*.zip")), "Native restore-point archive missing"
    print(json.dumps({"native_claw_dry_run": True, "user_data_import": True, "repeat_preserves_data": True,
                      "source_unchanged": True, "private_config_excluded": True, "pre_import_backup": True,
                      "dataset": "synthetic", "production_state_tested": False}))


if __name__ == "__main__":
    main()
