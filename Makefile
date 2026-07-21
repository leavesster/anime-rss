.PHONY: bootstrap bootstrap-web format lint lint-web typecheck typecheck-web test test-web test-unit test-integration migrate run run-web build-web verify verify-backend verify-web acceptance-compose

PYTHON := .venv/bin/python

bootstrap:
	uv pip install --python $(PYTHON) -e '.[dev]'

bootstrap-web:
	npm --prefix web install

format:
	.venv/bin/ruff format backend migrations
	.venv/bin/ruff check --fix backend migrations

lint:
	.venv/bin/ruff format --check backend migrations
	.venv/bin/ruff check backend migrations

lint-web:
	npm --prefix web run lint

typecheck:
	.venv/bin/pyright

typecheck-web:
	npm --prefix web run typecheck

test:
	$(PYTHON) -m pytest --cov=anime_rss --cov-report=term --cov-fail-under=85

test-web:
	npm --prefix web run test

test-unit:
	$(PYTHON) -m pytest backend/tests/unit

test-integration:
	$(PYTHON) -m pytest backend/tests/integration backend/tests/security

migrate:
	.venv/bin/alembic upgrade head

run:
	.venv/bin/anime-rss serve --reload

run-web:
	npm --prefix web run dev

build-web:
	npm --prefix web run build

verify-backend: lint typecheck test

verify-web:
	npm --prefix web run verify

verify: verify-backend verify-web

acceptance-compose:
	./scripts/acceptance-compose.sh
