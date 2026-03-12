# Spotvm Rename Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename the project, package, CLI, runtime identifiers, tests, and docs from the legacy public names to `spotvm` with no backward compatibility aliases.

**Architecture:** Move the Python package directory from the legacy package path to `src/spotvm`, then update packaging metadata and all imports to target the new module path. Finish by renaming user-facing/runtime strings such as the CLI program name, logger name, user agent, cache directory, and README usage examples, then verify the renamed package works end-to-end.

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
- CLI help now prints `spotvm`, not the legacy CLI name.
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

At this point in the plan Task 2 has not happened yet, so these paths still live under the legacy package directory.

```bash
git add tests/test_cli.py tests/test_cache.py tests/test_history.py tests/test_resource_graph.py \
    src/<legacy_package_dir>/cli.py src/<legacy_package_dir>/cache.py src/<legacy_package_dir>/history.py \
    src/<legacy_package_dir>/resource_graph.py src/<legacy_package_dir>/http_client.py
git commit -m "refactor: rename runtime identifiers to spotvm"
```

### Task 2: Rename the Python package from the legacy import path to `spotvm`

**Files:**
- Move: `src/<legacy_package_dir>/` -> `src/spotvm/`
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

Run a repo-wide search in `README.md` and `ROADMAP.md` for the legacy CLI/import names.

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

Run the same repo-wide search again in `README.md` and `ROADMAP.md`.

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
- Search `src`, `tests`, `README.md`, `ROADMAP.md`, and `pyproject.toml` for legacy CLI/import names.

Expected: no stale references except intentionally preserved plan files.

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: complete breaking rename to spotvm"
```
