"""
Tests for scripts/detect_fuzz_targets.py

Covers:
- load_targets() parsing (comments, blank lines, malformed lines)
- matches_glob() with *, ?, and ** patterns
- main() end-to-end: changed files → active harnesses output
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from detect_fuzz_targets import load_targets, main, matches_glob  # noqa: E402


# ---------------------------------------------------------------------------
# load_targets
# ---------------------------------------------------------------------------
class TestLoadTargets:
    def test_parses_valid_mapping(self, tmp_path):
        f = tmp_path / "targets.txt"
        f.write_text("src/parser.py  fuzz/fuzz_parser.py\n")
        result = load_targets(str(f))
        assert result == [("src/parser.py", "fuzz/fuzz_parser.py")]

    def test_skips_comment_lines(self, tmp_path):
        f = tmp_path / "targets.txt"
        f.write_text("# comment\nsrc/a.py  fuzz/a.py\n")
        result = load_targets(str(f))
        assert len(result) == 1

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "targets.txt"
        f.write_text("\n\nsrc/a.py  fuzz/a.py\n\n")
        result = load_targets(str(f))
        assert len(result) == 1

    def test_skips_malformed_lines(self, tmp_path):
        f = tmp_path / "targets.txt"
        # Only one token — should be skipped
        f.write_text("src/a.py\nsrc/b.py  fuzz/b.py\n")
        result = load_targets(str(f))
        assert result == [("src/b.py", "fuzz/b.py")]

    def test_returns_empty_for_missing_file(self, tmp_path):
        result = load_targets(str(tmp_path / "nonexistent.txt"))
        assert result == []

    def test_multiple_mappings(self, tmp_path):
        f = tmp_path / "targets.txt"
        f.write_text(
            "src/a.py  fuzz/fuzz_a.py\nsrc/b.py  fuzz/fuzz_b.py\nsrc/c.py  fuzz/fuzz_c.py\n"
        )
        result = load_targets(str(f))
        assert len(result) == 3


# ---------------------------------------------------------------------------
# matches_glob
# ---------------------------------------------------------------------------
class TestMatchesGlob:
    # Single wildcard
    def test_star_matches_any_filename(self):
        assert matches_glob("src/parsers/foo.py", "src/parsers/*.py")

    def test_star_matches_across_directories_in_fnmatch(self):
        # fnmatch's * does match across path separators — this is intentional
        # behaviour documented in targets.txt; use ** for recursive patterns.
        assert matches_glob("src/parsers/sub/foo.py", "src/parsers/*.py")

    # Double-star (recursive)
    def test_double_star_matches_nested(self):
        assert matches_glob("src/auth/login/handler.py", "src/auth/**")

    def test_double_star_matches_direct_child(self):
        assert matches_glob("src/auth/session.py", "src/auth/**")

    def test_double_star_with_extension(self):
        assert matches_glob("src/utils/deep/helper.py", "src/utils/**/*.py")

    # Question mark
    def test_question_mark_matches_single_char(self):
        assert matches_glob("src/v1/api.py", "src/v?/api.py")

    def test_question_mark_does_not_match_multiple(self):
        assert not matches_glob("src/v12/api.py", "src/v?/api.py")

    # Exact match
    def test_exact_path_matches(self):
        assert matches_glob("src/config.py", "src/config.py")

    def test_different_path_does_not_match(self):
        assert not matches_glob("src/config.py", "src/settings.py")

    # Edge cases
    def test_empty_path_does_not_match(self):
        assert not matches_glob("", "src/*.py")

    def test_invalid_glob_does_not_raise(self):
        # Should return False rather than crashing
        result = matches_glob("some/path.py", "[invalid")
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# main() end-to-end
# ---------------------------------------------------------------------------
class TestMain:
    def _make_targets(self, tmp_path, content: str) -> Path:
        f = tmp_path / "targets.txt"
        f.write_text(content)
        return f

    def _make_harness(self, tmp_path, name: str) -> Path:
        h = tmp_path / name
        h.write_text("# harness\n")
        return h

    def test_detects_matching_changed_file(self, tmp_path, monkeypatch):
        harness = self._make_harness(tmp_path, "fuzz_parser.py")
        targets = self._make_targets(tmp_path, f"src/parser.py  {harness}\n")
        output = tmp_path / "active.txt"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "detect_fuzz_targets.py",
                "--changed",
                "src/parser.py",
                "--targets",
                str(targets),
                "--output",
                str(output),
            ],
        )
        main()

        active = output.read_text().strip().splitlines()
        assert str(harness) in active

    def test_no_match_produces_empty_output(self, tmp_path, monkeypatch):
        harness = self._make_harness(tmp_path, "fuzz_parser.py")
        targets = self._make_targets(tmp_path, f"src/parser.py  {harness}\n")
        output = tmp_path / "active.txt"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "detect_fuzz_targets.py",
                "--changed",
                "src/unrelated.py",
                "--targets",
                str(targets),
                "--output",
                str(output),
            ],
        )
        main()

        assert output.read_text().strip() == ""

    def test_skips_harness_if_file_does_not_exist(self, tmp_path, monkeypatch):
        targets = self._make_targets(tmp_path, "src/parser.py  fuzz/nonexistent_harness.py\n")
        output = tmp_path / "active.txt"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "detect_fuzz_targets.py",
                "--changed",
                "src/parser.py",
                "--targets",
                str(targets),
                "--output",
                str(output),
            ],
        )
        main()

        assert output.read_text().strip() == ""

    def test_double_star_glob_via_main(self, tmp_path, monkeypatch):
        harness = self._make_harness(tmp_path, "fuzz_auth.py")
        targets = self._make_targets(tmp_path, f"src/auth/**  {harness}\n")
        output = tmp_path / "active.txt"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "detect_fuzz_targets.py",
                "--changed",
                "src/auth/login/handler.py",
                "--targets",
                str(targets),
                "--output",
                str(output),
            ],
        )
        main()

        active = output.read_text().strip().splitlines()
        assert str(harness) in active

    def test_multiple_changed_files_multiple_harnesses(self, tmp_path, monkeypatch):
        ha = self._make_harness(tmp_path, "fuzz_a.py")
        hb = self._make_harness(tmp_path, "fuzz_b.py")
        targets = self._make_targets(
            tmp_path,
            f"src/a.py  {ha}\nsrc/b.py  {hb}\n",
        )
        output = tmp_path / "active.txt"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "detect_fuzz_targets.py",
                "--changed",
                "src/a.py\nsrc/b.py",
                "--targets",
                str(targets),
                "--output",
                str(output),
            ],
        )
        main()

        active = set(output.read_text().strip().splitlines())
        assert str(ha) in active
        assert str(hb) in active
