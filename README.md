# Azure Spot VM Analysis Tool

This project delivers a Python CLI that correlates Azure Spot Placement Score data with the Spot price and eviction history published via Azure Resource Graph. It provides a consolidated, ranked report for a set of VM SKUs and regions so you can quickly identify combinations that balance availability, stability, and cost for Spot VM workloads.

## Prerequisites
- Python 3.10 or later.
- Azure credentials capable of acquiring an access token via `DefaultAzureCredential` (Azure CLI login, managed identity, or service principal).
- Read access to Azure Resource Graph (granted by default for most accounts) to query the `SpotResources` table.[^spotresources]
- *(Only for `--placement-check`)*: An Azure subscription ID and the **Compute Recommendations** role on the target subscription.[^placement-score]

[^placement-score]: Azure documentation: *Spot Placement Score* (REST) – https://learn.microsoft.com/azure/virtual-machine-scale-sets/spot-placement-score?tabs=rest-api
[^spotresources]: Azure documentation: *Use Azure Spot Virtual Machines* – https://learn.microsoft.com/azure/virtual-machines/spot-vms

## Installation

### Preferred: `uv`
For local development, the preferred workflow is `uv`.

```bash
uv tool install --editable .
# Re-run after changing pyproject metadata or dependencies:
uv tool install --editable --force .
```

This installs `spotvm` as a global CLI while keeping it linked to the current checkout, so Python code changes under `src/spotvm/` are picked up without reinstalling.

For a project-local development environment and tests:
```bash
uv sync --extra dev
uv run spotvm --help
```

Unless otherwise noted, the command examples below assume this repo-local workflow from the project root:

```bash
uv run spotvm ...
```

If you installed the CLI globally with `uv tool install --editable .`, you can omit the `uv run` prefix.

### One-command execution options
- **uv from GitHub:** `uvx --from git+https://github.com/Bafff/spotvm-price.git spotvm -- --help`
- **pipx from local checkout:** `pipx run --spec ./ spotvm -- --help`
- **pipx from GitHub:** `pipx run git+https://github.com/Bafff/spotvm-price.git -- --help`

All three commands read `pyproject.toml`, create an isolated environment, install dependencies, and directly execute the CLI without permanently installing the package.

### Breaking Rename Note
- The package name, import path, and CLI entry point are now `spotvm`.
- Legacy CLI and import names are intentionally unsupported in this branch.
- Existing cache data under the previous cache directory in `~/.cache` is not migrated automatically. It is safe to delete manually if you no longer need it.

### Complete `uv` example
If you keep your subscription ID in `.env` (for example `AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000000`), load it and execute:

```bash
uv sync --extra dev
set -a
source .env
set +a
uv run spotvm \
  --clear-cache \
  --subscription-id "$AZURE_SUBSCRIPTION_ID" \
  --placement-check \
  --regions centralus \
  --sizes Standard_D2as_v6 \
  --desired-count 10 \
  --json
```

Alternatively, pass the subscription inline:

```bash
uv run spotvm \
  --clear-cache \
  --subscription-id 00000000-0000-0000-0000-000000000000 \
  --placement-check \
  --regions centralus \
  --sizes Standard_D2as_v6 \
  --desired-count 10 \
  --json
```

`--clear-cache` ensures the run fetches fresh placement/Resource Graph data. If you prefer not to create a project-local environment, use the `uvx` or `pipx` one-command options above instead.

### `pip` / `pipx` fallback
If you do not want to use `uv`, the project still works with standard Python packaging tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .  # installs the CLI entry point `spotvm`
# For development or running tests:
pip install -e .[dev]
```

## Configuration
You can supply parameters directly via CLI arguments or load them from a JSON/YAML file. The sample below mirrors `config.sample.yaml` in the repository:

```yaml
# Required
regions:
  - centralus
  - eastus
sizes:
  - Standard_D4s_v5
  - Standard_E4s_v5
os_type: linux                    # linux or windows

# Optional: placement scoring (requires subscription_id)
# enable_placement: true
# subscription_id: "00000000-0000-0000-0000-000000000000"
# desired_count: 10            # only valid when enable_placement is true
# availability_zones: false    # only valid when enable_placement is true

# Optional: performance baseline
# baseline_sku: Standard_D4as_v6

# Optional: filtering (config-supported)
# cpu_arch: x64                   # x64 or arm

# Note: max_price, max_eviction, min_performance are CLI-only flags
# and cannot be set in the config file. Use them on the command line:
#   --max-price 0.10 --max-eviction 15 --min-performance 80

# Optional: output
cache_ttl_minutes: 15
# result_limit: 10
# emit_json: false
```

### Key fields
- `subscription_id`: **Azure subscription ID to query.** This determines:
  - **Authorization**: You need access to this subscription (with "Compute Recommendations" role for placement scores)
  - **Quota availability**: Shows vCPU quotas **for this specific subscription** (different subscriptions have different quotas)
  - **API endpoint**: Required in Placement Score API URL

  **Note:** Prices and eviction rates are the same for all subscriptions, but **quota availability is subscription-specific**.

  **Example:**
  ```bash
  # Subscription A has 100 vCPU quota in eastus (80 used, 20 free)
  uv run spotvm --subscription-id AAAA... --placement-check --regions eastus --sizes Standard_D4as_v5
  # Result: Quota = ✅ Yes (4 vCPU needed, 20 available)

  # Subscription B has 10 vCPU quota in eastus (9 used, 1 free)
  uv run spotvm --subscription-id BBBB... --placement-check --regions eastus --sizes Standard_D4as_v5
  # Result: Quota = ❌ No (4 vCPU needed, only 1 available)
  ```

- `regions`: Up to eight regions per request (the tool batches automatically if more are provided).
- `sizes`: Up to five SKUs per request (batched automatically as needed).
- `desired_count`: Placement-only field. Set it only when `enable_placement: true` (or `--placement-check`) is enabled; placement score sensitivity increases with larger counts.
- `os_type`: `linux` (default) or `windows` to align price history with OS-specific retail rates.
- `availability_zones`: Placement-only field. Set `true` only when `enable_placement: true` (or `--placement-check`) is enabled; otherwise the tool queries region scope.

  **Important:** When using `--availability-zones`:
  - **Placement Score** and **Quota Available** differ per zone (capacity and quotas vary)
  - **Price** and **Eviction Rate** are the **same** for all zones in a region (Azure sets prices at region level)
- `baseline_sku`: Optional VM SKU to use as 100% performance baseline for relative comparison (e.g., `Standard_D4as_v6`). When set, enables `Perf %` and `Price/Perf` columns and optimizes recommendations for value.
- `cache_ttl_minutes`: Reuses identical placement/Resource Graph responses for the specified TTL to respect Azure guidance of avoiding duplicate calls within 15 minutes.[^placement-score]
- `result_limit`: Optional maximum number of rows in the final ranked report.
- `emit_json`: When `true`, writes machine-readable JSON to `stdout` and suppresses the human-readable console table, recommendations, and explanatory text.
- `enable_placement`: Set to `true` (or pass `--placement-check`) to query the Spot Placement Score API for capacity and quota data. Requires `subscription_id`. Defaults to `false`. When this is `false`, omit `desired_count` and `availability_zones`.

## Usage
### Direct arguments
```bash
# Pricing and eviction data (no subscription needed)
uv run spotvm \
  --regions eastus westus \
  --sizes Standard_D2s_v4 Standard_D4s_v4

# With placement scoring (requires subscription)
uv run spotvm \
  --subscription-id 00000000-0000-0000-0000-000000000000 \
  --regions eastus westus \
  --sizes Standard_D2s_v4 Standard_D4s_v4 \
  --placement-check --desired-count 20
```

### With a configuration file
```bash
uv run spotvm --config config.sample.yaml --save-report reports/latest.json
```

`--save-report` creates the parent directory automatically if it does not already exist.

### Machine-readable JSON
```bash
uv run spotvm \
  --regions eastus westus \
  --sizes Standard_D2s_v4 Standard_D4s_v4 \
  --json | jq .
```

### Databricks pricing catalog
The CLI now reserves three Databricks-related flags:

```bash
uv run spotvm \
  --regions centralus \
  --sizes Standard_D4ps_v6 \
  --include-databricks-cost
```

- `--include-databricks-cost` enables optional Databricks cost fields in JSON/CSV/table output. Databricks-specific columns appear in this mode, and unmatched SKUs keep empty Databricks cells plus an explanatory note.
- `--include-photon-cost` requires `--include-databricks-cost`.
- `--refresh-databricks-catalog` prints the manual refresh procedure and exits. It does not fetch or rewrite pricing data automatically.

### Vendored Azure DBU pricing data

The repo now vendors a saved Azure node-type DBU dataset at:

`src/spotvm/data/databricks_azure_dbu_pricing.csv`

The manual refresh procedure is documented in:

`docs/databricks-dbu-pricing-refresh.md`

Code can reuse this data through `spotvm.databricks_catalog`:

```python
from spotvm.databricks_catalog import lookup_azure_node_type_pricing

row = lookup_azure_node_type_pricing("Standard_D4ds_v5")
if row is not None:
    print(row.dbu_per_hour)
```

### Export to CSV for Excel/Google Sheets
```bash
uv run spotvm \
  --regions eastus westus centralus \
  --sizes Standard_D2s_v4 Standard_D4s_v4 Standard_E4s_v5 \
  --baseline-sku Standard_D4s_v4 \
  --csv results/spot-analysis.csv
```

The `--csv` option exports results to a spreadsheet-compatible CSV file with:
- Clean format without emojis for Excel compatibility
- Numeric values without symbols ($, %) for proper sorting and charts
- ISO datetime format
- Mode-dependent columns:
  - Always included: Rank, Region, Availability Zone, VM Size, CPU Vendor, Price, Eviction Rate, CoreMark Score, CoreMark per vCPU, Price Last Updated, and Notes
  - Included with `--placement-check`: Placement Score and Quota Available
  - Included with `--baseline-sku`: Performance and Price per Performance

**CSV Example (with placement and baseline enabled):**
```csv
Rank,Region,Availability Zone,VM Size,CPU Vendor,Placement Score,Quota Available,Price (USD/hr),Eviction Rate (%),Performance (%),Price per Performance,CoreMark Score,CoreMark per vCPU,Price Last Updated,Notes
1,eastus,,Standard_D4as_v5,AMD,High,Yes,0.0336,3.0,100,0.000336,72928,18232,2025-01-26,
2,westus,2,Standard_E4s_v5,INTEL,Medium,No,0.0696,5.0,117,0.000597,65672,16418,2025-01-26,
```

The CLI prints an aligned ASCII table with the placement score, quota availability, latest spot price, and eviction rate for each combination. After sorting (High > Medium > Low, then by lowest eviction rate and price), it emits a short recommendation list and an optional JSON payload when requested.

### Example snippet
```
Rank | Region | Zone | VM Size          | CPU | Placement | Quota | Price (USD/hr) | Eviction % | Perf % | Price/Perf | CoreMark | CM/vCPU | Price Updated | Notes
---- | ------ | ---- | ---------------- | --- | --------- | ----- | -------------- | ---------- | ------ | ---------- | -------- | ------- | ------------- | -----
1    | eastus |      | Standard_D4as_v5 | 🟥  | High      | ✅ Yes| $0.0336        | 3.0%       | 100%   | $0.000336  | 72,928   | 18,232  | 2025-01-26    |
2    | westus | 2    | Standard_E4s_v5  | 🟦  | Medium    | ❌ No | $0.0696        | 5.0%       | 117%   | $0.000597  | 65,672   | 16,418  | 2025-01-26    |
3    | eastus | 1    | Standard_D4ps_v5 | 🟩  | Low       | ✅ Yes| $0.0280        | 1.5%       | 95%    | $0.000295  | -        | -       | 2025-01-26    |
```

**CPU Vendor Legend:**
- 🟦 = Intel Xeon
- 🟥 = AMD EPYC
- 🟩 = ARM (Ampere/Cobalt)

*(When using `--no-color`: displays as "INTEL", "AMD", "ARM")*
*(Perf %, Price/Perf, CoreMark, and CM/vCPU columns shown when `--baseline-sku` is specified)*

## Output artifacts
- **Console table** – emitted for human-readable runs with color-coded risk indicators. It is suppressed when `--json` is enabled.
- **Recommendations** – human-readable summary of the top three entries.
- **JSON report** – optional structured output (includes timestamps, metrics, performance basis, and notes) controllable via `--json` and `--save-report`.
- **CSV export** – optional spreadsheet-compatible export for Excel/Google Sheets via `--csv <file>`.

### Color-Coded Output

The terminal output uses colors to highlight eviction risk levels and placement scores for quick visual assessment:

**Eviction Rate Colors:**
- 🔵 **Blue** (<5%): Excellent - very low eviction risk
- 🟢 **Green** (5% to <10%): Good - low eviction risk
- 🟡 **Yellow** (10% to <15%): Medium - moderate eviction risk
- 🔴 **Red** (15% to <25%): High - high eviction risk
- 🔴 **Bright Red** (≥25%): Critical - very high eviction risk

**Placement Score Colors:**
- 🟢 **Green** (High): Good capacity availability
- 🟡 **Yellow** (Medium): Moderate capacity availability
- 🔴 **Red** (Low): Limited capacity availability

**Disable colors** for CI/CD or non-TTY environments:
```bash
uv run spotvm --no-color --regions eastus --sizes Standard_D4as_v5
```

Colors are automatically disabled when output is redirected to a file or pipe.

## Recommendation Logic

The tool ranks VM candidates using a three-tier priority system:

### Ranking Formula
```
Priority 1: Placement Score (High > Medium > Low)
Priority 2: Eviction Rate (lower is better)
Priority 3: Price/Performance ratio (lower is better value)
```

### How it works:
1. **Placement Score** (when `--placement-check` is enabled)
   - `High` (best) - Azure has strong capacity signals
   - `Medium` - Moderate availability
   - `Low` - Limited availability
   - `N/A` - No placement data (default, without `--placement-check`)

2. **Eviction Rate** - Historical eviction percentage
   - `5%` means 5% chance of eviction in the next hour
   - Lower rates indicate more stable workloads
   - Based on last 7 days of eviction history

3. **Price/Performance** - Cost per performance unit
   - When `--baseline-sku` is specified, sorts by price per performance unit
   - Without baseline, sorts by raw price
   - Optimizes for best value (bang for buck) rather than just cheapest option

### Performance Comparison

Add `--baseline-sku` to compare relative performance:

```bash
uv run spotvm \
  --baseline-sku Standard_D4as_v6 \
  --regions eastus centralus \
  --sizes Standard_D2as_v6 Standard_D4as_v5 Standard_E4s_v5
```

**Output includes:**
- `Perf %` - Performance relative to baseline (100% = baseline)
- `Price/Perf` - Price per 1% of baseline performance
- `CoreMark` - Absolute CoreMark benchmark score (CPU performance metric)
- `CM/vCPU` - CoreMark per vCPU (CPU efficiency metric, higher = more efficient)
- `Notes` - Uses a short `Heuristic perf*` marker when performance falls back to the non-CoreMark estimate; the footer expands the reason once.

**Performance calculation:**
- If both the candidate SKU and baseline SKU have published CoreMark data, `Perf %` uses the CoreMark ratio.
- Otherwise the tool falls back to the resource heuristic `Compute Score = (vCPUs × 100) + (RAM_GB × 5)`.
- When the fallback is used, the `Notes` column shows `Heuristic perf*` and the footer expands the warning once so the table stays compact.

*Source: [Azure VM Sizes Documentation](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes)*

**Example results:**
```
Rank | VM Size          | Price   | Eviction | Perf % | Price/Perf
-----|------------------|---------|----------|--------|------------
1    | Standard_D4as_v5 | $0.0336 | 5.0%     | 100%   | $0.000336
2    | Standard_E4s_v5  | $0.0696 | 5.0%     | 117%   | $0.000597
3    | Standard_D2as_v6 | $0.0168 | 20.0%    | 50%    | $0.000336
```

**Interpretation:**
- **D4as_v5**: Best recommendation - low eviction (5%) + best price/performance value
- **E4s_v5**: More RAM (+17% perf) but worse value due to higher price
- **D2as_v6**: Cheapest, same price/performance, but high eviction risk (20%)

**Notes:**
- The fallback heuristic weights CPU more heavily (100×) than RAM (5×).
- Heuristic comparisons are coarse; real performance still depends on workload type, CPU generation, cache behavior, I/O, and throttling.
- **Official Azure performance metrics status:**
  - **ACU (Azure Compute Units)**: Not published for v5/v6+ series. Microsoft is "reevaluating how they calculate Azure Compute Units weights for Virtual machine performance benchmarks to account for updates in processor architecture." Only v4 and older have ACU values.
  - **CoreMark benchmarks**: **Available for v5 series** (D/E/F) with full data in this tool. **Not available for v6+ series** - Microsoft [no longer publishes](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/compute-benchmark-scores) CoreMark for newest generations, stating: "Azure is no longer publishing CoreMark since the metric has limited ability to inform users of the expected performance."
  - **v6 series (Standard_D4as_v6, etc.)**: ❌ No CoreMark data available - columns will show `-`
  - **v5 series (Standard_D4as_v5, etc.)**: ✅ Full CoreMark data available
  - Microsoft recommends: *"Run your actual workload on target VMs for accurate performance assessment"*
- The vCPU + RAM formula is a fallback for SKUs without comparable CoreMark data, not a substitute for workload testing
- Choose a baseline similar to your typical workload for most accurate relative comparison

## Filtering and Auto-Discovery

### Requirements-Based Filtering

Filter VMs by hardware requirements instead of manually specifying SKUs:

```bash
# Auto-discover right-sized VMs near your requested shape
uv run spotvm \
  --regions centralus eastus \
  --min-vcpu 4 \
  --min-ram 32 \
  --max-price 0.10 \
  --limit 5
```

**What happens:**
1. Tool scans all known SKUs in specifications database
2. Builds bounded windows from the next three distinct hardware tiers in the bundled specs database
3. Keeps only SKUs that satisfy both windows
4. Queries Azure for those SKUs only
5. Applies cost filtering
6. Returns top 5 results

**Default bounded behavior:**
- `--min-vcpu 4` means the next known vCPU tiers `4`, `8`, and `16`
- `--min-vcpu 6` means the next known vCPU tiers `8`, `16`, and `32`
- RAM windows follow the same rule using distinct known RAM sizes from the specs database
- When both are set, the tool uses the intersection of both windows
- Unknown SKUs are excluded in bounded mode because their hardware cannot be verified

**Disable the bound:**

```bash
# Restore open-ended minimum filtering
uv run spotvm \
  --regions centralus eastus \
  --min-vcpu 4 \
  --min-ram 32 \
  --no-max-limit \
  --limit 5
```

**Output example:**
```
2025-10-25 19:30:00,000 INFO Auto-discovered 26 SKUs: Standard_D4as_v6, Standard_E4s_v5, ...
2025-10-25 19:30:05,000 INFO Filtered out 12 candidate(s) not meeting cost constraints

Rank | VM Size          | Region    | Price   | Eviction | vCPU | RAM
-----|------------------|-----------|---------|----------|------|------
1    | Standard_E4s_v5  | eastus    | $0.0696 | 5.0%     | 4    | 32 GB
2    | Standard_E8s_v5  | centralus | $0.0890 | 4.2%     | 8    | 64 GB
...
```

### Cost-Based Filtering

Apply maximum constraints on price, eviction rate, and performance:

```bash
# Find VMs cheaper than $0.10/hr with low eviction risk
uv run spotvm \
  --regions centralus eastus westus \
  --sizes Standard_D4as_v5 Standard_D4as_v6 Standard_E4s_v5 \
  --baseline-sku Standard_D4as_v6 \
  --max-price 0.10 \
  --max-eviction 10 \
  --min-performance 80
```

**Filters applied:**
- `--max-price 0.10` - Excludes VMs costing more than $0.10/hour
- `--max-eviction 10` - Excludes VMs with >10% eviction rate
- `--min-performance 80` - Excludes VMs with <80% of baseline performance

### Combined Filtering Example

Find the cheapest Spot VM for your workload:

```bash
uv run spotvm \
  --regions centralus eastus \
  --min-vcpu 8 \
  --min-ram 64 \
  --max-price 0.20 \
  --max-eviction 5 \
  --baseline-sku Standard_D8as_v6 \
  --min-performance 90 \
  --limit 3
```

Constraints in this example:
- at least `8` vCPUs
- at least `64` GB RAM
- max price `$0.20/hour`
- max eviction risk `5%`
- at least `90%` of baseline performance
- return the top `3` results

**Workflow:**
1. **Auto-discovery:** Finds SKUs in the next three distinct known CPU and RAM tiers above your minimums
2. **Azure query:** Fetches pricing and eviction data for discovered SKUs; placement scores are added only when `--placement-check` is enabled
3. **Hardware filter:** Re-validates vCPU/RAM against the same bounded windows
4. **Ranking:** Sorts by placement score → eviction → price/performance
5. **Performance calc:** Computes relative to Standard_D8as_v6
6. **Cost filter:** Removes VMs exceeding price/eviction/performance limits
7. **Results:** Shows top 3 candidates

### Filter Parameters Reference

**Hardware Requirements** (applied before ranking):
- `--min-vcpu <int>` - Minimum vCPUs required; defaults to the next three distinct known vCPU tiers
- `--min-ram <int>` - Minimum RAM in GB; defaults to the next three distinct known RAM tiers
- `--no-max-limit` - Disable bounded windows and restore open-ended minimum filtering

**Cost Constraints** (applied after ranking):
- `--max-price <float>` - Maximum price per hour (USD)
- `--max-eviction <float>` - Maximum eviction rate (percentage)
- `--min-performance <float>` - Minimum performance vs baseline (percentage, requires `--baseline-sku`)

**Notes:**
- Unknown SKUs are excluded in bounded mode and kept with warnings only when `--no-max-limit` is used
- Explicit `--sizes` keep the requested SKU list intact; bounded windows only guide auto-discovery
- Filters are optional - omit to see all candidates
- Combine multiple filters for precise requirements
- Verbose logging shows filtered count: `--verbose`

## Historical Price Trends

Track spot price and eviction rate changes over time by saving results from each run:

### Saving Results

Add `--save-results` to any normal run to save a timestamped snapshot:

```bash
uv run spotvm \
  --regions centralus eastus \
  --sizes Standard_D4as_v5 Standard_D2as_v6 \
  --baseline-sku Standard_D4as_v6 \
  --save-results
```

**Output:**
```
✅ Results saved to: results/runs/2025-01-25T14-30-00Z.json

Rank | Region    | VM Size          | Price   | Eviction % | Perf %
-----|-----------|------------------|---------|------------|-------
1    | centralus | Standard_D4as_v5 | $0.0336 | 2.5%       | 95%
...
```

Each run creates a JSON snapshot in `results/runs/` containing:
- Timestamp
- Configuration (regions, sizes, baseline)
- All candidate metrics (price, eviction, performance)

### Analyzing Historical Data

After accumulating multiple runs over days/weeks, generate a unified CSV for visualization:

```bash
uv run spotvm --analyze-history
```

**Output:**
```
Historical Analysis Complete:
  Runs analyzed: 42
  Data points: 168
  CSV output: results/history.csv

Use this CSV for visualization with tools like:
  - Excel/Google Sheets: Import results/history.csv
  - Python: pd.read_csv('results/history.csv')
  - Grafana: CSV data source plugin
```

**CSV Format:**
```csv
timestamp,vm_size,region,zone,price_usd,eviction_rate,placement_score,performance_relative
2025-01-25T14:30:00Z,Standard_D4as_v5,centralus,1,0.0336,2.5,High,95.2
2025-01-25T14:30:00Z,Standard_D2as_v6,eastus,2,0.0168,5.1,Medium,47.6
2025-01-26T09:15:00Z,Standard_D4as_v5,centralus,1,0.0342,3.2,High,95.2
```

### Advanced Options

**Limit analysis depth:**
```bash
# Analyze only last 7 runs
uv run spotvm --analyze-history --history-depth 7
```

**Custom output location:**
```bash
uv run spotvm --analyze-history --history-output /tmp/price_trends.csv
```

**Custom results directory:**
```bash
uv run spotvm --save-results --results-dir /data/spot-analysis
uv run spotvm --analyze-history --results-dir /data/spot-analysis
```

### Visualization Examples

**Python + matplotlib:**
```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('results/history.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Plot price trends for specific SKU (regional data only)
sku_regional = df[(df['vm_size'] == 'Standard_D4as_v5') & (df['zone'] == '')]
plt.plot(sku_regional['timestamp'], sku_regional['price_usd'])
plt.xlabel('Date')
plt.ylabel('Price (USD/hr)')
plt.title('Spot Price Trend: Standard_D4as_v5 (Regional)')
plt.show()
```

**Excel:**
1. Open Excel/Google Sheets
2. Import `results/history.csv`
3. Create pivot table with timestamp on X-axis
4. Plot price_usd for different vm_size values
5. Add trendlines to identify price patterns

### Use Cases

- **Budget Planning:** Identify optimal purchase windows when prices drop
- **Capacity Planning:** Correlate eviction rate spikes with your workload timing
- **SKU Comparison:** Track price/performance ratio evolution across different VMs
- **Regional Analysis:** Find which regions have most stable pricing
- **Automation:** Run hourly via cron with `--save-results`, analyze weekly trends

**Note:** The tool doesn't include built-in visualization (keeps dependencies minimal). Use the CSV output with your preferred analytics/charting tools.

### Unattended Monitoring Mode

For continuous data collection without setting up cron, use `--run-unattended`:

```bash
# Run every hour (default), saving data automatically
uv run spotvm \
  --regions centralus eastus \
  --min-vcpu 4 \
  --min-ram 16 \
  --max-price 0.10 \
  --run-unattended
```

**Output:**
```
🔄 Monitoring mode started (interval: 60 min)
📊 Results will be saved to: ./results/runs/
⏸️  Press Ctrl+C to stop

============================================================
Run #1 at 2025-10-25 19:00:00
============================================================
✅ Results saved to: results/runs/2025-10-25T19-00-00.123456Z.json

Rank | VM Size          | Region    | Price   | Eviction
-----|------------------|-----------|---------|----------
...

💤 Sleeping for 60 minutes...
   Next run at: 20:00:00

============================================================
Run #2 at 2025-10-25 20:00:00
============================================================
...
```

**Custom interval:**
```bash
# Run every 15 minutes
uv run spotvm \
  --regions centralus \
  --sizes Standard_D4as_v5 \
  --run-unattended 15
```

**Features:**
- **Automatic data saving**: Enables `--save-results` automatically
- **Graceful shutdown**: Press `Ctrl+C` to stop after current run completes
- **Error resilience**: Continues after individual run failures, but stops after 3 consecutive unexpected errors
- **Timestamped runs**: Each run saved with microsecond-precision timestamp
- **Flexible interval**: Specify minutes (default: 60)

**Use cases:**
- **Intraday analysis**: Run every 15-30 minutes during business hours
- **Daily tracking**: Run every hour to capture price fluctuations
- **Testing**: Run every 1-5 minutes to quickly accumulate test data

**Example workflow:**
```bash
# 1. Start monitoring (let it run for several hours)
uv run spotvm \
  --regions centralus \
  --min-vcpu 4 \
  --min-ram 16 \
  --run-unattended 30 &  # Every 30 minutes, in background

# 2. Stop after collecting enough data (Ctrl+C or kill process)

# 3. Analyze collected data
uv run spotvm --analyze-history

# 4. Visualize trends
python -c "
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('results/history.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Plot price changes throughout the day
for sku in df['vm_size'].unique():
    sku_data = df[df['vm_size'] == sku]
    plt.plot(sku_data['timestamp'], sku_data['price_usd'], label=sku, marker='o')

plt.xlabel('Time')
plt.ylabel('Price (USD/hr)')
plt.title('Intraday Spot Price Fluctuations')
plt.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
"
```

**Note:** For long-term production monitoring, consider using `systemd` service or `cron` with `--save-results` instead of `--run-unattended`.

### Working with Availability Zones in Historical Data

**Important:** The same SKU in the same region can appear multiple times in historical data:

**Scenario 1: Without `--availability-zones` (regional aggregation)**
```bash
uv run spotvm --subscription-id 00000000-0000-0000-0000-000000000000 --placement-check --regions centralus --sizes Standard_D4as_v5 --save-results
```
Produces:
```csv
timestamp,vm_size,region,zone,price_usd,...
2025-01-25T14:00:00Z,Standard_D4as_v5,centralus,,0.0336,...
```
- `zone` column is empty
- One record per SKU/Region

**Scenario 2: With `--availability-zones` (zone-specific)**
```bash
uv run spotvm --subscription-id 00000000-0000-0000-0000-000000000000 --placement-check --regions centralus --sizes Standard_D4as_v5 --availability-zones --save-results
```
Produces:
```csv
timestamp,vm_size,region,zone,price_usd,eviction_rate,placement_score,quota_available
2025-01-25T18:00:00Z,Standard_D4as_v5,centralus,1,0.0336,2.5,High,True
2025-01-25T18:00:00Z,Standard_D4as_v5,centralus,2,0.0336,2.5,Medium,True
2025-01-25T18:00:00Z,Standard_D4as_v5,centralus,3,0.0336,2.5,Low,False
```
- Three separate records (one per zone)
- **Price and Eviction Rate are IDENTICAL** across zones (Azure sets prices at region level)
- **Placement Score and Quota Available differ** per zone (capacity and quotas vary by zone)

**Scenario 3: Mixed runs (inconsistent zone usage)**

If you alternate between runs with/without `--availability-zones`:
```csv
timestamp,vm_size,region,zone,price_usd,placement_score
2025-01-25T14:00:00Z,Standard_D4as_v5,centralus,,0.0336,High        # Regional
2025-01-25T18:00:00Z,Standard_D4as_v5,centralus,1,0.0336,High       # Zone 1 (same price!)
2025-01-25T18:00:00Z,Standard_D4as_v5,centralus,2,0.0336,Medium     # Zone 2 (same price!)
2025-01-25T18:00:00Z,Standard_D4as_v5,centralus,3,0.0336,Low        # Zone 3 (same price!)
2025-01-26T10:00:00Z,Standard_D4as_v5,centralus,,0.0342,High        # Regional (price changed)
```

**Note:** Price changed from 0.0336 to 0.0342 between days (normal market fluctuation), but within each day all zones have identical prices.

**How to handle mixed data when visualizing:**

```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('results/history.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# OPTION 1: Regional data only (exclude zone-specific)
regional = df[(df['vm_size'] == 'Standard_D4as_v5') & (df['zone'] == '')]
plt.plot(regional['timestamp'], regional['price_usd'], label='Regional')

# OPTION 2: Specific zone only
zone1 = df[(df['vm_size'] == 'Standard_D4as_v5') & (df['zone'] == '1')]
plt.plot(zone1['timestamp'], zone1['price_usd'], label='Zone 1')

# OPTION 3: All zones as separate lines
for zone in df['zone'].unique():
    zone_label = f"Zone {zone}" if zone else "Regional"
    zone_data = df[(df['vm_size'] == 'Standard_D4as_v5') & (df['zone'] == zone)]
    plt.plot(zone_data['timestamp'], zone_data['price_usd'], label=zone_label, marker='o')

plt.legend()
plt.xlabel('Date')
plt.ylabel('Price (USD/hr)')
plt.title('Spot Price Trends by Availability Zone')
plt.show()
```

**Best Practices:**
1. **Consistency:** Use the **same parameters** for regular scheduled runs (always with or without `--availability-zones`)
2. **Filter by zone:** Always filter on the `zone` column when analyzing trends
3. **Aggregate carefully:** If you need regional averages from zone-specific data, use `groupby(['timestamp', 'vm_size', 'region']).mean()`
4. **Document your runs:** Keep track of which runs used `--availability-zones` to avoid confusion

## Operational notes
- The tool retries transient HTTP errors and honours `Retry-After` headers when Azure throttles requests.
- Cached responses are stored in `~/.cache/spotvm` as small JSON blobs.
- Clearing the cache can be forced with `--clear-cache`.
- Any placement entry flagged `DataNotFoundOrStale` or similar is surfaced in the `Notes` column for transparency.
- **Eviction rate timestamps:** Azure's SpotResources API does not expose `lastUpdatedTime` for eviction rate data. Eviction rates are updated approximately every 30 minutes, but the API does not provide when the last update occurred. Only price data includes update timestamps in the `Price Updated` column.

## Troubleshooting
| Symptom | Guidance |
| ------- | -------- |
| `AuthorizationFailed` from the placement score API | Confirm the caller has the *Compute Recommendations* role on the subscription. |
| `DataNotFoundOrStale` messages | Azure currently lacks fresh data for that SKU/region. Retry later or inspect alternative regions. |
| CLI exits with `No module named spotvm` when running from source | Prefer `uv sync --extra dev` and `uv run spotvm ...`. If you invoke `python -m spotvm.cli` directly, set `PYTHONPATH=src`. |

## Testing
The preferred quality workflow uses `uv`:

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

For a one-command local verification pass:

```bash
make check
```

To install the Git hooks locally:

```bash
uv run pre-commit install
```

To run the same hooks against the full tree on demand:

```bash
uv run pre-commit run --all-files
```

If you are using a traditional virtualenv instead, `pip install -e .[dev]` and `PYTHONPATH=src pytest` still work.

## Roadmap pointers
The PRD outlines potential enhancements such as visualisations, extended scheduling support, and automated discovery of alternative SKUs. The current implementation focuses on the ASCII reporting workflow and lays modular foundations for future iteration (separate modules for placement, historical metrics, and reporting).
