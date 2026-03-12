# Spotvm Rename Design

**Date:** 2026-03-12

**Goal:** Perform a full breaking rename of the tool from the legacy public names to `spotvm`.

## Context

Today the project mixes three public identities:

- distribution/package metadata uses a legacy name
- the console entry point uses a legacy name
- the Python package/import path uses a legacy name

That split leaks into docs, tests, cache paths, loggers, and the HTTP user agent. The rename should make the tool consistently appear as `spotvm` everywhere the user or integrator sees it.

## Approved Behavior

- The Python distribution name becomes `spotvm`.
- The console entry point becomes `spotvm`.
- The Python package directory and import path become `spotvm`.
- `python -m spotvm` is the supported module entry point.
- Logger names, user agent strings, and cache paths are renamed to `spotvm`.
- Existing legacy names and related aliases are not preserved.

## Scope

- `pyproject.toml` project metadata and console scripts.
- Rename the legacy package directory to `src/spotvm/`.
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
- No migration tooling for legacy cache paths or legacy commands.

## Design Notes

- This is intentionally a breaking rename. Failures for legacy names are acceptable.
- The cleanest implementation is a real package-directory rename, not a thin alias layer.
- Tests should be updated to import `spotvm` directly so the suite validates the new package layout.
- README and troubleshooting text should stop mentioning legacy CLI/import names except where needed to explain the breaking change.
- The current clean-worktree baseline in the isolated worktree fails on packaging/import setup. The rename work will proceed anyway and must end with a green full test run in the renamed state.
