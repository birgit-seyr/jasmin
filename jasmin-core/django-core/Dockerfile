# syntax=docker/dockerfile:1.6
# =============================================================================
# Jasmin Django backend - multi-stage build
#   Stages:
#     base    - common system layer (used by builder, dev, runtime)
#     builder - installs poetry deps into /app/.venv
#     dev     - includes dev dependencies, source mounted at runtime via compose
#     runtime - lean production image, runs gunicorn via entrypoint
# =============================================================================

ARG PYTHON_VERSION=3.14

# -----------------------------------------------------------------------------
# base
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings

# Runtime libs needed in every stage (libpq for psycopg2, postgresql-client for
# pg_isready / psql in the entrypoint, gettext for compilemessages, fonts for
# WeasyPrint PDF generation).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
        gettext \
        curl \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app


# -----------------------------------------------------------------------------
# builder - installs python dependencies into /app/.venv
# -----------------------------------------------------------------------------
FROM base AS builder

ENV POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_CACHE_DIR=/tmp/poetry_cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="${POETRY_HOME}/bin:${PATH}"

COPY pyproject.toml poetry.lock ./

# Install ALL deps here; runtime stage will not bring in the dev group anyway
# because we only copy /app/.venv after a re-install without dev for runtime.
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ] ; then \
        poetry install --no-root --no-interaction --no-ansi ; \
    else \
        poetry install --no-root --without dev --no-interaction --no-ansi ; \
    fi \
    && rm -rf "$POETRY_CACHE_DIR"


# -----------------------------------------------------------------------------
# dev - source code is bind-mounted by docker-compose.dev.yml
# -----------------------------------------------------------------------------
FROM base AS dev

# Re-run the builder stage with dev deps. We just copy a venv built with
# INSTALL_DEV=true. To keep this Dockerfile self-contained we install poetry
# here too and re-resolve.
ENV POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="${POETRY_HOME}/bin:/app/.venv/bin:${PATH}"

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-interaction --no-ansi

# Source code will be bind-mounted; copy it anyway so the image is usable
# standalone (e.g. for one-off `docker run` commands).
COPY . .
RUN chmod +x /app/docker_entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media /app/logs

EXPOSE 8000
ENTRYPOINT ["/app/docker_entrypoint.sh"]
CMD ["runserver"]


# -----------------------------------------------------------------------------
# runtime - production image
# -----------------------------------------------------------------------------
FROM base AS runtime

# Non-root user
RUN groupadd --system django && useradd --system --gid django --home /app django

# Bring in the venv from the builder stage (without dev deps).
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

COPY --chown=django:django . .
RUN chmod +x /app/docker_entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media /app/logs \
    && chown -R django:django /app/staticfiles /app/media /app/logs

USER django

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/ || exit 1

ENTRYPOINT ["/app/docker_entrypoint.sh"]
CMD ["gunicorn"]
