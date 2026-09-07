#!/usr/bin/env python3
"""Verify that internal Markdown links and heading anchors resolve.

Checks every tracked Markdown file for links whose target is a path in this
repository, and for `#anchor` fragments that must exist in the target file.
External URLs are not fetched -- this runs offline and deterministically.

Fenced code blocks are skipped, so documentation that *shows* link syntax (the
ADR template, for example) is not reported.

    python3 scripts/check-docs-links.py [--quiet]

Exit code 0 when everything resolves, 1 otherwise.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_PREFIXES = ("vendor/",)
EXTERNAL = ("http://", "https://", "mailto:", "tel:", "data:", "#", "<")

LINK_RE = re.compile(r"\]\(\s*([^)\s]+?)\s*(?:\"[^\"]*\")?\s*\)")
SRC_RE = re.compile(r'(?:src|srcset)="([^"]+)"')
HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
EXPLICIT_ANCHOR_RE = re.compile(r'<a\s+(?:id|name)="([^"]+)"')

# Placeholders that are meant to be filled in by a reader, not resolved.
PLACEHOLDER_RE = re.compile(r"[<{]|url-or-path|NNNN|YYYY")


def strip_fences(text: str) -> str:
    """Blank out fenced code blocks, preserving line numbers."""
    out, in_fence, marker = [], False, ""
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if m and not in_fence:
            in_fence, marker = True, m.group(1)
            out.append("")
            continue
        if in_fence:
            out.append("")
            if line.strip().startswith(marker):
                in_fence = False
            continue
        out.append(line)
    return "\n".join(out)


def slugify(title: str) -> str:
    """Approximate GitHub's heading-anchor algorithm."""
    s = title.strip().lower()
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_~]", "", s)
    kept = [
        ch for ch in s
        if ch.isalnum() or ch in "-_ " or unicodedata.category(ch).startswith("L")
    ]
    return "".join(kept).replace(" ", "-")


_anchor_cache: dict[Path, set[str]] = {}


def anchors_of(path: Path) -> set[str]:
    if path not in _anchor_cache:
        found: set[str] = set()
        try:
            body = strip_fences(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            _anchor_cache[path] = found
            return found
        for line in body.split("\n"):
            m = HEAD_RE.match(line)
            if m:
                found.add(slugify(m.group(2)))
        found.update(EXPLICIT_ANCHOR_RE.findall(body))
        _anchor_cache[path] = found
    return _anchor_cache[path]


def tracked_markdown() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [p for p in out if not p.startswith(SKIP_PREFIXES)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    args = ap.parse_args()

    files = tracked_markdown()
    missing: list[tuple[str, str, str]] = []
    checked = 0

    for rel in files:
        f = ROOT / rel
        body = strip_fences(f.read_text(encoding="utf-8"))
        targets = LINK_RE.findall(body) + SRC_RE.findall(body)

        for target in targets:
            if not target or target.startswith(EXTERNAL):
                continue
            if PLACEHOLDER_RE.search(target):
                continue
            path_part, _, anchor = target.partition("#")
            checked += 1

            dest = f if not path_part else (f.parent / path_part)
            if not dest.exists():
                missing.append((rel, target, "no such file"))
                continue
            if anchor and dest.is_file() and dest.suffix == ".md":
                if anchor.lower() not in anchors_of(dest):
                    missing.append((rel, target, "no such heading"))

    for rel, target, why in missing:
        print(f"{rel}: {target}  ({why})")

    if missing:
        print(f"\n{len(missing)} unresolved of {checked} internal links "
              f"in {len(files)} files")
        return 1
    if not args.quiet:
        print(f"{checked} internal links resolve across {len(files)} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
