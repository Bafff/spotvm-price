.PHONY: check lint format type test

check: lint format type test

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

type:
	uv run mypy src

test:
	uv run pytest -q
