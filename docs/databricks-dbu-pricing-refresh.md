# Databricks DBU Pricing Refresh

This project currently vendors Azure node-type DBU pricing from a manual Chrome DevTools extraction.

The supported refresh workflow is manual on purpose. `spotvm` does not attempt to refresh this data automatically.

## Source

Databricks UI compute creation pages expose a browser config map:

```js
window.settings["defaultNodeTypeToPricingUnitsMap"]
```

This is the source used to build the vendored Azure CSV.

## Refresh Steps

1. Open any Databricks workspace in Chrome.
2. Open DevTools.
3. In the Console, run:

```js
JSON.stringify(window.settings["defaultNodeTypeToPricingUnitsMap"])
```

4. Save the extracted map.
5. Filter to Azure node types and convert the result into the CSV shape used here:

```csv
node_type_id,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated
```

6. Replace:

`src/spotvm/data/databricks_azure_dbu_pricing.csv`

7. Review the diff manually and commit it if the update is correct.

## Multipliers

The UI also exposes performance multipliers:

- `window.settings["defaultPerformanceMultipliersForDbr"]`
- `window.settings["defaultPerformanceMultipliersForPhoton"]`

Notes captured from the browser session:

- Standard: `1x`
- Photon All-Purpose: `2x`
- Photon Jobs: `2.5x`

These multipliers explain UI totals, but the vendored CSV stores only the base per-node `dbu_per_hour` values.
When `spotvm` shows Photon output, it treats the Photon number as the full Photon
DBU rate for the node type, not as a separate additive surcharge field.

## Reuse In Code

The repo exposes helper functions in `spotvm.databricks_catalog`:

- `load_azure_dbu_pricing_rows()`
- `lookup_azure_node_type_pricing(node_type_id)`

Example:

```python
from spotvm.databricks_catalog import lookup_azure_node_type_pricing

row = lookup_azure_node_type_pricing("Standard_D4ds_v5")
assert row is not None
print(row.dbu_per_hour)  # 1.0
```
