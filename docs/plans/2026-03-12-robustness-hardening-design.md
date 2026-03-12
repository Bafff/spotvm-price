# Robustness Hardening Design

**Date:** 2026-03-12

## Goal

Harden cache, history, CLI save-results, and parsing paths so malformed data or filesystem problems emit warning-level signals and degrade gracefully instead of crashing the tool or silently disappearing.

## Scope

- Add warning-level handling for cache read/write failures.
- Add warning-level handling for malformed history snapshot files.
- Add warning-level handling for save-results write failures in CLI runs.
- Add warning-level handling for malformed numeric and eviction values from Azure responses.
- Add direct unit tests for low-level hardware-window and performance helpers.
- Add a `main()` regression test for `--no-max-limit` passthrough.
- Simplify the duplicated `filter_by_requirements()` call in `_run_single_analysis()`.
- Clarify `--desired-count` help text to describe the effective placement-mode default.

## Non-Goals

- No broad refactor of cache/history APIs.
- No new strict-failure mode for malformed data.
- No changes to unrelated local modifications in `src/spotvm_tool/vm_specs.py`.

## Design

### Error Handling

- `cache.load()` treats filesystem failures as cache misses, logs `warning`, and continues.
- `cache.store()` logs `warning` and skips caching when writes fail.
- `load_historical_runs()` skips unreadable or malformed files, logs `warning`, and continues loading remaining snapshots.
- `_run_single_analysis()` wraps `save_run_results()` so save-results failures log `warning` and do not suppress console output or other artifacts.

### Parsing Observability

- `_to_float()` logs `warning` when given non-empty unparseable input.
- `_extract_eviction()` logs `warning` when a non-empty eviction string cannot be interpreted after all parsing attempts.
- Keep benign empty or missing values non-fatal.

### Testing

- Add direct helper tests for:
  - `known_hardware_tiers()`
  - `hardware_window_tiers()`
  - `matches_hardware_constraint()`
  - `calculate_relative_performance_details()`
- Add `main()` test covering `discover_skus(..., no_max_limit=True)`.
- Add cache/history/CLI robustness tests for filesystem and malformed-data paths.

## Verification

- Targeted pytest runs for touched test modules while iterating.
- Final full suite run before commit.
- `git diff --check` before commit.
