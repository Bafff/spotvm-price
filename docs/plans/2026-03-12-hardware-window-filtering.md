# Hardware Window Filtering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add bounded CPU/RAM discovery windows by default, with `--no-max-limit` to restore unbounded minimum filtering.

**Architecture:** Introduce shared helpers that compute bounded hardware windows from known VM specs, then use them from both SKU autodiscovery and post-fetch requirement filtering. Keep bounded mode as the default, exclude unknown SKUs only in bounded mode, and expose the behavior clearly through CLI help and docs.

**Tech Stack:** Python, argparse, pytest, README markdown

---

### Task 1: Add failing tests for bounded autodiscovery and filtering

**Files:**
- Modify: `tests/test_filtering.py`

**Step 1: Write the failing test**

Add tests that assert:
- `discover_skus(min_vcpu=4)` excludes large tiers such as 32/64 vCPU by default.
- `discover_skus(min_vcpu=4, min_ram=16)` only returns SKUs within the CPU and RAM windows.
- `filter_by_requirements(..., min_vcpu=4, min_ram=16)` excludes unknown SKUs in bounded mode.
- `discover_skus(..., no_max_limit=True)` and `filter_by_requirements(..., no_max_limit=True)` keep current unbounded behavior.

**Step 2: Run test to verify it fails**

Run: `./.review-venv/bin/pytest tests/test_filtering.py -q`

Expected: FAIL because bounded-window behavior and `no_max_limit` do not exist yet.

**Step 3: Write minimal implementation**

Implement the minimal helpers and function signatures needed to satisfy the new tests.

**Step 4: Run test to verify it passes**

Run: `./.review-venv/bin/pytest tests/test_filtering.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_filtering.py src/spotvm_tool/vm_specs.py src/spotvm_tool/analysis.py
git commit -m "feat: bound hardware discovery windows"
```

### Task 2: Add failing CLI tests for new flag and help text

**Files:**
- Modify: `tests/test_cli.py`

**Step 1: Write the failing test**

Add tests that assert:
- `parse_args` recognizes `--no-max-limit`.
- `--help` text for `--min-vcpu` and `--min-ram` describes the default 3-tier window.
- `--help` text includes `--no-max-limit`.

**Step 2: Run test to verify it fails**

Run: `./.review-venv/bin/pytest tests/test_cli.py -q`

Expected: FAIL because the parser and help text have not been updated.

**Step 3: Write minimal implementation**

Update argparse definitions and CLI plumbing for the new flag and messaging.

**Step 4: Run test to verify it passes**

Run: `./.review-venv/bin/pytest tests/test_cli.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/spotvm_tool/cli.py
git commit -m "feat: add no-max-limit hardware flag"
```

### Task 3: Update documentation

**Files:**
- Modify: `README.md`

**Step 1: Write the failing test**

No automated test. Use a documentation review checklist.

**Step 2: Run test to verify it fails**

Manually verify that the README does not yet describe bounded windows or `--no-max-limit`.

**Step 3: Write minimal implementation**

Update command examples and option descriptions to explain:
- bounded 3-tier CPU/RAM windows by default
- `--no-max-limit` for unbounded discovery
- unknown SKUs being excluded in bounded mode

**Step 4: Run test to verify it passes**

Run: `rg -n \"no-max-limit|3-tier|nearest 3|bounded\" README.md`

Expected: matching documentation lines

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs: explain bounded hardware filtering"
```

### Task 4: Final verification

**Files:**
- Verify: `tests/test_filtering.py`
- Verify: `tests/test_cli.py`
- Verify: `README.md`

**Step 1: Run targeted tests**

Run: `./.review-venv/bin/pytest tests/test_filtering.py tests/test_cli.py -q`

Expected: PASS

**Step 2: Run full suite**

Run: `./.review-venv/bin/pytest -q`

Expected: PASS

**Step 3: Spot-check CLI behavior**

Run:
- `spotvm-tool --help`
- `spotvm-tool --regions centralus --min-vcpu 4 --min-ram 16 --json`
- `spotvm-tool --regions centralus --min-vcpu 4 --min-ram 16 --no-max-limit --json`

Expected:
- help describes bounded mode and the escape hatch
- bounded mode returns right-sized SKUs
- `--no-max-limit` reintroduces larger tiers

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: add bounded hardware requirement windows"
```
