# Tooling Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the same core code-quality and automation baseline used in `azure-databricks-cost-optimization` to `spotvm`.

**Architecture:** Introduce tooling in stages. First add `ruff` configuration and clean the repo until linting and formatting are green. Then add `mypy` with a pragmatic config and fix any type issues. Finally add `pre-commit`, a small `Makefile`, and extend CI to run the same local checks through `uv`.

**Tech Stack:** Python, uv, Ruff, mypy, pre-commit, GitHub Actions, Makefile

---

### Task 1: Add Ruff and make the repository Ruff-clean

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: source/test files reported by Ruff

**Step 1: Write the failing test**

Use the linter run itself as the failing quality gate.

**Step 2: Run test to verify it fails**

Run: `uv run ruff check .`

Expected: FAIL with current lint violations because Ruff is not configured or fully satisfied yet.

**Step 3: Write minimal implementation**

Add Ruff to the dev dependency set and transfer the relevant Ruff configuration from the reference project, adapted for `spotvm` and Python 3.10. Fix reported issues with the smallest behavior-preserving edits possible.

**Step 4: Run test to verify it passes**

Run:
- `uv run ruff check .`
- `uv run ruff format --check .`

Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock src tests
git commit -m "style: add ruff and clean the codebase"
```

### Task 2: Add mypy and make `src` type-check cleanly

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/**/*.py`

**Step 1: Write the failing test**

Use the type-check run itself as the failing quality gate.

**Step 2: Run test to verify it fails**

Run: `uv run mypy src`

Expected: FAIL because mypy is not configured yet and/or existing code has typing gaps.

**Step 3: Write minimal implementation**

Add a pragmatic mypy configuration modeled on the reference project, then fix real type issues in `src/` until the check is green.

**Step 4: Run test to verify it passes**

Run: `uv run mypy src`

Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock src
git commit -m "style: add mypy checks"
```

### Task 3: Add local automation with pre-commit and Makefile

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `Makefile`
- Modify: `README.md` (only if local commands need documentation updates)

**Step 1: Write the failing test**

Use missing-file/tooling absence as the failure condition.

**Step 2: Run test to verify it fails**

Run:
- `test -f .pre-commit-config.yaml`
- `test -f Makefile`

Expected: FAIL because these files do not exist yet.

**Step 3: Write minimal implementation**

Create a `.pre-commit-config.yaml` with Ruff, pre-commit-hooks, mypy, and a `pytest -q` pre-push hook. Add a small `Makefile` with a canonical `check` target running Ruff, Ruff format check, mypy, and pytest through `uv`.

**Step 4: Run test to verify it passes**

Run:
- `pre-commit validate-config`
- `make check`

Expected: PASS

**Step 5: Commit**

```bash
git add .pre-commit-config.yaml Makefile README.md
git commit -m "chore: add local quality automation"
```

### Task 4: Expand CI to match the local verification flow

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Write the failing test**

Use workflow review plus local command parity as the quality check.

**Step 2: Run test to verify it fails**

Inspect the current workflow and confirm it only runs tests, not linting or type-checking.

**Step 3: Write minimal implementation**

Update CI to:
- install dependencies with `uv`
- run `uv run ruff check .`
- run `uv run ruff format --check .`
- run `uv run mypy src`
- run `uv run pytest -q`

**Step 4: Run test to verify it passes**

Run the same commands locally and verify the workflow file is valid YAML.

**Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run lint, type-check, and tests"
```

### Task 5: Final verification

**Files:**
- Verify: `pyproject.toml`
- Verify: `.pre-commit-config.yaml`
- Verify: `Makefile`
- Verify: `.github/workflows/ci.yml`
- Verify: `src/**/*.py`
- Verify: `tests/**/*.py`

**Step 1: Run targeted quality checks**

Run:
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`

Expected: PASS

**Step 2: Run full test suite**

Run: `uv run pytest -q`

Expected: PASS

**Step 3: Run the canonical local check path**

Run: `make check`

Expected: PASS

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: finalize tooling parity baseline"
```
