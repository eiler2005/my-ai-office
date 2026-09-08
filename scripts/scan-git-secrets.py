#!/usr/bin/env python3
"""Scan every reachable Git blob plus the public working tree without echoing secrets.

detect-secrets runs with --no-verify: no discovered credential is submitted to a
provider. Detailed findings contain hashes and locations, never plaintext values.
The private report is a publication gate, not an automatic cleanup operation.
"""
import hashlib
import json
import os
import secrets
import shutil
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REVIEWED_VALUES = {
    "scripts/prepare-hermes-panel.py": {"scrypt$16384$8$1$"},  # Algorithm/parameter prefix, no salt or derived key.
    "artifacts/signals-bridge/tests/test_model_fallbacks.py": {"test-key", "reserve-key"},
    "artifacts/telethon-digest/tests/test_llm_fallbacks.py": {"test-key", "reserve-key", "test"},
    "tests/hermes/test_model_native.py": {"synthetic-local-fixture"},
    "tests/hermes/test_model_child.py": {"synthetic-provider-key"},
    "tests/hermes/test_production_prepare.py": {
        # Synthetic snapshot fixture: a container name and a placeholder model key.
        "OPENCLAW_EXEC_CONTAINER=openclaw-gateway\\n",
        "DASHSCOPE_API_KEY=synthetic-qwen-fixture\\nOPENCLAW_EXEC_CONTAINER=openclaw-gateway\\n",
    },
    "scripts/deploy-agentmail-email.sh": {
        "OPENCLAW_EXEC_CONTAINER=openclaw-openclaw-gateway-1\\n",
        "EMAIL_CONTAINER_NAME=agentmail-email-bridge\\n",
    },
}
REVIEWED_VALUES["scripts/scan-git-secrets.py"] = {
    value.replace("\\n", "\\\\n") for source in ("scripts/deploy-agentmail-email.sh",
                                                 "tests/hermes/test_production_prepare.py")
    for value in REVIEWED_VALUES[source]
}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def main():
    report_dir = ROOT / ".migration"
    report_dir.mkdir(mode=0o700, exist_ok=True)
    mapping = {}
    with tempfile.TemporaryDirectory(prefix="benka-secret-audit-") as temporary:
        temp = Path(temporary)
        objects = git("rev-list", "--objects", "--all").decode().splitlines()
        batch = subprocess.Popen(["git", "-C", str(ROOT), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for entry in objects:
                parts = entry.split(" ", 1)
                if len(parts) != 2:
                    continue
                sha, name = parts
                batch.stdin.write((sha + "\n").encode())
                batch.stdin.flush()
                header = batch.stdout.readline().decode().split()
                if len(header) != 3:
                    raise RuntimeError("Unexpected git object response")
                data = batch.stdout.read(int(header[2]))
                batch.stdout.read(1)
                if header[1] != "blob":
                    continue
                target = temp / (sha + Path(name).suffix)
                target.write_bytes(data)
                mapping[target.name] = {"blob": sha, "path": name}
        finally:
            batch.stdin.close()
            batch.wait()
        names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
        for name in names:
            path = ROOT / name
            if not name or not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
            key = "working-" + hashlib.sha256(data).hexdigest() + path.suffix
            (temp / key).write_bytes(data)
            mapping[key] = {"path": name, "working_tree": True}
        sentinel = temp / "scanner-self-test.py"
        sentinel.write_text('github_token = "' + 'ghp_' + secrets.token_hex(18) + '"\n')
        scanner = (["detect-secrets"] if shutil.which("detect-secrets") else
                   ["uv", "tool", "run", "--from", "detect-secrets==1.5.0", "detect-secrets"])
        result = subprocess.run([*scanner, "-C", str(temp), "scan", "--all-files", "--no-verify"],
                                capture_output=True, text=True, check=True)
        scan = json.loads(result.stdout)
        if not any(Path(name).name == sentinel.name for name in scan["results"]):
            raise RuntimeError("Secret scanner self-test failed; publication is blocked")
        findings = []
        for filename, items in scan["results"].items():
            if Path(filename).name == sentinel.name:
                continue
            source = mapping.get(Path(filename).name, {"path": "unknown"})
            for item in items:
                findings.append({**source, "line": item["line_number"], "type": item["type"],
                                 "hashed_secret": item["hashed_secret"]})
        report = {"git_head": git("rev-parse", "HEAD").decode().strip(), "objects_scanned": len(mapping),
                  "findings": findings, "publication_allowed": not findings,
                  "scanner": "detect-secrets==1.5.0", "network_verification": False}
        destination = report_dir / "secret-scan.json"
        for finding in findings:
            reviewed = {hashlib.sha1(value.encode()).hexdigest() for value in REVIEWED_VALUES.get(finding["path"], set())}
            finding["reviewed_false_positive"] = finding["hashed_secret"] in reviewed
        unresolved = [finding for finding in findings if not finding["reviewed_false_positive"]]
        report["publication_allowed"] = not unresolved
        report["scanner_self_test_passed"] = True
        destination.write_text(json.dumps(report, indent=2))
        os.chmod(destination, 0o600)
        print(json.dumps({"objects_scanned": len(mapping), "detector_matches": len(findings),
                          "unresolved_findings": len(unresolved), "publication_allowed": not unresolved,
                          "private_report": ".migration/secret-scan.json"}))
        for item in unresolved:
            print(json.dumps({k: item[k] for k in ("path", "line", "type")}))
        return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
