.DEFAULT_GOAL := help
.PHONY: help install run migrate lint format typecheck test test-browser coverage check hooks

help:  ## list the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install:  ## install the locked dependencies (including the dev tools)
	uv sync --frozen

run:  ## the dev server with auto-reload (http://localhost:8000)
	uv run fastapi dev

migrate:  ## bring the database to the latest schema
	uv run alembic upgrade head

lint:  ## ruff: lint rules and a formatting check
	uv run ruff check app tests migrations scripts
	uv run ruff format --check app tests migrations scripts

format:  ## ruff: fix what can be fixed and format the code
	uv run ruff check --fix app tests migrations scripts
	uv run ruff format app tests migrations scripts

typecheck:  ## pyrefly over app/
	uv run pyrefly check

test:  ## the unit and web tests (the browser tests are skipped without a browser)
	uv run pytest -q

test-browser:  ## the browser tests in Docker; FINODE_BROWSER=webkit for Safari's engine
	scripts/browser-tests.sh

coverage:  ## the tests with a coverage report
	uv run pytest -q --cov --cov-report=term-missing:skip-covered

check: lint typecheck test  ## everything CI runs (except the browser tests)

hooks:  ## install the git pre-commit hook
	uv run pre-commit install
