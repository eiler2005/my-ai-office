"""Retain the original pinned Last30Days GitHub-source environment adaptation."""
from pathlib import Path
import sys


def patch(root: Path):
    path = root / "scripts/lib/env.py"
    text = path.read_text()
    needle = "        ('BSKY_APP_PASSWORD', None),\n"
    insert = "        ('GITHUB_TOKEN', None),\n"
    if insert not in text:
        if needle not in text:
            raise ValueError("Pinned Last30Days environment contract changed")
        path.write_text(text.replace(needle, needle + insert, 1))


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
