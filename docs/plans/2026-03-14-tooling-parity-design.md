# Tooling Parity Design

**Date:** 2026-03-14

**Goal:** Bring `spotvm` up to the same developer-experience baseline already used in `azure-databricks-cost-optimization`, with `ruff`, `mypy`, `pre-commit`, a simple `Makefile`, and CI checks aligned around `uv`.

## Context

The reference project already standardizes local development around:

- `uv` for dependency management and command execution
- `ruff` for linting and formatting
- `mypy` for lightweight static typing
- `pre-commit` hooks for fast local feedback
- a small `Makefile` for the common verification path
- CI that runs the same checks used locally

`spotvm` currently has only `pytest` wired into `pyproject.toml` and the recently added basic GitHub Actions test workflow. There is no shared linting, formatting, type-checking, or pre-commit baseline yet.

## Approved Behavior

- Add `ruff` and make it the first enforcement step.
- After the repository is `ruff`-clean, add `mypy` with a pragmatic configuration similar to the reference project.
- Add `.pre-commit-config.yaml` and a small `Makefile` exposing the canonical local check flow.
- Expand CI so it verifies linting, formatting, type-checking, and tests.
- Keep the setup `uv`-first and adapt the reference project patterns to `spotvm` rather than copying them blindly.

## Scope

- `pyproject.toml` dev dependencies and tool configuration
- `uv.lock`
- repository source and tests as needed to satisfy `ruff` and `mypy`
- `.pre-commit-config.yaml`
- `Makefile`
- `.github/workflows/ci.yml`
- README updates only if the new local workflow needs to be documented

## Non-Goals

- No worktree setup for this task; use a dedicated branch instead, as requested.
- No attempt to copy unrelated repo-specific scripts from the reference project.
- No strict typing push beyond what is needed to get `mypy src` green under a pragmatic config.
- No large architectural refactors justified only by lint preferences.

## Design Notes

- `ruff` should land first because it is the cheapest signal and will surface the mechanical cleanup needed before introducing stronger gates.
- `mypy` should follow only after the codebase is style-clean, so failures are easier to triage.
- Pre-commit and CI should run the same commands the developer can run locally through `uv`.
- The reference project uses Python 3.11; `spotvm` supports Python 3.10+, so the transferred configs must reflect this repository's actual supported baseline.
