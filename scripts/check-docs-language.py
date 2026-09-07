#!/usr/bin/env python3
"""Fail if Cyrillic text appears outside the documented exceptions.

The repository is English (CONTRIBUTING.md#language). Three exceptions are
deliberate and are excluded here rather than silently tolerated everywhere:

  workspace/**        prompt artifacts mounted into the running agent
  docs/archive/**     a historical record of the predecessor system
  CHANGELOG.md        records what actually shipped, including Russian names
  artifacts/openclaw/ redacted predecessor config, including pinned message text

Within the checked files, a small set of tokens is allowed because they are
quoted deliberately: the `обсуди:` trigger keyword and the assistant's name.

    python3 scripts/check-docs-language.py

Exit code 0 when clean, 1 otherwise.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDE = [
    ":!:workspace/**",
    ":!:docs/archive/**",
    ":!:vendor/**",
    ":!:CHANGELOG.md",
    ":!:artifacts/openclaw/**",
]

# Quoted on purpose: a literal user-facing command, and the assistant's name.
ALLOWED = ("обсуди", "Бенька", "Беньки", "Беньке", "Беньку", "Бенькой")

CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def main() -> int:
    files = subprocess.run(
        ["git", "ls-files", "*.md", *EXCLUDE],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()

    offenders: list[tuple[str, int, str]] = []
    for rel in files:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in ALLOWED:
            text = text.replace(token, "")
        hits = CYRILLIC.findall(text)
        if hits:
            sample = "".join(dict.fromkeys(hits))[:40]
            offenders.append((rel, len(hits), sample))

    for rel, count, sample in offenders:
        print(f"::error file={rel}::unexpected Cyrillic text "
              f"({count} characters, e.g. {sample})")

    if offenders:
        print(f"\n{len(offenders)} file(s) contain undocumented Cyrillic text")
        return 1
    print(f"{len(files)} Markdown files are English "
          f"apart from the documented exceptions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
