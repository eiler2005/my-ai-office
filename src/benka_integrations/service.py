"""Container entrypoint with an operator-controlled activation gate."""
import os
from pathlib import Path
import sys
import time

from .config import load_manifest, require_active


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "standby"
    config = load_manifest()
    if action == "standby":
        if config["mode"] != "standby":
            raise PermissionError("Standby container must use a standby manifest")
        print("MIGRATION_IN_PROGRESS: no polling, schedules or delivery enabled", flush=True)
        while True:
            time.sleep(30)
    commands = {"gateway": ["hermes", "gateway", "run"],
                "dashboard": ["hermes", "dashboard", "--no-open", "--skip-build", "--host", "0.0.0.0", "--port", "9119"],
                # Legacy bridge env files may define PATH.  Invoke the
                # packaged console entry point directly so that cannot hide
                # the Hermes integration worker.
                "worker": ["/opt/benka/.venv/bin/benka", "worker"],
                "wiki": [sys.executable, "/opt/benka/artifacts/wiki-import/service.py"]}
    if action not in commands:
        raise ValueError("Unknown service")
    require_active(config, action)
    if action == "wiki" and not os.environ.get("WIKI_IMPORT_TOKEN"):
        raise PermissionError("Wiki must not run without authentication")
    os.execvp(commands[action][0], commands[action])


if __name__ == "__main__":
    main()
