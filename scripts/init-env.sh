#!/usr/bin/env bash
# =============================================================================
# init-env.sh — generate a production .env with fresh secrets.
#
# Generates every cryptographic secret the stack needs (Django secret key,
# Fernet field-encryption key, DB / Redis / backup / GlitchTip passwords, the
# super-admin login password) and writes a complete .env. Values you must
# supply by hand — the PLATFORM SMTP host/user/pass (ops-alerts only) — are
# left as CHANGE_ME so deploy.sh refuses to launch until you fill them.
#
# openssl is the only dependency, so this runs anywhere (your Mac or the
# server). Run it ON THE SERVER for the real deploy so the secrets are born
# where they live.
#
# Usage:
#   ./scripts/init-env.sh --domain jasmin.example.com --admin-email you@example.com
#
# Flags:
#   --domain <d>                 apex domain (required)
#   --admin-email <e>            ops-alert inbox + super-admin login (required)
#   --super-admin-subdomain <s>  admin host label (default: admin)
#   --timezone <tz>              (default: Europe/Berlin)
#   --force                      overwrite an existing .env — regenerates ALL
#                                secrets; DESTROYS encrypted PII + locks out the
#                                DB if the box is already deployed. Fresh box only.
#   --yes                        skip the interactive --force confirmation
#
# The super-admin password is generated and PRINTED ONCE at the end — save it.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

DOMAIN=""
ADMIN_EMAIL=""
SUPER_ADMIN_SUBDOMAIN="admin"
TIMEZONE="Europe/Berlin"
FORCE=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --domain) DOMAIN="${2:?}"; shift 2 ;;
        --admin-email) ADMIN_EMAIL="${2:?}"; shift 2 ;;
        --super-admin-subdomain) SUPER_ADMIN_SUBDOMAIN="${2:?}"; shift 2 ;;
        --timezone) TIMEZONE="${2:?}"; shift 2 ;;
        --force) FORCE=1; shift ;;
        --yes) ASSUME_YES=1; shift ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Prompt for the two required human values if not passed and we have a TTY.
if [ -z "$DOMAIN" ] && [ -t 0 ]; then
    read -r -p "Apex domain (e.g. jasmin.example.com): " DOMAIN
fi
if [ -z "$ADMIN_EMAIL" ] && [ -t 0 ]; then
    read -r -p "Ops-alert / super-admin email: " ADMIN_EMAIL
fi
: "${DOMAIN:?--domain is required}"
: "${ADMIN_EMAIL:?--admin-email is required}"

# --force is NOT enough to clobber an existing .env. Regenerating
# FIELD_ENCRYPTION_KEY makes already-encrypted PII UNRECOVERABLE, and a new
# POSTGRES_PASSWORD locks out the running database. Demand explicit intent.
if [ -f "$ENV_FILE" ]; then
    if [ "$FORCE" -ne 1 ]; then
        echo "❌ $ENV_FILE already exists — this script is for INITIAL setup." >&2
        echo "   Re-running regenerates EVERY secret, including FIELD_ENCRYPTION_KEY" >&2
        echo "   (existing encrypted PII becomes UNRECOVERABLE) and POSTGRES_PASSWORD" >&2
        echo "   (locks out the running DB). Use --force only on a fresh box." >&2
        exit 1
    fi
    if [ "$ASSUME_YES" -ne 1 ]; then
        if [ -t 0 ]; then
            echo "⚠️  --force will OVERWRITE $ENV_FILE and regenerate ALL secrets." >&2
            echo "    If this box is already deployed: UNRECOVERABLE PII (new" >&2
            echo "    FIELD_ENCRYPTION_KEY) and a locked-out DB (new POSTGRES_PASSWORD)." >&2
            read -r -p "    Type 'destroy' to proceed: " _confirm
            [ "$_confirm" = "destroy" ] || { echo "Aborted." >&2; exit 1; }
        else
            echo "❌ Refusing to --force overwrite non-interactively. Pass --yes if" >&2
            echo "   you are certain this box has no data to lose." >&2
            exit 1
        fi
    fi
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "❌ openssl not found — install it and re-run." >&2
    exit 1
fi

# ── secret generators ───────────────────────────────────────────────────────
gen_hex()    { openssl rand -hex 32; }                       # DB / Redis / backup / glitchtip
gen_django() { openssl rand -hex 64; }                       # Django SECRET_KEY (entropy only)
gen_fernet() { openssl rand -base64 32 | tr '+/' '-_'; }     # urlsafe base64 == Fernet key
gen_alnum()  {                                                # human-typable super-admin pw
    local raw
    raw="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9')"
    printf '%s' "${raw:0:20}"
}

DJANGO_SECRET_KEY="$(gen_django)"
FIELD_ENCRYPTION_KEY="$(gen_fernet)"
POSTGRES_PASSWORD="$(gen_hex)"
REDIS_PASSWORD="$(gen_hex)"
BACKUP_ENCRYPTION_KEY="$(gen_hex)"
GLITCHTIP_DB_PASSWORD="$(gen_hex)"
GLITCHTIP_SECRET_KEY="$(gen_hex)"
SUPERUSER_PASSWORD="$(gen_alnum)"

umask 077   # .env is 0600 — it holds every secret
cat > "$ENV_FILE" <<EOF
# =============================================================================
# Production environment — generated by scripts/init-env.sh
# Secrets are real; CHANGE_ME values are yours to fill. Never commit this file.
# =============================================================================

# --- identity / pinning ---
# COMPOSE_PROJECT_NAME is load-bearing: certbots/init-wildcard-cert.sh hardcodes
# the "jasmin-platform_*" volume names. Do not change it.
COMPOSE_PROJECT_NAME=jasmin-platform
IMAGE_TAG=v1
FRONTEND_DOMAIN=${DOMAIN}
DJANGO_ALLOWED_HOSTS=${DOMAIN},.${DOMAIN}
TIME_ZONE=${TIMEZONE}
# Behind just nginx today = 1. Bump to 2 once Bunny sits in front (Phase 4).
TRUSTED_PROXY_COUNT=1

# --- core secrets (generated) ---
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}
POSTGRES_DB=jasmin
POSTGRES_USER=jasmin
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
REDIS_PASSWORD=${REDIS_PASSWORD}

# --- PLATFORM email = OPS ALERTS ONLY (mail_admins). NOT a fallback for tenant
#     mail — each tenant configures its own SMTP in-app. The backend refuses to
#     boot if EMAIL_HOST is empty/localhost, and deploy.sh refuses to launch
#     while any CHANGE_ME remains. Fill these in. ---
EMAIL_HOST=CHANGE_ME
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=CHANGE_ME
EMAIL_HOST_PASSWORD=CHANGE_ME
DEFAULT_FROM_EMAIL=noreply@${DOMAIN}
SERVER_EMAIL=noreply@${DOMAIN}
EMAIL_ADMIN=${ADMIN_EMAIL}

# --- super-admin platform host + first-boot login ---
# The admin host is <SUPER_ADMIN_SUBDOMAIN>.<domain>. The backend, the nginx
# gateway, and the frontend build must all agree — keep the two below equal.
SUPER_ADMIN_SUBDOMAIN=${SUPER_ADMIN_SUBDOMAIN}
VITE_SUPER_ADMIN_SUBDOMAIN=${SUPER_ADMIN_SUBDOMAIN}
# The entrypoint auto-creates this SuperAdmin on first boot. SAVE THE PASSWORD.
DJANGO_SUPERUSER_EMAIL=${ADMIN_EMAIL}
DJANGO_SUPERUSER_PASSWORD=${SUPERUSER_PASSWORD}

# --- backups ---
BACKUP_ENCRYPTION_KEY=${BACKUP_ENCRYPTION_KEY}
BACKUP_SCHEDULE=0 2 * * *
# Off-host push (Phase 3): create backups/rclone.conf, then set these.
RCLONE_REMOTE=
RCLONE_CONFIG=

# --- monitoring (services stay STOPPED until Phase 5, but compose needs the
#     values to parse the file) ---
GLITCHTIP_DOMAIN=glitchtip.${DOMAIN}
GLITCHTIP_DB_USER=glitchtip
GLITCHTIP_DB_PASSWORD=${GLITCHTIP_DB_PASSWORD}
GLITCHTIP_SECRET_KEY=${GLITCHTIP_SECRET_KEY}

# --- frontend build-time (baked into the bundle at 'docker compose build') ---
VITE_APP_NAME=Jasmin
EOF

echo ""
echo "✅ Wrote ${ENV_FILE} (mode 0600) with fresh secrets."
echo ""
echo "┌───────────────────────────────────────────────────────────────────┐"
echo "│  SUPER-ADMIN LOGIN — save this NOW (shown once):                   │"
echo "│    email:    ${ADMIN_EMAIL}"
echo "│    password: ${SUPERUSER_PASSWORD}"
echo "└───────────────────────────────────────────────────────────────────┘"
echo ""
echo "Next: fill the 3 EMAIL_* CHANGE_ME values (your platform SMTP for ops"
echo "alerts), then run scripts/deploy.sh."
