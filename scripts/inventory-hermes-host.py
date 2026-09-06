#!/usr/bin/env python3
"""Read-only host inventory. No environment values, addresses or cron command bodies."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import socket
import subprocess


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=45).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["source", "target"], required=True)
    args = parser.parse_args()
    report = {"role": args.role, "timestamp": datetime.now(timezone.utc).isoformat(),
              "architecture": platform.machine(), "cpu": __import__("os").cpu_count(), "containers": []}
    report["disk_opt"] = dict(zip(("total", "used", "free"), shutil.disk_usage("/opt")))
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            memory[key] = int(value.split()[0]) * 1024
    report["memory"] = memory
    ids = run(["docker", "ps", "-aq"]).splitlines()
    containers = json.loads(run(["docker", "inspect", *ids])) if ids else []
    for item in containers:
        labels = item["Config"].get("Labels") or {}
        report["containers"].append({"name": item["Name"].lstrip("/"), "project": labels.get("com.docker.compose.project"),
            "image_ref": item["Config"]["Image"], "image_id": item["Image"], "status": item["State"]["Status"],
            "health": item["State"].get("Health", {}).get("Status"),
            "memory_limit": item["HostConfig"].get("Memory"),
            "mounts": [{"destination": m["Destination"], "type": m["Type"], "writable": m.get("RW")} for m in item["Mounts"]],
            "environment_names": sorted(e.split("=", 1)[0] for e in item["Config"].get("Env", []))})
    report["ports"] = {}
    for port in (80, 443, 8450, 8451, 9119):
        with socket.socket() as sock:
            try:
                sock.bind(("0.0.0.0", port))
                report["ports"][str(port)] = "available"
            except OSError:
                report["ports"][str(port)] = "occupied_or_denied"
    if args.role == "source":
        report["openclaw_cron"] = []
        for path in Path("/opt/openclaw/config").glob("**/cron/jobs.json"):
            raw = json.loads(path.read_text())
            for job in raw.get("jobs", []) if isinstance(raw, dict) else raw:
                report["openclaw_cron"].append({"identity_sha256": hashlib.sha256(str(job.get("id", "")).encode()).hexdigest(),
                    "enabled": job.get("enabled"), "schedule": job.get("schedule"),
                    "session_target": job.get("sessionTarget")})
        report["system_cron_files"] = []
        cron = Path("/etc/cron.d")
        for path in sorted(cron.iterdir()):
            if path.is_file():
                report["system_cron_files"].append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        report["component_kib"] = {}
        for name, location in {"openclaw": "/opt/openclaw/config", "workspace": "/opt/openclaw/workspace",
                "vault": "/opt/obsidian-vault", "lightrag": "/opt/lightrag/data",
                "telegram": "/opt/telethon-digest", "signals": "/opt/signals-bridge"}.items():
            path = Path(location)
            try:
                report["component_kib"][name] = int(run(["du", "-sk", str(path)]).split()[0]) if path.exists() else None
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                report["component_kib"][name] = "unverified: access or timeout"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
