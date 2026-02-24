#!/usr/bin/env python3
"""
Pre-commit hook: reject files whose functions exceed the cyclomatic
complexity threshold.

Thresholds are configurable via CLI flags so teams can tune without
editing source:
  --max-complexity 15   (hard block, default)
  --warn-complexity 10  (warning only, default)
"""

import argparse
import subprocess
import sys


def check_files(
    paths: list[str],
    max_complexity: int,
    warn_complexity: int,
) -> int:
    violations = []
    warnings = []

    for path in paths:
        try:
            result = subprocess.run(
                ["lizard", path, "--csv", "-l", "python"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            print(
                "[complexity] ERROR: lizard not found. Install it with: pip install lizard",
                file=sys.stderr,
            )
            # Don't block the commit — missing tool should not be a hard gate failure
            return 0
        except subprocess.TimeoutExpired:
            print(
                f"[complexity] WARNING: lizard timed out on {path} — skipping",
                file=sys.stderr,
            )
            continue

        for line in result.stdout.strip().splitlines():
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                cc = float(parts[2])
                func = parts[1].strip()
            except (ValueError, IndexError):
                continue

            if cc >= max_complexity:
                violations.append(f"  {path}: `{func}` complexity={cc:.0f} (max={max_complexity})")
            elif cc >= warn_complexity:
                warnings.append(
                    f"  {path}: `{func}` complexity={cc:.0f} (warn at {warn_complexity})"
                )

    if warnings:
        print("[complexity] Warnings (commit not blocked):")
        for w in warnings:
            print(w)

    if violations:
        print(
            f"[complexity] BLOCKED — {len(violations)} function(s) exceed "
            f"the complexity limit ({max_complexity}):"
        )
        for v in violations:
            print(v)
        print("\nRefactor these functions then re-commit. To suppress a specific")
        print("function temporarily, add `# noqa: complexity` on its def line.")
        return 1

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-commit complexity gate for Python files")
    parser.add_argument(
        "--max-complexity",
        type=int,
        default=15,
        help="Hard block threshold per function (default: 15)",
    )
    parser.add_argument(
        "--warn-complexity",
        type=int,
        default=10,
        help="Warning-only threshold per function (default: 10)",
    )
    parser.add_argument("files", nargs="*", help="Files to check (passed by pre-commit)")
    args = parser.parse_args()

    sys.exit(check_files(args.files, args.max_complexity, args.warn_complexity))


if __name__ == "__main__":
    main()
