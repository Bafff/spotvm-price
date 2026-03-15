# CLI Decomposition Todo

## Scope

Next substantive health batch should target `src/spotvm/cli.py`, specifically:

- `test_coverage::src/spotvm/cli.py::untested_critical`
- `smells::src/spotvm/cli.py::monster_function`
- `smells::src/spotvm/cli.py::high_cyclomatic_complexity`

Keep this batch narrow. Do not start the full architecture split.

## Commit-Sized Plan

1. Extract `_run_single_analysis()` into a small set of helpers for:
   - data collection
   - candidate processing and filtering
   - persistence and export
   - terminal rendering
2. Preserve `main()` behavior and CLI arguments.
3. Add direct tests around the extracted flow to reduce reliance on stacked mocks.
4. Re-scan and resolve only the exact `cli.py` findings cleared by the batch.

## Review Workflow

Before implementation:

- Run a planning review with Claude on the target `cli.py` diff/area.
- Run a planning review with Gemini using `-y` to get a second action plan.

Suggested Gemini command shape:

```bash
gemini -y -p "Review src/spotvm/cli.py and propose a commit-sized decomposition plan focused on monster_function, high_cyclomatic_complexity, and untested_critical. Ignore broad rewrites."
```

For each `cli.py` commit:

- Run local Claude diff review for real bugs/regressions only.
- Run local Gemini diff review with `-y` for a second bug/regression pass.
- Fix valid findings, reject invalid ones with evidence, then rerun focused and full verification.

## Constraints

- Keep commits scoped and meaningful.
- Do not touch `scorecard.png`.
- Prefer extraction over redesign.
- Maintain current CLI output and exit-code behavior.
