#!/usr/bin/env python3
"""Check session and cron compatibility against a disposable copy of a Hermes home."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3


def rows(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone() == ("ok",), "SQLite integrity check failed"
        sessions = conn.execute("SELECT id FROM sessions ORDER BY id").fetchall()
        messages = conn.execute("SELECT id, session_id, role FROM messages ORDER BY id").fetchall()
    return sessions, messages


def main():
    home = Path(os.environ["HERMES_HOME"]).resolve()
    from cron.jobs import list_jobs
    from hermes_state import SessionDB

    counts = {"databases": 0, "sessions": 0, "messages": 0, "transcripts": 0}
    databases = sorted(home.glob("profiles/*/state.db"))
    if (home / "state.db").is_file():
        databases.append(home / "state.db")
    for database in databases:
        sessions, messages = rows(database)
        with closing(SessionDB(db_path=database)) as state:
            if sessions:
                assert state.get_session(sessions[-1][0]) is not None, "Session missing after open"
            if messages:
                session_id = messages[-1][1]
                assert state.get_messages_as_conversation(session_id), "Existing transcript is unreadable"
                counts["transcripts"] += 1
        assert rows(database) == (sessions, messages), "Session or message identities changed"
        counts["databases"] += 1
        counts["sessions"] += len(sessions)
        counts["messages"] += len(messages)

    jobs_file = home / "cron" / "jobs.json"
    raw_jobs = json.loads(jobs_file.read_text())["jobs"]
    expected = {job["id"]: job.get("enabled", True) for job in raw_jobs}
    loaded = {job["id"]: job.get("enabled", True) for job in list_jobs(include_disabled=True)}
    assert len(raw_jobs) == len(expected), "Duplicate job identities in input"
    assert expected == loaded, "Cron job identity or enabled state changed"
    assert counts["transcripts"] and loaded, "Expected existing sessions and cron jobs in the rehearsal copy"
    print(json.dumps({**counts, "jobs": len(loaded)}))


if __name__ == "__main__":
    main()
