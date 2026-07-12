# Variables
DJANGO_DIR = jasmin-core/django-core
REACT_DIR = jasmin-core/react-core

# Local interpreter resolution.
#
# `make` recipes run in a non-interactive shell that often does NOT have your
# pyenv shims on PATH, and `poetry` itself shells out to a bare `python` to
# locate the project venv. When the only interpreters around are `python3`
# (Homebrew) or unconfigured pyenv shims, `poetry run python` dies with
# "No such file or directory: 'python'" — which takes down every target below.
#
# So resolve the project's venv interpreter DIRECTLY (it works regardless of
# pyenv/poetry shell state), and only fall back to `poetry run python` if no
# venv is found. Override anytime: `make migrate PYTHON=/path/to/python`.
ifndef PYTHON
PYTHON := $(shell \
	for p in "$$VIRTUAL_ENV/bin/python" \
	         $$HOME/Library/Caches/pypoetry/virtualenvs/jasmin-django-core-*/bin/python \
	         $$HOME/.cache/pypoetry/virtualenvs/jasmin-django-core-*/bin/python; do \
	  [ -x "$$p" ] && { echo "$$p"; exit 0; }; \
	done; echo "poetry run python")
endif

# Docker compose project files
COMPOSE_PROD = docker compose
COMPOSE_DEV  = docker compose -f docker-compose.dev.yml --env-file .env.dev

# ============================================================================
# Docker - Development
# ============================================================================
dev-up:
	$(COMPOSE_DEV) up -d --build

dev-down:
	$(COMPOSE_DEV) down

dev-restart-frontend:
	$(COMPOSE_DEV) restart frontend

dev-stop:
	$(COMPOSE_DEV) stop

dev-logs:
	$(COMPOSE_DEV) logs -f --tail=200 $(container)

dev-rebuild:
	$(COMPOSE_DEV) build --no-cache

dev-shell:
	$(COMPOSE_DEV) exec backend python manage.py shell

dev-bash:
	$(COMPOSE_DEV) exec backend bash

dev-migrate:
	$(COMPOSE_DEV) exec backend python manage.py migrate_schemas --shared
	$(COMPOSE_DEV) exec backend python manage.py migrate_schemas --tenant

dev-makemigrations:
	$(COMPOSE_DEV) exec backend python manage.py makemigrations

dev-superuser:
	$(COMPOSE_DEV) exec backend python manage.py createsuperuser

# Seed (idempotent) a local dev tenant reachable at http://test.localhost:3000
# with an admin login (admin@test.localhost / Test-Test-2026) + persona logins.
# Run after `make dev-up`. Needs `127.0.0.1 test.localhost` in /etc/hosts.
dev-seed:
	$(COMPOSE_DEV) exec backend python manage.py seed_dev_tenant

dev-reset:
	$(COMPOSE_DEV) down -v
	$(COMPOSE_DEV) up -d --build



# ============================================================================
# Local (no Docker)
# ============================================================================
runserver:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py runserver 0.0.0.0:8000

# Run the Huey background-task worker locally (no Docker). REQUIRED for async
# tasks — notably the DEFERRED Forecast recompute (recompute_shares_async):
# without a running worker a saved Forecast links its ShareContents but never
# builds their TheoreticalHarvest / stock movements (they just never appear).
# Run this in a second terminal alongside `make runserver`. NOTE: the docker
# dev stack (docker-compose.dev.yml) currently has NO huey service either, so
# a worker must be started this way in BOTH dev flows. Needs Redis or falls
# back to the SqliteHuey broker per settings.
#
# ``-w 1`` (single worker) is just a resource-friendly dev default. It used to
# be load-bearing: concurrent recompute_shares_async tasks acquired the
# per-entity ``current_balance:*`` advisory locks in cascade-discovery order
# and could AB/BA-deadlock. The recompute now defers every intermediate
# snapshot cascade into ONE sorted union pass per transaction (see
# ShareContentService.recompute_for_shares / SnapshotService.
# cascade_for_movements), so overlapping recomputes acquire locks in the same
# canonical order and multi-worker operation is safe.
huey:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py run_huey -w 1 -k thread

# Run the backend test suite locally against the Postgres dev container
# (jasmin-postgres, published on host :5433). Uses the resolved venv interpreter
# so it works regardless of pyenv/poetry shell state. Pass extra args via
# PYTEST_ARGS, e.g.  make test-local PYTEST_ARGS="-k billing -x".
test-local:
	cd $(DJANGO_DIR) && POSTGRES_HOST=localhost POSTGRES_PORT=5433 \
		POSTGRES_DB=jasmin POSTGRES_USER=jasmin POSTGRES_PASSWORD=DontForgetMeAgain \
		$(PYTHON) -m pytest $(PYTEST_ARGS)


makemigrations:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py makemigrations

# Replace lines 18-23 with:
migrate:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py migrate_schemas --shared
	cd $(DJANGO_DIR) && $(PYTHON) manage.py migrate_schemas --tenant

migrate-tenants:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py migrate_schemas --tenant

# Migrate specific tenant
migrate-tenant:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py migrate_schemas --schema=$(SCHEMA)


# Frontend commands
frontend:
	cd $(REACT_DIR) && npm run dev -- --port 3000


# Regenerate the OpenAPI schema YAML from the Django code. The CI's
# "api schema is up to date" step runs the same spectacular command
# and fails on any diff against the committed file — so this MUST
# run before committing serializer / viewset changes that touch the
# wire shape.
.PHONY: generate-schema
generate-schema:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py spectacular --file ../react-core/schema.yml
	@echo "📄 Schema regenerated at $(REACT_DIR)/schema.yml"

# Regenerate the TypeScript client + TanStack Query hooks from the
# schema YAML via orval. Rewrites $(REACT_DIR)/src/shared/api/generated/.
.PHONY: generate-frontend-api
generate-frontend-api:
	cd $(REACT_DIR) && npm run generate-api
	@echo "🔧 Frontend client regenerated under $(REACT_DIR)/src/shared/api/generated/"

# this one is used
.PHONY: generate-api
generate-api: generate-schema generate-frontend-api
	@echo "✅ API generated successfully!"
	@echo "📝 Don't forget to commit the generated files!"

shell: 
	cd $(DJANGO_DIR) && $(PYTHON) manage.py shell

shell-tenant:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py tenant_command shell --schema=test_tenant

# Load specific fixture from specific app
loaddata-app:
	cd $(DJANGO_DIR) && $(PYTHON) manage.py loaddata $(APP)/fixtures/$(FIXTURE).json

# =============================================================================
# Tests, formatters & linters — run INSIDE the running dev containers.
# The dev stack must be up first:  make dev-up
#   backend  = Django / pytest / black / ruff  (talks to the postgres service)
#   frontend = Vite / vitest / eslint / tsc
# =============================================================================

# --- Backend (in the `backend` container) ------------------------------------
# Extra pytest args via ARGS, e.g.  make pytest ARGS="-k test_foo -x -q"
.PHONY: pytest
pytest:
	$(COMPOSE_DEV) exec backend pytest $(ARGS)

.PHONY: black
black:
	$(COMPOSE_DEV) exec backend black --check apps core config

.PHONY: black-fix
black-fix:
	$(COMPOSE_DEV) exec backend black apps core config

.PHONY: ruff
ruff:
	$(COMPOSE_DEV) exec backend ruff check apps core config

.PHONY: ruff-fix
ruff-fix:
	$(COMPOSE_DEV) exec backend ruff check apps core config --fix

# --- Frontend (in the `frontend` container) ----------------------------------
.PHONY: lint
lint:
	$(COMPOSE_DEV) exec frontend npm run lint

.PHONY: lint-fix
lint-fix:
	$(COMPOSE_DEV) exec frontend npm run lint:fix

.PHONY: type-check
type-check:
	$(COMPOSE_DEV) exec frontend npm run type-check

.PHONY: test-frontend
test-frontend:
	$(COMPOSE_DEV) exec frontend npm run test:run

# --- Run the whole CI gate in one shot ---------------------------------------
.PHONY: check
check: black ruff pytest type-check lint test-frontend
