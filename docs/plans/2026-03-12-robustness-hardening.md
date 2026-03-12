# Robustness Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden cache, history, parsing, and CLI save-results paths so malformed data and filesystem errors warn and degrade gracefully instead of crashing or failing silently.

**Architecture:** Keep the existing APIs and call structure intact. Add localized warning-level exception handling and parsing diagnostics, then backfill the missing direct unit tests and passthrough coverage without broad refactors.

**Tech Stack:** Python, pytest, argparse, pathlib, standard logging

---

### Task 1: Add missing low-level helper coverage

**Files:**
- Modify: `tests/test_filtering.py`
- Modify: `tests/test_performance.py`

**Step 1: Write the failing tests**

Add direct tests for:
- `known_hardware_tiers("vcpu")` / `known_hardware_tiers("ram")`
- `hardware_window_tiers(...)`
- `matches_hardware_constraint(...)` with bounded and unbounded cases
- `calculate_relative_performance_details(...)` for CoreMark, heuristic, and missing-SKU cases

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_filtering.py tests/test_performance.py -q -k 'known_hardware_tiers or hardware_window_tiers or matches_hardware_constraint or calculate_relative_performance_details'`

**Step 3: Write minimal implementation**

Only adjust production code if a helper behaves differently than intended.

**Step 4: Run test to verify it passes**

Run the same command and confirm green.

### Task 2: Add CLI passthrough and save-results robustness coverage

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/spotvm_tool/cli.py`

**Step 1: Write the failing tests**

Add tests for:
- `main()` passing `no_max_limit=True` into `discover_skus()`
- `_run_single_analysis()` continuing after `save_run_results()` raises `OSError`
- `--desired-count` help text describing the effective placement-mode default

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q -k 'no_max_limit or save_run_results or desired_count'`

**Step 3: Write minimal implementation**

- Simplify `_run_single_analysis()` to a single `filter_by_requirements()` call using `effective_no_max_limit`
- Wrap `save_run_results()` with warning-level handling
- Update help text for `--desired-count`

**Step 4: Run test to verify it passes**

Run the same command and confirm green.

### Task 3: Harden cache and history file handling

**Files:**
- Modify: `src/spotvm_tool/cache.py`
- Modify: `src/spotvm_tool/history.py`
- Modify: `tests/test_history.py`

**Step 1: Write the failing tests**

Add tests for:
- `cache.load()` treating `OSError` as a cache miss with warning
- `cache.store()` warning and returning when writes fail
- `load_historical_runs()` skipping malformed/unreadable files and still loading valid ones

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_history.py -q -k 'cache or malformed or unreadable'`

**Step 3: Write minimal implementation**

- Catch `OSError` in cache read/write paths
- Catch malformed JSON and `OSError` in historical run loading and continue

**Step 4: Run test to verify it passes**

Run the same command and confirm green.

### Task 4: Add parsing warnings for malformed numeric fields

**Files:**
- Modify: `src/spotvm_tool/resource_graph.py`
- Modify: `tests/test_resource_graph.py`

**Step 1: Write the failing tests**

Add tests that malformed non-empty price/eviction values emit warning logs and return `None`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_resource_graph.py -q -k 'warning or malformed'`

**Step 3: Write minimal implementation**

- Add warning logs in `_to_float()`
- Add warning log in `_extract_eviction()` when parsing fails after fallback attempts

**Step 4: Run test to verify it passes**

Run the same command and confirm green.

### Task 5: Final verification and commit

**Files:**
- Modify: tracked files touched above

**Step 1: Run full verification**

Run: `uv run pytest -q`

**Step 2: Check diff health**

Run: `git diff --check`

**Step 3: Commit**

Commit only the intended tracked files for this robustness pass.
