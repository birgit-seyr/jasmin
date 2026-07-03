"""Super-admin rotation service layer.

Single source of truth for the four "operator-side" rotations the
``OpsChecklistItem`` model declares as ``KIND_CHOICES``:

  * ``rotate_django_secret``: generates a new ``DJANGO_SECRET_KEY``
    candidate. Django cannot apply this itself — the operator updates
    ``.env`` and restarts every running process.

  * ``rotate_db_password``: generates a new Postgres password
    candidate + the matching ``ALTER USER`` SQL. Same operator-applies
    pattern.

  * ``rotate_bunny_token``: no integration in code today, so the
    service emits a runbook only. Listed for completeness so the
    super-admin UI button is non-misleading: it tells the operator
    exactly which dashboard to log into rather than promising
    work the platform can't do.

  * ``rotate_email_creds``: per-tenant, real Django side effects.
    Clears every ``TenantEmailConfig.smtp_password`` and flips
    ``is_verified=False`` — forces the tenant office to re-enter
    fresh credentials before the next outbound email.

The fifth declared rotation, ``rotate_field_encryption``, has its
own dedicated management command (chunked over millions of
ciphertext rows) and is NOT dispatched through this service — see
``rotate_field_encryption.py``.

Design notes
------------
* Generated secrets are returned in the ``RotationResult``; callers
  must surface them to the operator (modal, command stdout) and then
  drop them. We never log secret VALUES — only the rotation event
  (kind + actor + timestamp).

* ``dry_run`` is honoured by ``rotate_email_creds`` (the only
  rotation that mutates state). The secret-generators are
  side-effect-free either way; dry-run there just clarifies intent.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field

from apps.shared.tenants.models import TenantEmailConfig

logger = logging.getLogger("super_admin")

# Allowlist of rotation kinds this service knows how to dispatch.
# Kinds outside this set raise ``UnknownRotationKind`` — callers can
# use that to 404 / 400 sensibly.
DISPATCHABLE_KINDS = frozenset(
    {
        "rotate_django_secret",
        "rotate_db_password",
        "rotate_bunny_token",
        "rotate_email_creds",
    }
)


class UnknownRotationKind(ValueError):
    """Raised when a caller asks to rotate a kind this service doesn't
    handle (typo, ``rotate_field_encryption`` which has its own
    dedicated command, or a non-rotation kind like
    ``restore_drill``)."""


@dataclass
class RotationResult:
    """What the operator / API sees after a rotation.

    ``generated_secret`` is populated only when the rotation produces
    a value the operator needs to copy somewhere (``.env``, Postgres
    role). It is NEVER logged — the calling layer must show it once
    and treat it as sensitive.

    ``instructions`` is the runbook the operator follows AFTER reading
    the generated secret. For rotations that have side-effects of
    their own (``rotate_email_creds``), the instructions describe
    what just happened + what the tenant office now needs to do.

    ``items_affected`` is the count of rows the service modified.
    Always 0 for the secret-generator rotations (Django doesn't own
    the destination state).
    """

    kind: str
    instructions: str
    generated_secret: str | None = None
    items_affected: int = 0
    extras: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------
# Per-kind implementations
# ---------------------------------------------------------------


def _rotate_django_secret() -> RotationResult:
    new_key = secrets.token_urlsafe(50)
    return RotationResult(
        kind="rotate_django_secret",
        generated_secret=new_key,
        instructions=(
            "1. Copy the generated key above and save it in your password manager.\n"
            "2. Update DJANGO_SECRET_KEY in the prod .env file.\n"
            "3. Restart every Django process (gunicorn, huey worker, scheduler).\n"
            "4. All existing sessions + CSRF tokens are invalidated — users will\n"
            "   need to log in again. JWT access/refresh tokens are signed via\n"
            "   simplejwt's own SIGNING_KEY (separate setting) and are NOT\n"
            "   affected by this rotation.\n"
            "5. Mark this checklist item done once you've verified the new key\n"
            "   is live (visit a page that uses CSRF — e.g. the office login —\n"
            "   and confirm the form submits cleanly)."
        ),
    )


def _rotate_db_password() -> RotationResult:
    new_password = secrets.token_urlsafe(32)
    db_user = "jasmin"  # matches the default in docker-compose / .env.example
    alter_sql = f"ALTER USER {db_user} WITH PASSWORD '{new_password}';"
    return RotationResult(
        kind="rotate_db_password",
        generated_secret=new_password,
        instructions=(
            "1. Copy the generated password above and save it in your password\n"
            "   manager.\n"
            "2. Apply the ALTER USER SQL on the Postgres host:\n"
            "       sudo -u postgres psql -d jasmin\n"
            f"       {alter_sql}\n"
            "3. Update POSTGRES_PASSWORD in the prod .env file.\n"
            "4. Restart every service that holds a DB connection (gunicorn,\n"
            "   huey worker, scheduler). Backup scripts that connect directly\n"
            "   (backups/backup.sh) need their PGPASSWORD env updated too.\n"
            "5. Verify with `make prod-bash` that the new password is in\n"
            "   effect (a trivial query like `SELECT 1` should succeed)."
        ),
        extras={"db_user": db_user, "alter_sql": alter_sql},
    )


def _rotate_bunny_token() -> RotationResult:
    return RotationResult(
        kind="rotate_bunny_token",
        instructions=(
            "There is no BunnyCDN integration in code today, so there's nothing\n"
            "for Django to rotate from a button. This rotation is purely\n"
            "operator-side:\n"
            "\n"
            "1. Log into the BunnyCDN dashboard (https://panel.bunny.net/).\n"
            "2. Storage Zones → your zone → FTP & API Access → Reset Password.\n"
            "3. Save the new password in your password manager.\n"
            "4. Update BUNNY_STORAGE_PASSWORD (or whichever env var your deploy\n"
            "   uses) in the prod .env file. Add the variable to settings.py\n"
            "   first if it isn't there yet.\n"
            "5. Restart every Django process.\n"
            "\n"
            "If/when BunnyCDN gets a real integration in this codebase, replace\n"
            "this stub with a real rotation that hits Bunny's API directly."
        ),
    )


def _rotate_email_creds(*, dry_run: bool) -> RotationResult:
    """Clear every tenant's stored SMTP password.

    This is the one rotation where Django CAN act unilaterally: the
    credential lives in our DB (``TenantEmailConfig.smtp_password``,
    an ``EncryptedCharField``). Clearing it + flipping ``is_verified``
    forces the tenant office to re-enter the value before the next
    outbound email leaves the platform.

    Deliberately heavy-handed: this rotation is supposed to be rare
    (annual at most). When it runs, every tenant gets a forced
    re-enter prompt; we'd rather over-rotate than have a stale
    credential survive past an annual review.
    """
    configs = TenantEmailConfig.objects.filter(smtp_password__gt="")
    affected = list(configs.values_list("tenant_id", flat=True))
    count = len(affected)

    if not dry_run and count:
        for config in TenantEmailConfig.objects.filter(
            tenant_id__in=affected,
        ):
            config.smtp_password = ""
            config.is_verified = False
            config.save(update_fields=["smtp_password", "is_verified"])

    instructions_lines = [
        f"{'DRY RUN — would clear' if dry_run else 'Cleared'} {count} "
        "tenant SMTP password(s).",
        "",
        "Each affected tenant's office UI will now show 'SMTP credentials",
        "needed' until the tenant admin re-enters them via",
        "Configuration → Email. Until they do, outbound email from that",
        "tenant will fail.",
        "",
        "Recommended follow-up: notify each tenant admin (out-of-band) that",
        "they need to re-enter their SMTP password.",
    ]
    return RotationResult(
        kind="rotate_email_creds",
        instructions="\n".join(instructions_lines),
        items_affected=count,
        extras={"affected_tenant_ids": ",".join(str(t) for t in affected)},
    )


# ---------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------


def rotate(kind: str, *, dry_run: bool = False) -> RotationResult:
    """Dispatch to the right per-kind implementation.

    Raises ``UnknownRotationKind`` for kinds we don't handle so
    callers (viewset action, management command) can translate to
    a sensible HTTP / CLI error.
    """
    if kind not in DISPATCHABLE_KINDS:
        raise UnknownRotationKind(
            f"Unknown rotation kind: {kind!r}. "
            f"Known kinds: {sorted(DISPATCHABLE_KINDS)}"
        )
    if kind == "rotate_django_secret":
        return _rotate_django_secret()
    if kind == "rotate_db_password":
        return _rotate_db_password()
    if kind == "rotate_bunny_token":
        return _rotate_bunny_token()
    if kind == "rotate_email_creds":
        return _rotate_email_creds(dry_run=dry_run)
    raise UnknownRotationKind(kind)  # defensive
