# Databricks Pricing Catalog Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an opt-in Databricks pricing overlay to `spotvm` using a vendored local DBU catalog, a separate refresh command, and optional Photon surcharge support without live pricing lookups by default.

**Architecture:** Keep the current Azure VM analysis flow intact, then layer Databricks pricing on top only when requested. Store DBU metadata in a versioned package-data JSON file, load it during analysis, and refresh it only through an explicit CLI path that writes a deterministic snapshot back into the repo.

**Tech Stack:** Python 3.10+, `argparse`, `pytest`, `json`, package data under `src/spotvm/`, existing `CandidateInsight`/`reporting`/`history` pipeline

---

### Task 1: Freeze The Desired CLI And Output Contracts

**Files:**
- Modify: `tests/test_cli_args.py`
- Modify: `tests/test_output_contracts.py`
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_history.py`
- Inspect: `src/spotvm/cli.py`
- Inspect: `src/spotvm/reporting.py`
- Inspect: `src/spotvm/history.py`
- Inspect: `src/spotvm/projection.py`

**Step 1: Write the failing tests**

Add tests that define the target behavior:

- parser accepts:
  - `--include-databricks-cost`
  - `--include-photon-cost`
  - `--refresh-databricks-catalog`
- parser rejects `--include-photon-cost` without `--include-databricks-cost`
- default output contracts remain unchanged when Databricks mode is off
- CSV/report/history include the new pricing fields only when Databricks mode is on

Use concrete assertions, for example:

```python
args = build_parser().parse_args(
    [
        "--regions", "centralus",
        "--sizes", "Standard_D4ps_v6",
        "--include-databricks-cost",
    ]
)
assert args.include_databricks_cost is True
assert args.include_photon_cost is False
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q tests/test_cli_args.py tests/test_output_contracts.py tests/test_reporting.py tests/test_history.py
```

Expected: FAIL because the flags and optional output fields do not exist yet.

**Step 3: Write minimal implementation**

Do not implement behavior yet. Only add the smallest placeholders needed later if a test absolutely requires importable symbols. Prefer leaving the failure until the real tasks.

**Step 4: Run test to verify it still reflects the missing feature**

Run:

```bash
uv run pytest -q tests/test_cli_args.py tests/test_output_contracts.py tests/test_reporting.py tests/test_history.py
```

Expected: FAIL with missing flags or fields, not unrelated breakage.

**Step 5: Commit**

```bash
git add tests/test_cli_args.py tests/test_output_contracts.py tests/test_reporting.py tests/test_history.py
git commit -m "test: define databricks pricing cli and output contracts"
```

### Task 2: Add A Vendored Databricks Pricing Catalog Loader

**Files:**
- Create: `src/spotvm/databricks_catalog.py`
- Create: `src/spotvm/data/databricks_pricing.json`
- Modify: `pyproject.toml`
- Create: `tests/test_databricks_catalog.py`
- Inspect: `src/spotvm/models.py`

**Step 1: Write the failing test**

Add tests for loading the vendored catalog and looking up SKU pricing:

```python
from spotvm.databricks_catalog import load_catalog, lookup_sku

def test_lookup_sku_returns_dbu_and_photon_values():
    catalog = load_catalog()
    entry = lookup_sku(catalog, "Standard_D4ps_v6")
    assert entry.sku == "Standard_D4ps_v6"
    assert entry.dbu_per_hour > 0
```

Also add tests for:

- stable metadata shape
- case-sensitive exact SKU matching
- helpful failure on malformed JSON

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q tests/test_databricks_catalog.py
```

Expected: FAIL because the loader module and package data do not exist.

**Step 3: Write minimal implementation**

Implement:

- dataclasses for catalog metadata and SKU entries
- loader using package-local JSON
- lookup helper returning `None` for unknown SKU
- deterministic seed snapshot JSON with a small starter set of SKUs used in current ARM work

Also update packaging so `databricks_pricing.json` ships with the package.

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q tests/test_databricks_catalog.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/databricks_catalog.py src/spotvm/data/databricks_pricing.json pyproject.toml tests/test_databricks_catalog.py
git commit -m "feat: add vendored databricks pricing catalog"
```

### Task 3: Implement Explicit Catalog Refresh

**Files:**
- Modify: `src/spotvm/cli.py`
- Modify: `src/spotvm/databricks_catalog.py`
- Create: `tests/test_databricks_refresh.py`
- Modify: `README.md`

**Step 1: Write the failing test**

Add tests for refresh-only behavior:

```python
def test_refresh_databricks_catalog_exits_without_running_analysis(monkeypatch, tmp_path):
    ...
    rc = main(["--refresh-databricks-catalog"])
    assert rc == 0
```

Also test:

- refresh writes the vendored JSON atomically
- refresh reports changed/new/removed counts
- normal analysis path does not call refresh fetch logic

Stub the network/parser boundary so the test stays offline.

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q tests/test_databricks_refresh.py tests/test_cli_args.py
```

Expected: FAIL because refresh mode does not exist.

**Step 3: Write minimal implementation**

Implement:

- CLI flag `--refresh-databricks-catalog`
- early-return execution path in `main()` before normal analysis
- fetch/parse/write orchestration in `databricks_catalog.py`
- atomic JSON write preserving the existing catalog on failure

Do not couple refresh to ordinary analysis.

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q tests/test_databricks_refresh.py tests/test_cli_args.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/cli.py src/spotvm/databricks_catalog.py tests/test_databricks_refresh.py README.md
git commit -m "feat: add explicit databricks catalog refresh mode"
```

### Task 4: Add Databricks Cost Fields To The Candidate Model

**Files:**
- Modify: `src/spotvm/models.py`
- Create: `src/spotvm/databricks_costs.py`
- Create: `tests/test_databricks_costs.py`
- Inspect: `src/spotvm/analysis.py`

**Step 1: Write the failing test**

Add tests that enrich a candidate with Databricks pricing:

```python
from spotvm.databricks_costs import apply_databricks_costs
from spotvm.models import CandidateInsight

def test_apply_databricks_costs_sets_total_price_and_preserves_compute_price():
    candidate = CandidateInsight(region="centralus", vm_size="Standard_D4ps_v6", placement_score=None, quota_available=None, price_usd=0.03, price_last_updated=None, eviction_rate=5.0, eviction_last_updated=None)
    enriched = apply_databricks_costs([candidate], catalog=..., include_photon=False)
    assert enriched[0].compute_price_usd == 0.03
    assert enriched[0].databricks_dbu_per_hour == 1.17
    assert enriched[0].price_usd > 0.03
```

Also test:

- missing SKU leaves VM-only price intact and adds a note
- Photon path adds surcharge only when enabled
- `price_per_performance` inputs can later use the effective `price_usd`

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q tests/test_databricks_costs.py
```

Expected: FAIL because the new fields and enrichment module do not exist.

**Step 3: Write minimal implementation**

Extend `CandidateInsight` with optional fields:

- `compute_price_usd`
- `databricks_dbu_per_hour`
- `databricks_dbu_cost_usd`
- `databricks_photon_dbu_per_hour`
- `databricks_photon_cost_usd`
- `databricks_total_price_usd`
- `databricks_catalog_updated`

Implement a focused enrichment helper that:

- copies the original VM price into `compute_price_usd`
- calculates DBU and Photon dollar values from the catalog metadata
- updates `candidate.price_usd` to the effective total used later by ranking and filtering
- leaves unknown SKUs untouched except for a note

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q tests/test_databricks_costs.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/models.py src/spotvm/databricks_costs.py tests/test_databricks_costs.py
git commit -m "feat: add databricks pricing enrichment model"
```

### Task 5: Wire Databricks Pricing Into The Analysis Pipeline

**Files:**
- Modify: `src/spotvm/config.py`
- Modify: `src/spotvm/cli.py`
- Modify: `src/spotvm/analysis.py`
- Modify: `tests/test_analysis.py`
- Modify: `tests/test_cli_args.py`

**Step 1: Write the failing test**

Add tests proving the pipeline semantics:

- `--include-databricks-cost` changes the effective candidate price used in ranking
- `--max-price` applies to total price in Databricks mode
- `price_per_performance` is based on effective price in Databricks mode
- `--include-photon-cost` requires Databricks mode

Example:

```python
def test_rank_candidates_uses_total_price_when_databricks_mode_enabled():
    ...
    assert ranked[0].vm_size == "Standard_E2ps_v6"
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q tests/test_analysis.py tests/test_cli_args.py
```

Expected: FAIL because config fields and pipeline hook do not exist.

**Step 3: Write minimal implementation**

Implement:

- new `ToolConfig` booleans:
  - `include_databricks_cost`
  - `include_photon_cost`
- CLI parsing and merged config validation
- pipeline hook after `merge_datasets()` and before ranking/performance filtering
- validation error for Photon without Databricks cost

Keep the ordinary path unchanged when the flags are absent.

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q tests/test_analysis.py tests/test_cli_args.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/config.py src/spotvm/cli.py src/spotvm/analysis.py tests/test_analysis.py tests/test_cli_args.py
git commit -m "feat: wire databricks pricing into ranking and filters"
```

### Task 6: Expose Databricks Fields In Table, CSV, JSON, And Saved Runs

**Files:**
- Modify: `src/spotvm/reporting.py`
- Modify: `src/spotvm/projection.py`
- Modify: `src/spotvm/history.py`
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_output_contracts.py`
- Modify: `tests/test_history.py`

**Step 1: Write the failing test**

Add tests for each output mode:

- table adds Databricks columns only when Databricks mode is enabled
- CSV appends the new columns in stable order
- report JSON emits the optional keys when enabled
- saved run snapshots and generated history CSV include the optional fields when present

Verify that the default mode still emits the original stable schemas.

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q tests/test_reporting.py tests/test_output_contracts.py tests/test_history.py
```

Expected: FAIL because the extra columns/keys are not projected yet.

**Step 3: Write minimal implementation**

Implement:

- optional column groups in `reporting.py`
- optional projection keys in `projection.py`
- snapshot persistence in `history.py`
- conditional history CSV widening when Databricks pricing fields exist

Rules:

- keep `Price (USD/hr)` as the effective ranked price
- expose raw VM price and DBU/Photon fields separately
- do not change default schemas when the feature is off

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q tests/test_reporting.py tests/test_output_contracts.py tests/test_history.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/spotvm/reporting.py src/spotvm/projection.py src/spotvm/history.py tests/test_reporting.py tests/test_output_contracts.py tests/test_history.py
git commit -m "feat: expose databricks pricing across outputs"
```

### Task 7: Document The New Workflow And Seed Catalog Maintenance Rules

**Files:**
- Modify: `README.md`
- Modify: `config.sample.yaml`
- Modify: `src/spotvm/data/databricks_pricing.json`
- Inspect: `docs/plans/2026-03-19-databricks-pricing-catalog-design.md`

**Step 1: Write the failing doc checks**

Add documentation expectations in a lightweight way:

- README examples for base mode, Databricks mode, Photon mode, and refresh mode
- config sample comments for Databricks flags if config-file support is added
- clear statement that live pricing fetch is refresh-only

If the repo has no doc tests, capture the expected examples directly in review notes and verify manually.

**Step 2: Run verification to confirm gaps**

Run:

```bash
uv run spotvm --help
rg -n "databricks|photon|refresh-databricks" README.md config.sample.yaml
```

Expected: current docs/help do not mention the new flow.

**Step 3: Write minimal implementation**

Update docs with:

- what the local catalog is
- when to refresh it
- that normal analysis is offline with respect to Databricks pricing
- sample commands:

```bash
uv run spotvm --regions centralus --sizes Standard_D4ps_v6 --include-databricks-cost
uv run spotvm --regions centralus --sizes Standard_D4ps_v6 --include-databricks-cost --include-photon-cost
uv run spotvm --refresh-databricks-catalog
```

**Step 4: Run verification**

Run:

```bash
uv run spotvm --help
uv run pytest -q tests/test_cli_args.py tests/test_output_contracts.py tests/test_databricks_catalog.py tests/test_databricks_refresh.py tests/test_databricks_costs.py tests/test_analysis.py tests/test_reporting.py tests/test_history.py
```

Expected: PASS, and help/docs mention the new options.

**Step 5: Commit**

```bash
git add README.md config.sample.yaml src/spotvm/data/databricks_pricing.json
git commit -m "docs: describe databricks pricing catalog workflow"
```

### Task 8: Full Verification And Handoff Notes

**Files:**
- Inspect: `src/spotvm/`
- Inspect: `tests/`
- Inspect: `README.md`

**Step 1: Run focused verification**

Run:

```bash
uv run pytest -q tests/test_databricks_catalog.py tests/test_databricks_refresh.py tests/test_databricks_costs.py tests/test_analysis.py tests/test_reporting.py tests/test_history.py tests/test_output_contracts.py tests/test_cli_args.py
```

Expected: PASS

**Step 2: Run broader verification**

Run:

```bash
uv run pytest -q
uv run mypy src
uv run ruff check src tests
uv run spotvm --help
```

Expected: PASS

**Step 3: Manual smoke checks**

Run:

```bash
uv run spotvm --regions centralus --sizes Standard_D4ps_v6 --include-databricks-cost --no-color
uv run spotvm --regions centralus --sizes Standard_D4ps_v6 --include-databricks-cost --include-photon-cost --no-color
uv run spotvm --refresh-databricks-catalog
```

Expected:

- first run shows DBU columns and effective total price
- second run adds Photon columns and higher total price
- refresh rewrites the vendored catalog deterministically and exits cleanly

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: finish databricks pricing catalog support"
```

## Implementation Notes For The Next Agent

- Do not build a display-only version. When Databricks cost mode is on, ranking and `--max-price` must use total price.
- Do not make refresh implicit. The default analysis path must remain offline for Databricks pricing.
- Preserve existing default CSV/JSON/table contracts when the new flags are not set.
- Keep Photon fully separate from base Databricks DBU cost.
- Write the catalog file in stable sorted order so git diffs stay reviewable.
