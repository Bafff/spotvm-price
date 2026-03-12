# Hardware Window Filtering Design

**Date:** 2026-03-12

**Goal:** Make hardware discovery and requirement filtering more practical by default when users specify minimum CPU and/or memory requirements.

## Context

Today `--min-vcpu` and `--min-ram` are open-ended lower bounds. A request like `--min-vcpu 4 --min-ram 16` can return very large SKUs such as 64-vCPU machines, which makes discovery noisy when the user is trying to find a right-sized SKU family. Unknown SKUs are currently preserved because the tool cannot verify their vCPU/RAM requirements.

## Approved Behavior

- By default, minimum hardware constraints create bounded windows of the next 3 standard sizes, inclusive.
- CPU example: `4 -> 4, 8, 16`; `8 -> 8, 16, 32`; `16 -> 16, 32, 64`.
- RAM example: `16 -> 16, 32, 64`; `32 -> 32, 64, 128`.
- When both CPU and RAM constraints are provided, candidates must satisfy both windows.
- Unknown SKUs are excluded while bounded windows are active.
- New flag `--no-max-limit` disables the bounded behavior and restores the current unbounded lower-bound semantics.

## Scope

- CLI help text for `--min-vcpu`, `--min-ram`, and the new `--no-max-limit`.
- Auto-discovery in `src/spotvm_tool/vm_specs.py`.
- Requirement filtering in `src/spotvm_tool/analysis.py`.
- CLI plumbing and logging in `src/spotvm_tool/cli.py`.
- Tests and README updates.

## Non-Goals

- No new Intel/AMD vendor filter in this change.
- No exact-match CPU or RAM filter in this change.
- No config-file support for `--no-max-limit` unless already needed by current CLI plumbing.

## Design Notes

- The bounded window should be derived from the distinct hardware values already present in `VM_SPECIFICATIONS`, not from hardcoded tier tables.
- The same helper logic should be shared between autodiscovery and candidate filtering so their behavior stays aligned.
- Explicit `--sizes` should continue to mean “use these SKUs”; the bounded window should not rewrite the user’s SKU list beyond existing requirement filtering.
- Unknown SKUs should only be dropped in bounded mode. In unlimited mode, current warning-based behavior remains useful because the filter is only enforcing minimums.
