# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.12.22

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- build: resolve dependencies from uv.lock into a standalone virtualenv ---
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Dependencies only, so code changes reuse this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# --- runtime: just the interpreter, the virtualenv and the application ---
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINODE_DATABASE_ECHO=false

RUN groupadd --system --gid 10001 finode \
    && useradd --system --uid 10001 --gid finode --no-create-home --shell /usr/sbin/nologin finode

WORKDIR /srv/finode

COPY --from=builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY app ./app

USER finode

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"]

# Worker count comes from WEB_CONCURRENCY (read by uvicorn), defaulting to 1.
CMD ["fastapi", "run", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
