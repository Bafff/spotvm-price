# CLI Request Shape Design

**Date:** 2026-03-14

**Goal:** Remove `_run_single_analysis()`'s dependency on the raw `argparse.Namespace` while keeping the first `cli.py` cleanup batch narrow and behavior-preserving.

## Context

`desloppify` now ranks `review::.::holistic::abstraction_fitness::cli_namespace_and_config_bags` as the top real backlog item after the latest rescan. The issue is not that `ToolConfig` exists; the issue is that the core execution path depends on two overlapping bags of runtime state:

- `args`, which carries CLI-only execution inputs such as `csv`, `results_dir`, `no_color`, `min_vcpu`, and `max_price`
- `ToolConfig`, which carries validated runtime configuration such as `enable_placement`, `baseline_sku`, `emit_json`, and `save_report`

That split makes it hard to reason about where a new execution option belongs and keeps `_run_single_analysis()` coupled to a parser product instead of an explicit execution contract.

## Constraints

- Keep the first batch narrow.
- Do not start the large `cli.py` architecture split yet.
- Preserve current user-visible behavior.
- Use TDD.
- Run a focused pytest pass, then full pytest.
- Run a local Claude bug/regression review before each code commit.
- Keep follow-up improvements as distinct commits.

## Approaches Considered

### 1. Recommended: introduce one CLI-owned execution request object

Add a small typed request object for the values `_run_single_analysis()` actually needs from the CLI layer, build it in `main()`, and pass it instead of the raw `Namespace`.

Why this is the right first slice:

- directly addresses the top review finding
- keeps `ToolConfig` intact for now
- does not force fetcher API changes in the same commit
- reduces test coupling by letting tests construct an explicit request instead of a fake namespace

### 2. Broader cleanup: fix the CLI request shape and fetcher `ToolConfig` usage together

This would move `resource_graph.py` and `placement_score.py` to explicit request shapes in the same batch.

Why not first:

- touches more modules than necessary
- expands the test surface immediately
- makes the first architectural commit harder to review

### 3. Full CLI orchestration split

Start splitting `main()` and `_run_single_analysis()` into separate orchestration modules now.

Why not first:

- too wide for the requested narrow first step
- higher regression risk
- would blur the review signal for the top abstraction-fitness fix

## Chosen Design

### Batch 1 scope

Create a small immutable CLI execution request type in `src/spotvm/cli.py` and change `_run_single_analysis()` to depend on that type instead of `args`.

The request should own only CLI execution concerns, for example:

- `no_color`
- `min_vcpu`
- `min_ram`
- `no_max_limit`
- `explicit_sizes`
- `max_price`
- `max_eviction`
- `min_performance`
- `csv`
- `results_dir`
- `save_results`

`ToolConfig` remains the validated runtime configuration object for domain behavior and persisted config values.

### Data flow

1. `main()` parses CLI args.
2. `main()` merges config file data with CLI overrides into `ToolConfig`.
3. `main()` builds `AnalysisRunRequest` from the CLI-only execution inputs.
4. `main()` passes `AnalysisRunRequest` plus `ToolConfig` into `_run_single_analysis()`.
5. Unattended mode forces persisted snapshots by producing a modified request with `save_results=True`, instead of passing an extra boolean parameter.

### Testing impact

- Replace namespace-based test helpers in `tests/test_cli.py` with an explicit request helper.
- Add at least one direct test that proves request construction captures CLI-only execution state correctly.
- Keep existing behavior tests intact by translating them to the new request object instead of broad rewrites.

## Non-Goals For Batch 1

- No fetcher signature changes in `src/spotvm/resource_graph.py`.
- No fetcher signature changes in `src/spotvm/placement_score.py`.
- No large split of `main()` or `_run_single_analysis()`.
- No output schema consolidation.
- No `tests/test_cli.py` over-mock reduction in the same commit.

## Follow-On Batch Roadmap

These stay separate from Batch 1 and should land as distinct commits, each with focused tests and a Claude review:

1. `resource_graph.py` explicit request inputs
   Target item: `review::.::holistic::abstraction_fitness::domain_apis_hidden_behind_toolconfig` for historical metrics.
2. `placement_score.py` explicit request inputs
   Same review theme, but separate commit for placement fetching.
3. `tests/test_cli.py` over-mock reduction
   Target item: `test_coverage::src/spotvm/cli.py::over_mocked::test_cli.py`.
4. Next `cli.py` structural slice
   Candidate items: `smells::src/spotvm/cli.py::monster_function` and `smells::src/spotvm/cli.py::high_cyclomatic_complexity`.

## Review And Verification Gates

Every code batch in this sequence should follow the same gate:

1. Write failing tests first.
2. Run the focused pytest target and confirm the intended failure.
3. Implement the smallest change that makes the focused tests pass.
4. Run the required focused verification.
5. Run `uv run pytest -q`.
6. Run a local Claude Code review on the uncommitted diff, bugs/regressions only.
7. Fix valid review findings.
8. Re-run verification before committing.
