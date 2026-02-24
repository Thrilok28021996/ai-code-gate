#!/usr/bin/env python3
"""
JavaScript/TypeScript complexity analyser.

Uses `escomplex-cli` (npm) to measure cyclomatic complexity for JS/TS files
and outputs a JSON summary compatible with score.py's --js-complexity flag.

Output schema:
  {
    "avg_complexity": float,
    "worst_complexity": float,
    "function_count": int,
    "high_complexity_functions": [
      {"name": str, "complexity": float, "file": str}
    ],
    "error": str | null
  }
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Directories to exclude from JS/TS analysis
JS_EXCLUDE_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "coverage",
    "__pycache__",
    ".git",
}

JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def find_js_files(src_path: str) -> list[str]:
    """Collect JS/TS files, excluding noise directories."""
    root = Path(src_path).resolve()
    files = []
    for p in root.rglob("*"):
        if p.suffix not in JS_EXTENSIONS:
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in JS_EXCLUDE_DIRS:
            continue
        files.append(str(p))
    return sorted(files)


def run_escomplex(files: list[str]) -> dict:
    """
    Run escomplex-cli on the given files and return parsed JSON output.
    Returns an empty dict if escomplex is not installed or fails.
    """
    if not files:
        return {}

    try:
        result = subprocess.run(
            ["escomplex", "--format", "json", *files],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return {"error": "escomplex-cli not installed — run: npm install -g escomplex-cli"}
    except subprocess.TimeoutExpired:
        return {"error": "escomplex timed out after 120s"}

    if result.returncode not in (0, 1):
        return {"error": f"escomplex error: {result.stderr[:200]}"}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"Could not parse escomplex output: {e}"}


def analyse(src_path: str) -> dict:
    """
    Orchestrate JS/TS complexity analysis and return a normalised summary dict.
    """
    empty_result: dict = {
        "avg_complexity": 0.0,
        "worst_complexity": 0.0,
        "function_count": 0,
        "high_complexity_functions": [],
        "error": None,
    }

    files = find_js_files(src_path)
    if not files:
        empty_result["error"] = "No JS/TS files found"
        return empty_result

    raw = run_escomplex(files)

    if "error" in raw:
        empty_result["error"] = raw["error"]
        return empty_result

    # escomplex JSON structure: {"reports": [{"path": ..., "functions": [{"name": ..., "cyclomatic": ...}]}]}
    complexities: list[float] = []
    high_cc: list[dict] = []

    for report in raw.get("reports", []):
        file_path = report.get("path", "unknown")
        for fn in report.get("functions", []):
            cc = float(fn.get("cyclomatic", 1))
            name = fn.get("name", "<anonymous>")
            complexities.append(cc)
            if cc > 10:
                high_cc.append({"name": name, "complexity": cc, "file": file_path})

    if not complexities:
        empty_result["error"] = "No functions found in JS/TS files"
        return empty_result

    avg = sum(complexities) / len(complexities)
    worst = max(complexities)

    return {
        "avg_complexity": round(avg, 2),
        "worst_complexity": round(worst, 2),
        "function_count": len(complexities),
        "high_complexity_functions": sorted(high_cc, key=lambda x: -x["complexity"])[:20],
        "error": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure JS/TS cyclomatic complexity")
    parser.add_argument("--src", default=".", help="Source directory to analyse")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    args = parser.parse_args()

    result = analyse(args.src)
    Path(args.output).write_text(json.dumps(result, indent=2))

    if result.get("error"):
        print(f"[js-complexity] Warning: {result['error']}", file=sys.stderr)
    else:
        print(
            f"[js-complexity] avg={result['avg_complexity']:.1f} "
            f"worst={result['worst_complexity']:.0f} "
            f"functions={result['function_count']}"
        )


if __name__ == "__main__":
    main()
