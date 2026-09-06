"""Local searchable transcript archive, kept outside Git and Hermes memory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

from .config import digest


def index(source: Path, database: Path) -> dict:
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if database.is_symlink():
        raise ValueError("Archive database may not be a symlink")
    db = sqlite3.connect(database)
    os.chmod(database, 0o600)
    imported, skipped = 0, []
    try:
        db.execute("CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS skipped(source TEXT, line INTEGER, reason TEXT)")
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS conversations USING fts5(text, source UNINDEXED, line UNINDEXED)")
        for path in sorted([*source.rglob("*.jsonl"), *source.rglob("*.md")]):
            if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
                raise ValueError("Archive source may not escape its root")
            relative, sha = path.relative_to(source).as_posix(), digest(path)
            if db.execute("SELECT 1 FROM sources WHERE path=? AND sha256=?", (relative, sha)).fetchone():
                skipped.extend({"source": relative, "line": row[0], "reason": row[1]}
                               for row in db.execute("SELECT line,reason FROM skipped WHERE source=?", (relative,)))
                continue
            rows = []
            before = len(skipped)
            with path.open() as stream:
                for number, line in enumerate(stream, 1):
                    if path.suffix == ".md":
                        if line.strip():
                            rows.append((line.rstrip(), relative, number))
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        skipped.append({"source": relative, "line": number, "reason": "invalid_json"})
                        continue
                    message = entry.get("message", entry) if isinstance(entry, dict) else {}
                    if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
                        continue
                    content = message.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(str(x["text"]) for x in content if isinstance(x, dict) and x.get("type") == "text" and x.get("text"))
                    if isinstance(content, str) and content.strip():
                        rows.append((content, relative, number))
                    else:
                        skipped.append({"source": relative, "line": number, "reason": "no_text"})
            with db:
                db.execute("DELETE FROM conversations WHERE source=?", (relative,))
                db.executemany("INSERT INTO conversations(text,source,line) VALUES (?,?,?)", rows)
                db.execute("INSERT OR REPLACE INTO sources VALUES (?,?)", (relative, sha))
                db.execute("DELETE FROM skipped WHERE source=?", (relative,))
                db.executemany("INSERT INTO skipped VALUES (?,?,?)",
                               [(item["source"], item["line"], item["reason"]) for item in skipped[before:]])
            imported += len(rows)
        return {"imported_messages": imported, "skipped": skipped}
    finally:
        db.close()


def search(database: Path, query: str, limit: int = 10) -> list[dict]:
    if not query.strip() or len(query) > 500:
        raise ValueError("Expected a query of 1 to 500 characters")
    # Treat input as literal FTS phrases, not caller-controlled FTS syntax.
    expression = '"' + query.replace('"', '""') + '"'
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT snippet(conversations,0,'[',']','…',40),source,line FROM conversations "
                          "WHERE conversations MATCH ? ORDER BY rank LIMIT ?", (expression, min(max(limit, 1), 50))).fetchall()
    return [{"excerpt": row[0], "source": row[1], "line": row[2]} for row in rows]
