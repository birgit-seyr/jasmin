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

# The backend's venv and the frontend's node_modules live in named volumes that
# a rebuild never touches, so a lock change has to be installed into them.
# The services stop for it: installing under a running dev server makes its
# reloader restart on half-installed packages. Keeps the dev database;
# `make deps-check` says when this is needed.
.PHONY: dev-sync-deps
dev-sync-deps:
	$(COMPOSE_DEV) stop backend huey frontend
	$(COMPOSE_DEV) run --rm --no-deps -T --entrypoint poetry backend sync
	$(COMPOSE_DEV) run --rm --no-deps -T --entrypoint npm frontend ci
	$(COMPOSE_DEV) up -d backend huey frontend

dev-shell:
	$(COMPOSE_DEV) exec backend python manage.py shell

dev-bash:
	$(COMPOSE_DEV) exec backend bash

dev-migrate:
	$(COMPOSE_DEV) exec backend python manage.py migrate_schemas --shared
	$(COMPOSE_DEV) exec backend python manage.py migrate_schemas --tenant

dev-makemigrations:
	$(COMPOSE_DEV) exec backend python manage.py makemigrations

# Create a super-admin login for http://marillen.localhost:3000; prompts for
# the password. Usage: make dev-superuser EMAIL=you@example.com
dev-superuser:
	@test -n "$(EMAIL)" || { echo "Usage: make dev-superuser EMAIL=you@example.com"; exit 1; }
	$(COMPOSE_DEV) exec backend python manage.py createsuperadmin --email=$(EMAIL)

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

# Run the Huey background-task worker on the host (no Docker), in a second
# terminal alongside `make runserver`. Needed when REDIS_URL points the host
# flow at a Redis broker: the enqueued tasks (the bulk email sends) and the
# periodic jobs queue there, and only a consumer runs them. Without REDIS_URL
# a DEBUG host runs tasks inline at enqueue (HUEY ``immediate`` in
# config/settings.py), and the Docker dev stack runs its own ``huey`` service.
# ``-w 1`` (a single worker) is just a resource-friendly dev default.
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
	$(COMPOSE_DEV) exec backend black --check apps config core scripts

.PHONY: black-fix
black-fix:
	$(COMPOSE_DEV) exec backend black apps config core scripts

# ruff runs against a frozen baseline, same shape as mypy below: the strict
# rules (E,F,B,BLE,UP,I) have no baseline entries so they still fail hard, while
# the hygiene rules (N naming, C901 complexity, PLR0913/PLR0915 size) are held at
# the 201 findings that predate them. Fix findings, then `make ruff-freeze` and
# commit the smaller baseline. This is exactly what CI runs.
.PHONY: ruff
ruff:
	$(COMPOSE_DEV) exec backend python scripts/ruff_baseline.py check

.PHONY: ruff-freeze
ruff-freeze:
	$(COMPOSE_DEV) exec backend python scripts/ruff_baseline.py freeze

# Autofix pass. Only the fixable rules move; the baselined naming/complexity
# findings have no autofix and are left for a human.
.PHONY: ruff-fix
ruff-fix:
	$(COMPOSE_DEV) exec backend ruff check apps core config --fix

# One-way import layering: apps/commissioning must stay extractable, apps/shared
# must stay the bottom layer. Known extraction blockers are named exemptions
# inside the script, and an exemption that no longer matches is an error too.
.PHONY: import-contracts
import-contracts:
	$(COMPOSE_DEV) exec backend python scripts/import_contracts.py

# Backend modules over 1000 lines are pinned at their length in
# jasmin-core/django-core/module-length-baseline.txt, and a pin only goes down:
# split a module, then `make module-length-freeze`.
.PHONY: module-length
module-length:
	$(COMPOSE_DEV) exec backend python scripts/module_length.py check

.PHONY: module-length-freeze
module-length-freeze:
	$(COMPOSE_DEV) exec backend python scripts/module_length.py freeze

# mypy runs against a frozen baseline: only findings that are NOT in
# jasmin-core/django-core/mypy-baseline.txt fail. Fix findings, then
# `make mypy-freeze` and commit the smaller baseline.
# Needs mypy inside the container — if this reports "No module named mypy",
# the dev venv volume predates the dependency: remove it and rebuild.
.PHONY: mypy
mypy:
	$(COMPOSE_DEV) exec backend python scripts/mypy_baseline.py check

.PHONY: mypy-freeze
mypy-freeze:
	$(COMPOSE_DEV) exec backend python scripts/mypy_baseline.py freeze

# --- Frontend (in the `frontend` container) ----------------------------------
.PHONY: lint
lint:
	$(COMPOSE_DEV) exec frontend npm run lint

.PHONY: lint-fix
lint-fix:
	$(COMPOSE_DEV) exec frontend npm run lint:fix

# The per-file pins in eslint.hygiene-pins.js are ceilings, and `npm run lint`
# cannot see below one: a file that improves keeps its old pin and is free to
# grow back. This re-measures every pinned file and fails on a pin above the
# value the file now reports — the ruff/mypy ratchet, applied to the pins.
.PHONY: lint-pins
lint-pins:
	$(COMPOSE_DEV) exec frontend npm run lint:pins

.PHONY: type-check
type-check:
	$(COMPOSE_DEV) exec frontend npm run type-check

# The dev container sets NODE_ENV=development for Vite's dev server; vitest only
# sets "test" when nothing is set, and under "development" AntD's styles build
# selectors jsdom rejects. CI sets nothing, so pin the value it effectively runs.
.PHONY: test-frontend
test-frontend:
	$(COMPOSE_DEV) exec -e NODE_ENV=test frontend npm run test:run

# Likewise a production build: `vite build` keeps an inherited NODE_ENV, so the
# container's "development" would bundle development React and skew `size`.
.PHONY: build
build:
	$(COMPOSE_DEV) exec -e NODE_ENV=production frontend npm run build

# The bundle-size budgets can only be measured on built output, and vitest
# never runs Rollup — so a chunking regression is invisible to every other
# frontend target here. Depends on `build` so `check` cannot measure a stale
# or absent dist.
.PHONY: size
size: build
	$(COMPOSE_DEV) exec frontend npm run size

# --- End-to-end (Playwright, runs on the host against the dev stack) ---------
# The dev stack must be up (make dev-up). The suite runs in its own e2e and
# e2e_other tenants (e2e.localhost / e2e-other.localhost), never in `test`;
# seed_e2e creates or refreshes them first. Extra Playwright args via E2E_ARGS,
# e.g.  make e2e E2E_ARGS="--repeat-each=3".
E2E_DIR = jasmin-core/e2e

.PHONY: e2e-install
e2e-install:
	cd $(E2E_DIR) && npm ci && npx playwright install chromium

.PHONY: e2e
e2e:
	$(COMPOSE_DEV) exec -T backend python manage.py seed_e2e
	cd $(E2E_DIR) && npx playwright test $(E2E_ARGS)

.PHONY: e2e-ui
e2e-ui:
	$(COMPOSE_DEV) exec -T backend python manage.py seed_e2e
	cd $(E2E_DIR) && npx playwright test --ui $(E2E_ARGS)

# --- Inventory drift (runs on the host) --------------------------------------
# Sweeps the code for module-level numeric constants and reports them. Where a
# curated numeric-constants inventory is present it also reports the drift both
# ways: constants the page does not name, and names it lists that no longer
# exist. That page is a local, gitignored artifact, so on a checkout without it
# you get the plain census and no comparison. A report, not a gate — it exits 0
# on drift unless you pass TUNABLES_ARGS=--strict, and it is deliberately not
# part of `check`. Host-run because it reads outside the backend container's
# mounts.
.PHONY: tunables
tunables:
	cd $(DJANGO_DIR) && $(PYTHON) scripts/tunables.py $(TUNABLES_ARGS)

# --- The rest of what CI checks ----------------------------------------------
# $(call poetry-in-sync,<command prefix>,<which venv>,<fix>): fails, listing the
# pending changes, when that venv differs from poetry.lock.
define poetry-in-sync
@out=$$($(1) poetry sync --dry-run 2>&1) || { echo "$$out"; exit 1; }; \
echo "$$out" | grep -qE "No dependencies to install or update|0 installs, 0 updates, 0 removals" || { \
  echo "$$out" | grep -E "^  - (Installing|Updating|Removing)" | grep -v Skipped; \
  echo "✗ $(2) differs from poetry.lock. Run: $(3)"; exit 1; }
endef

# The packages every gate runs on must match the locks, or they test the old
# versions: the containers' venv and node_modules (see dev-sync-deps), and the
# host venv test-local runs the suite in.
.PHONY: deps-check
deps-check:
	$(call poetry-in-sync,$(COMPOSE_DEV) exec -T backend,The backend container's venv,make dev-sync-deps)
	$(call poetry-in-sync,cd $(DJANGO_DIR) &&,The host venv (test-local),cd $(DJANGO_DIR) && poetry sync)
	$(COMPOSE_DEV) exec -T frontend node scripts/check-installed-deps.mjs

.PHONY: lock-check
lock-check:
	$(COMPOSE_DEV) exec -T backend poetry check --lock

.PHONY: migrations-check
migrations-check:
	$(COMPOSE_DEV) exec -T backend python manage.py makemigrations --check --dry-run

# Regenerates the OpenAPI schema and compares it with the committed one,
# without overwriting it. Fix a difference with `make generate-api`.
.PHONY: schema-check
schema-check:
	@$(COMPOSE_DEV) exec -T backend python manage.py spectacular 2>/dev/null \
	  | diff -u $(REACT_DIR)/schema.yml - \
	  || { echo "✗ schema.yml is out of date. Run: make generate-api"; exit 1; }

# The same advisory gates as CI's two "Security audit" steps; each ignored
# advisory carries its reason there and in scripts/check-prod-audit.mjs.
.PHONY: audit
audit:
	$(COMPOSE_DEV) exec -T backend python -m pip_audit --strict --ignore-vuln PYSEC-2025-183
	$(COMPOSE_DEV) exec -T frontend node scripts/check-prod-audit.mjs

# CI's gitleaks scan, over the files a commit would carry (scripts/secret_scan.sh).
.PHONY: secrets
secrets:
	./scripts/secret_scan.sh

# --- Run the whole CI gate in one shot ---------------------------------------
# Everything CI runs except the image builds and the nginx config check, in
# roughly the order of their cost, so a cheap failure stops it early. The suite
# runs on the host (test-local), as in CI's checkout: some tests read repo files
# outside django-core (scripts/, backups/), which the backend container lacks.
.PHONY: check
check: deps-check lock-check secrets black ruff import-contracts module-length mypy migrations-check schema-check type-check lint lint-pins audit test-local test-frontend size
