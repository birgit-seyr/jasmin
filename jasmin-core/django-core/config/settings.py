import logging.handlers  # noqa: F401  (registers RotatingFileHandler)
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

# Force the process timezone so log timestamps (which use time.localtime via
# the logging module) are in our local zone instead of UTC.
os.environ.setdefault("TZ", os.environ.get("TIME_ZONE", "Europe/Berlin"))
try:
    time.tzset()
except AttributeError:  # Windows has no tzset
    pass

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-change-in-production")
# Rotation support for ``django.core.signing`` (password-reset + invitation
# links, sessions, CSRF): to rotate, set DJANGO_SECRET_KEY to the NEW key and
# DJANGO_SECRET_KEY_FALLBACK to the previous one — Django verifies existing
# signatures against SECRET_KEY + fallbacks, so rotation no longer instantly
# invalidates every in-flight signed link. (SimpleJWT HS256 signs with
# SIGNING_KEY = SECRET_KEY and does NOT consult fallbacks, so already-issued
# JWTs still re-auth after a rotation — but access tokens live only 15 min.)
SECRET_KEY_FALLBACKS = [
    key for key in (os.environ.get("DJANGO_SECRET_KEY_FALLBACK", "").strip(),) if key
]

# SECURITY WARNING: don't run with debug turned on in production!
# Default OFF (fail safe): a real deploy that forgets to set DEBUG boots
# secure, not insecure. Two dev conveniences preserve the old ergonomics where
# DEBUG is unset: (1) under pytest we default it ON (the suite runs on the dev
# secrets and must skip the prod-only ``if not DEBUG`` boot guards below), and
# (2) ``manage.py`` ``setdefault``s it True for local CLI use. The prod compose
# sets DEBUG=False explicitly regardless, and the serving path (gunicorn) has
# neither pytest nor manage.py in play, so it fails safe.
_UNDER_PYTEST = "pytest" in sys.modules
DEBUG = os.environ.get("DEBUG", "True" if _UNDER_PYTEST else "False").lower() == "true"
RUNNING_IN_DOCKER = os.environ.get("RUNNING_IN_DOCKER", "False").lower() == "true"

# Refuse to boot in production with insecure defaults.
if not DEBUG:
    if SECRET_KEY == "dev-secret-key-change-in-production":
        raise ValueError("DJANGO_SECRET_KEY must be set in production.")
    if os.environ.get("FIELD_ENCRYPTION_KEY", "") in (
        "",
        "HeQ7tkqHP7nVB1hA7VkX0SVIan3y_NUFrjyeDnfzcXk=",
    ):
        raise ValueError(
            "FIELD_ENCRYPTION_KEY must be set in production (and must not be the dev default)."
        )
    # Ops-alert email: ``mail_admins()`` and ``AdminEmailHandler`` send
    # to whatever's in ADMINS. If EMAIL_ADMIN is unset or still points
    # at one of the placeholder domains nobody owns, those alerts go
    # to /dev/null and the team finds out about outages on Twitter.
    _email_admin = os.environ.get("EMAIL_ADMIN", "").strip()
    if _email_admin in ("", "admin@jasmin.coop", "admin@jasmin.example.com"):
        raise ValueError(
            "EMAIL_ADMIN must be set in production to a real ops inbox "
            "(used by mail_admins / AdminEmailHandler for critical alerts)."
        )
    # The alert is only as good as the SMTP transport that carries it.
    # docker-compose passes ``EMAIL_HOST: ${EMAIL_HOST:-}`` (empty-string
    # default), and a set-but-empty value bypasses the ``localhost`` fallback
    # at EMAIL_HOST below — so mail_admins() would connect to loopback and
    # every alert is swallowed by ``fail_silently=True``. Refuse to boot
    # unless a real SMTP host is configured, mirroring the EMAIL_ADMIN guard.
    _email_host = os.environ.get("EMAIL_HOST", "").strip()
    if _email_host in ("", "localhost", "127.0.0.1"):
        raise ValueError(
            "EMAIL_HOST must be set in production to a reachable SMTP host "
            "(mail_admins / AdminEmailHandler alerts connect to it; an empty "
            "or loopback host silently drops every ops alert)."
        )
    # CFG-3: the CORS allow-regex + CSRF trusted origins for the browser auth
    # surface are DERIVED from FRONTEND_DOMAIN. Unset, the tenant-subdomain CORS
    # regex is never built and the app boots with a broken cross-origin auth
    # surface — fail fast instead.
    if not os.environ.get("FRONTEND_DOMAIN", "").strip():
        raise ValueError(
            "FRONTEND_DOMAIN must be set in production (drives the CORS "
            "allow-regex and CSRF trusted origins for the browser auth surface)."
        )
    # CFG-4: defense-in-depth, symmetric with the SECRET_KEY / FIELD_ENCRYPTION
    # _KEY guards above — refuse to boot on the committed dev DB password.
    if os.environ.get("POSTGRES_PASSWORD", "") == "DontForgetMeAgain":
        raise ValueError(
            "POSTGRES_PASSWORD must be set in production (and must not be the "
            "dev default)."
        )

# ---------------------------------------------------------------------------
# Error monitoring — Sentry-protocol SDK, points at self-hosted GlitchTip
# ---------------------------------------------------------------------------
# Initialised here (early, before INSTALLED_APPS) so the Django and
# Logging integrations attach to the right signals. No-op when
# ``SENTRY_DSN`` is unset, which keeps dev runs noise-free until you
# paste a real DSN from the GlitchTip UI.
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.huey import HueyIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    # send_default_pii=False stops Sentry AUTO-attaching user.email / IP, but
    # NOT PII the app put into a log message. INFO/WARNING lines become
    # breadcrumbs on the next ERROR event, beyond the GDPR erasure pipeline —
    # these hooks scrub email/IP substrings (see core/sentry_scrub.py).
    from core.sentry_scrub import (
        before_breadcrumb as _sentry_before_breadcrumb,
    )
    from core.sentry_scrub import (
        before_send as _sentry_before_send,
    )

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            # WARNING-level log lines become Sentry breadcrumbs; ERROR
            # and above become Sentry events. Keeps the noise floor
            # honest without flooding the project.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            # Surface Huey periodic-task crashes as Sentry events with
            # task name + args + traceback (the LoggingIntegration alone
            # would catch the bare exception line but lose the context).
            HueyIntegration(),
        ],
        # 5% perf sampling — cheap baseline; raise once you have a
        # specific endpoint you want to drill into.
        traces_sample_rate=0.05,
        # GDPR: never auto-attach user.email / IP. If you ever decide
        # to attach them deliberately, do it per-event with
        # ``sentry_sdk.set_user(...)`` after consent gating.
        send_default_pii=False,
        before_breadcrumb=_sentry_before_breadcrumb,
        before_send=_sentry_before_send,
        environment="production" if not DEBUG else "development",
    )

# TRANSLATION for pdfs:
USE_I18N = True
USE_L10N = True

# Available languages
LANGUAGES = [
    ("de", "Deutsch"),
    ("en", "English"),
    ("fr", "Français"),
]

# Default language
LANGUAGE_CODE = "de"

# Locale paths
LOCALE_PATHS = [
    os.path.join(BASE_DIR, "locale"),
]


# Security settings - SSL is handled by nginx, not Django
SECURE_SSL_REDIRECT = False  # ← Nginx handles SSL, not Django

# Trust nginx's X-Forwarded-Proto header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Upload size limits — must align with nginx `client_max_body_size`.
# Defaults match the 50 MB ceiling configured in nginx/nginx.conf.template.
# A request exceeding DATA_UPLOAD_MAX_MEMORY_SIZE is rejected before being read
# into memory. FILE_UPLOAD_MAX_MEMORY_SIZE controls when uploads spill to disk.
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.environ.get("DATA_UPLOAD_MAX_MEMORY_SIZE", str(50 * 1024 * 1024))
)
FILE_UPLOAD_MAX_MEMORY_SIZE = int(
    os.environ.get("FILE_UPLOAD_MAX_MEMORY_SIZE", str(50 * 1024 * 1024))
)
# Cap on the number of POST/GET parameters parsed (DoS guard).
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(
    os.environ.get("DATA_UPLOAD_MAX_NUMBER_FIELDS", "1000")
)

if not DEBUG:
    SESSION_COOKIE_SECURE = True  # Only send session cookie over HTTPS
    CSRF_COOKIE_SECURE = True  # Only send CSRF cookie over HTTPS
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = (
        False  # JS needs to read the token; HttpOnly would break the SPA
    )
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    X_FRAME_OPTIONS = "DENY"

    # HSTS — nginx also sets this header; Django sets it as a belt & braces.
    # Start with a low number (e.g. 3600) when first enabling, then raise.
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


# Logging
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        # Injects request.id onto every LogRecord as ``request_id`` so the
        # formatter below can render it. Logs that run outside a request
        # (Huey tasks, management commands) get "-".
        "request_id": {"()": "core.middleware.RequestIdLogFilter"},
    },
    "formatters": {
        "verbose": {
            "format": "{asctime} {request_id} {levelname:8s} {name:20s} {message}",
            "style": "{",
        },
        # When you switch to centralized logs (Loki etc.), swap to JSON:
        # "json": {"()": "pythonjsonlogger.jsonlogger.JsonFormatter",
        #          "format": "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
            "level": "INFO",
        },
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "app.log"),
            "maxBytes": 50 * 1024 * 1024,  # 50 MB per file
            "backupCount": 10,  # keep 10 rotated files
            "formatter": "verbose",
            "filters": ["request_id"],
            "level": "INFO",
        },
        "auth_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "auth.log"),
            "maxBytes": 50 * 1024 * 1024,
            "backupCount": 20,  # keep more for security forensics
            "formatter": "verbose",
            "filters": ["request_id"],
            "level": "INFO",
        },
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "security.log"),
            "maxBytes": 50 * 1024 * 1024,
            "backupCount": 20,
            "formatter": "verbose",
            "filters": ["request_id"],
            "level": "WARNING",
        },
    },
    "loggers": {
        # Security-sensitive
        "authentication": {
            "handlers": ["auth_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "authz": {
            "handlers": ["security_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "super_admin": {
            "handlers": ["auth_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "axes": {
            "handlers": ["security_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        # Business
        "gdpr": {
            "handlers": ["app_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "payments": {
            "handlers": ["app_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "tenants": {
            "handlers": ["app_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "tasks": {
            "handlers": ["app_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        # Catch-all for the service layer: modules log via
        # getLogger(__name__) -> "apps.payments.services",
        # "apps.commissioning.services.*", etc. Without this parent those
        # records fall through to the last-resort handler (INFO dropped, no
        # request_id). More-specific "apps.*" loggers above keep propagate
        # False, so they don't double-log through here.
        "apps": {
            "handlers": ["app_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        # Framework
        "apps.shared.tenants": {
            "handlers": ["app_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "django_tenants": {
            "handlers": ["app_file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["security_file", "console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["app_file", "console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Project-wide DRF exception handler (core.exception_handler).
        # Logs every API error with a consistent format + request_id.
        "jasmin.errors": {
            "handlers": ["app_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Container logging is stdout-only. Python's RotatingFileHandler is not
# multi-process/multi-container safe: in prod the 4 gunicorn workers AND the
# huey container all mount the same ``/app/logs`` volume, so a 50 MB rollover
# in one process renames the active file out from under the others and silently
# drops / truncates lines — including the auth.log / security.log forensics you
# can least afford to lose. Docker already captures the console handler
# (stdout → journald) and the GlitchTip pipeline carries the same records, so
# in any container we route every logger to the console handler only and drop
# the file handlers entirely (an unreferenced FileHandler would still open its
# file at dictConfig time). Bare-metal local dev (no RUNNING_IN_DOCKER) keeps
# the rotating files under ./logs for convenience.
if RUNNING_IN_DOCKER:
    _file_handlers = {"app_file", "auth_file", "security_file"}
    for _handler_name in _file_handlers:
        LOGGING["handlers"].pop(_handler_name, None)
    for _logger in LOGGING["loggers"].values():
        _kept_handlers = [h for h in _logger["handlers"] if h not in _file_handlers]
        if "console" not in _kept_handlers:
            _kept_handlers.append("console")
        _logger["handlers"] = _kept_handlers

# EMAIL SETTINGS
ADMINS = [("Admin", os.environ.get("EMAIL_ADMIN", "admin@jasmin.coop"))]
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@jasmin.coop")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", "admin@jasmin.coop")
# Cap how long an SMTP connect/send may block so a slow/unreachable
# (possibly malicious) host can't hang a worker indefinitely. Applies to
# the platform default backend and is passed explicitly when building a
# per-tenant connection.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", 10))
# Allow tenant-supplied SMTP hosts that resolve to private / loopback /
# link-local addresses. Defaults to DEBUG so local dev (MailHog /
# localhost) and tests work; production (DEBUG=False) blocks them as an
# SSRF guard. Set to "true" only to support a legitimate internal relay.
SMTP_ALLOW_PRIVATE_HOSTS = (
    os.environ.get("SMTP_ALLOW_PRIVATE_HOSTS", str(DEBUG)).lower() == "true"
)

# Field-level encryption key (Fernet, for EncryptedCharField columns).
# The fallback is a DEV-ONLY key: it must be a *valid* Fernet key (an
# obvious "CHANGE_ME" placeholder would crash at import) and it must
# stay stable — existing dev databases hold ciphertext encrypted with
# it. Production refuses to boot on this value (guard at the top of
# this file), so the fallback can never silently reach prod.
FIELD_ENCRYPTION_KEY = [
    os.environ.get(
        "FIELD_ENCRYPTION_KEY", "HeQ7tkqHP7nVB1hA7VkX0SVIan3y_NUFrjyeDnfzcXk="
    )
]

# Platform / super-admin domain configuration. Reads the SAME env name the
# rest of the stack uses (docker-compose, nginx, .env.example, and the
# frontend's VITE_SUPER_ADMIN_SUBDOMAIN) so there is one name for one concept.
# Feeds only the localhost ALLOWED_HOSTS default below — prod overrides the
# whole list via DJANGO_ALLOWED_HOSTS.
SUPER_ADMIN_SUBDOMAIN = os.environ.get(
    "SUPER_ADMIN_SUBDOMAIN", "marillen"
)  # Default: marillen.localhost

# ALLOWED HOSTS - Dynamic for multi-tenant
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS",
    f".localhost,localhost,127.0.0.1,backend,{SUPER_ADMIN_SUBDOMAIN}.localhost",
).split(",")

# CORS settings - Dynamic for multi-tenant
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["Authorization"]

# In development, be permissive — but NOT a wildcard, because cookies
# (HttpOnly refresh tokens) require an explicit origin in
# Access-Control-Allow-Origin together with Allow-Credentials: true.
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    # Allow any *.localhost subdomain (tenant1.localhost, admin.localhost, …)
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^http://([a-z0-9-]+\.)?localhost(:\d+)?$",
        r"^http://([a-z0-9-]+\.)?127\.0\.0\.1(:\d+)?$",
    ]
else:
    # Production - strict CORS, with wildcard support for tenant subdomains.
    CORS_ALLOW_ALL_ORIGINS = False
    cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    if cors_origins:
        CORS_ALLOWED_ORIGINS = [origin.strip() for origin in cors_origins.split(",")]
    else:
        CORS_ALLOWED_ORIGINS = []

    # Allow https://<anything>.<FRONTEND_DOMAIN> (tenant subdomains).
    # CFG-3: define the regex list UNCONDITIONALLY so a prod branch with
    # FRONTEND_DOMAIN unset has an explicit (empty) value rather than leaving
    # the setting undefined.
    CORS_ALLOWED_ORIGIN_REGEXES = []
    _frontend_domain = os.environ.get("FRONTEND_DOMAIN", "").strip()
    if _frontend_domain:
        import re as _re

        _escaped = _re.escape(_frontend_domain)
        CORS_ALLOWED_ORIGIN_REGEXES = [
            rf"^https://([a-z0-9-]+\.)?{_escaped}$",
        ]
        # CSRF must trust the same origins (Django 4+ requires scheme).
        CSRF_TRUSTED_ORIGINS = [
            f"https://{_frontend_domain}",
            f"https://*.{_frontend_domain}",
        ]
    else:
        CSRF_TRUSTED_ORIGINS = []

    # Optional extra CSRF origins via env (comma-separated), APPENDED to the
    # FRONTEND_DOMAIN-derived ones above — never overwriting. A prod deploy
    # that doesn't set CSRF_TRUSTED_ORIGINS must keep trusting the derived
    # origins, not silently collapse to an empty list.
    CSRF_TRUSTED_ORIGINS += [
        origin.strip()
        for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
        if origin.strip()
    ]

# NOTE: no "x-tenant" header — the tenant is resolved from the subdomain
# (TenantMainMiddleware); a client-sent tenant header was never read.
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-requested-with",
]

if DEBUG:
    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
# In production CSRF_TRUSTED_ORIGINS is derived from FRONTEND_DOMAIN (plus any
# CSRF_TRUSTED_ORIGINS env extras) in the CORS block above. Do NOT re-read the
# env var here — an unconditional read would overwrite that derived value with
# an empty list whenever the (optional) env var is unset.


# Apps
SHARED_APPS = [
    "corsheaders",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    # Registers the ``run_huey`` management command (the background-task
    # consumer used by the docker ``huey`` service and ``make huey``). The
    # ``@db_task`` / ``@db_periodic_task`` decorators read ``settings.HUEY``
    # regardless, but WITHOUT this app the consumer command is undiscoverable
    # ("Unknown command: run_huey") and deferred tasks (e.g. the Forecast
    # recompute) never run. Schema-agnostic infra with no models → SHARED_APPS.
    "huey.contrib.djhuey",
    "django_tenants",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # NOTE: ``auditlog`` is in TENANT_APPS only. We tried adding it to
    # SHARED_APPS too so Tenant + TenantSettings could be audited, but
    # auditlog.LogEntry has a hard FK to ``settings.AUTH_USER_MODEL``
    # (= accounts.JasminUser, tenant-scoped) — creating the table in
    # the public schema fails with "relation accounts_jasminuser does
    # not exist". A single global AUTH_USER_MODEL can't point at both
    # JasminUser (tenant) and SuperAdmin (public), so this gap can't be
    # closed without forking django-auditlog or building a parallel
    # audit table. Tenant lifecycle is covered by event-log lines
    # written to auth.log by ``apps.shared.tenants.apps.TenantsConfig``.
    "apps.shared.tenants",
    "apps.shared.super_admin",
    # Support tickets: a PUBLIC-schema table so the super-admin can aggregate
    # every tenant's tickets (see apps/shared/support/models.py).
    "apps.shared.support",
]

TENANT_APPS = [
    "django.contrib.auth",
    # simplejwt + token_blacklist live in TENANT_APPS because token_blacklist
    # has a FK to AUTH_USER_MODEL (accounts.JasminUser), which is tenant-scoped.
    # Super-admin endpoints therefore must NOT call .blacklist() / verify
    # against the blacklist (no tenant schema -> no table). See
    # apps/shared/super_admin/views.py.
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "axes",
    "auditlog",
    # Two-factor auth. ``django_otp`` is in TENANT_APPS because the OTP
    # device tables have a FK to AUTH_USER_MODEL (JasminUser) which is
    # tenant-scoped. Super-admin users (public schema) are NOT covered
    # by TOTP — instead the super-admin host is locked down by an IP
    # allowlist enforced AT THE NGINX GATEWAY (a dedicated server block
    # in nginx/nginx.conf.template that includes
    # nginx/super_admin_allowed_ips.conf, terminating in ``deny all;``).
    # The ``gateway`` CI job (scripts/verify_super_admin_allowlist.sh)
    # asserts the block + allowlist stay wired so this exemption can't
    # silently become single-factor-password-only. As app-layer
    # defense-in-depth, ``SuperAdminIPAllowlistMiddleware`` enforces the
    # SAME allowlist inside Django over the ``/api/super-admin/`` path
    # prefix when ``SUPER_ADMIN_ALLOWED_IPS`` is set (see that setting
    # below), so the control no longer depends on nginx host routing alone.
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "apps.authz",
    "apps.accounts",
    "apps.commissioning",
    "apps.cultivation",
    "apps.economics",
    "apps.gdpr",
    "apps.notifications",
    "apps.payments",
    "apps.staff",
]

INSTALLED_APPS = SHARED_APPS + TENANT_APPS

AUTH_USER_MODEL = "accounts.JasminUser"
TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.Domain"

MIDDLEWARE = [
    # Liveness probe short-circuit. MUST be above TenantMainMiddleware: the
    # Docker / gateway / uptime healthchecks hit /health/ on hosts that map to
    # no tenant (localhost, 127.0.0.1, the upstream name), which the tenant
    # middleware would 404 before any view runs. Answers /health/ with 200
    # without tenant/DB resolution.
    "core.middleware.HealthCheckMiddleware",
    # Stamps Cache-Control: no-store on every /api/ response so a shared CDN
    # (Bunny) can never cache + cross-serve a per-tenant API response. Near the
    # top so it wraps the final response regardless of what any view sets.
    "core.middleware.ApiNoStoreCacheControlMiddleware",
    # Must be near the top: assigns request.id and exposes it via contextvars
    # so every downstream middleware, view, and log line can correlate.
    "core.middleware.RequestIdMiddleware",
    # App-layer IP allowlist for /api/super-admin/ — defense-in-depth mirror of
    # the nginx gateway allowlist, so the platform-root API can't be reached
    # off-allowlist via a host-routing gap. No-op unless SUPER_ADMIN_ALLOWED_IPS
    # is set. Before TenantMainMiddleware so a blocked request is denied early,
    # without tenant/schema resolution.
    "apps.shared.super_admin.middleware.SuperAdminIPAllowlistMiddleware",
    "django_tenants.middleware.main.TenantMainMiddleware",
    # Dev-only N+1 surfacer — see QUERYCOUNT config below. Inserted right
    # after the tenant middleware so it counts queries in the correct
    # schema. No-op in production (DEBUG=False).
    *(["querycount.middleware.QueryCountMiddleware"] if DEBUG else []),
    "corsheaders.middleware.CorsMiddleware",
    # Operator kill-switch: 403 every request against a tenant whose
    # ``is_active`` is False. After CorsMiddleware so the 403 keeps its
    # CORS headers; after TenantMainMiddleware so ``request.tenant`` + the
    # schema are resolved. Never gates the public/platform schema.
    "apps.shared.tenants.middleware.TenantActiveMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # django-auditlog: captures the acting user on each request so model
    # changes are attributed to a real user, not "system".
    "auditlog.middleware.AuditlogMiddleware",
    # django-axes must be LAST so it sees the resolved request.user.
    "axes.middleware.AxesMiddleware",
]

# ──────────────────────────────────────────────────────────────────────
# django-querycount — DEV ONLY
# ──────────────────────────────────────────────────────────────────────
# Prints a per-request line to the runserver console:
#   |GET     /api/commissioning/invoices/        |  42 queries, 18 dup |
# When duplicate-query count exceeds ``DISPLAY_DUPLICATES``, it also
# dumps the top-N most-duplicated SQL statements — which is the canonical
# N+1 fingerprint. The lock-tests in
# ``apps/payments/tests/test_query_count_locks.py`` own regression
# prevention; this middleware is the "spot it while you're writing the
# feature" complement.
#
# THRESHOLDS:
#   MEDIUM/HIGH  – colour thresholds for the printed count. Pick numbers
#                  matching your hot-page baseline so non-suspicious
#                  pages don't trigger.
#   MIN_QUERY_COUNT_TO_LOG = 1 – log every request, even quiet ones
#                  (set higher to mute static-asset / auth-refresh noise).
# Tuned for this codebase based on observed values in
# ``test_query_count_locks.py``:
#   members/      ~25 queries
#   abos/         ~30
#   share_delivery ~28
#   invoices/     ~16-20 (post-fix)
# So MEDIUM=50 is well above normal but well below the hard ceiling
# (HARD_CEILING=80 in the lock tests).
if DEBUG:
    QUERYCOUNT = {
        "THRESHOLDS": {
            "MEDIUM": 50,
            "HIGH": 200,
            # ``django-querycount``'s middleware reads BOTH thresholds
            # unconditionally — omitting either raises KeyError on every
            # response. ``MIN_TIME_TO_LOG=0`` means "log regardless of
            # request duration" (we filter by query count, not by time).
            "MIN_TIME_TO_LOG": 0,
            # Mute requests below this count. A bare authenticated request
            # already costs ~8-12 queries from django-tenants' schema
            # resolution + JWT auth + the tenant/user lookups, so a
            # threshold of 15 silences those baseline hits and only logs
            # endpoints actually doing real work. A real N+1 jumps well
            # above 15 fast, so detection sensitivity isn't lost.
            "MIN_QUERY_COUNT_TO_LOG": 15,
        },
        # Ignore noisy paths that wouldn't surface real N+1s.
        "IGNORE_REQUEST_PATTERNS": [
            r"^/static/",
            r"^/media/",
            r"^/api/auth/refresh/?$",
        ],
        "IGNORE_SQL_PATTERNS": [
            # auditlog's own writes
            r"INSERT INTO .auditlog_logentry",
            # django-tenants' schema-switching tax. Each cross-schema
            # access (e.g. read Tenant from public → read JasminUser from
            # tenant schema → write back to public) flips the path. Fires
            # 4-6 times per request and would otherwise dominate the
            # ``Duplicates`` counter — masking real app-level repetition.
            r"^SET search_path",
        ],
        # Top-N most-duplicated SQL statements printed for any request
        # whose duplicate count exceeds this number.
        "DISPLAY_DUPLICATES": 5,
        # Adds ``X-DjangoQueryCount-Count: <n>`` so a browser dev-tools
        # tab or curl -I shows the count per response without scraping
        # the server log.
        "RESPONSE_HEADER": "X-DjangoQueryCount-Count",
    }

PUBLIC_SCHEMA_NAME = "public"
PUBLIC_SCHEMA_URLCONF = "config.public_urls"
ROOT_URLCONF = "config.tenant_urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTHENTICATION_BACKENDS = [
    # django-axes must be FIRST so it can intercept failed logins.
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.EmailOrUsernameModelBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# django-axes — account-level lockout against credential stuffing.
AXES_ENABLED = not DEBUG  # Don't get locked out during development.
AXES_FAILURE_LIMIT = 5  # Lock after 5 failed attempts.
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = [
    ["username", "ip_address"]
]  # Lock the (user, ip) pair, not the whole IP.
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_CALLABLE = None  # Default 403 response.
AXES_VERBOSE = True
# Exactly one trusted proxy hop today: the gateway nginx (no CDN in the
# stack). It appends the real client IP to X-Forwarded-For, so we trust the
# last entry. If a CDN is ever added in front of the gateway, bump
# TRUSTED_PROXY_COUNT to match the number of trusted hops. Single source of
# truth for the proxy depth — django-axes, DRF's NUM_PROXIES, and
# ``apps.shared.request_utils.client_ip`` all read it so throttle/lockout
# keying and the recorded forensic/consent IP stay in sync.
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "1"))
# django-ipware is NOT a dependency, so axes' ``AXES_IPWARE_*`` settings were
# inert and axes silently fell back to ``REMOTE_ADDR`` (= the gateway proxy IP),
# attributing every lockout to the proxy instead of the real client. Point axes
# at the same proxy-aware helper the rest of the stack uses (it honors
# ``TRUSTED_PROXY_COUNT`` / X-Forwarded-For) so throttle + lockout keying match
# the recorded forensic IP. axes calls this with a single ``request`` arg (see
# ``axes.helpers.get_client_ip_address``), which ``client_ip`` accepts.
AXES_CLIENT_IP_CALLABLE = "apps.shared.request_utils.client_ip"

# ---- Super-admin IP allowlist (app-layer defense-in-depth) ----------------
# The nginx gateway restricts the super-admin HOST to an IP allowlist (see the
# django_otp note above + scripts/verify_super_admin_allowlist.sh). That is the
# primary control, but it depends on host routing staying correct — a routing
# gap (e.g. the apex domain resolving to the public schema) could expose the
# platform-root API off-allowlist. ``SuperAdminIPAllowlistMiddleware`` enforces
# the SAME allowlist inside Django over the ``/api/super-admin/`` path prefix so
# it can't be bypassed by host routing, using the same trusted client IP
# (``TRUSTED_PROXY_COUNT``) as throttle/lockout keying.
#
# Comma-separated IPs / CIDRs (v4 or v6), e.g.
#   SUPER_ADMIN_ALLOWED_IPS="203.0.113.42,198.51.100.0/29,2001:db8::/64"
# UNSET / empty -> middleware is a no-op (dev, and deployments relying solely on
# the nginx allowlist, keep working). Keep this in sync with
# nginx/super_admin_allowed_ips.conf when set.
SUPER_ADMIN_ALLOWED_IPS = [
    entry.strip()
    for entry in os.environ.get("SUPER_ADMIN_ALLOWED_IPS", "").split(",")
    if entry.strip()
]

# Per-account brute-force lockout for the super-admin login. The super-admin
# authenticates via ``check_password`` OUTSIDE django-axes, and the
# ``super_admin_login`` throttle caps attempts only PER IP (10/hour) — a
# distributed / rotating-IP attacker sidesteps it. After
# ``SUPER_ADMIN_LOGIN_MAX_FAILURES`` failed attempts on an account it is refused
# for ``SUPER_ADMIN_LOGIN_LOCKOUT_SECONDS``, regardless of source IP. Backed by
# the shared cache (see CACHES, Redis in prod); state auto-expires via TTL, so a
# genuine lockout self-heals after the window with no ops intervention.
SUPER_ADMIN_LOGIN_MAX_FAILURES = int(
    os.environ.get("SUPER_ADMIN_LOGIN_MAX_FAILURES", "5")
)
SUPER_ADMIN_LOGIN_LOCKOUT_SECONDS = int(
    os.environ.get("SUPER_ADMIN_LOGIN_LOCKOUT_SECONDS", str(15 * 60))
)

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.authz.authentication.TenantBoundJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        # Tenant-aware: namespaces each scope's cache bucket by schema so a
        # shared egress IP can't burn one tenant's login/register limit and 429
        # another tenant's users (see core/throttling.py).
        "core.throttling.TenantScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Anti-enumeration / anti-flood for the password reset endpoints.
        "password_reset": "5/hour",
        # Anti-flood for the public self-registration endpoint. Bots
        # filling the pending-approval queue create DB rows + can
        # trigger welcome mail to victims via email-spoofed signups.
        # 10/hour per client IP is generous for real signups (which
        # spike rarely, e.g. when a new season opens) and cheap for
        # the office to bump if a real campaign is running.
        "register": "10/hour",
        # Login: anti-credential-stuffing. django-axes locks individual
        # accounts after N failures, but doesn't slow an attacker
        # iterating a list of emails (each is a single attempt per
        # account). 20/minute per IP throttles the iteration loop
        # itself without blocking a human typing their own password.
        "login": "20/minute",
        # GDPR Art. 17 request lodging — each request sends mail to
        # ``user.email``. A stolen JWT (or a malicious office account)
        # can spam the linked inbox by re-lodging on a loop.
        # ScopedRateThrottle keys on user pk when authenticated.
        "gdpr_request_deletion": "5/hour",
        # GDPR token-confirm endpoint is ``AllowAny`` so an attacker
        # can grind UUIDs. Hit-rate is astronomically low, but free
        # for them — slow the iteration regardless. Keyed by IP.
        "gdpr_confirm_deletion": "10/minute",
        # SAR (Art. 15 bundle) is DB-expensive — joins across member,
        # coop_shares, subscriptions, invoices, email_log, login_history.
        # Keyed PER AUTHENTICATED USER, so a caller can only ever fetch their
        # OWN bundle — one user pulling their own data isn't a meaningful DoS.
        # NOTE: the "My data" profile tab fetches this bundle on every open (for
        # the consents read-out + the "Export as JSON" payload), so the old
        # 2/hour locked the tab out after a couple of opens. 30/hour matches
        # normal tab usage while still capping a runaway client.
        "gdpr_sar_export": "30/hour",
        # Test-send in the email-template editor sends a real mail.
        # A compromised office account could use it as a spam relay.
        # 5/minute matches "I'm iterating on the wording" cadence.
        "email_test_send": "5/minute",
        # Invitation verify/accept are ``AllowAny`` and hit the DB with
        # a caller-supplied token. Tokens are uuid4 (122 bits, not
        # guessable), so this is anti-flood / anti-grind rather than
        # anti-enumeration — keyed by IP. Generous for a real invitee
        # (one verify on page load, one accept).
        "invitation": "20/minute",
        # Support tickets: an authenticated/stolen staff token could loop
        # create → flood the public table AND email-bomb the platform admin
        # over live SMTP (create fires mail_admins). Reply is cheaper but still
        # capped. Keyed per authenticated user (nanoid), namespaced by schema.
        "support_ticket_create": "10/hour",
        "support_ticket_reply": "30/hour",
        # Tenant-detection bootstrap (``CurrentTenantView``) is ``AllowAny`` and
        # fires once on SPA load / refresh. Anti-flood only, keyed by IP;
        # generous since many users behind one shared egress IP all bootstrap.
        "current_tenant": "60/minute",
        # Super-admin login + step-up re-confirm. These authenticate via
        # ``SuperAdmin.check_password`` directly, NOT Django's
        # ``authenticate()``, so django-axes (which only hooks
        # ``authenticate()``) never counts the failures. The super-admin is
        # the highest-privilege principal on the platform; without an
        # app-layer cap the only brute-force control is the nginx IP
        # allowlist. Strict — login keys by IP, step-up by the super-admin
        # pk. Treat the IP allowlist as defense-in-depth, not the sole gate.
        "super_admin_login": "10/hour",
        # Tenant step-up password re-confirm. Previously shared the generous
        # ``login`` bucket (20/min); a valid low-privilege token could grind
        # the password at that ceiling to mint a sudo-mode token. Tighter
        # per-user rate here PLUS the step-up view now feeds django-axes so
        # repeated wrong passwords lock the (username, ip) pair.
        "step_up": "10/minute",
    },
    # Exactly one trusted proxy in front of Django: the gateway nginx, which
    # APPENDS the real client IP to any client-supplied X-Forwarded-For
    # (``$proxy_add_x_forwarded_for``). Without this, DRF's ``get_ident()``
    # keys throttles on the ENTIRE XFF string, so an attacker who prepends a
    # per-request-varying forged XFF gets a fresh throttle bucket every
    # request — a full bypass of the scoped rate limits below. NUM_PROXIES=1
    # makes DRF read only the last (gateway-appended) entry, i.e. the true
    # client IP. Driven by the same TRUSTED_PROXY_COUNT as
    # AXES_IPWARE_PROXY_COUNT above so both stay in sync (e.g. when a CDN is
    # added in front of the gateway).
    "NUM_PROXIES": TRUSTED_PROXY_COUNT,
    # Single project-wide exception handler. Translates every exception that
    # escapes a view into the canonical {code, message, field, details,
    # request_id} response. See core/exception_handler.py for the contract.
    "EXCEPTION_HANDLER": "core.exception_handler.jasmin_exception_handler",
}

# Password reset links expire after 1 hour. Django's default is 3 days,
# which is too long for a recovery link.
PASSWORD_RESET_TIMEOUT = 60 * 60

# Two-factor auth (TOTP) — challenge token lifetime between password
# success and code submission. Short enough that a stolen challenge is
# useless, long enough for a human to fish their phone out of a pocket.
TWO_FACTOR_CHALLENGE_LIFETIME = timedelta(minutes=5)
# Enrolment token lifetime: issued on the role-mandated-enrolment login path
# so a user with no session yet can reach enroll-start + enroll-confirm. Longer
# than the challenge window because it must cover scanning the QR, switching to
# the authenticator app, and submitting the first code (two requests).
TWO_FACTOR_ENROLMENT_LIFETIME = timedelta(minutes=15)
# Roles that MUST enrol 2FA before a JWT is issued. Empty = opt-in for
# everyone; flip to e.g. ["admin"] once the office has all enrolled.
# Super-admin (public schema) is not eligible for this gate — its host is
# instead IP-restricted at the nginx gateway (see the django_otp note in
# TENANT_APPS and nginx/super_admin_allowed_ips.conf). That allowlist is
# the ONLY thing standing in for 2FA on super-admin, so it is not optional
# infra — the ``gateway`` CI job verifies it.
TWO_FACTOR_REQUIRED_ROLES: list[str] = []

# Friendly Captcha — bot / abuse protection on public auth endpoints
# (login, register, password-reset-request, password-reset-confirm).
# Ships dormant: when ``FRIENDLY_CAPTCHA_ENABLED=False`` the verifier
# is a no-op and the endpoints accept requests with no FC solution
# token. To turn it on:
#   1. Sign the Friendly Captcha DPA, create a Site, get sitekey + secret.
#   2. Set ``FRIENDLY_CAPTCHA_SITEKEY`` and ``FRIENDLY_CAPTCHA_SECRET``
#      in the prod env.
#   3. Flip ``FRIENDLY_CAPTCHA_ENABLED=True``.
# The sitekey is a PUBLIC value and is shipped to anonymous callers
# via ``CurrentTenantSerializer``; the secret is server-side only.
FRIENDLY_CAPTCHA_ENABLED = (
    os.environ.get("FRIENDLY_CAPTCHA_ENABLED", "False").lower() == "true"
)
FRIENDLY_CAPTCHA_SITEKEY = os.environ.get("FRIENDLY_CAPTCHA_SITEKEY", "").strip()
FRIENDLY_CAPTCHA_SECRET = os.environ.get("FRIENDLY_CAPTCHA_SECRET", "").strip()
# Verification API. Documented at https://docs.friendlycaptcha.com/.
# Configurable so we can point at the EU endpoint if FC ever exposes
# a regional split (today it's a single global endpoint).
FRIENDLY_CAPTCHA_VERIFY_URL = os.environ.get(
    "FRIENDLY_CAPTCHA_VERIFY_URL",
    "https://api.friendlycaptcha.com/api/v1/siteverify",
)
# Hard timeout for the verification call. If FC's API is unreachable
# within this window the verifier raises ``CaptchaVerificationFailed``
# (fail-CLOSED). Flip to fail-open only if you're willing to accept
# unverified submissions during an FC outage.
FRIENDLY_CAPTCHA_TIMEOUT_SECONDS = float(
    os.environ.get("FRIENDLY_CAPTCHA_TIMEOUT_SECONDS", "5.0")
)

# Step-up authentication — short-lived "sudo mode" on irreversible
# endpoints (GDPR approve-deletion, super-admin role grant, backup
# trigger). The frontend pops a password modal, calls
# ``/api/auth/step-up/``, receives a new access token carrying
# ``step_up_verified_at``, and retries the original request. The
# permission class ``apps.accounts.permissions.RequiresStepUp`` raises
# ``StepUpRequired`` when the claim is missing or older than the TTL.
STEP_UP_TTL_SECONDS = int(os.environ.get("STEP_UP_TTL_SECONDS", "300"))
# When True, the step-up endpoint requires a fresh TOTP code on top
# of the password. Flip this once TOTP MFA is rolled out and you
# want the strongest gate on destructive actions. Until then, password
# re-confirmation is the bar.
STEP_UP_REQUIRES_TOTP = (
    os.environ.get("STEP_UP_REQUIRES_TOTP", "False").lower() == "true"
)

# JWT Settings
SIMPLE_JWT = {
    # Short access token = small blast radius if a token is leaked.
    # Refresh token rotates on every refresh and old ones are blacklisted.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": str(SECRET_KEY),
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    "JWK_URL": None,
    "LEEWAY": 0,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "TOKEN_USER_CLASS": "rest_framework_simplejwt.models.TokenUser",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=15),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=7),
}

WSGI_APPLICATION = "config.wsgi.application"


# Helper function: Required in production, optional in development
def get_env(var_name, default=None, required_in_production=False):
    """
    Get environment variable with smart defaults:
    - Development: Uses fallback if not set
    - Production: Raises error if required var is missing
    """
    value = os.environ.get(var_name)

    # Reuse the module-level DEBUG (which already defaults to production-safe
    # False when DEBUG is unset outside pytest). Recomputing here with a
    # DIFFERENT default ("True") would make a deploy that forgets to set DEBUG
    # boot in production (module DEBUG=False) yet silently skip the
    # required-in-production variable checks.
    is_production = not DEBUG

    if value is None:
        if required_in_production and is_production:
            raise ValueError(
                f"❌ PRODUCTION ERROR: Required environment variable '{var_name}' is not set!\n"
                f"   Add it to your .env file before deploying."
            )
        return default

    return value


# Database - Safe fallbacks for development, strict in production
_DB_STATEMENT_TIMEOUT_MS = get_env("DB_STATEMENT_TIMEOUT_MS", default="30000")

DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": get_env("POSTGRES_DB", default="jasmin", required_in_production=True),
        "USER": get_env("POSTGRES_USER", default="jasmin", required_in_production=True),
        "PASSWORD": get_env(
            "POSTGRES_PASSWORD",
            default="DontForgetMeAgain",
            required_in_production=True,
        ),
        "HOST": get_env("POSTGRES_HOST", default="localhost"),
        "PORT": get_env("POSTGRES_PORT", default="5432"),
        # Cheap stale-connection health check. It's a no-op while
        # CONN_MAX_AGE=0 (the default we keep — persistent connections +
        # django-tenants schema switching are a known foot-gun); it only
        # matters if CONN_MAX_AGE is ever raised.
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": 10,
            # Per-STATEMENT timeout so one pathological query can't pin a
            # gunicorn gthread worker for the full request timeout. Being
            # per-statement, it doesn't bite fast migrations at current scale;
            # raise it (or set 0 to disable) via DB_STATEMENT_TIMEOUT_MS for a
            # slow migration deploy.
            "options": f"-c statement_timeout={_DB_STATEMENT_TIMEOUT_MS}",
        },
    }
}


DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        # 12 = the modern audit floor (NIST 800-63B, BSI TR-02102,
        # ANSSI guidance). Auditors check the literal number, even
        # though the zxcvbn validator below does the actual work.
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    # zxcvbn = real entropy-based strength check. Score 0-4; we require >= 3
    # (configured via the package-wide ``PASSWORD_MINIMAL_STRENGTH`` setting
    # below — this validator does not accept per-instance OPTIONS).
    {
        "NAME": "django_zxcvbn_password_validator.ZxcvbnPasswordValidator",
    },
]

PASSWORD_MINIMAL_STRENGTH = 3

# Internationalization
TIME_ZONE = os.environ.get("TIME_ZONE", "Europe/Berlin")
USE_TZ = True

# Static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Tenant-specific media: files stored under media/<schema_name>/.
# The storage subclass signs every ``.url()`` with a time-limited
# capability token; ``core.protected_media.protected_media_view``
# validates it before nginx (X-Accel-Redirect) serves the file.
STORAGES = {
    "default": {
        "BACKEND": "core.protected_media.SignedTenantFileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"
# How long a signed media URL stays valid. Generous on purpose: the
# frontend refetches API payloads (and thereby fresh URLs) on every
# mount, so this only bounds how long a leaked/shared link works.
MEDIA_URL_SIGNATURE_MAX_AGE = int(
    os.environ.get("MEDIA_URL_SIGNATURE_MAX_AGE", str(60 * 60 * 24))
)
# Time-bucket size (seconds) for the signed media token. The token embeds a
# bucket number instead of an exact timestamp, so the emitted ``?st=`` URL is
# stable for this window — letting the browser cache repeat-viewed images/PDFs
# instead of re-downloading them on every refetch (see core/protected_media.py).
# Kept well below MEDIA_URL_SIGNATURE_MAX_AGE so it doesn't meaningfully widen
# the leaked-link validity window (1 h bucket vs 24 h max-age).
MEDIA_URL_SIGNATURE_BUCKET = int(
    os.environ.get("MEDIA_URL_SIGNATURE_BUCKET", str(60 * 60))
)

# Filesystem location of the pg_dump backup files. Read by the
# ``prune_old_backups`` Huey task in apps/shared/tenants/tasks.py.
# Default ``/backups`` matches the path inside the prod container as
# mounted by docker-compose.yml; override via environment for dev/tests.
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/backups")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# TASK SCHEDULER
# Production / docker-compose: RedisHuey backed by the ``redis`` service
# (``REDIS_URL=redis://:<password>@redis:6379/0`` is set in docker-compose;
# the server runs with ``--requirepass``). Redis has ``--appendonly yes``
# + a named volume, so pending tasks survive container restarts.
# Local dev without redis (and CI): fall back to SqliteHuey so the
# import-time decorators don't crash on missing connectivity.
_REDIS_URL = os.environ.get("REDIS_URL", "").strip()
# Consumer threads — bump above 1 so a long bulk-email job doesn't starve the
# */15 security-alert periodic tasks. Django DB connections are thread-local,
# so the extra worker threads don't share a connection. Env-tunable.
_HUEY_WORKERS = int(get_env("HUEY_WORKERS", default="4"))
# Run tasks INLINE (no separate consumer) only in the no-Docker local dev flow
# — DEBUG on, no Redis broker, and NOT under pytest. Without this, a `make
# runserver` dev who forgets `make huey` enqueues to the Sqlite broker and the
# task never runs (forecasts silently don't rebuild). Excluded from pytest
# (which also runs DEBUG=on / no-Redis) so tests keep the real async semantics
# they assert on; Docker dev has Redis so it runs the `huey` compose service;
# prod is DEBUG=off. ``immediate`` executes the task synchronously at enqueue
# (and, for on_commit-deferred tasks, right after the commit fires).
_HUEY_IMMEDIATE = DEBUG and not _REDIS_URL and "pytest" not in sys.modules
if _REDIS_URL:
    HUEY = {
        "huey_class": "huey.RedisHuey",
        "name": "jasmin-huey",
        "url": _REDIS_URL,
        # Fire-and-forget tasks: every task returns None and no call site reads
        # the Result handle, so storing results just leaks a never-read,
        # never-expiring entry per invocation into the Redis result hash.
        "results": False,
        "store_none": False,
        "immediate": _HUEY_IMMEDIATE,
        # Match crontabs against local time (TIME_ZONE = Europe/Berlin), which is
        # what every periodic-task docstring and schedule-ordering rationale
        # assumes. With utc=True huey matched against UTC, firing every job 1-2h
        # later local than documented.
        "utc": False,
        "consumer": {
            "workers": _HUEY_WORKERS,
            "worker_type": "thread",
            "initial_delay": 0.1,
            "backoff": 1.15,
            "max_delay": 10.0,
            "scheduler_interval": 1,
            "periodic": True,
            "check_worker_health": True,
            "health_check_interval": 1,
        },
    }
else:
    HUEY = {
        "huey_class": "huey.SqliteHuey",
        "name": "huey.sqlite",
        "results": False,
        "store_none": False,
        "immediate": _HUEY_IMMEDIATE,
        "utc": False,
        "consumer": {
            "workers": _HUEY_WORKERS,
            "worker_type": "thread",
            "initial_delay": 0.1,
            "backoff": 1.15,
            "max_delay": 10.0,
            "scheduler_interval": 1,
            "periodic": True,
            "check_worker_health": True,
            "health_check_interval": 1,
        },
    }


# CACHE BACKEND
# Same dual-backend pattern as HUEY above: Redis in docker-compose/prod
# (consistent across every gunicorn worker, survives restarts on the
# appendonly volume), LocMem fallback for local dev / CI without redis.
# Without this, Django falls back to the per-process LocMemCache default
# — cache.set() in one gunicorn worker isn't visible to other workers
# or the Huey container, so invalidation hooks become best-effort.
if _REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _REDIS_URL,
            # Distinct key prefix so cache entries can't collide with
            # Huey's own redis keys (Huey uses its own namespacing too,
            # but explicit prefixing makes a future cache.clear() safe).
            "KEY_PREFIX": "jasmin-cache",
        }
    }
elif DEBUG:
    # Local dev / CI without redis: a single runserver / pytest process, so
    # the per-process LocMemCache is fine (nothing to share across workers).
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    # Prod (DEBUG=False) MUST have a shared cache: throttle counters and cache
    # invalidation are shared across gunicorn workers + the Huey container.
    # Falling through to the implicit per-process LocMemCache would give each
    # worker its own rate-limit tally (N workers ⇒ ~N× the configured limit)
    # and make invalidation hooks best-effort. Mirror the SECRET_KEY / FIELD_*
    # boot-guards above and refuse to start misconfigured.
    raise ValueError(
        "REDIS_URL must be set when DEBUG=False — it backs the shared cache and "
        "throttle counters across gunicorn workers."
    )


# DRF Spectacular
SPECTACULAR_SETTINGS = {
    "TITLE": "Jasmin Platform API",
    "DESCRIPTION": "CSA Management Platform API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # THE KEY SETTING - Don't split request/response into separate schemas
    "COMPONENT_SPLIT_REQUEST": False,
    "COMPONENT_SPLIT_PATCH": False,
    # Map your enum classes to prevent duplicates
    "ENUM_NAME_OVERRIDES": {
        "MovementTypeEnum": "apps.commissioning.models.choices.MovementTypeOptions",
        "CultivationOriginEnum": "apps.commissioning.models.choices.CultivationOriginOptions",
        "DeliveryCycleEnum": "apps.commissioning.models.choices.DeliveryCycleOptions",
        "ShareTypeVariationSizeEnum": "apps.commissioning.models.choices.ShareTypeVariationSizeOptions",
        "UnitEnum": "apps.commissioning.models.choices.UnitOptions",
        "PaymentCycleEnum": "apps.commissioning.models.choices.PaymentCycleOptions",
        "VegetableSizeEnum": "apps.commissioning.models.choices.VegetableSizeOptions",
        "ShareTypeEnum": "apps.commissioning.models.choices.ShareOptions",
        # All the *_day fields across SharesDeliveryDay / OrdersDeliveryDay /
        # Order / Share / etc. use the same DayNumberOptions choice set.
        # Without this override, spectacular auto-generates ~8 distinct
        # enum names (HarvestingDayEnum, WashingDayEnum, etc.) that all
        # describe the same Monday-to-Sunday set — one shared
        # ``DayNumberEnum`` keeps the generated TS client cleaner.
        "DayNumberEnum": "apps.commissioning.models.choices.DayNumberOptions",
        # Three unrelated models each have a ``kind`` CharField with its
        # own choice set; without these overrides spectacular falls back
        # to hash-suffixed names like ``Kind085Enum``.
        "OpsChecklistKindEnum": "apps.shared.super_admin.models.OpsChecklistItem.KIND_CHOICES",
        "ExternalCodeMappingKindEnum": "apps.commissioning.models.imports.ExternalCodeMapping.KIND_CHOICES",
        "ConsentKindEnum": "apps.commissioning.models.choices.ConsentKind",
        "TicketStatusEnum": "apps.shared.support.models.TicketStatus",
        "TicketPriorityEnum": "apps.shared.support.models.TicketPriority",
        "AuthorKindEnum": "apps.shared.support.models.AuthorKind",
    },
    "COMPONENT_NO_READ_ONLY_REQUIRED": True,
    "SCHEMA_PATH_PREFIX": "/api/",
    "ENUM_ADD_EXPLICIT_BLANK_NULL_CHOICE": False,
    "SCHEMA_COERCE_PATH_PK": True,
    # Postprocessing to handle any remaining edge cases
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        # Auto-inject canonical 4xx error responses (400/401/403/404)
        # into every operation so the orval-generated frontend client
        # carries a typed ErrorResponse for every endpoint without us
        # having to litter every viewset with ``responses={400: ...}``.
        # Explicit per-view declarations always win — the hook uses
        # setdefault. See ``core.openapi`` for the rules.
        "core.openapi.inject_canonical_error_responses",
    ],
}


# Security Headers
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Production settings
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Local settings override
if not RUNNING_IN_DOCKER:
    try:
        from .settings_local import *
    except ModuleNotFoundError:
        pass
