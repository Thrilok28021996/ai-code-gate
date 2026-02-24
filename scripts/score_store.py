#!/usr/bin/env python3
"""
Score history store — lightweight SQLite backend.

Records every gate run so teams can track score trends over time.
Intended to be called from CI after score.py completes.

Usage (CI):
  python scripts/score_store.py \
    --db /path/to/scores.db \
    --score 82.5 \
    --repo "org/repo" \
    --pr 42 \
    --sha "abc1234" \
    --branch "feature/ai-refactor"

Query examples:
  python scripts/score_store.py --db scores.db --query trend --repo "org/repo"
  python scripts/score_store.py --db scores.db --query latest --repo "org/repo"
"""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS score_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT    NOT NULL,           -- ISO-8601 UTC timestamp
    repo        TEXT    NOT NULL,           -- "owner/repo"
    branch      TEXT    NOT NULL DEFAULT '',
    pr          INTEGER,                    -- PR number, NULL for push runs
    sha         TEXT    NOT NULL DEFAULT '',
    score       REAL    NOT NULL,
    passed      INTEGER NOT NULL,           -- 1 = passed, 0 = blocked
    threshold   REAL    NOT NULL DEFAULT 70,
    complexity_score  REAL DEFAULT NULL,
    coverage_score    REAL DEFAULT NULL,
    antipattern_score REAL DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_repo_recorded ON score_runs(repo, recorded_at);
CREATE INDEX IF NOT EXISTS idx_repo_branch   ON score_runs(repo, branch);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
def record_run(
    db_path: str,
    score: float,
    repo: str,
    branch: str = "",
    pr: int | None = None,
    sha: str = "",
    threshold: float = 70.0,
    complexity_score: float | None = None,
    coverage_score: float | None = None,
    antipattern_score: float | None = None,
) -> int:
    """
    Insert a new score run and return its row ID.
    """
    conn = get_connection(db_path)
    now = datetime.now(UTC).isoformat()
    passed = 1 if score >= threshold else 0

    cursor = conn.execute(
        """
        INSERT INTO score_runs
            (recorded_at, repo, branch, pr, sha, score, passed, threshold,
             complexity_score, coverage_score, antipattern_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            repo,
            branch,
            pr,
            sha,
            score,
            passed,
            threshold,
            complexity_score,
            coverage_score,
            antipattern_score,
        ),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id or 0


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def query_trend(db_path: str, repo: str, limit: int = 30) -> list[dict]:
    """Return the last `limit` runs for a repo, oldest first."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT recorded_at, branch, pr, sha, score, passed, threshold
        FROM score_runs
        WHERE repo = ?
        ORDER BY recorded_at DESC
        LIMIT ?
        """,
        (repo, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def query_latest(db_path: str, repo: str, branch: str | None = None) -> dict | None:
    """Return the most recent run for a repo (optionally filtered by branch)."""
    conn = get_connection(db_path)
    if branch:
        row = conn.execute(
            """
            SELECT * FROM score_runs
            WHERE repo = ? AND branch = ?
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (repo, branch),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM score_runs
            WHERE repo = ?
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (repo,),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def query_stats(db_path: str, repo: str) -> dict:
    """Return aggregate statistics for a repo."""
    conn = get_connection(db_path)
    row = conn.execute(
        """
        SELECT
            COUNT(*)          AS total_runs,
            AVG(score)        AS avg_score,
            MAX(score)        AS best_score,
            MIN(score)        AS worst_score,
            SUM(passed)       AS passed_runs,
            COUNT(*) - SUM(passed) AS blocked_runs
        FROM score_runs
        WHERE repo = ?
        """,
        (repo,),
    ).fetchone()
    conn.close()
    if not row or row["total_runs"] == 0:
        return {}
    stats = dict(row)
    stats["pass_rate"] = round(stats["passed_runs"] / stats["total_runs"] * 100, 1)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Record and query AI gate score history")
    parser.add_argument("--db", required=True, help="Path to SQLite database file")

    sub = parser.add_subparsers(dest="mode")

    # --- record (default) ---
    rec = sub.add_parser("record", help="Record a new score run (default mode)")
    rec.add_argument("--score", type=float, required=True)
    rec.add_argument("--repo", required=True)
    rec.add_argument("--branch", default="")
    rec.add_argument("--pr", type=int, default=None)
    rec.add_argument("--sha", default="")
    rec.add_argument("--threshold", type=float, default=70.0)
    rec.add_argument("--complexity-score", type=float, default=None)
    rec.add_argument("--coverage-score", type=float, default=None)
    rec.add_argument("--antipattern-score", type=float, default=None)

    # --- query ---
    qry = sub.add_parser("query", help="Query score history")
    qry.add_argument("--repo", required=True)
    qry.add_argument(
        "--type",
        choices=["trend", "latest", "stats"],
        default="latest",
        help="Type of query to run",
    )
    qry.add_argument("--branch", default=None)
    qry.add_argument("--limit", type=int, default=30)
    qry.add_argument("--format", choices=["json", "text"], default="text")

    args = parser.parse_args()

    # Support legacy flat flags (used by action.yml) alongside subcommand mode
    if args.mode is None:
        # Flat mode: python score_store.py --db x --score y --repo z ...
        flat = argparse.ArgumentParser()
        flat.add_argument("--db", required=True)
        flat.add_argument("--score", type=float, required=True)
        flat.add_argument("--repo", required=True)
        flat.add_argument("--branch", default="")
        flat.add_argument("--pr", type=int, default=None)
        flat.add_argument("--sha", default="")
        flat.add_argument("--threshold", type=float, default=70.0)
        fargs = flat.parse_args()
        row_id = record_run(
            fargs.db,
            fargs.score,
            fargs.repo,
            fargs.branch,
            fargs.pr,
            fargs.sha,
            fargs.threshold,
        )
        print(f"Score {fargs.score:.1f} recorded (run #{row_id})")
        return

    if args.mode == "record":
        row_id = record_run(
            args.db,
            args.score,
            args.repo,
            args.branch,
            args.pr,
            args.sha,
            args.threshold,
            args.complexity_score,
            args.coverage_score,
            args.antipattern_score,
        )
        print(f"Score {args.score:.1f} recorded (run #{row_id})")

    elif args.mode == "query":
        if args.type == "trend":
            data = query_trend(args.db, args.repo, args.limit)
        elif args.type == "latest":
            data = query_latest(args.db, args.repo, args.branch)
        else:
            data = query_stats(args.db, args.repo)

        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            if isinstance(data, list):
                for run in data:
                    status = "PASS" if run["passed"] else "FAIL"
                    print(
                        f"{run['recorded_at'][:10]}  {status}  {run['score']:.1f}  {run['branch']}"
                    )
            elif isinstance(data, dict):
                for k, v in data.items():
                    print(f"{k}: {v}")
            else:
                print("No data found.")


if __name__ == "__main__":
    main()
