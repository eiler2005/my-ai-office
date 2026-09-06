#!/usr/bin/env python3
"""Run each legacy service in its own interpreter (module names overlap)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    failures = []
    with tempfile.TemporaryDirectory(prefix="benka-test-") as temporary:
        # Tests may import dotenv-aware business modules. An explicit clean env
        # and cwd prevent accidental use of a developer's production credentials.
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR") if key in os.environ}
        env.update(HERMES_HOME=temporary, BENKA_ARTIFACTS=str(ROOT / "artifacts"),
                   PYTHONDONTWRITEBYTECODE="1", STATE_DIR=temporary, OPENCLAW_FALLBACK_ENABLED="0",
                   HERMES_MODEL_ENABLED="0")
        suites = [ROOT / "tests/hermes"] + [ROOT / "artifacts" / name / "tests" for name in (
            "agentmail-email", "telethon-digest", "signals-bridge", "wiki-import")]
        for suite in suites:
            if not suite.is_dir():
                failures.append(str(suite.relative_to(ROOT)) + ": missing suite")
                continue
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", str(suite)],
                                    cwd=temporary, env=env, check=False)
            if result.returncode:
                failures.append(str(suite.relative_to(ROOT)))
    if failures:
        print("Failed suites: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
