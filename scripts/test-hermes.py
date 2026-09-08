#!/usr/bin/env python3
"""Run each legacy service in its own interpreter (module names overlap)."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

# Keyed by functional area rather than by directory, so a run can be narrowed to
# the part of the system a change actually touched.
SUITES = {
    "hermes": ("tests/hermes", "Hermes core: safety gates, entrypoints, dispatch, cutover"),
    "email": ("artifacts/agentmail-email/tests", "AgentMail: poll prefilter, digest rendering"),
    "telegram": ("artifacts/telethon-digest/tests", "Telethon digest: read, score, summarise, post"),
    "signals": ("artifacts/signals-bridge/tests", "Signals and Last30Days: matching, delivery, state"),
    "wiki": ("artifacts/wiki-import/tests", "Wiki import: importer and embeddings"),
}


def main():
    parser = argparse.ArgumentParser(description="Offline test runner; one interpreter per suite")
    parser.add_argument("--suite", action="append", choices=sorted(SUITES), metavar="NAME",
                        help="Run only this suite; repeatable. Default is all of them.")
    parser.add_argument("--list", action="store_true", help="List the suites and exit")
    args = parser.parse_args()
    if args.list:
        for name, (path, description) in SUITES.items():
            print(f"{name:<9} {path:<38} {description}")
        return 0

    selected = args.suite or list(SUITES)
    results = {}
    with tempfile.TemporaryDirectory(prefix="benka-test-") as temporary:
        # Tests may import dotenv-aware business modules. An explicit clean env
        # and cwd prevent accidental use of a developer's production credentials.
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR") if key in os.environ}
        env.update(HERMES_HOME=temporary, BENKA_ARTIFACTS=str(ROOT / "artifacts"),
                   PYTHONDONTWRITEBYTECODE="1", STATE_DIR=temporary, OPENCLAW_FALLBACK_ENABLED="0",
                   HERMES_MODEL_ENABLED="0")
        for name in selected:
            suite = ROOT / SUITES[name][0]
            print(f"\n=== {name}: {SUITES[name][0]} ===", flush=True)
            if not suite.is_dir():
                results[name] = "missing suite"
                continue
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", str(suite)],
                                    cwd=temporary, env=env, check=False)
            results[name] = "ok" if result.returncode == 0 else f"failed (exit {result.returncode})"

    print("\nSummary")
    for name in selected:
        print(f"  {name:<9} {results[name]}")
    failures = [name for name in selected if results[name] != "ok"]
    if failures:
        print("Failed suites: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
