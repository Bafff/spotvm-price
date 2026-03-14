# CLI Request Shape Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the raw `argparse.Namespace` dependency in `_run_single_analysis()` with one explicit CLI execution request, then queue adjacent abstraction and test-health items as separate follow-up commits.

**Architecture:** Keep `ToolConfig` as the validated runtime configuration object. Add a small immutable `AnalysisRunRequest` owned by `cli.py` for CLI-only execution inputs, build it in `main()`, and pass it into `_run_single_analysis()`. Follow-on batches narrow the fetcher APIs and then reduce `tests/test_cli.py` over-mocking, each in its own commit.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, pytest

---

### Task 1: Add failing CLI request-shape tests

**Files:**
- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add tests that prove:

- a new `AnalysisRunRequest` captures the CLI-only execution inputs currently read from `args`
- `_run_single_analysis()` no longer requires a raw `argparse.Namespace`
- unattended mode can force `save_results=True` via the request shape rather than a separate boolean parameter

Suggested test names:

```python
def test_build_analysis_run_request_copies_cli_execution_fields():
    ...

def test_run_single_analysis_uses_analysis_run_request():
    ...
```

**Step 2: Run test to verify it fails**

Run:

- `uv run pytest -q tests/test_cli.py -k analysis_run_request`

Expected: FAIL because the request type/builder does not exist yet and `_run_single_analysis()` still depends on `args`.

**Step 3: Write minimal implementation**

Add a small immutable request object and builder, for example:

```python
@dataclass(frozen=True)
class AnalysisRunRequest:
    no_color: bool
    min_vcpu: int | None
    min_ram: int | None
    no_max_limit: bool
    explicit_sizes: bool
    max_price: float | None
    max_eviction: float | None
    min_performance: float | None
    csv: Path | None
    results_dir: Path
    save_results: bool
```

Then build it in `main()` and pass it to `_run_single_analysis()`.

**Step 4: Run test to verify it passes**

Run:

- `uv run pytest -q tests/test_cli.py -k analysis_run_request`

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/cli.py tests/test_cli.py
git commit -m "desloppify: add explicit cli run request"
```

### Task 2: Keep the CLI batch behavior-preserving

**Files:**
- Modify: `src/spotvm/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add or update tests that cover the existing execution behavior after the signature change:

- save-results path still uses `results_dir`
- CSV export still uses the request CSV path
- color handling still derives from the request and terminal state

**Step 2: Run test to verify it fails**

Run:

- `uv run pytest -q tests/test_cli.py -k 'save_results or csv_export or save_report'`

Expected: FAIL if any behavior regressed during the API switch.

**Step 3: Write minimal implementation**

Update `_run_single_analysis()` internals to read from `AnalysisRunRequest` instead of `args`, without changing user-visible behavior or broadening scope.

**Step 4: Run test to verify it passes**

Run:

- `uv run pytest -q tests/test_cli.py -k 'save_results or csv_export or save_report'`

Expected: PASS

**Step 5: Commit**

Keep this work in the same commit as Task 1 if it is part of the same narrow request-shape batch. Do not mix in fetcher API changes.

### Task 3: Verify and review Batch 1

**Files:**
- Verify: `src/spotvm/cli.py`
- Verify: `tests/test_cli.py`

**Step 1: Run focused verification**

Run:

- `uv run pytest -q tests/test_cli.py`

Expected: PASS

**Step 2: Run full verification**

Run:

- `uv run pytest -q`

Expected: PASS

**Step 3: Run Claude review**

Run the local Claude CLI on the uncommitted Batch 1 diff, asking for real bugs/regressions only. Fix valid findings, then re-run the focused and full verification commands.

**Step 4: Commit**

```bash
git add src/spotvm/cli.py tests/test_cli.py
git commit -m "desloppify: add explicit cli run request"
```

### Task 4: Follow-on batch queue, separate commits

**Files:**
- Modify later: `src/spotvm/resource_graph.py`
- Modify later: `src/spotvm/placement_score.py`
- Modify later: `tests/test_resource_graph.py`
- Modify later: `tests/test_placement_score.py`
- Modify later: `tests/test_cli.py`

**Step 1: Resource Graph request batch**

Goal: replace the broad `ToolConfig` parameter in `fetch_historical_metrics()` with explicit inputs or a small request object local to that module.

Commit:

```bash
git commit -m "desloppify: narrow resource graph inputs"
```

**Step 2: Placement Score request batch**

Goal: replace the broad `ToolConfig` parameter in `fetch_placement_scores()` with explicit inputs or a small request object local to that module.

Commit:

```bash
git commit -m "desloppify: narrow placement score inputs"
```

**Step 3: CLI test-strategy batch**

Goal: reduce `tests/test_cli.py` over-mocking by introducing a smaller number of higher-signal integration-style tests around request/config orchestration.

Commit:

```bash
git commit -m "desloppify: reduce cli test over-mocking"
```

**Step 4: Next CLI structure batch**

Goal: extract one focused slice from `main()` or `_run_single_analysis()` to start shrinking `monster_function` and `high_cyclomatic_complexity` without starting the full architecture split.

Commit:

```bash
git commit -m "desloppify: extract cli execution helpers"
```

**Step 5: Review gate for each follow-on batch**

For each batch above:

- write failing tests first
- run focused pytest and confirm failure
- implement the smallest fix
- run focused verification
- run `uv run pytest -q`
- run local Claude review on the uncommitted diff
- fix valid findings
- re-run verification before committing
