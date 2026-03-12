# Spotvm Rename Design

**Date:** 2026-03-12

**Goal:** Perform a full breaking rename of the tool from `spotvm-tool` / `spotvm_tool` to `spotvm`.

## Context

Today the project mixes three public identities:

- distribution/package metadata uses `spotvm-tool`
- the console entry point is `spotvm-tool`
- the Python package/import path is `spotvm_tool`

That split leaks into docs, tests, cache paths, loggers, and the HTTP user agent. The rename should make the tool consistently appear as `spotvm` everywhere the user or integrator sees it.

## Approved Behavior

- The Python distribution name becomes `spotvm`.
- The console entry point becomes `spotvm`.
- The Python package directory and import path become `spotvm`.
- `python -m spotvm` is the supported module entry point.
- Logger names, user agent strings, and cache paths are renamed to `spotvm`.
- Existing names `spotvm-tool`, `spotvm_tool`, and related aliases are not preserved.

## Scope

- `pyproject.toml` project metadata and console scripts.
- `src/spotvm_tool/` package rename to `src/spotvm/`.
- Internal imports, tests, docs, and examples.
- Runtime strings:
  - argparse `prog`
  - help/epilog examples
  - logger names
  - cache directory
  - HTTP user agent
  - package version lookup

## Non-Goals

- No repository rename in git or GitHub.
- No compatibility alias package.
- No compatibility wrapper CLI.
- No migration tooling for old cache paths or old commands.

## Design Notes

- This is intentionally a breaking rename. Failures for old names are acceptable.
- The cleanest implementation is a real package-directory rename, not a thin alias layer.
- Tests should be updated to import `spotvm` directly so the suite validates the new package layout.
- README and troubleshooting text should stop mentioning `spotvm-tool` and `spotvm_tool` except where needed to explain the breaking change.
- The current clean-worktree baseline in the isolated worktree fails on packaging/import setup. The rename work will proceed anyway and must end with a green full test run in the renamed state.
