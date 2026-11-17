.DEFAULT_GOAL := help
.PHONY: help install install-backend install-frontend run run-frontend migrate lint format typecheck test test-browser coverage check backend-check frontend-check hooks

# The API lives in backend/ (uv), the app in frontend/ (npm). Every target runs from the repository root.
BACKEND := cd backend &&
PY_PATHS := finode tests migrations scripts

help:  ## list the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-17s %s\n", $$1, $$2}'

install: install-backend install-frontend  ## install the locked dependencies of both halves (dev tools included)

install-backend:  ## the API's locked dependencies (uv)
	$(BACKEND) uv sync --frozen

install-frontend:  ## the app's locked dependencies (npm; Node from frontend/.nvmrc)
	npm --prefix frontend ci

run:  ## the API with auto-reload (http://localhost:8000)
	$(BACKEND) uv run fastapi dev

run-frontend:  ## the app with hot reload (http://localhost:5173, passing /api on to the API)
	npm --prefix frontend run dev

migrate:  ## bring the database to the latest schema
	$(BACKEND) uv run alembic upgrade head

lint:  ## ruff: lint rules and a formatting check
	$(BACKEND) uv run ruff check $(PY_PATHS)
	$(BACKEND) uv run ruff format --check $(PY_PATHS)

format:  ## ruff and prettier: fix what can be fixed and format the code
	$(BACKEND) uv run ruff check --fix $(PY_PATHS)
	$(BACKEND) uv run ruff format $(PY_PATHS)
	npm --prefix frontend run format

typecheck:  ## pyrefly over backend/finode
	$(BACKEND) uv run pyrefly check

test:  ## the API's tests (the browser tests are skipped without a browser)
	$(BACKEND) uv run pytest -q

test-browser:  ## the browser tests in Docker; FINODE_BROWSER=webkit for Safari's engine
	scripts/browser-tests.sh

coverage:  ## the API's tests with a coverage report
	$(BACKEND) uv run pytest -q --cov --cov-report=term-missing:skip-covered

backend-check: lint typecheck test  ## the API: lint, types, tests

frontend-check:  ## the app: lint, types, unit tests, build, audit
	npm --prefix frontend run check

check: backend-check frontend-check  ## everything CI runs (except the browser tests and the image builds)

hooks:  ## install the git pre-commit hook
	uv run --project backend pre-commit install
