.PHONY: setup assets run test typecheck browser-install browser-check

setup:
	uv sync --locked
	npm ci
	npm run build

assets:
	npm run build

run:
	uv run python -m lastro

test:
	uv run pytest

typecheck:
	uv run mypy

browser-install:
	uv run playwright install chromium

browser-check:
	uv run python -m scripts.check_browser
