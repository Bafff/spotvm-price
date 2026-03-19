# Code Health Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve best-practice usage in `spotvm` without overengineering by making the CLI safer to change, reducing brittle tests, clarifying output contracts, and separating a few overloaded responsibilities.

**Architecture:** Keep the current package shape and CLI behavior. Work in small, behavior-preserving commits that first add safety nets, then simplify hot spots, then split only the modules that are still carrying too many responsibilities. Preserve current output formats unless the team explicitly decides to version and migrate them.

**Tech Stack:** Python 3.10+, `argparse`, `pytest`, `ruff`, `mypy`, `uv`, `make`, Azure REST helpers already in `src/spotvm/`

---

### Task 1: Freeze Current Output Contracts

**Files:**
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_history.py`
- Modify: `tests/test_cli.py`
- Inspect: `src/spotvm/cli.py:1012`
- Inspect: `src/spotvm/history.py`
- Inspect: `src/spotvm/reporting.py`

**Step 1: Write the failing tests**

Add contract tests that lock down the current machine-readable shapes for:
- `_build_report()` JSON keys and value formatting
- history snapshot field names and required fields
- CSV header names and column presence for the supported output modes

**Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest -q tests/test_reporting.py tests/test_history.py tests/test_cli.py
```

Expected: FAIL because at least one contract test will expose undocumented or inconsistent output assumptions.

**Step 3: Write minimal implementation**

Adjust only the tests or tiny projection helpers needed to make the existing behavior explicit. Do not rename JSON keys, history keys, or CSV headers in this task.

**Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest -q tests/test_reporting.py tests/test_history.py tests/test_cli.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_reporting.py tests/test_history.py tests/test_cli.py
git commit -m "test: freeze current output contracts"
```

### Task 2: Replace Fragile CLI Mock Stacks With Boundary Tests

**Files:**
- Create: `tests/test_cli_pipeline.py`
- Create: `tests/test_cli_parser.py`
- Create: `tests/test_cli_unattended.py`
- Modify: `tests/test_cli.py`
- Inspect: `src/spotvm/cli.py:721`
- Inspect: `src/spotvm/cli.py:735`
- Inspect: `src/spotvm/cli.py:768`
- Inspect: `src/spotvm/http_client.py`

**Step 1: Write the failing test**

Create 2-3 integration-style tests that exercise `_run_single_analysis()` and adjacent CLI orchestration with a lightweight boundary fake instead of deep nested mocks.

**Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest -q tests/test_cli.py tests/test_cli_pipeline.py tests/test_cli_parser.py tests/test_cli_unattended.py
```

Expected: FAIL because the new tests should initially reveal missing fixtures, missing helpers, or existing test structure that is too coupled.

**Step 3: Write minimal implementation**

Split `tests/test_cli.py` by behavior slice and keep only the remaining cases that truly belong in the legacy file. Patch only the Azure boundary or use small local fakes; do not patch every internal helper in the pipeline.

**Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest -q tests/test_cli.py tests/test_cli_pipeline.py tests/test_cli_parser.py tests/test_cli_unattended.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py tests/test_cli_pipeline.py tests/test_cli_parser.py tests/test_cli_unattended.py
git commit -m "test: simplify cli coverage and reduce overmocking"
```

### Task 3: Finish the Narrow `cli.py` Decomposition

**Files:**
- Modify: `src/spotvm/cli.py:412`
- Modify: `src/spotvm/cli.py:450`
- Modify: `src/spotvm/cli.py:768`
- Modify: `src/spotvm/cli.py:936`
- Modify: `tests/test_cli_pipeline.py`
- Modify: `tests/test_cli_unattended.py`

**Step 1: Write the failing test**

Add or extend direct-call tests for the extracted CLI orchestration seams around:
- data collection
- candidate processing and filtering
- persistence and export
- terminal rendering

**Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest -q tests/test_cli_pipeline.py tests/test_cli_unattended.py
```

Expected: FAIL before the extraction because the new helper boundaries do not exist yet.

**Step 3: Write minimal implementation**

Extract private helpers from `cli.py` only where they reduce branching and make tests simpler. Preserve `main()` behavior, CLI arguments, output text, and exit-code behavior.

**Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest -q tests/test_cli_pipeline.py tests/test_cli_unattended.py tests/test_cli.py
uv run spotvm --help
```

Expected: PASS and unchanged help output structure.

**Step 5: Commit**

```bash
git add src/spotvm/cli.py tests/test_cli.py tests/test_cli_pipeline.py tests/test_cli_unattended.py
git commit -m "refactor: finish narrow cli orchestration extraction"
```

### Task 4: Centralize Candidate Projection Without Changing External Schemas

**Files:**
- Modify: `src/spotvm/cli.py:1012`
- Modify: `src/spotvm/history.py`
- Modify: `src/spotvm/reporting.py`
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_history.py`
- Modify: `tests/test_cli_pipeline.py`

**Step 1: Write the failing test**

Add tests showing that report JSON, history snapshots, and CSV exports are built from overlapping but currently duplicated candidate projection logic.

**Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest -q tests/test_reporting.py tests/test_history.py tests/test_cli_pipeline.py
```

Expected: FAIL because the shared mapping layer does not exist yet.

**Step 3: Write minimal implementation**

Introduce one small internal mapping layer for candidate projection and reuse it across JSON report, history, and CSV code paths. Preserve the current public output keys per format.

**Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest -q tests/test_reporting.py tests/test_history.py tests/test_cli_pipeline.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/cli.py src/spotvm/history.py src/spotvm/reporting.py tests/test_reporting.py tests/test_history.py tests/test_cli_pipeline.py
git commit -m "refactor: share candidate projection across outputs"
```

### Task 5: Clarify Error Contracts And Narrow Boundary Typing

**Files:**
- Modify: `src/spotvm/config.py`
- Modify: `src/spotvm/http_client.py`
- Modify: `src/spotvm/resource_graph.py`
- Modify: `src/spotvm/cli.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_http_client.py`
- Modify: `tests/test_cli_parser.py`

**Step 1: Write the failing test**

Add tests that make the intended failure modes explicit for config loading, CLI validation, and Azure HTTP failures.

**Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest -q tests/test_config.py tests/test_http_client.py tests/test_cli_parser.py
uv run mypy src
```

Expected: FAIL because the current contracts are only implicit and some boundary types are too loose.

**Step 3: Write minimal implementation**

Document or narrow the existing exceptions, add lightweight `TypedDict` or local typed payload helpers only where the code already consumes a known subset of fields, and reduce `Any` in the most-used CLI pipeline signatures.

**Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest -q tests/test_config.py tests/test_http_client.py tests/test_cli_parser.py
uv run mypy src
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/config.py src/spotvm/http_client.py src/spotvm/resource_graph.py src/spotvm/cli.py tests/test_config.py tests/test_http_client.py tests/test_cli_parser.py
git commit -m "refactor: clarify boundary contracts and typing"
```

### Task 6: Split `vm_specs` Catalog From Policy Behind A Stable Facade

**Files:**
- Create: `src/spotvm/vm_catalog.py`
- Modify: `src/spotvm/vm_specs.py`
- Modify: `tests/test_vm_specs.py`

**Step 1: Write the failing test**

Add tests that separately exercise static catalog lookup and policy-driven filtering/scoring behavior while keeping `spotvm.vm_specs` public usage unchanged.

**Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest -q tests/test_vm_specs.py
```

Expected: FAIL because the catalog/policy seam is not explicit yet.

**Step 3: Write minimal implementation**

Move the static VM specification catalog into one adjacent module and keep policy/filtering helpers in `vm_specs.py` or small private helpers. Re-export or preserve the current public API surface from `spotvm.vm_specs`.

**Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest -q tests/test_vm_specs.py
uv run pytest -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/vm_catalog.py src/spotvm/vm_specs.py tests/test_vm_specs.py
git commit -m "refactor: separate vm catalog from policy"
```

### Task 7: Reconcile Health Tracking And Lock The Batch

**Files:**
- Inspect: `.desloppify/state-python.json`
- Inspect: `.desloppify/plan.json`
- Modify: docs or notes only if needed for evidence

**Step 1: Re-run health checks**

Run:
```bash
make check
uv run pytest -q
```

Expected: PASS

**Step 2: Re-scan the code health backlog**

Run the repo’s normal `.desloppify` scan/status workflow and verify which exact items were cleared by the batch.

**Step 3: Resolve only evidence-backed findings**

Close stale or fixed items only when the code and tests clearly support the resolution.

**Step 4: Commit**

```bash
git add -A
git commit -m "docs: update code health tracking after roadmap batch"
```

## Constraints

- Preserve current CLI behavior and user-facing output unless a separate migration plan is approved.
- Prefer extraction and deduplication over new abstractions.
- Keep each commit narrow enough that a junior developer can review and revert it confidently.
- Do not touch `scorecard.png`.
- Do not migrate to Typer, Click, async I/O, or a large schema library in this roadmap.

## Verification Checklist For Every Commit

- Run the smallest focused tests first for the files touched.
- Run `uv run pytest -q` before marking a task complete.
- Run `make check` before finishing the branch or claiming the roadmap batch is done.
- Review the diff for accidental output, help-text, or exit-code changes.

## Suggested Execution Order

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 6
7. Task 7

