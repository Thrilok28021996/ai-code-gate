"""
Tests for scripts/score_store.py

Covers:
- record_run(): inserts row, returns valid ID
- query_trend(): returns chronological list
- query_latest(): returns most recent run, branch filter
- query_stats(): aggregates pass rate, averages
- get_connection(): creates schema on first call, idempotent on repeat
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from score_store import (  # noqa: E402
    get_connection,
    query_latest,
    query_stats,
    query_trend,
    record_run,
)


class TestRecordRun:
    def test_returns_positive_row_id(self, tmp_path):
        db = str(tmp_path / "scores.db")
        row_id = record_run(db, score=75.0, repo="org/repo")
        assert row_id > 0

    def test_successive_runs_have_increasing_ids(self, tmp_path):
        db = str(tmp_path / "scores.db")
        id1 = record_run(db, score=60.0, repo="org/repo")
        id2 = record_run(db, score=80.0, repo="org/repo")
        assert id2 > id1

    def test_passed_flag_set_correctly_when_passing(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=75.0, repo="org/repo", threshold=70.0)
        conn = get_connection(db)
        row = conn.execute("SELECT passed FROM score_runs LIMIT 1").fetchone()
        assert row["passed"] == 1

    def test_passed_flag_set_correctly_when_failing(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=55.0, repo="org/repo", threshold=70.0)
        conn = get_connection(db)
        row = conn.execute("SELECT passed FROM score_runs LIMIT 1").fetchone()
        assert row["passed"] == 0

    def test_stores_branch_and_pr(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=80.0, repo="org/repo", branch="feat/ai", pr=42, sha="abc123")
        conn = get_connection(db)
        row = conn.execute("SELECT branch, pr, sha FROM score_runs LIMIT 1").fetchone()
        assert row["branch"] == "feat/ai"
        assert row["pr"] == 42
        assert row["sha"] == "abc123"

    def test_stores_sub_scores(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(
            db,
            score=78.0,
            repo="org/repo",
            complexity_score=30.0,
            coverage_score=28.0,
            antipattern_score=20.0,
        )
        conn = get_connection(db)
        row = conn.execute(
            "SELECT complexity_score, coverage_score, antipattern_score FROM score_runs LIMIT 1"
        ).fetchone()
        assert row["complexity_score"] == pytest.approx(30.0)
        assert row["coverage_score"] == pytest.approx(28.0)
        assert row["antipattern_score"] == pytest.approx(20.0)

    def test_creates_db_file_if_missing(self, tmp_path):
        db = str(tmp_path / "nested" / "dir" / "scores.db")
        record_run(db, score=70.0, repo="org/repo")
        assert Path(db).exists()


class TestQueryTrend:
    def test_returns_runs_oldest_first(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=60.0, repo="org/repo")
        record_run(db, score=70.0, repo="org/repo")
        record_run(db, score=80.0, repo="org/repo")
        trend = query_trend(db, "org/repo")
        scores = [r["score"] for r in trend]
        assert scores == [60.0, 70.0, 80.0]

    def test_limit_applied(self, tmp_path):
        db = str(tmp_path / "scores.db")
        for i in range(10):
            record_run(db, score=float(50 + i), repo="org/repo")
        trend = query_trend(db, "org/repo", limit=3)
        assert len(trend) == 3

    def test_filters_by_repo(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=70.0, repo="org/repo-a")
        record_run(db, score=80.0, repo="org/repo-b")
        trend = query_trend(db, "org/repo-a")
        assert len(trend) == 1
        assert trend[0]["score"] == pytest.approx(70.0)

    def test_empty_repo_returns_empty_list(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=70.0, repo="org/other")
        trend = query_trend(db, "org/nonexistent")
        assert trend == []


class TestQueryLatest:
    def test_returns_most_recent_run(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=60.0, repo="org/repo")
        record_run(db, score=85.0, repo="org/repo")
        result = query_latest(db, "org/repo")
        assert result is not None
        assert result["score"] == pytest.approx(85.0)

    def test_returns_none_for_unknown_repo(self, tmp_path):
        db = str(tmp_path / "scores.db")
        result = query_latest(db, "org/nonexistent")
        assert result is None

    def test_branch_filter_returns_correct_run(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=60.0, repo="org/repo", branch="main")
        record_run(db, score=90.0, repo="org/repo", branch="feat/x")
        result = query_latest(db, "org/repo", branch="main")
        assert result is not None
        assert result["score"] == pytest.approx(60.0)

    def test_branch_filter_returns_none_if_no_match(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=70.0, repo="org/repo", branch="main")
        result = query_latest(db, "org/repo", branch="nonexistent-branch")
        assert result is None


class TestQueryStats:
    def test_basic_stats(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=60.0, repo="org/repo", threshold=70.0)  # fail
        record_run(db, score=80.0, repo="org/repo", threshold=70.0)  # pass
        record_run(db, score=90.0, repo="org/repo", threshold=70.0)  # pass
        stats = query_stats(db, "org/repo")
        assert stats["total_runs"] == 3
        assert stats["passed_runs"] == 2
        assert stats["blocked_runs"] == 1
        assert stats["pass_rate"] == pytest.approx(66.7, abs=0.2)

    def test_avg_score(self, tmp_path):
        db = str(tmp_path / "scores.db")
        record_run(db, score=70.0, repo="org/repo")
        record_run(db, score=90.0, repo="org/repo")
        stats = query_stats(db, "org/repo")
        assert stats["avg_score"] == pytest.approx(80.0)

    def test_best_and_worst(self, tmp_path):
        db = str(tmp_path / "scores.db")
        for score in [55.0, 72.0, 88.0, 91.0]:
            record_run(db, score=score, repo="org/repo")
        stats = query_stats(db, "org/repo")
        assert stats["best_score"] == pytest.approx(91.0)
        assert stats["worst_score"] == pytest.approx(55.0)

    def test_empty_repo_returns_empty_dict(self, tmp_path):
        db = str(tmp_path / "scores.db")
        stats = query_stats(db, "org/nonexistent")
        assert stats == {}


class TestGetConnection:
    def test_schema_created_on_first_call(self, tmp_path):
        db = str(tmp_path / "test.db")
        conn = get_connection(db)
        # If schema was created, this query must not raise
        conn.execute("SELECT * FROM score_runs LIMIT 0")
        conn.close()

    def test_idempotent_schema_creation(self, tmp_path):
        db = str(tmp_path / "test.db")
        get_connection(db).close()
        # Second call must not fail (CREATE TABLE IF NOT EXISTS)
        conn = get_connection(db)
        conn.execute("SELECT * FROM score_runs LIMIT 0")
        conn.close()
