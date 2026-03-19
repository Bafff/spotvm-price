# Databricks Pricing Catalog Design

## Goal

Расширить `spotvm`, чтобы он умел по отдельному ключу учитывать Azure Databricks DBU cost для поддерживаемых SKU, опционально добавлять Photon surcharge, показывать эти значения в финальной таблице и хранить локальный версионируемый snapshot DBU metadata в repo без live-запросов по умолчанию.

## Accepted Constraints

- По умолчанию `spotvm` не делает live-запросы к Databricks pricing source.
- Источник истины для DBU metadata хранится в версионируемом файле внутри repo.
- Обновление каталога выполняется только отдельной командой `refresh`.
- Photon включается отдельным ключом и не должен неявно активироваться вместе с базовым Databricks cost.
- Текущий Azure Spot VM analysis path должен продолжать работать без изменений, если новые ключи не заданы.

## Recommended Approach

Использовать локальный каталожный snapshot `databricks_pricing.json`, загружаемый из package data, и отдельный refresh path, который по требованию обновляет этот snapshot из официального источника и записывает его обратно в repo в детерминированном виде.

Это лучше, чем live lookup в обычном анализе, потому что:

- вывод остаётся воспроизводимым;
- CSV/JSON/table не зависят от временной доступности внешнего pricing endpoint;
- изменения DBU catalog можно ревьюить как обычный diff;
- CI и локальные прогоны не требуют Databricks/API доступа, если нужен только existing analysis.

## Scope

### In Scope

- Azure Databricks pricing overlay для существующих Azure VM candidate rows.
- Локальный каталог с:
  - `dbu_per_hour` на SKU
  - `photon_dbu_per_hour` на SKU
  - unit pricing metadata для расчёта dollar cost
  - source metadata и timestamp snapshot
- Отдельные CLI flags для:
  - включения базового Databricks cost
  - включения Photon cost
  - ручного refresh каталога
- Вывод DBU/Photon полей в human table, CSV, report JSON и saved history snapshots.
- Ранжирование, `--max-price` и `Price/Perf` по итоговой стоимости, когда Databricks cost mode включён.

### Out of Scope

- Автоматический background refresh.
- Перечень pricing profiles для всех возможных Databricks tiers и compute modes.
- Workspace-specific Databricks API discovery.
- Пересчёт historical runs задним числом по новому каталогу.

## Pricing Model

### Base Candidate Price Semantics

Сейчас `CandidateInsight.price_usd` означает Azure VM hourly price и участвует в:

- ranking
- `--max-price`
- `price_per_performance`
- summary lines
- JSON/CSV/table output

Если просто добавить DBU columns и не поменять `price_usd`, ранжирование останется по VM-only стоимости и станет вводить в заблуждение. Поэтому в Databricks mode нужен явный раздел:

- `compute_price_usd`: исходная Azure VM hourly price
- `databricks_dbu_per_hour`
- `databricks_dbu_cost_usd`
- `databricks_photon_dbu_per_hour`
- `databricks_photon_cost_usd`
- `total_price_usd`

А `CandidateInsight.price_usd` в Databricks mode должен использоваться как effective price for ranking and display, то есть содержать `total_price_usd`. Это позволяет не переписывать все существующие cost-based code paths по отдельности.

### Cost Formula

When `--include-databricks-cost` is enabled:

- `compute_price_usd = existing spot VM price`
- `dbu_cost_usd = dbu_per_hour * jobs_dbu_unit_price_usd`
- `effective price_usd = compute_price_usd + dbu_cost_usd`

When `--include-photon-cost` is also enabled:

- `photon_cost_usd = photon_dbu_per_hour * photon_dbu_unit_price_usd`
- `effective price_usd = compute_price_usd + dbu_cost_usd + photon_cost_usd`

`price_per_performance` must be recalculated from the effective `price_usd`.

## Catalog Shape

Recommended package data file:

`src/spotvm/data/databricks_pricing.json`

Recommended top-level shape:

```json
{
  "catalog_version": 1,
  "cloud": "azure",
  "pricing_profile": {
    "name": "standard_jobs",
    "dbu_unit_price_usd": 0.15,
    "photon_dbu_unit_price_usd": 0.0
  },
  "captured_at": "2026-03-19T00:00:00Z",
  "source": {
    "type": "official_pricing_snapshot",
    "url": "https://azure.microsoft.com/en-us/pricing/details/databricks/"
  },
  "entries": [
    {
      "sku": "Standard_D4ps_v6",
      "dbu_per_hour": 1.17,
      "photon_dbu_per_hour": 1.17,
      "notes": ""
    }
  ]
}
```

Design choices:

- one canonical file, not per-region
- SKU keys use exact Azure VM size names
- stable sorted ordering by SKU for readable diffs
- explicit snapshot metadata for traceability

## CLI Design

Recommended new flags:

- `--include-databricks-cost`
- `--include-photon-cost`
- `--refresh-databricks-catalog`

Behavior:

- `--include-databricks-cost`:
  - load local catalog
  - enrich matching candidates
  - change effective ranking/filter/display cost to total price
- `--include-photon-cost`:
  - requires `--include-databricks-cost`
  - adds Photon surcharge on top of DBU cost
- `--refresh-databricks-catalog`:
  - runs refresh flow only
  - writes updated `databricks_pricing.json`
  - exits without regular VM analysis

No extra config-file surface is required in the first version beyond booleans for include flags if desired. The refresh path should remain explicit from CLI.

## Refresh Workflow

Recommended refresh sequence:

1. Fetch the current official Databricks pricing source.
2. Parse supported SKU rows into normalized records.
3. Validate all numeric fields and duplicate SKUs.
4. Merge with any existing catalog notes only if needed.
5. Write a deterministic JSON snapshot.
6. Print a concise summary:
   - number of SKUs loaded
   - pricing profile values
   - changed/new/removed SKU counts

Important behavior:

- refresh is the only live-query path
- standard analysis never mutates the catalog
- refresh failures must leave the existing catalog untouched

## Reporting Changes

### Human Table

Current `Price (USD/hr)` column should continue to exist, but in Databricks mode it should show the effective total price used for ranking.

Add optional Databricks columns when feature is enabled:

- `VM (USD/hr)`
- `DBU/h`
- `DB Cost`
- `Photon DBU/h`
- `Photon Cost`
- `Catalog Updated`

Photon columns should appear only when `--include-photon-cost` is active.

### CSV

Append optional columns at the end of the existing CSV schema when Databricks mode is enabled:

- `VM Price (USD/hr)`
- `DBU per Hour`
- `Databricks Cost (USD/hr)`
- `Photon DBU per Hour`
- `Photon Cost (USD/hr)`
- `Total Cost (USD/hr)`
- `Databricks Catalog Updated`

Do not change the default CSV header set when Databricks mode is off.

### JSON Report

Add optional keys when Databricks mode is enabled:

- `computePriceUSDPerHour`
- `databricksDBUPerHour`
- `databricksCostUSDPerHour`
- `photonDBUPerHour`
- `photonCostUSDPerHour`
- `totalPriceUSDPerHour`
- `databricksCatalogUpdated`

### Saved Run History

Persist the same optional pricing fields in snapshots so later history analysis can include them if present. History CSV generation should append stable optional columns when any snapshot contains Databricks pricing fields.

## Error Handling

- If `--include-photon-cost` is passed without `--include-databricks-cost`, fail in CLI validation.
- If Databricks mode is enabled and a SKU is missing from the local catalog:
  - keep the candidate
  - preserve VM-only price
  - add a note like `Databricks DBU metadata unavailable for this SKU`
  - do not fabricate DBU values
- If catalog file is missing/corrupt:
  - fail fast with a clear remediation message telling the user to run refresh or restore the vendored file
- If refresh fetch/parse/write fails:
  - non-zero exit
  - keep previous catalog intact

## Testing Strategy

Coverage should be split into four areas:

- catalog loading and refresh parsing
- CLI validation and mode switching
- cost enrichment and ranking semantics
- output contracts for table/CSV/report/history

Key regression to prevent:

- feature silently showing DBU columns but still sorting/filtering by VM-only price

## Files Expected To Change

- `src/spotvm/cli.py`
- `src/spotvm/config.py`
- `src/spotvm/models.py`
- `src/spotvm/analysis.py`
- `src/spotvm/projection.py`
- `src/spotvm/reporting.py`
- `src/spotvm/history.py`
- `pyproject.toml`
- `README.md`
- `config.sample.yaml`
- `src/spotvm/data/databricks_pricing.json`
- new module for catalog/refresh logic
- tests for new CLI, catalog, output contracts, and cost behavior

## Chosen Implementation Direction

Implement a vendored Databricks pricing catalog plus explicit refresh command, treat Databricks cost as an opt-in pricing overlay that updates the effective candidate price used by ranking and filters, and expose raw DBU/Photon fields in optional output columns only when the feature is active.
