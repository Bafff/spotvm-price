# Databricks Review Follow-Up Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep Databricks total-price semantics for ranking and `--max-price`, while making unavailable totals and related exclusions visible and handling history CSV write failures cleanly.

**Architecture:** Preserve the existing `total_price_usd` model as the comparable ranked price in Databricks mode. Improve user-facing behavior in reporting and CLI summaries instead of falling back to VM-only pricing for filtering, and tighten a few low-risk operational/type-doc issues raised in review.

**Tech Stack:** Python 3.10, pytest, argparse CLI, dataclasses

---

### Task 1: Lock in the desired behavior with tests

**Files:**
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_databricks_catalog.py`

**Step 1: Write the failing reporting tests**

Add tests covering:
- Databricks table output keeps `Price (USD/hr)` empty when `total_price_usd` is unavailable but still shows `VM (USD/hr)` and a compact `DBU1` note.
- JSON/CSV-facing behavior remains unchanged unless explicitly intended.

**Step 2: Run the focused reporting tests to verify they fail**

Run: `uv run pytest tests/test_reporting.py -q`
Expected: FAIL on the new visibility expectations.

**Step 3: Write the failing CLI/history tests**

Add tests covering:
- `_render_analysis_results()` emits a visible note when candidates were excluded from `--max-price` because Databricks total price was unavailable.
- `_run_history_analysis()` returns a friendly non-zero result on `OSError` from history CSV generation.

**Step 4: Run the focused CLI tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL on the new CLI/output expectations.

**Step 5: Write the failing catalog logging/doc tests**

Add a test covering:
- Stub-row skipping is surfaced at warning level.

**Step 6: Run the focused catalog tests to verify they fail**

Run: `uv run pytest tests/test_databricks_catalog.py -q`
Expected: FAIL on the new warning-level expectation.

### Task 2: Implement the minimal production changes

**Files:**
- Modify: `src/spotvm/analysis.py`
- Modify: `src/spotvm/cli.py`
- Modify: `src/spotvm/reporting.py`
- Modify: `src/spotvm/models.py`
- Modify: `src/spotvm/databricks_catalog.py`

**Step 1: Surface Databricks exclusion state on candidates**

Add a small helper or note-merging path so candidates excluded by `--max-price` due to missing total price can be counted and reported by the CLI without changing ranking/filter semantics.

**Step 2: Update terminal rendering behavior**

Keep `Price (USD/hr)` tied to `effective_price_usd(candidate)`, but ensure Databricks-mode rows with missing totals still expose the VM-only price through the Databricks columns and notes.

**Step 3: Update CLI reporting**

Catch `OSError` in `_run_history_analysis()` and return the same friendly style used elsewhere. Also emit a visible summary note when `--max-price` excluded candidates because Databricks totals were unavailable.

**Step 4: Tighten low-risk review follow-ups**

Adjust the stub-row skip log level and improve Databricks field/captured-at documentation/types only where it does not expand scope.

**Step 5: Run focused tests to verify green**

Run:
- `uv run pytest tests/test_reporting.py -q`
- `uv run pytest tests/test_cli.py -q`
- `uv run pytest tests/test_databricks_catalog.py -q`

Expected: PASS

### Task 3: Full verification

**Files:**
- No additional code changes expected

**Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: PASS

**Step 2: Run static checks**

Run:
- `uv run mypy src`
- `uv run ruff check .`
- `uv run ruff format --check .`

Expected: PASS

**Step 3: Commit**

```bash
git add docs/plans/2026-03-24-databricks-review-followup.md tests/test_reporting.py tests/test_cli.py tests/test_databricks_catalog.py src/spotvm/analysis.py src/spotvm/cli.py src/spotvm/reporting.py src/spotvm/models.py src/spotvm/databricks_catalog.py
git commit -m "fix: surface databricks pricing exclusion details"
```
