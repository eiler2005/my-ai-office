#!/usr/bin/env python3
"""Export only reviewed staged Git files and the pinned public Hermes submodule."""
import argparse
import io
import os
from pathlib import Path
import subprocess
import tarfile


def git(*args, cwd=None):
    return subprocess.check_output(["git", "-c", "core.autocrlf=false", *args], cwd=cwd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tree = git("write-tree", cwd=root).decode().strip()
    pin = git("rev-parse", ":vendor/hermes-agent", cwd=root).decode().strip()
    actual = git("rev-parse", "HEAD", cwd=root / "vendor/hermes-agent").decode().strip()
    if actual != pin or git("status", "--porcelain", cwd=root / "vendor/hermes-agent").strip():
        raise ValueError("Hermes submodule must exactly match the staged pin")
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with args.output.open("xb") as raw:
        os.chmod(args.output, 0o600)
        with tarfile.open(fileobj=raw, mode="w:gz") as bundle:
            metadata = (tree + "\n").encode()
            member = tarfile.TarInfo("CANDIDATE_TREE")
            member.size, member.mode = len(metadata), 0o644
            bundle.addfile(member, io.BytesIO(metadata))
            archives = [git("archive", tree, cwd=root),
                        git("archive", "--prefix=vendor/hermes-agent/", pin, cwd=root / "vendor/hermes-agent")]
            for content in archives:
                with tarfile.open(fileobj=io.BytesIO(content)) as source:
                    for member in source:
                        # Git cannot export runtime data that was not explicitly staged.
                        bundle.addfile(member, source.extractfile(member) if member.isfile() else None)
    print("Packaged staged tree " + tree + "; Hermes " + pin)


if __name__ == "__main__":
    main()
