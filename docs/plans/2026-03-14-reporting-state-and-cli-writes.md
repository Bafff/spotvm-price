# Reporting State And CLI Writes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove `reporting.py` import-time/shared render state and make JSON report writes in the CLI atomic.

**Architecture:** Replace the module-global color toggle with explicit render options passed into rendering helpers so output behavior is controlled by call sites instead of hidden shared state. Keep the CLI responsible for initializing terminal color support and use a small file-write helper that writes JSON via a temp file and `Path.replace()` so report writes are atomic.

**Tech Stack:** Python 3.10+, pytest, pathlib, colorama, dataclasses.

---

### Task 1: Add failing reporting-state tests

**Files:**
- Modify: `tests/test_reporting.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_reporting.py`

**Step 1: Write the failing tests**

Add tests that prove:
- `render_table()` can be forced into plain-text mode via an explicit render option instead of global mutation
- colorized helpers still colorize when explicit options enable colors
- tests no longer depend on `reporting._COLORS_ENABLED`

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_reporting.py`
Expected: FAIL because the reporting module still uses shared global state.

### Task 2: Add failing atomic report-write tests

**Files:**
- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add tests that prove:
- report saving no longer depends on `Path.write_text()`
- report saving uses an atomic temp-write path and still creates parent directories

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_cli.py -k save_report`
Expected: FAIL because `_run_single_analysis()` still calls `write_text()` directly.

### Task 3: Implement explicit reporting options

**Files:**
- Modify: `src/spotvm/reporting.py`
- Modify: `src/spotvm/cli.py`
- Test: `tests/test_reporting.py`

**Step 1: Write minimal implementation**

Change reporting so that:
- import-time `colorama.init()` side effects are removed
- module-global color flags are removed
- rendering helpers take explicit `RenderOptions` or `colors_enabled` input
- CLI initializes color support once and passes render options to `render_table()`

**Step 2: Run test to verify it passes**

Run: `uv run pytest -q tests/test_reporting.py`
Expected: PASS

### Task 4: Implement atomic report writes

**Files:**
- Modify: `src/spotvm/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write minimal implementation**

Add a helper that:
- ensures the parent directory exists
- writes JSON to a temp file in the target directory
- atomically replaces the destination file

**Step 2: Run test to verify it passes**

Run: `uv run pytest -q tests/test_cli.py -k save_report`
Expected: PASS

### Task 5: Verify and review

**Files:**
- Verify: `src/spotvm/reporting.py`
- Verify: `src/spotvm/cli.py`
- Verify: `tests/test_reporting.py`
- Verify: `tests/test_cli.py`

**Step 1: Run focused and full verification**

Run: `uv run pytest -q tests/test_reporting.py tests/test_cli.py`
Expected: PASS

Run: `uv run pytest -q`
Expected: PASS

**Step 2: Request external review**

Run the local Claude CLI in print mode against the diff for this batch, review the findings, fix any valid issues, and re-run verification.

**Step 3: Commit**

```bash
git add docs/plans/2026-03-14-reporting-state-and-cli-writes.md src/spotvm/reporting.py src/spotvm/cli.py tests/test_reporting.py tests/test_cli.py tests/conftest.py
git commit -m "desloppify: remove reporting shared state"
desloppify plan commit-log record
```
