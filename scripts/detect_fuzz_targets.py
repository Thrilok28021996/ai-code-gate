#!/usr/bin/env python3
"""
Given a list of changed files and a fuzz targets registry,
emit the fuzz harness files that should run for this PR.

fuzz/targets.txt format (one mapping per line):
  <source_glob>  <fuzz_harness_file>

Example:
  src/parsers/*.py    fuzz/fuzz_parser.py
  src/auth/**         fuzz/fuzz_auth.py

Glob matching uses fnmatch.fnmatch(), which correctly handles * and **
on Python 3.12+. Note: fnmatch treats ** the same as * (any chars including
path separators) — sufficient for the directory-recursive use case here.
"""

import argparse
import fnmatch
from pathlib import Path


def load_targets(targets_file: str) -> list[tuple[str, str]]:
    mappings = []
    path = Path(targets_file)
    if not path.exists():
        return mappings
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            mappings.append((parts[0], parts[1]))
    return mappings


def matches_glob(file_path: str, glob: str) -> bool:
    """
    Return True if file_path matches glob pattern.
    Supports *, ?, and ** via fnmatch (** matches across path separators
    on Python 3.12+).
    """
    try:
        return fnmatch.fnmatch(file_path, glob)
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed", required=True, help="Newline-separated changed file paths")
    parser.add_argument("--targets", required=True, help="Path to fuzz/targets.txt")
    parser.add_argument("--output", required=True, help="Output file listing active harnesses")
    args = parser.parse_args()

    changed_files = [f.strip() for f in args.changed.splitlines() if f.strip()]
    mappings = load_targets(args.targets)

    active = set()
    for changed in changed_files:
        for glob, harness in mappings:
            if matches_glob(changed, glob):
                harness_path = Path(harness)
                if harness_path.exists():
                    active.add(harness)

    Path(args.output).write_text("\n".join(sorted(active)) + ("\n" if active else ""))
    print(f"Active fuzz targets ({len(active)}): {', '.join(sorted(active)) or 'none'}")


if __name__ == "__main__":
    main()
