#!/usr/bin/env python3
"""
Maintainability Score Calculator
Produces a 0-100 score from three signals:
  - Code complexity (lizard / escomplex) → 40 pts max
  - Test coverage (coverage.py)          → 35 pts max
  - Anti-pattern density (semgrep)       → 25 pts max

Score is written to --score-output (a plain number) so CI can read it in a
subsequent step without re-running the full analysis.

Thresholds can be set via:
  1. CLI flags (highest priority)
  2. pyproject.toml [tool.ai-gate] section (--config flag)
  3. Built-in defaults (lowest priority)
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Default thresholds — override via CLI flags or pyproject.toml [tool.ai-gate]
# ---------------------------------------------------------------------------
DEFAULT_COMPLEXITY_EXCELLENT = 5  # avg cyclomatic complexity → full 40 pts
DEFAULT_COMPLEXITY_ACCEPTABLE = 10  # → 20 pts
DEFAULT_COMPLEXITY_POOR = 20  # → 0 pts

DEFAULT_COVERAGE_EXCELLENT = 90  # % branch+line coverage → full 35 pts
DEFAULT_COVERAGE_ACCEPTABLE = 70  # → 17.5 pts
DEFAULT_COVERAGE_POOR = 40  # → 0 pts

DEFAULT_ANTIPATTERN_EXCELLENT = 0  # findings per 100 LOC → full 25 pts
DEFAULT_ANTIPATTERN_ACCEPTABLE = 2  # → 12.5 pts
DEFAULT_ANTIPATTERN_POOR = 5  # → 0 pts

# Directories excluded from LOC counting (noise sources that inflate denominator)
LOC_EXCLUDE_DIRS = {
    "tests",
    "test",
    "scripts",
    "fuzz",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
}


# ---------------------------------------------------------------------------
# pyproject.toml config loader
# ---------------------------------------------------------------------------
def load_pyproject_config(config_path: str | None) -> dict:
    """
    Read [tool.ai-gate] section from pyproject.toml and return a flat dict
    of threshold overrides.  Returns an empty dict if the file is missing,
    malformed, or has no [tool.ai-gate] section.
    """
    if config_path is None:
        # Auto-discover: walk up from cwd
        candidate = Path.cwd() / "pyproject.toml"
        if not candidate.exists():
            return {}
        config_path = str(candidate)

    path = Path(config_path)
    if not path.exists():
        return {}

    try:
        # tomllib is stdlib in Python 3.11+
        import tomllib  # type: ignore[import]

        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}

    gate = data.get("tool", {}).get("ai-gate", {})
    result: dict = {}

    if "threshold" in gate:
        result["threshold"] = int(gate["threshold"])

    for section, prefix in [
        ("complexity", "complexity"),
        ("coverage", "coverage"),
        ("antipatterns", "antipattern"),
    ]:
        sub = gate.get(section, {})
        for key in ("excellent", "acceptable", "poor"):
            if key in sub:
                result[f"{prefix}_{key}"] = float(sub[key])

    return result


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ScoreBreakdown:
    complexity_score: float = 0.0
    coverage_score: float = 0.0
    antipattern_score: float = 0.0
    complexity_detail: str = ""
    coverage_detail: str = ""
    antipattern_detail: str = ""
    warnings: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=lambda: ["python"])

    @property
    def total(self) -> float:
        return self.complexity_score + self.coverage_score + self.antipattern_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def lerp_score(
    value: float,
    excellent: float,
    acceptable: float,
    poor: float,
    max_pts: float,
    invert: bool = False,
) -> float:
    """
    Linear interpolation between thresholds.
    invert=True: lower value is better (complexity, antipattern density).

    The interpolation always works in the "higher is better" direction:
    - For normal signals (coverage): score scales linearly from poor → excellent.
    - For inverted signals (complexity, density): we negate both value and thresholds
      so the same linear formula applies. The negated ordering must satisfy
      -excellent > -acceptable > -poor (i.e. excellent < acceptable < poor originally).
    """
    if invert:
        value = -value
        excellent, acceptable, poor = -excellent, -acceptable, -poor

    if value >= excellent:
        return max_pts
    if value >= acceptable:
        frac = (value - acceptable) / (excellent - acceptable)
        return max_pts * 0.5 + max_pts * 0.5 * frac
    if value >= poor:
        frac = (value - poor) / (acceptable - poor)
        return max_pts * 0.5 * frac
    return 0.0


# ---------------------------------------------------------------------------
# Signal: complexity via lizard (Python) + optional JS/TS JSON
# ---------------------------------------------------------------------------
def measure_complexity(
    src_path: str,
    js_complexity_json: str | None = None,
) -> tuple[float, str, list[str]]:
    """
    Returns (avg_complexity, detail_string, warnings).

    For Python, runs lizard. If js_complexity_json is provided and contains
    valid data, blends it with the Python result (simple average).
    """
    python_avg, python_detail, python_warnings = _measure_python_complexity(src_path)
    js_avg, js_detail = _load_js_complexity(js_complexity_json)

    # Blend if both signals are available
    if js_avg > 0 and python_avg > 0:
        blended = (python_avg + js_avg) / 2
        detail = f"Python: {python_detail} | JS/TS: {js_detail}"
        return blended, detail, python_warnings
    if js_avg > 0:
        return js_avg, js_detail, []
    return python_avg, python_detail, python_warnings


def _measure_python_complexity(src_path: str) -> tuple[float, str, list[str]]:
    """Returns (avg_complexity, detail_string, warnings) for Python files."""
    try:
        result = subprocess.run(
            ["lizard", src_path, "--csv", "-l", "python"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return (
            0.0,
            "lizard not installed — skipped",
            ["lizard not found; install via `pip install lizard`"],
        )
    except subprocess.TimeoutExpired:
        return 0.0, "lizard timed out after 120s", ["lizard analysis timed out"]

    if result.returncode not in (0, 1):
        return 0.0, f"lizard error: {result.stderr[:200]}", []

    lines = [ln for ln in result.stdout.strip().splitlines() if ln]
    if not lines:
        return 0.0, "No Python files analysed", []

    complexities = []
    warnings = []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            cc = float(parts[2])
            func_name = parts[1].strip() if len(parts) > 1 else "unknown"
            complexities.append(cc)
            if cc > DEFAULT_COMPLEXITY_POOR:
                warnings.append(
                    f"Very high complexity ({cc:.0f}) in `{func_name}` — consider splitting"
                )
        except (ValueError, IndexError):
            continue

    if not complexities:
        return 0.0, "No functions found by lizard", []

    avg = sum(complexities) / len(complexities)
    worst = max(complexities)
    detail = (
        f"avg cyclomatic complexity: **{avg:.1f}** "
        f"(worst: {worst:.0f} across {len(complexities)} functions)"
    )
    return avg, detail, warnings


def _load_js_complexity(js_complexity_json: str | None) -> tuple[float, str]:
    """Load pre-computed JS/TS complexity from measure_js_complexity.py output."""
    if not js_complexity_json:
        return 0.0, ""
    path = Path(js_complexity_json)
    if not path.exists():
        return 0.0, ""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return 0.0, ""

    if data.get("error"):
        return 0.0, f"JS/TS analysis: {data['error']}"

    avg = float(data.get("avg_complexity", 0))
    worst = float(data.get("worst_complexity", 0))
    count = int(data.get("function_count", 0))
    detail = f"JS/TS avg complexity: **{avg:.1f}** (worst: {worst:.0f} across {count} functions)"
    return avg, detail


# ---------------------------------------------------------------------------
# Signal: coverage
# ---------------------------------------------------------------------------
def measure_coverage(coverage_json: str) -> tuple[float, str]:
    """Returns (percent_covered, detail_string)."""
    path = Path(coverage_json)
    if not path.exists():
        return 0.0, "coverage.json not found — run `coverage json` first"

    try:
        data = json.loads(path.read_text())
        totals = data.get("totals", {})
        pct = totals.get("percent_covered", totals.get("percent_covered_display", 0))
        pct = float(pct)
        return pct, f"branch+line coverage: **{pct:.1f}%**"
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        return 0.0, f"Could not parse coverage.json: {e}"


# ---------------------------------------------------------------------------
# Signal: semgrep anti-patterns
# ---------------------------------------------------------------------------
def measure_antipatterns(semgrep_json: str, src_path: str) -> tuple[float, str, list[str]]:
    """Returns (findings_per_100_loc, detail_string, per-finding warnings)."""
    path = Path(semgrep_json)
    if not path.exists():
        return 0.0, "semgrep-results.json not found — semgrep not run", []

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return 0.0, f"Could not parse semgrep results: {e}", []

    results = data.get("results", [])
    finding_count = len(results)

    loc = _count_loc(src_path)
    density = (finding_count / loc * 100) if loc > 0 else 0.0

    detail = (
        f"**{finding_count}** anti-pattern findings "
        f"({density:.2f} per 100 LOC, ~{loc} source lines)"
    )

    warnings = []
    for r in results[:10]:
        path_str = r.get("path", "?")
        line = r.get("start", {}).get("line", "?")
        msg = r.get("extra", {}).get("message", r.get("check_id", "unknown"))
        # Truncate long messages
        msg = msg.replace("\n", " ")[:120]
        warnings.append(f"`{path_str}:{line}` — {msg}")

    if finding_count > 10:
        warnings.append(f"...and {finding_count - 10} more findings (see semgrep-results.json)")

    return density, detail, warnings


def _count_loc(src_path: str) -> int:
    """
    Count non-blank, non-comment Python lines in src_path,
    excluding noise directories (tests, scripts, fuzz, venvs).
    """
    total = 0
    root = Path(src_path).resolve()
    for p in root.rglob("*.py"):
        # Skip excluded top-level directories
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in LOC_EXCLUDE_DIRS:
            continue
        try:
            for line in p.read_text(errors="ignore").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    total += 1
        except OSError:
            continue
    return max(total, 1)


# ---------------------------------------------------------------------------
# Badge generation
# ---------------------------------------------------------------------------
def generate_badge_json(score: float, threshold: float) -> dict:
    """
    Generate a Shields.io endpoint-compatible JSON object.
    Host this at a URL and reference it in your README:
      ![AI Gate Score](https://img.shields.io/endpoint?url=<your-url>/badge.json)
    """
    if score >= 90:
        color = "brightgreen"
    elif score >= 70:
        color = "green"
    elif score >= 50:
        color = "yellow"
    else:
        color = "red"

    passed = score >= threshold
    label = "AI Gate"
    message = f"{score:.0f}/100 {'✓' if passed else '✗'}"

    return {
        "schemaVersion": 1,
        "label": label,
        "message": message,
        "color": color,
        "namedLogo": "github-actions",
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def build_report(breakdown: ScoreBreakdown, threshold: int) -> str:
    total = breakdown.total
    passed = total >= threshold
    status_icon = "✅" if passed else "❌"
    status_word = "PASSED" if passed else "BLOCKED"

    lang_str = ", ".join(breakdown.languages).upper() if breakdown.languages else "Python"

    lines = [
        f"## {status_icon} AI Code Quality Gate — {status_word}",
        "",
        f"**Languages analysed:** {lang_str}",
        "",
        "| Signal | Score | Detail |",
        "|--------|------:|--------|",
        f"| Complexity (40 pts) | {breakdown.complexity_score:.1f} | {breakdown.complexity_detail} |",
        f"| Coverage (35 pts)   | {breakdown.coverage_score:.1f} | {breakdown.coverage_detail} |",
        f"| Anti-patterns (25 pts) | {breakdown.antipattern_score:.1f} | {breakdown.antipattern_detail} |",
        f"| **Total** | **{total:.1f} / 100** | Threshold: {threshold} |",
        "",
    ]

    if breakdown.warnings:
        lines += ["### Findings", ""]
        for w in breakdown.warnings:
            lines.append(f"- {w}")
        lines.append("")

    if not passed:
        lines += [
            "> **Merge blocked.** Resolve the findings above and re-push to re-run the gate.",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Compute AI code maintainability score")
    parser.add_argument("--coverage", default="coverage.json")
    parser.add_argument("--semgrep", default="semgrep-results.json")
    parser.add_argument("--src", default=".")
    parser.add_argument("--threshold", type=int, default=None)
    parser.add_argument("--output", default=None, help="Write markdown report to this file")
    parser.add_argument(
        "--score-output",
        default=None,
        help="Write raw score (float) to this file for CI consumption",
    )
    parser.add_argument(
        "--badge-output",
        default=None,
        help="Write shields.io endpoint JSON to this file",
    )
    parser.add_argument(
        "--fail-on-threshold",
        action="store_true",
        help="Exit 1 if score < threshold",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to pyproject.toml to read [tool.ai-gate] thresholds from",
    )
    parser.add_argument(
        "--js-complexity",
        default=None,
        help="Path to JS/TS complexity JSON produced by measure_js_complexity.py",
    )
    parser.add_argument(
        "--languages",
        default="python",
        help="Comma-separated languages being analysed (for report display)",
    )
    # Threshold overrides (CLI wins over pyproject.toml)
    parser.add_argument("--complexity-excellent", type=float, default=None)
    parser.add_argument("--complexity-acceptable", type=float, default=None)
    parser.add_argument("--complexity-poor", type=float, default=None)
    parser.add_argument("--coverage-excellent", type=float, default=None)
    parser.add_argument("--coverage-acceptable", type=float, default=None)
    parser.add_argument("--coverage-poor", type=float, default=None)
    parser.add_argument("--antipattern-excellent", type=float, default=None)
    parser.add_argument("--antipattern-acceptable", type=float, default=None)
    parser.add_argument("--antipattern-poor", type=float, default=None)
    args = parser.parse_args()

    # Load config: pyproject.toml values fill gaps, CLI values override all
    cfg = load_pyproject_config(args.config)

    def resolve(cli_val: float | None, cfg_key: str, default: float) -> float:
        if cli_val is not None:
            return cli_val
        return cfg.get(cfg_key, default)

    threshold = args.threshold if args.threshold is not None else cfg.get("threshold", 70)
    cx_exc = resolve(
        args.complexity_excellent, "complexity_excellent", DEFAULT_COMPLEXITY_EXCELLENT
    )
    cx_acc = resolve(
        args.complexity_acceptable, "complexity_acceptable", DEFAULT_COMPLEXITY_ACCEPTABLE
    )
    cx_poor = resolve(args.complexity_poor, "complexity_poor", DEFAULT_COMPLEXITY_POOR)
    cov_exc = resolve(args.coverage_excellent, "coverage_excellent", DEFAULT_COVERAGE_EXCELLENT)
    cov_acc = resolve(args.coverage_acceptable, "coverage_acceptable", DEFAULT_COVERAGE_ACCEPTABLE)
    cov_poor = resolve(args.coverage_poor, "coverage_poor", DEFAULT_COVERAGE_POOR)
    ap_exc = resolve(
        args.antipattern_excellent, "antipattern_excellent", DEFAULT_ANTIPATTERN_EXCELLENT
    )
    ap_acc = resolve(
        args.antipattern_acceptable, "antipattern_acceptable", DEFAULT_ANTIPATTERN_ACCEPTABLE
    )
    ap_poor = resolve(args.antipattern_poor, "antipattern_poor", DEFAULT_ANTIPATTERN_POOR)

    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]

    breakdown = ScoreBreakdown(languages=languages)

    # --- Complexity ---
    avg_cc, cc_detail, cc_warnings = measure_complexity(args.src, args.js_complexity)
    breakdown.complexity_score = lerp_score(
        avg_cc,
        cx_exc,
        cx_acc,
        cx_poor,
        max_pts=40,
        invert=True,
    )
    breakdown.complexity_detail = cc_detail
    breakdown.warnings.extend(cc_warnings)

    # --- Coverage ---
    pct, cov_detail = measure_coverage(args.coverage)
    breakdown.coverage_score = lerp_score(
        pct,
        cov_exc,
        cov_acc,
        cov_poor,
        max_pts=35,
        invert=False,
    )
    breakdown.coverage_detail = cov_detail

    # --- Anti-patterns ---
    density, ap_detail, ap_warnings = measure_antipatterns(args.semgrep, args.src)
    breakdown.antipattern_score = lerp_score(
        density,
        ap_exc,
        ap_acc,
        ap_poor,
        max_pts=25,
        invert=True,
    )
    breakdown.antipattern_detail = ap_detail
    breakdown.warnings.extend(ap_warnings)

    report = build_report(breakdown, threshold)
    total = breakdown.total

    if args.output:
        Path(args.output).write_text(report)
        print(f"Score report written to {args.output}")

    if args.score_output:
        Path(args.score_output).write_text(f"{total:.2f}")

    if args.badge_output:
        badge = generate_badge_json(total, threshold)
        Path(args.badge_output).write_text(json.dumps(badge, indent=2))
        print(f"Badge JSON written to {args.badge_output}")

    print(report)

    if args.fail_on_threshold and total < threshold:
        sys.exit(1)


if __name__ == "__main__":
    main()
