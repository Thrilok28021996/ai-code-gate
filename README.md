# 🛡️ AI Code Gate

> **Block low-quality AI-generated code before it merges.**
>
> A GitHub Action that scores every pull request on cyclomatic complexity,
> test coverage, and AI anti-pattern density — and blocks the merge if the
> score drops below your threshold.

[![AI Gate Score](https://img.shields.io/badge/AI%20Gate-passing-brightgreen)](https://github.com/your-org/ai-code-gate)
[![126 tests](https://img.shields.io/badge/tests-126%20passing-brightgreen)](tests/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Why this exists

AI coding assistants generate code fast. Too fast. Engineers are merging
pull requests that:

- **Pass tests** but have cyclomatic complexity of 35 — because the AI didn't refactor
- **Look clean** but contain `cursor.execute(f"SELECT ... {user_input}")` — SQL injection
- **Have 80% line coverage** but 0% branch coverage on every error path
- **Never crash in tests** but crash on malformed input that a 30-second fuzz run would find

AI Code Gate is the automated defence layer between AI output and your main branch.

---

## Quick start — 2 minutes

### 1. Add the workflow

```yaml
# .github/workflows/ai-gate.yml
name: AI Code Quality Gate
on:
  pull_request:
    branches: [main, master, develop]

permissions:
  contents: read
  pull-requests: write   # required to post the score comment

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }

      - name: Run AI Code Gate
        uses: your-org/ai-code-gate@v1
        with:
          threshold: "70"
          languages: "python"    # python | javascript | typescript | python,javascript,typescript
          post-comment: "true"
```

### 2. (Optional) Add pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

The bundled `.pre-commit-config.yaml` will:
- Block commits with cyclomatic complexity ≥ 15
- Scan for AI anti-patterns via Semgrep
- Lint and format with Ruff
- Detect accidentally committed secrets

### 3. (Optional) Tune thresholds in pyproject.toml

```toml
[tool.ai-gate]
threshold = 75        # min score to pass (default: 70)

[tool.ai-gate.complexity]
excellent   = 5       # avg CC ≤ 5 → full 40 pts
acceptable  = 10      # avg CC = 10 → 20 pts
poor        = 20      # avg CC ≥ 20 → 0 pts

[tool.ai-gate.coverage]
excellent   = 90      # ≥90% → full 35 pts
acceptable  = 70      # 70% → 17.5 pts
poor        = 40      # ≤40% → 0 pts

[tool.ai-gate.antipatterns]
excellent   = 0       # 0 findings per 100 LOC → full 25 pts
acceptable  = 2       # 2/100 → 12.5 pts
poor        = 5       # ≥5/100 → 0 pts
```

---

## How scoring works

Every PR is scored 0–100 from three signals using piecewise-linear interpolation:

| Signal | Max pts | Tool | What it measures |
|--------|--------:|------|-----------------|
| **Complexity** | 40 | lizard / escomplex | Avg cyclomatic complexity across all functions |
| **Coverage** | 35 | coverage.py | Branch + line coverage % |
| **Anti-patterns** | 25 | Semgrep | AI-specific pattern findings per 100 LOC |
| **Total** | **100** | | Score < threshold → merge blocked |

Score appears as a sticky comment on every PR:

```
## ✅ AI Code Quality Gate — PASSED

Languages analysed: PYTHON

| Signal              | Score | Detail                                   |
|---------------------|------:|------------------------------------------|
| Complexity (40 pts) |  36.0 | avg cyclomatic complexity: **3.2**       |
| Coverage (35 pts)   |  28.0 | branch+line coverage: **76.4%**          |
| Anti-patterns (25)  |  25.0 | **0** findings (0.00 per 100 LOC)        |
| **Total**           | **89.0 / 100** | Threshold: 70                 |
```

---

## Action inputs

| Input | Default | Description |
|-------|---------|-------------|
| `threshold` | `70` | Minimum score to pass |
| `src` | `.` | Source directory to analyse |
| `languages` | `python` | Comma-separated: `python`, `javascript`, `typescript` |
| `fail-on-threshold` | `true` | Exit 1 when score < threshold |
| `post-comment` | `true` | Post score as sticky PR comment |
| `coverage-json` | _(auto)_ | Path to pre-computed `coverage.json` |
| `semgrep-config` | _(bundled)_ | Path to custom semgrep rules dir |
| `slack-webhook-url` | _(off)_ | Slack incoming webhook URL |
| `score-store` | _(off)_ | Path to SQLite DB for score history |
| `complexity-excellent` | `5` | Avg CC that earns full complexity points |
| `complexity-acceptable` | `10` | Avg CC that earns half complexity points |
| `complexity-poor` | `20` | Avg CC that earns zero complexity points |
| `coverage-excellent` | `90` | Coverage % for full points |
| `coverage-acceptable` | `70` | Coverage % for half points |
| `coverage-poor` | `40` | Coverage % for zero points |
| `antipattern-excellent` | `0` | Findings/100 LOC for full points |
| `antipattern-acceptable` | `2` | Findings/100 LOC for half points |
| `antipattern-poor` | `5` | Findings/100 LOC for zero points |

## Action outputs

| Output | Description |
|--------|-------------|
| `score` | The computed score (float, 0–100) |
| `passed` | `true` or `false` |
| `report-path` | Path to the generated `score-report.md` |

---

## Languages supported

### Python
- **Complexity:** `lizard --csv -l python`
- **Anti-patterns:** 13 custom Semgrep rules (`semgrep-rules/ai-antipatterns.yml`)
- **Coverage:** `coverage.py` with branch coverage

### JavaScript / TypeScript
- **Complexity:** `escomplex-cli` (npm, auto-installed in CI)
- **Anti-patterns:** 15 custom Semgrep rules (`semgrep-rules/js-antipatterns.yml`)
- **Coverage:** supply your own `coverage.json` via `coverage-json` input

---

## Anti-pattern rules

### Python (`semgrep-rules/ai-antipatterns.yml`)

| Rule | Category | Severity |
|------|----------|----------|
| `bare-except` | Error handling | WARNING |
| `broad-exception-catch` | Error handling | WARNING |
| `mutable-default-argument` | Correctness | WARNING |
| `mutable-default-dict` | Correctness | WARNING |
| `sql-string-format` | Security | **ERROR** |
| `hardcoded-secret-assignment` | Security | WARNING |
| `shell-injection` | Security | **ERROR** |
| `missing-input-validation-api` | Validation | WARNING |
| `nested-loop-append` | Performance | WARNING |
| `string-concat-in-loop` | Performance | WARNING |
| `unjustified-global` | Design | WARNING |
| `assert-true-without-message` | Test quality | WARNING |
| `empty-except-in-test` | Test quality | **ERROR** |

### JavaScript / TypeScript (`semgrep-rules/js-antipatterns.yml`)

| Rule | Category | Severity |
|------|----------|----------|
| `empty-catch-block-js` | Error handling | WARNING |
| `catch-and-console-only-js` | Error handling | WARNING |
| `promise-catch-missing` | Error handling | WARNING |
| `eval-usage` | Security | **ERROR** |
| `hardcoded-secret-js` | Security | WARNING |
| `innerHTML-xss` | Security | **ERROR** |
| `sql-template-literal-js` | Security | **ERROR** |
| `dangerously-set-inner-html` | Security | WARNING |
| `nested-loop-push-js` | Performance | WARNING |
| `string-concat-loop-js` | Performance | WARNING |
| `sync-fs-in-handler` | Performance | WARNING |
| `any-type-annotation` | Type safety (TS) | WARNING |
| `non-null-assertion-overuse` | Type safety (TS) | WARNING |
| `expect-true-js` | Test quality | WARNING |
| `empty-test-block` | Test quality | WARNING |

---

## Fuzz testing

Register fuzz harnesses against source file globs in `fuzz/targets.txt`:

```
# fuzz/targets.txt
src/parsers/*.py          fuzz/fuzz_parser.py
src/auth/**               fuzz/fuzz_auth.py
src/api/serializers.py    fuzz/fuzz_serializers.py
```

When a PR touches a file matching a glob, the paired harness runs in CI
under `atheris` for 30 seconds per harness. A crash blocks the merge.

Copy `fuzz/fuzz_example.py` as a starting point for new harnesses.

> **Note:** `atheris` requires Linux. Fuzz tests run in CI only, not locally on macOS/Windows.

---

## Score history

Track score trends per repo and branch with the built-in SQLite store:

```yaml
- name: Run AI Code Gate
  uses: your-org/ai-code-gate@v1
  with:
    score-store: ".ai-gate/scores.db"
```

Query from the CLI:

```bash
# Latest score for a repo
python scripts/score_store.py --db .ai-gate/scores.db query \
  --repo "myorg/myrepo" --type latest

# Score trend (last 30 runs), JSON output
python scripts/score_store.py --db .ai-gate/scores.db query \
  --repo "myorg/myrepo" --type trend --format json

# Aggregate stats (pass rate, avg score, best/worst)
python scripts/score_store.py --db .ai-gate/scores.db query \
  --repo "myorg/myrepo" --type stats
```

---

## Slack notifications

```yaml
- name: Run AI Code Gate
  uses: your-org/ai-code-gate@v1
  with:
    slack-webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

Posts a pass/fail card to your Slack channel with the score, repo, and PR link.

---

## Score badge

Add a live badge to your README:

```markdown
![AI Gate](https://img.shields.io/endpoint?url=https://your-host.com/badge.json)
```

Generate `badge.json` in CI via `--badge-output`:

```bash
python scripts/score.py \
  --coverage coverage.json \
  --semgrep semgrep-results.json \
  --badge-output badge.json
```

---

## Scripts reference

| Script | Purpose |
|--------|---------|
| `scripts/score.py` | Main scorer — computes 0–100 score, report, badge JSON |
| `scripts/detect_fuzz_targets.py` | Maps changed files to fuzz harnesses |
| `scripts/run_fuzz.py` | Runs atheris harnesses, captures crashes |
| `scripts/precommit_complexity.py` | Pre-commit hook — blocks high-complexity commits |
| `scripts/measure_js_complexity.py` | JS/TS complexity via escomplex, outputs JSON |
| `scripts/score_store.py` | SQLite score history — record and query |
| `scripts/notify.py` | Slack / generic webhook notification dispatcher |

---

## Local development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all 126 tests
pytest tests/ -v

# Lint + format
ruff check . && ruff format .

# Run the gate against this repo itself
coverage run --branch -m pytest tests/ -q
coverage json
semgrep --config semgrep-rules/ --json --output semgrep-results.json . || true
python scripts/score.py --coverage coverage.json --semgrep semgrep-results.json --src .

# Install pre-commit hooks
pre-commit install
```

---

## Project structure

```
ai-code-gate/
├── action.yml                    # GitHub Action definition (composite)
├── pyproject.toml                # Python config + [tool.ai-gate] thresholds
├── .pre-commit-config.yaml       # Pre-commit hooks
├── scripts/
│   ├── score.py                  # Main scorer
│   ├── detect_fuzz_targets.py    # Fuzz target resolver
│   ├── run_fuzz.py               # Atheris runner
│   ├── precommit_complexity.py   # Pre-commit complexity gate
│   ├── measure_js_complexity.py  # JS/TS complexity via escomplex
│   ├── score_store.py            # SQLite score history
│   └── notify.py                 # Slack / webhook notifications
├── semgrep-rules/
│   ├── ai-antipatterns.yml       # Python AI anti-patterns (13 rules)
│   └── js-antipatterns.yml       # JS/TS AI anti-patterns (15 rules)
├── fuzz/
│   ├── fuzz_example.py           # Atheris harness template
│   └── targets.txt               # Source glob → harness mapping registry
├── tests/                        # 126 pytest tests
│   ├── test_score.py
│   ├── test_detect_fuzz_targets.py
│   ├── test_score_store.py
│   └── test_notify.py
└── docs/
    └── index.html                # Landing page
```

---

## Contributing

1. Fork the repo and create a branch
2. Add tests for any new functionality — `pytest tests/ -v` must stay green
3. Run `ruff check . && ruff format .` before committing
4. Open a PR — the gate will score itself

---

## License

MIT — free to use, modify, and distribute.
