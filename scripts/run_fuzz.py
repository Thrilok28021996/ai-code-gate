#!/usr/bin/env python3
"""
Runs atheris fuzz harnesses from a list file, captures crashes,
and produces a markdown report + a crash flag file.

The crash flag file (--score-output) contains '1' if any crash was found,
'0' otherwise. CI reads this file in a subsequent step instead of re-running
the harnesses a second time.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_harness(harness: str, timeout: int, corpus_dir: str, artifacts_dir: str) -> dict:
    """Run a single atheris harness and return a result dict."""
    result: dict = {
        "harness": harness,
        "crashed": False,
        "crash_input": None,
        "output": "",
        "timed_out": False,
    }

    # Per-harness sub-corpus so harnesses don't share (and corrupt) each other's seeds
    harness_corpus = Path(corpus_dir) / Path(harness).stem
    harness_corpus.mkdir(parents=True, exist_ok=True)

    artifacts_path = Path(artifacts_dir)
    artifacts_path.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            [
                sys.executable,
                harness,
                str(harness_corpus),
                f"-max_total_time={timeout}",
                "-print_final_stats=1",
                f"-artifact_prefix={artifacts_path}/",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 15,  # wall-clock headroom beyond LibFuzzer budget
        )
        # Capture last 2k chars of combined output for the report
        result["output"] = (proc.stdout + proc.stderr)[-2000:]

        # atheris/LibFuzzer signals a crash via non-zero exit + summary line
        if proc.returncode != 0 and "LibFuzzer: crash" in result["output"]:
            result["crashed"] = True
            crash_files = sorted(artifacts_path.glob("crash-*"))
            if crash_files:
                result["crash_input"] = crash_files[0].read_bytes().hex()[:100]

    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        result["output"] = f"Harness exceeded {timeout + 15}s wall-clock limit"

    return result


def build_report(results: list[dict], timeout: int) -> str:
    crashes = [r for r in results if r["crashed"]]
    timeouts = [r for r in results if r["timed_out"]]

    lines = [
        "## Fuzz Testing Report",
        "",
        f"Ran **{len(results)}** harness(es) × {timeout}s each.",
        "",
        "| Harness | Result | Notes |",
        "|---------|--------|-------|",
    ]

    for r in results:
        if r["crashed"]:
            status = "CRASH"
            note = (
                f"Input prefix: `{r['crash_input']}`"
                if r["crash_input"]
                else "Artifact saved to fuzz-artifacts/"
            )
        elif r["timed_out"]:
            status = "Timeout"
            note = "Wall-clock exceeded"
        else:
            status = "Clean"
            note = "No crash within time budget"
        lines.append(f"| `{r['harness']}` | {status} | {note} |")

    lines.append("")

    if crashes:
        lines.append(
            f"> **{len(crashes)} crash(es) found.** "
            "Reproduce locally: `python <harness> fuzz-corpus/ fuzz-artifacts/<crash-file>`"
        )
    elif timeouts:
        lines.append(
            f"> {len(timeouts)} harness(es) timed out — increase `--timeout` for deeper coverage."
        )
    else:
        lines.append("> No crashes found within the time budget.")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run atheris fuzz harnesses and report crashes")
    parser.add_argument("--targets", required=True, help="File listing harness paths, one per line")
    parser.add_argument("--timeout", type=int, default=30, help="Seconds per harness")
    parser.add_argument(
        "--corpus-dir",
        default="fuzz-corpus",
        help="Root directory for per-harness corpus seeds (persisted between runs)",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="fuzz-artifacts",
        help="Directory for crash artifacts",
    )
    parser.add_argument("--output", default=None, help="Write markdown report to this file")
    parser.add_argument(
        "--score-output",
        default=None,
        help="Write '1' (crashed) or '0' (clean) to this file for CI consumption",
    )
    parser.add_argument(
        "--fail-on-crash",
        action="store_true",
        help="Exit 1 if any crash was found",
    )
    args = parser.parse_args()

    targets_path = Path(args.targets)
    if not targets_path.exists():
        print(f"Targets file not found: {args.targets}")
        sys.exit(1)

    harnesses = [
        h.strip()
        for h in targets_path.read_text().splitlines()
        if h.strip() and not h.startswith("#")
    ]

    if not harnesses:
        print("No fuzz targets to run.")
        if args.score_output:
            Path(args.score_output).write_text("0")
        return

    results = []
    for h in harnesses:
        print(f"Fuzzing {h} for {args.timeout}s …", flush=True)
        results.append(run_harness(h, args.timeout, args.corpus_dir, args.artifacts_dir))

    report = build_report(results, args.timeout)
    any_crash = any(r["crashed"] for r in results)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Fuzz report written to {args.output}")

    if args.score_output:
        Path(args.score_output).write_text("1" if any_crash else "0")

    print(report)

    if args.fail_on_crash and any_crash:
        sys.exit(1)


if __name__ == "__main__":
    main()
