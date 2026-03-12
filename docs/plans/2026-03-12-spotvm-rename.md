# Spotvm Rename Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename the project, package, CLI, runtime identifiers, tests, and docs from `spotvm-tool` / `spotvm_tool` to `spotvm` with no backward compatibility aliases.

**Architecture:** Move the Python package directory from `src/spotvm_tool` to `src/spotvm`, then update packaging metadata and all imports to target the new module path. Finish by renaming user-facing/runtime strings such as the CLI program name, logger name, user agent, cache directory, and README usage examples, then verify the renamed package works end-to-end.

**Tech Stack:** Python, setuptools `pyproject.toml`, argparse, pytest, Markdown docs

---

### Task 1: Add failing rename coverage for the new public identity

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_cache.py`
- Modify: `tests/test_history.py`
- Modify: `tests/test_resource_graph.py`

**Step 1: Write the failing test**

Add or update tests that assert:
- CLI help now prints `spotvm`, not `spotvm-tool`.
- logger-based tests use the `spotvm` logger.
- cache tests expect the `~/.cache/spotvm` path.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py tests/test_cache.py tests/test_history.py tests/test_resource_graph.py -q`

Expected: FAIL because the code still emits old names.

**Step 3: Write minimal implementation**

Update the minimal runtime strings needed to satisfy the new expectations.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py tests/test_cache.py tests/test_history.py tests/test_resource_graph.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py tests/test_cache.py tests/test_history.py tests/test_resource_graph.py \
    src/spotvm_tool/cli.py src/spotvm_tool/cache.py src/spotvm_tool/history.py \
    src/spotvm_tool/resource_graph.py src/spotvm_tool/http_client.py
git commit -m "refactor: rename runtime identifiers to spotvm"
```

### Task 2: Rename the Python package from `spotvm_tool` to `spotvm`

**Files:**
- Move: `src/spotvm_tool/` -> `src/spotvm/`
- Modify: `pyproject.toml`
- Modify: all files under `src/`
- Modify: all files under `tests/`

**Step 1: Write the failing test**

Update imports in a focused subset of tests to use `spotvm`, then ensure they fail until the package move is complete.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reporting.py tests/test_performance.py tests/test_placement_score.py -q`

Expected: FAIL with `ModuleNotFoundError` or import errors referencing `spotvm`.

**Step 3: Write minimal implementation**

- Rename the package directory.
- Update internal relative imports if needed.
- Update external imports in tests.
- Change `pyproject.toml` project name and console entry point to `spotvm`.
- Change `__version__` lookup to use `spotvm`.
- Ensure `src` package discovery still works after the move.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reporting.py tests/test_performance.py tests/test_placement_score.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml src tests
git commit -m "refactor: rename python package to spotvm"
```

### Task 3: Update README, roadmap, and examples for the breaking rename

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`

**Step 1: Write the failing test**

No automated test. Use a grep-based docs checklist.

**Step 2: Run test to verify it fails**

Run: `rg -n "spotvm-tool|spotvm_tool" README.md ROADMAP.md`

Expected: old names still appear.

**Step 3: Write minimal implementation**

Update:
- installation commands
- usage examples
- troubleshooting text
- cache path mentions
- module invocation examples

Only keep old names where explicitly describing the breaking rename.

**Step 4: Run test to verify it passes**

Run: `rg -n "spotvm-tool|spotvm_tool" README.md ROADMAP.md`

Expected: no stale references, or only deliberate explanatory references if added.

**Step 5: Commit**

```bash
git add README.md ROADMAP.md
git commit -m "docs: rename tool references to spotvm"
```

### Task 4: Full verification of the renamed package

**Files:**
- Verify: `pyproject.toml`
- Verify: `src/spotvm/`
- Verify: `tests/`
- Verify: `README.md`

**Step 1: Run targeted rename checks**

Run:
- `uv run pytest tests/test_cli.py tests/test_cache.py tests/test_history.py tests/test_resource_graph.py tests/test_reporting.py tests/test_performance.py tests/test_placement_score.py -q`
- `uv run python -m spotvm --help`

Expected:
- tests pass
- module help renders with `spotvm`

**Step 2: Run full suite**

Run: `uv run pytest -q`

Expected: PASS

**Step 3: Check for stale names**

Run:
- `rg -n "spotvm-tool|spotvm_tool" src tests README.md ROADMAP.md pyproject.toml`

Expected: no stale references except intentionally preserved plan files.

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: complete breaking rename to spotvm"
```
