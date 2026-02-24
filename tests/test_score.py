"""
Tests for scripts/score.py

Covers:
- lerp_score() math for all three signals (normal and inverted)
- measure_coverage() JSON parsing and edge cases
- measure_antipatterns() density calculation
- _count_loc() directory exclusion
- build_report() pass/fail output
- generate_badge_json() colour thresholds
- load_pyproject_config() TOML parsing
- _load_js_complexity() JSON loading
"""

import json
import sys
from pathlib import Path

import pytest

# Make scripts/ importable without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from score import (  # noqa: E402
    LOC_EXCLUDE_DIRS,
    ScoreBreakdown,
    _count_loc,
    _load_js_complexity,
    build_report,
    generate_badge_json,
    lerp_score,
    load_pyproject_config,
    measure_antipatterns,
    measure_coverage,
)


# ---------------------------------------------------------------------------
# lerp_score
# ---------------------------------------------------------------------------
class TestLerpScore:
    def test_at_excellent_returns_max(self):
        assert lerp_score(90, excellent=90, acceptable=70, poor=40, max_pts=35) == 35.0

    def test_above_excellent_returns_max(self):
        assert lerp_score(100, excellent=90, acceptable=70, poor=40, max_pts=35) == 35.0

    def test_at_acceptable_returns_half(self):
        result = lerp_score(70, excellent=90, acceptable=70, poor=40, max_pts=35)
        assert result == pytest.approx(17.5)

    def test_at_poor_returns_zero(self):
        result = lerp_score(40, excellent=90, acceptable=70, poor=40, max_pts=35)
        assert result == pytest.approx(0.0)

    def test_below_poor_returns_zero(self):
        assert lerp_score(0, excellent=90, acceptable=70, poor=40, max_pts=35) == 0.0

    def test_midpoint_between_acceptable_and_excellent(self):
        # midpoint of [70, 90] → should be between 17.5 and 35
        result = lerp_score(80, excellent=90, acceptable=70, poor=40, max_pts=35)
        assert 17.5 < result < 35.0

    def test_midpoint_between_poor_and_acceptable(self):
        result = lerp_score(55, excellent=90, acceptable=70, poor=40, max_pts=35)
        assert 0 < result < 17.5

    # --- inverted (lower is better) ---
    def test_invert_at_excellent_returns_max(self):
        # complexity: excellent=5, lower is better
        result = lerp_score(5, excellent=5, acceptable=10, poor=20, max_pts=40, invert=True)
        assert result == 40.0

    def test_invert_below_excellent_returns_max(self):
        result = lerp_score(1, excellent=5, acceptable=10, poor=20, max_pts=40, invert=True)
        assert result == 40.0

    def test_invert_at_acceptable_returns_half(self):
        result = lerp_score(10, excellent=5, acceptable=10, poor=20, max_pts=40, invert=True)
        assert result == pytest.approx(20.0)

    def test_invert_at_poor_returns_zero(self):
        result = lerp_score(20, excellent=5, acceptable=10, poor=20, max_pts=40, invert=True)
        assert result == pytest.approx(0.0)

    def test_invert_above_poor_returns_zero(self):
        result = lerp_score(25, excellent=5, acceptable=10, poor=20, max_pts=40, invert=True)
        assert result == 0.0

    def test_antipattern_zero_density_returns_max(self):
        # excellent=0: density of 0 should give full 25 pts
        result = lerp_score(0, excellent=0, acceptable=2, poor=5, max_pts=25, invert=True)
        assert result == 25.0

    def test_antipattern_at_acceptable(self):
        result = lerp_score(2, excellent=0, acceptable=2, poor=5, max_pts=25, invert=True)
        assert result == pytest.approx(12.5)

    def test_antipattern_above_poor(self):
        result = lerp_score(6, excellent=0, acceptable=2, poor=5, max_pts=25, invert=True)
        assert result == 0.0


# ---------------------------------------------------------------------------
# measure_coverage
# ---------------------------------------------------------------------------
class TestMeasureCoverage:
    def test_reads_percent_covered(self, tmp_path):
        data = {"totals": {"percent_covered": 82.5}}
        cov_file = tmp_path / "coverage.json"
        cov_file.write_text(json.dumps(data))

        pct, detail = measure_coverage(str(cov_file))
        assert pct == pytest.approx(82.5)
        assert "82.5%" in detail

    def test_missing_file_returns_zero(self, tmp_path):
        pct, detail = measure_coverage(str(tmp_path / "nonexistent.json"))
        assert pct == 0.0
        assert "not found" in detail

    def test_malformed_json_returns_zero(self, tmp_path):
        cov_file = tmp_path / "coverage.json"
        cov_file.write_text("NOT JSON {{{")
        pct, detail = measure_coverage(str(cov_file))
        assert pct == 0.0
        assert "Could not parse" in detail

    def test_missing_totals_key_returns_zero(self, tmp_path):
        cov_file = tmp_path / "coverage.json"
        cov_file.write_text(json.dumps({"files": {}}))
        pct, detail = measure_coverage(str(cov_file))
        assert pct == 0.0

    def test_fallback_to_percent_covered_display(self, tmp_path):
        data = {"totals": {"percent_covered_display": "75.0"}}
        cov_file = tmp_path / "coverage.json"
        cov_file.write_text(json.dumps(data))
        pct, detail = measure_coverage(str(cov_file))
        assert pct == pytest.approx(75.0)

    def test_full_coverage(self, tmp_path):
        data = {"totals": {"percent_covered": 100.0}}
        cov_file = tmp_path / "coverage.json"
        cov_file.write_text(json.dumps(data))
        pct, _ = measure_coverage(str(cov_file))
        assert pct == 100.0

    def test_zero_coverage(self, tmp_path):
        data = {"totals": {"percent_covered": 0}}
        cov_file = tmp_path / "coverage.json"
        cov_file.write_text(json.dumps(data))
        pct, _ = measure_coverage(str(cov_file))
        assert pct == 0.0


# ---------------------------------------------------------------------------
# measure_antipatterns
# ---------------------------------------------------------------------------
class TestMeasureAntipatterns:
    def _make_semgrep_results(self, tmp_path, results: list) -> Path:
        data = {"results": results, "errors": []}
        f = tmp_path / "semgrep-results.json"
        f.write_text(json.dumps(data))
        return f

    def _make_src(self, tmp_path, line_count: int = 100) -> Path:
        src = tmp_path / "src"
        src.mkdir()
        py = src / "main.py"
        py.write_text("\n".join([f"x = {i}" for i in range(line_count)]))
        return tmp_path

    def test_zero_findings_returns_zero_density(self, tmp_path):
        f = self._make_semgrep_results(tmp_path, [])
        src = self._make_src(tmp_path)
        density, detail, warnings = measure_antipatterns(str(f), str(src))
        assert density == 0.0
        assert "0" in detail
        assert warnings == []

    def test_density_scales_with_findings(self, tmp_path):
        # 100 source lines, 2 findings → 2 per 100 LOC
        findings = [
            {
                "path": "src/main.py",
                "start": {"line": 1},
                "extra": {"message": "bad pattern"},
                "check_id": "test-rule",
            }
            for _ in range(2)
        ]
        f = self._make_semgrep_results(tmp_path, findings)
        src = self._make_src(tmp_path, line_count=100)
        density, detail, warnings = measure_antipatterns(str(f), str(src))
        assert density == pytest.approx(2.0, abs=0.5)
        assert len(warnings) == 2

    def test_caps_warnings_at_10(self, tmp_path):
        findings = [
            {
                "path": "src/main.py",
                "start": {"line": i},
                "extra": {"message": "bad"},
                "check_id": "r",
            }
            for i in range(15)
        ]
        f = self._make_semgrep_results(tmp_path, findings)
        src = self._make_src(tmp_path)
        _, _, warnings = measure_antipatterns(str(f), str(src))
        # 10 individual findings + 1 "...and N more" message
        assert len(warnings) == 11
        assert "5 more" in warnings[-1]

    def test_missing_file_returns_zero(self, tmp_path):
        density, detail, warnings = measure_antipatterns(
            str(tmp_path / "missing.json"), str(tmp_path)
        )
        assert density == 0.0
        assert "not found" in detail


# ---------------------------------------------------------------------------
# _count_loc
# ---------------------------------------------------------------------------
class TestCountLoc:
    def test_counts_source_lines(self, tmp_path):
        src = tmp_path / "mymodule.py"
        src.write_text("def foo():\n    return 1\n\n# comment\n\n")
        count = _count_loc(str(tmp_path))
        assert count == 2  # def line + return line; comment and blank excluded

    def test_excludes_tests_directory(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("def test_x():\n    assert True\n")
        (tmp_path / "mymodule.py").write_text("def foo():\n    return 1\n")
        count = _count_loc(str(tmp_path))
        assert count == 2  # only mymodule.py lines

    def test_excludes_scripts_directory(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "helper.py").write_text("x = 1\ny = 2\n")
        (tmp_path / "app.py").write_text("z = 3\n")
        count = _count_loc(str(tmp_path))
        assert count == 1  # only app.py

    def test_excludes_fuzz_directory(self, tmp_path):
        (tmp_path / "fuzz").mkdir()
        (tmp_path / "fuzz" / "harness.py").write_text("import atheris\n")
        (tmp_path / "app.py").write_text("x = 1\n")
        count = _count_loc(str(tmp_path))
        assert count == 1

    def test_excludes_venv(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("a = 1\nb = 2\nc = 3\n")
        (tmp_path / "src.py").write_text("d = 4\n")
        count = _count_loc(str(tmp_path))
        assert count == 1

    def test_minimum_returns_one(self, tmp_path):
        # Empty directory → min(0, 1) = 1 to avoid division by zero
        count = _count_loc(str(tmp_path))
        assert count == 1

    def test_all_exclude_dirs_are_excluded(self, tmp_path):
        """Verify every directory in LOC_EXCLUDE_DIRS is actually excluded."""
        for d in LOC_EXCLUDE_DIRS:
            excluded = tmp_path / d
            excluded.mkdir(exist_ok=True)
            (excluded / "code.py").write_text("secret_line = 1\n")
        (tmp_path / "real_src.py").write_text("real_line = 1\n")
        count = _count_loc(str(tmp_path))
        assert count == 1  # only real_src.py


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------
class TestBuildReport:
    def _make_breakdown(self, complexity=40.0, coverage=35.0, antipattern=25.0):
        b = ScoreBreakdown()
        b.complexity_score = complexity
        b.coverage_score = coverage
        b.antipattern_score = antipattern
        b.complexity_detail = "avg CC: 3.0"
        b.coverage_detail = "95%"
        b.antipattern_detail = "0 findings"
        return b

    def test_passed_contains_passed(self):
        breakdown = self._make_breakdown()  # total = 100
        report = build_report(breakdown, threshold=70)
        assert "PASSED" in report
        assert "BLOCKED" not in report

    def test_failed_contains_blocked(self):
        breakdown = self._make_breakdown(complexity=0, coverage=0, antipattern=0)
        report = build_report(breakdown, threshold=70)
        assert "BLOCKED" in report
        assert "PASSED" not in report

    def test_report_shows_total(self):
        breakdown = self._make_breakdown(complexity=20, coverage=17.5, antipattern=12.5)
        report = build_report(breakdown, threshold=70)
        assert "50.0 / 100" in report

    def test_report_shows_threshold(self):
        breakdown = self._make_breakdown()
        report = build_report(breakdown, threshold=80)
        assert "80" in report

    def test_findings_section_appears_with_warnings(self):
        breakdown = self._make_breakdown()
        breakdown.warnings = ["finding A", "finding B"]
        report = build_report(breakdown, threshold=70)
        assert "### Findings" in report
        assert "finding A" in report
        assert "finding B" in report

    def test_no_findings_section_when_no_warnings(self):
        breakdown = self._make_breakdown()
        report = build_report(breakdown, threshold=70)
        assert "### Findings" not in report

    def test_blocked_includes_re_push_instruction(self):
        breakdown = self._make_breakdown(complexity=0, coverage=0, antipattern=0)
        report = build_report(breakdown, threshold=70)
        assert "re-push" in report

    def test_passed_does_not_include_blocked_instruction(self):
        breakdown = self._make_breakdown()
        report = build_report(breakdown, threshold=70)
        assert "Merge blocked" not in report

    def test_report_shows_languages(self):
        breakdown = self._make_breakdown()
        breakdown.languages = ["python", "javascript"]
        report = build_report(breakdown, threshold=70)
        assert "PYTHON" in report
        assert "JAVASCRIPT" in report


# ---------------------------------------------------------------------------
# generate_badge_json
# ---------------------------------------------------------------------------
class TestGenerateBadgeJson:
    def test_score_90_is_brightgreen(self):
        badge = generate_badge_json(90.0, threshold=70)
        assert badge["color"] == "brightgreen"

    def test_score_70_is_green(self):
        badge = generate_badge_json(70.0, threshold=70)
        assert badge["color"] == "green"

    def test_score_50_is_yellow(self):
        badge = generate_badge_json(50.0, threshold=70)
        assert badge["color"] == "yellow"

    def test_score_30_is_red(self):
        badge = generate_badge_json(30.0, threshold=70)
        assert badge["color"] == "red"

    def test_badge_contains_score(self):
        badge = generate_badge_json(82.0, threshold=70)
        assert "82" in badge["message"]

    def test_badge_passed_shows_checkmark(self):
        badge = generate_badge_json(75.0, threshold=70)
        assert "✓" in badge["message"]

    def test_badge_failed_shows_cross(self):
        badge = generate_badge_json(60.0, threshold=70)
        assert "✗" in badge["message"]

    def test_badge_schema_version(self):
        badge = generate_badge_json(80.0, threshold=70)
        assert badge["schemaVersion"] == 1

    def test_badge_label(self):
        badge = generate_badge_json(80.0, threshold=70)
        assert badge["label"] == "AI Gate"


# ---------------------------------------------------------------------------
# load_pyproject_config
# ---------------------------------------------------------------------------
class TestLoadPyprojectConfig:
    def _make_pyproject(self, tmp_path, content: str) -> str:
        f = tmp_path / "pyproject.toml"
        f.write_text(content)
        return str(f)

    def test_reads_threshold(self, tmp_path):
        path = self._make_pyproject(
            tmp_path,
            "[tool.ai-gate]\nthreshold = 80\n",
        )
        cfg = load_pyproject_config(path)
        assert cfg["threshold"] == 80

    def test_reads_complexity_thresholds(self, tmp_path):
        path = self._make_pyproject(
            tmp_path,
            "[tool.ai-gate.complexity]\nexcellent = 3\nacceptable = 8\npoor = 15\n",
        )
        cfg = load_pyproject_config(path)
        assert cfg["complexity_excellent"] == 3.0
        assert cfg["complexity_acceptable"] == 8.0
        assert cfg["complexity_poor"] == 15.0

    def test_reads_coverage_thresholds(self, tmp_path):
        path = self._make_pyproject(
            tmp_path,
            "[tool.ai-gate.coverage]\nexcellent = 95\nacceptable = 75\npoor = 50\n",
        )
        cfg = load_pyproject_config(path)
        assert cfg["coverage_excellent"] == 95.0
        assert cfg["coverage_acceptable"] == 75.0
        assert cfg["coverage_poor"] == 50.0

    def test_reads_antipattern_thresholds(self, tmp_path):
        path = self._make_pyproject(
            tmp_path,
            "[tool.ai-gate.antipatterns]\nexcellent = 0\nacceptable = 3\npoor = 8\n",
        )
        cfg = load_pyproject_config(path)
        assert cfg["antipattern_excellent"] == 0.0
        assert cfg["antipattern_acceptable"] == 3.0
        assert cfg["antipattern_poor"] == 8.0

    def test_missing_file_returns_empty_dict(self, tmp_path):
        cfg = load_pyproject_config(str(tmp_path / "nonexistent.toml"))
        assert cfg == {}

    def test_no_ai_gate_section_returns_empty_dict(self, tmp_path):
        path = self._make_pyproject(tmp_path, "[tool.ruff]\nline-length = 100\n")
        cfg = load_pyproject_config(path)
        assert cfg == {}

    def test_none_path_autodiscovers_or_returns_empty(self):
        # In a test environment without pyproject.toml in cwd, returns {}
        # (or reads actual pyproject.toml if it has [tool.ai-gate])
        cfg = load_pyproject_config(None)
        assert isinstance(cfg, dict)

    def test_partial_section_reads_available_keys(self, tmp_path):
        path = self._make_pyproject(
            tmp_path,
            "[tool.ai-gate]\nthreshold = 65\n[tool.ai-gate.coverage]\nexcellent = 92\n",
        )
        cfg = load_pyproject_config(path)
        assert cfg["threshold"] == 65
        assert cfg["coverage_excellent"] == 92.0
        # Keys not present in TOML should be absent from dict
        assert "complexity_excellent" not in cfg


# ---------------------------------------------------------------------------
# _load_js_complexity
# ---------------------------------------------------------------------------
class TestLoadJsComplexity:
    def _make_js_json(self, tmp_path, data: dict) -> str:
        f = tmp_path / "js-complexity.json"
        f.write_text(json.dumps(data))
        return str(f)

    def test_reads_avg_complexity(self, tmp_path):
        path = self._make_js_json(
            tmp_path,
            {
                "avg_complexity": 4.2,
                "worst_complexity": 12.0,
                "function_count": 30,
                "error": None,
            },
        )
        avg, detail = _load_js_complexity(path)
        assert avg == pytest.approx(4.2)
        assert "4.2" in detail

    def test_error_field_returns_zero(self, tmp_path):
        path = self._make_js_json(tmp_path, {"error": "escomplex not installed"})
        avg, detail = _load_js_complexity(path)
        assert avg == 0.0
        assert "escomplex not installed" in detail

    def test_missing_file_returns_zero(self, tmp_path):
        avg, detail = _load_js_complexity(str(tmp_path / "nonexistent.json"))
        assert avg == 0.0
        assert detail == ""

    def test_none_path_returns_zero(self):
        avg, detail = _load_js_complexity(None)
        assert avg == 0.0
        assert detail == ""

    def test_malformed_json_returns_zero(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("NOT JSON")
        avg, detail = _load_js_complexity(str(f))
        assert avg == 0.0
