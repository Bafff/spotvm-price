# Azure Spot VM Placement Score Analysis Tool

This project delivers a Python CLI that correlates Azure Spot Placement Score data with the Spot price and eviction history published via Azure Resource Graph. It provides a consolidated, ranked report for a set of VM SKUs and regions so you can quickly identify combinations that balance availability, stability, and cost for Spot VM workloads.

## Prerequisites
- Python 3.10 or later.
- An Azure subscription ID and credentials capable of acquiring an access token via `DefaultAzureCredential` (Azure CLI login, managed identity, or service principal).
- The **Compute Recommendations** role assigned to the caller on the target subscription in order to invoke the Spot Placement Score API.[^placement-score]
- Read access to Azure Resource Graph (granted by default for most accounts) to query the `SpotResources` table.[^spotresources]

[^placement-score]: Azure documentation: *Spot Placement Score* (REST) – https://learn.microsoft.com/azure/virtual-machine-scale-sets/spot-placement-score?tabs=rest-api
[^spotresources]: Azure documentation: *Use Azure Spot Virtual Machines* – https://learn.microsoft.com/azure/virtual-machines/spot-vms

## Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .  # installs the CLI entry point `spotvm-tool`
# For development or running tests:
pip install -e .[dev]
```

### One-command execution options
- **pipx from local checkout:** `pipx run --spec ./ spotvm-tool -- --help`
- **pipx from GitHub:** `pipx run git+https://github.com/Bafff/spotvm-price.git -- --help`
- **uv (if installed):** `uvx --from git+https://github.com/Bafff/spotvm-price.git spotvm-tool -- --help`

All three commands read `pyproject.toml`, create an isolated environment, install dependencies, and directly execute the CLI without permanently installing the package.

### Complete pipx example
If you keep your subscription ID in `.env` (for example `AZURE_SUBSCRIPTION_ID=2f929c0a-d1f4-480c-a610-f75d1862fd53`), load it and execute:

```bash
set -a
source .env
set +a
pipx run --pip-args="--force-reinstall" --spec ./ spotvm-tool \
  --clear-cache \
  --subscription-id "$AZURE_SUBSCRIPTION_ID" \
  --regions centralus \
  --sizes Standard_D2as_v6 \
  --desired-count 10 \
  --json
```

Alternatively, pass the subscription inline:

```bash
pipx run --pip-args="--force-reinstall" --spec ./ spotvm-tool \
  --clear-cache \
  --subscription-id 2f929c0a-d1f4-480c-a610-f75d1862fd53 \
  --regions centralus \
  --sizes Standard_D2as_v6 \
  --desired-count 10 \
  --json
```

`--clear-cache` ensures the run fetches fresh placement/Resource Graph data, while `--pip-args="--force-reinstall"` makes pipx rebuild the package from the current checkout before executing it.

## Configuration
You can supply parameters directly via CLI arguments or load them from a JSON/YAML file. The sample below mirrors `config.sample.yaml` in the repository:

```yaml
subscription_id: "00000000-0000-0000-0000-000000000000"
regions:
  - eastus
  - westus
sizes:
  - Standard_D2s_v4
  - Standard_D4s_v4
desired_count: 10
os_type: linux
availability_zones: false
cache_ttl_minutes: 15
result_limit: 10
emit_json: false
```

### Key fields
- `subscription_id`: Azure subscription to query.
- `regions`: Up to eight regions per request (the tool batches automatically if more are provided).
- `sizes`: Up to five SKUs per request (batched automatically as needed).
- `desired_count`: Number of VMs you intend to launch; placement score sensitivity increases with larger counts.
- `os_type`: `linux` (default) or `windows` to align price history with OS-specific retail rates.
- `availability_zones`: Set `true` to request zone-level placement scores; otherwise the tool queries region scope.
- `baseline_sku`: Optional VM SKU to use as 100% performance baseline for relative comparison (e.g., `Standard_D4as_v6`). When set, enables `Perf %` and `Price/Perf` columns and optimizes recommendations for value.
- `cache_ttl_minutes`: Reuses identical placement/Resource Graph responses for the specified TTL to respect Azure guidance of avoiding duplicate calls within 15 minutes.[^placement-score]
- `result_limit`: Optional maximum number of rows in the final ranked report.
- `emit_json`: When `true`, prints a JSON representation in addition to the table (also useful when saving reports).
- `enable_placement`: Set to `false` (or pass `--skip-placement`) to temporarily bypass the Spot Placement Score API when you only want historical metrics or need to avoid rate limits.

## Usage
### Direct arguments
```bash
spotvm-tool \
  --subscription-id 00000000-0000-0000-0000-000000000000 \
  --regions eastus westus \
  --sizes Standard_D2s_v4 Standard_D4s_v4 \
  --desired-count 20 \
  --os-type linux \
  --json
```

### With a configuration file
```bash
spotvm-tool --config config.sample.yaml --save-report reports/latest.json
```

The CLI prints an aligned ASCII table with the placement score, quota availability, latest spot price, and eviction rate for each combination. After sorting (High > Medium > Low, then by lowest eviction rate and price), it emits a short recommendation list and an optional JSON payload when requested.

### Example snippet
```
Rank | Region | Zone | VM Size         | Placement | Quota | Price (USD/hr) | Eviction % | Perf % | Price/Perf | Price Updated     | Eviction Updated  | Notes
---- | ------ | ---- | --------------- | --------- | ----- | -------------- | ---------- | ------ | ---------- | ----------------- | ----------------- | -----
1    | eastus |      | Standard_D2s_v4 | High      | Yes   | $0.0450        | 3.0%       | 100%   | $0.000450  | 2025-10-24T12:00  | 2025-10-20T08:00  |
2    | westus | 2    | Standard_D4s_v4 | Medium    | No    | $0.0820        | 6.5%       | 200%   | $0.000410  | 2025-10-24T11:45  | 2025-10-19T21:15  | Data not found
```
*(Perf % and Price/Perf columns shown when `--baseline-sku` is specified)*

## Output artifacts
- **Console table** – always emitted.
- **Recommendations** – human-readable summary of the top three entries.
- **JSON report** – optional structured output (includes timestamps, metrics, and notes) controllable via `--json` and `--save-report`.

## Recommendation Logic

The tool ranks VM candidates using a three-tier priority system:

### Ranking Formula
```
Priority 1: Placement Score (High > Medium > Low)
Priority 2: Eviction Rate (lower is better)
Priority 3: Price/Performance ratio (lower is better value)
```

### How it works:
1. **Placement Score** (when `--skip-placement` is NOT used)
   - `High` (best) - Azure has strong capacity signals
   - `Medium` - Moderate availability
   - `Low` - Limited availability
   - `N/A` - No placement data (when using `--skip-placement`)

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
spotvm-tool \
  --baseline-sku Standard_D4as_v6 \
  --regions eastus centralus \
  --sizes Standard_D2as_v6 Standard_D4as_v5 Standard_E4s_v5 \
  --desired-count 10
```

**Output includes:**
- `Perf %` - Performance relative to baseline (100% = baseline)
- `Price/Perf` - Price per 1% of baseline performance

**Performance calculation:**
```
Compute Score = (vCPUs × 100) + (RAM_GB × 5)
Relative % = (SKU_score / Baseline_score) × 100
```

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
- Performance formula weights CPU more heavily (100×) than RAM (5×)
- Formula is simplified; real performance depends on workload type, CPU generation, I/O, etc.
- **Why not use official Azure metrics?**
  - **ACU (Azure Compute Units)**: [Deprecated 12/16/2024](https://learn.microsoft.com/en-us/azure/virtual-machines/acu). No longer published for ANY VM series.
  - **CoreMark benchmarks**: Available for older generations (v2, v3, v4) but [no longer published](https://learn.microsoft.com/en-us/azure/virtual-machines/windows/compute-benchmark-scores) for newer generations (v5, v6+). See [GitHub Issue #84034](https://github.com/MicrosoftDocs/azure-docs/issues/84034).
  - Microsoft recommends: *"Run your actual workload on target VMs for accurate performance assessment"*
- Our vCPU + RAM formula provides a reasonable approximation until you can benchmark your specific workload
- Choose a baseline similar to your typical workload for most accurate relative comparison

## Operational notes
- The tool retries transient HTTP errors and honours `Retry-After` headers when Azure throttles requests.
- Cached responses are stored in `~/.cache/spotvm_tool` as small JSON blobs.
- Clearing the cache can be forced with `--clear-cache`.
- Any placement entry flagged `DataNotFoundOrStale` or similar is surfaced in the `Notes` column for transparency.

## Troubleshooting
| Symptom | Guidance |
| ------- | -------- |
| `AuthorizationFailed` from the placement score API | Confirm the caller has the *Compute Recommendations* role on the subscription. |
| `DataNotFoundOrStale` messages | Azure currently lacks fresh data for that SKU/region. Retry later or inspect alternative regions. |
| CLI exits with `No module named spotvm_tool` when running from source | Set `PYTHONPATH=src` when invoking via `python -m spotvm_tool.cli`. |

## Testing
Install the development extras and execute `pytest` (requires an environment with Pytest available):
```bash
pip install -e .[dev]
PYTHONPATH=src pytest
```

## Roadmap pointers
The PRD outlines potential enhancements such as visualisations, extended scheduling support, and automated discovery of alternative SKUs. The current implementation focuses on the ASCII reporting workflow and lays modular foundations for future iteration (separate modules for placement, historical metrics, and reporting).
