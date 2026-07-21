.PHONY: bootstrap format lint typecheck test test-unit test-integration migrate run verify

PYTHON := .venv/bin/python

bootstrap:
	uv pip install --python $(PYTHON) -e '.[dev]'

format:
	.venv/bin/ruff format backend migrations
	.venv/bin/ruff check --fix backend migrations

lint:
	.venv/bin/ruff format --check backend migrations
	.venv/bin/ruff check backend migrations

typecheck:
	.venv/bin/pyright

test:
	$(PYTHON) -m pytest --cov=anime_rss --cov-report=term --cov-fail-under=85

test-unit:
	$(PYTHON) -m pytest backend/tests/unit

test-integration:
	$(PYTHON) -m pytest backend/tests/integration backend/tests/security

migrate:
	.venv/bin/alembic upgrade head

run:
	.venv/bin/anime-rss serve --reload

verify: lint typecheck test
