from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import archive, migration
from .config import load_manifest


def main():
    parser = argparse.ArgumentParser(description="Benka Hermes candidate operations; no automatic cutover")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    registry = sub.add_parser("jobs-prepare")
    registry.add_argument("reviewed_source", type=Path)
    profiles = sub.add_parser("profiles-prepare")
    profiles.add_argument("bindings", type=Path)
    profiles.add_argument("destination", type=Path)
    profiles.add_argument("--repo", required=True, type=Path)
    cron = sub.add_parser("cron-prepare")
    cron.add_argument("hermes_home", type=Path)
    export = sub.add_parser("snapshot")
    export.add_argument("source", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--cold-receipt", required=True, type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("manifest", type=Path)
    restore.add_argument("destination", type=Path)
    restore.add_argument("--apply", action="store_true", help="Default is checksum verification only")
    idx = sub.add_parser("archive-index")
    idx.add_argument("source", type=Path)
    idx.add_argument("database", type=Path)
    search = sub.add_parser("archive-search")
    search.add_argument("database", type=Path)
    search.add_argument("query")
    claw = sub.add_parser("claw-layout")
    claw.add_argument("config", type=Path)
    claw.add_argument("curated_workspace", type=Path)
    claw.add_argument("destination", type=Path)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("job")
    enqueue.add_argument("--slot", required=True, help="Stable schedule slot or request ID")
    sub.add_parser("worker")
    rollback = sub.add_parser("rollback-delta")
    rollback.add_argument("baseline_vault", type=Path)
    rollback.add_argument("hermes_vault", type=Path)
    rollback.add_argument("old_vault", type=Path)
    args = parser.parse_args()
    if args.command == "jobs-prepare":
        from .job_registry import build
        result = build(json.loads(args.reviewed_source.read_text()))
    elif args.command == "profiles-prepare":
        from .profiles import prepare
        result = prepare(json.loads(args.bindings.read_text()), args.destination, repo=args.repo)
    elif args.command == "rollback-delta":
        result = migration.rollback_delta(args.baseline_vault, args.hermes_vault, args.old_vault)
    elif args.command == "cron-prepare":
        from .schedules import sync
        result = sync(load_manifest(), args.hermes_home)
    elif args.command == "snapshot":
        result = migration.snapshot(args.source, args.output, cold_receipt=args.cold_receipt)
    elif args.command == "restore":
        result = migration.restore(args.archive, args.manifest, args.destination, dry_run=not args.apply)
    elif args.command == "archive-index":
        result = archive.index(args.source, args.database)
    elif args.command == "archive-search":
        result = archive.search(args.database, args.query)
    elif args.command == "claw-layout":
        result = migration.prepare_claw_layout(args.config, args.curated_workspace, args.destination)
    elif args.command == "status":
        cfg = load_manifest()
        result = {"mode": cfg["mode"], "domain": cfg["domain"], "automatic_cutover": False}
    elif args.command == "enqueue":
        from .queue import connection, enqueue as put
        cfg = load_manifest()
        result = {"entry_id": put(connection(cfg), cfg, args.job, args.slot)}
    else:
        from .pipelines import execute
        from .queue import connection, consume_one
        cfg = load_manifest()
        client = connection(cfg)
        while True:
            # Re-read the operator manifest: revoking activation stops consumption.
            cfg = load_manifest()
            consume_one(client, cfg, lambda data: execute(cfg, data))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
