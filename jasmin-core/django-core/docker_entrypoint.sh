#!/usr/bin/env bash
# =============================================================================
# Jasmin Django container entrypoint
#
# Usage:
#   docker_entrypoint.sh runserver         # dev (Django auto-reload server)
#   docker_entrypoint.sh gunicorn          # prod (gunicorn WSGI)
#   docker_entrypoint.sh huey              # huey task consumer
#   docker_entrypoint.sh manage <args...>  # arbitrary `manage.py` invocation
#   docker_entrypoint.sh <anything else>   # exec'd verbatim
#
# Environment toggles:
#   SKIP_MIGRATIONS=1   - do not run migrate_schemas at startup
#   SKIP_COLLECTSTATIC=1 - do not run collectstatic in production
#   GUNICORN_WORKERS    - override gunicorn worker count (default: 4)
#   GUNICORN_THREADS    - override gunicorn thread count (default: 2)
# =============================================================================
set -euo pipefail

echo "=== Jasmin Django container starting ==="

# -----------------------------------------------------------------------------
# Wait for PostgreSQL
# -----------------------------------------------------------------------------
if [[ -n "${POSTGRES_HOST:-}" ]]; then
    echo "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT:-5432} ..."
    until PGPASSWORD="${POSTGRES_PASSWORD:-}" psql \
            -h "${POSTGRES_HOST}" \
            -p "${POSTGRES_PORT:-5432}" \
            -U "${POSTGRES_USER}" \
            -d "${POSTGRES_DB}" \
            -c '\q' >/dev/null 2>&1; do
        sleep 1
    done
    echo "PostgreSQL is ready."
fi

# -----------------------------------------------------------------------------
# Wait for Redis (optional)
# -----------------------------------------------------------------------------
if [[ -n "${REDIS_URL:-}" ]]; then
    echo "Waiting for Redis at ${REDIS_URL} ..."
    until python -c "import redis,os; redis.from_url(os.environ['REDIS_URL']).ping()" >/dev/null 2>&1; do
        sleep 1
    done
    echo "Redis is ready."
fi

# -----------------------------------------------------------------------------
# Migrations
# -----------------------------------------------------------------------------
if [[ "${SKIP_MIGRATIONS:-0}" != "1" ]]; then
    echo "Running shared schema migrations ..."
    python manage.py migrate_schemas --shared --noinput

    echo "Ensuring public tenant + platform domains exist ..."
    python manage.py shell <<'PYEOF'
import os
from apps.shared.tenants.models import Tenant, Domain

tenant, created = Tenant.objects.get_or_create(
    schema_name="public", defaults={"name": "Public"}
)
if created:
    print("Created public tenant")

frontend_domain = os.environ.get("FRONTEND_DOMAIN", "localhost").split(":")[0]
super_admin_subdomain = os.environ.get("SUPER_ADMIN_SUBDOMAIN", "marillen").strip()

# The public schema serves BOTH the bare frontend domain and the super-admin /
# platform host. django-tenants' TenantMainMiddleware does an exact
# Domain.get(domain=host) and raises Http404 on miss, so BOTH hostnames need a
# Domain row or ``${SUPER_ADMIN_SUBDOMAIN}.<domain>/api/super-admin/*`` 404s
# before any view runs. get_or_create keeps this idempotent across restarts.
Domain.objects.get_or_create(
    domain=frontend_domain,
    defaults={"tenant": tenant, "is_primary": True},
)
if super_admin_subdomain:
    Domain.objects.get_or_create(
        domain=f"{super_admin_subdomain}.{frontend_domain}",
        defaults={"tenant": tenant, "is_primary": False},
    )
    print(f"Ensured platform domain {super_admin_subdomain}.{frontend_domain}")
PYEOF

    echo "Running tenant schema migrations ..."
    python manage.py migrate_schemas --tenant --noinput
fi

# -----------------------------------------------------------------------------
# Collectstatic (production only)
# -----------------------------------------------------------------------------
if [[ "${DEBUG:-True}" != "True" && "${SKIP_COLLECTSTATIC:-0}" != "1" ]]; then
    echo "Collecting static files ..."
    python manage.py collectstatic --noinput
fi

# -----------------------------------------------------------------------------
# Optional: create the platform SuperAdmin if env vars are set.
#
# The platform admin is a PUBLIC-schema ``apps.shared.super_admin.SuperAdmin``
# (keyed on email) — NOT ``accounts.JasminUser``, which is a TENANT-only model
# with no table in the public schema. The ``createsuperadmin`` command targets
# the right model and is idempotent via --update-if-exists. Failures (e.g. a
# password below the policy minimum) are non-fatal: log and boot anyway rather
# than crash-looping the container under ``set -euo pipefail``.
# -----------------------------------------------------------------------------
if [[ -n "${DJANGO_SUPERUSER_EMAIL:-}" \
   && -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]]; then
    echo "Ensuring SuperAdmin '${DJANGO_SUPERUSER_EMAIL}' exists ..."
    python manage.py createsuperadmin \
        --email "${DJANGO_SUPERUSER_EMAIL}" \
        --password "${DJANGO_SUPERUSER_PASSWORD}" \
        --update-if-exists \
        || echo "createsuperadmin failed — starting anyway; fix DJANGO_SUPERUSER_* and re-run 'docker compose exec backend python manage.py createsuperadmin --email … --password … --update-if-exists'."
fi

# -----------------------------------------------------------------------------
# Optional: seed a local DEV test tenant (test.localhost) + admin & persona
# logins so the dockerized dev stack is usable immediately after `make dev-up`.
# Opt-in via SEED_DEV_TENANT (set ONLY in docker-compose.dev.yml). Runs AFTER
# migrations so the schemas exist, and is idempotent — every restart just
# refreshes it. ``seed_dev_tenant`` itself refuses to run when DEBUG is False,
# so the fixed test credentials can never be seeded into production.
# -----------------------------------------------------------------------------
if [[ "${SEED_DEV_TENANT:-0}" == "1" ]]; then
    echo "Seeding dev test tenant (test.localhost) ..."
    python manage.py seed_dev_tenant \
        || echo "seed_dev_tenant failed — starting anyway; run 'make dev-seed' to retry."
fi

echo "=== Startup checks complete ==="

# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------
cmd="${1:-gunicorn}"
shift || true

case "$cmd" in
    runserver)
        echo "Starting Django dev server ..."
        exec python manage.py runserver 0.0.0.0:8000
        ;;
    gunicorn)
        echo "Starting gunicorn ..."
        exec gunicorn config.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-4}" \
            --threads "${GUNICORN_THREADS:-2}" \
            --worker-class gthread \
            --worker-tmp-dir /dev/shm \
            --access-logfile - \
            --error-logfile - \
            --log-level "${GUNICORN_LOG_LEVEL:-info}" \
            --timeout "${GUNICORN_TIMEOUT:-120}" \
            --keep-alive 5
        ;;
    huey)
        echo "Starting huey consumer ..."
        exec python manage.py run_huey
        ;;
    manage)
        exec python manage.py "$@"
        ;;
    *)
        exec "$cmd" "$@"
        ;;
esac
