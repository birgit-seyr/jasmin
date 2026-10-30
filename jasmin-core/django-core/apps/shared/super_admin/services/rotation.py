"""Super-admin rotation service layer.

Single source of truth for the four rotations of ``OpsChecklistItem``'s
``KIND_CHOICES`` that the super-admin UI and the ``rotate_*`` commands
can run:

  * ``rotate_django_secret``: generates a new ``DJANGO_SECRET_KEY``
    candidate. Django cannot apply this itself — the operator updates
    ``.env`` and recreates the backend and huey containers.

  * ``rotate_db_password``: generates a new Postgres password
    candidate + the runbook that sets it. Same operator-applies
    pattern.

  * ``rotate_bunny_token``: a runbook only. The account's API key
    lives in Bunny's dashboard, and the origin secret is set by hand
    in ``.env`` and in the pull zones' edge rules, so the super-admin
    UI button tells the operator exactly what to change rather than
    promising work the platform can't do.

  * ``rotate_email_creds``: per-tenant, real Django side effects.
    Clears every ``TenantEmailConfig.smtp_password`` and flips
    ``is_verified=False`` — forces the tenant office to re-enter
    fresh credentials before the next outbound email.

``rotate_field_encryption`` has its own dedicated management command
(chunked over millions of ciphertext rows) and is NOT dispatched
through this service — see ``rotate_field_encryption.py``. The other
rotation kinds (Redis password, backup encryption key, off-site backup
credentials, DNS API token) are operator-side only; their checklist
item's description is the runbook.

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
            "Every user and super-admin is logged out: the access and refresh\n"
            "tokens are signed with this key, and the fallback below doesn't\n"
            "cover them. Pick a quiet hour.\n"
            "\n"
            "1. Save the generated key above in your password manager.\n"
            "2. In the prod .env, move the current DJANGO_SECRET_KEY value to\n"
            "   DJANGO_SECRET_KEY_FALLBACK and set DJANGO_SECRET_KEY to the new\n"
            "   key. Password-reset and protected-media links signed with the\n"
            "   old key keep working through the fallback.\n"
            "3. From the repo root on the server:\n"
            "       docker compose up -d backend huey\n"
            "       docker compose restart gateway\n"
            "   up -d recreates both containers with the new .env (a restart\n"
            "   keeps the old values); the gateway restart lets nginx find the\n"
            "   recreated backend.\n"
            "4. Log in on the admin host and on a tenant host.\n"
            "5. After 24 hours, when the last link signed with the old key has\n"
            "   expired, remove DJANGO_SECRET_KEY_FALLBACK from .env and run\n"
            "   the two commands of step 3 again."
        ),
    )


def _rotate_db_password() -> RotationResult:
    new_password = secrets.token_urlsafe(32)
    return RotationResult(
        kind="rotate_db_password",
        generated_secret=new_password,
        instructions=(
            "The database has two logins: the app's role, APP_DB_USER in the\n"
            "prod .env, which backend and huey use, and the superuser,\n"
            "POSTGRES_USER, which backups and restores use (and the app too\n"
            "while APP_DB_USER is unset). This password is for one of them;\n"
            "run the rotation again for the other.\n"
            "1. Save the generated password above in your password manager.\n"
            "2. Set it on the role. From the repo root on the server:\n"
            '       docker compose exec postgres sh -c \'psql -U "$POSTGRES_USER" '
            '-d "$POSTGRES_DB"\'\n'
            "   and at the psql prompt, for the app's role:\n"
            "       \\password jasmin_app\n"
            "   (the name APP_DB_USER holds), or \\password alone for the\n"
            "   superuser. Paste the new password twice, then leave with \\q.\n"
            "   psql sends it hashed, so it ends up in no log and no shell\n"
            "   history.\n"
            "3. Set it in the prod .env: APP_DB_PASSWORD for the app's role,\n"
            "   POSTGRES_PASSWORD for the superuser.\n"
            "4. Recreate everything that connects with it, then let nginx find\n"
            "   the recreated backend:\n"
            "       docker compose up -d backend huey backup\n"
            "       docker compose restart gateway\n"
            "   The postgres container itself needs nothing: it reads both\n"
            "   passwords only when the database is first created.\n"
            "5. Check that backend and huey are healthy (docker compose ps) and\n"
            "   that a backup still works:\n"
            "       docker compose exec backup /usr/local/bin/backup.sh now"
        ),
    )


def _rotate_bunny_token() -> RotationResult:
    return RotationResult(
        kind="rotate_bunny_token",
        instructions=(
            "Two Bunny credentials, each rotated on its own.\n"
            "\n"
            "The account's API key. Nothing on the server uses it:\n"
            "1. In the Bunny dashboard, reset the account's API key.\n"
            "2. Update any tool outside this platform that uses it.\n"
            "3. Save the new key in your password manager and check that the\n"
            "   account still has two-factor login on.\n"
            "\n"
            "The origin secret, while BUNNY_ORIGIN_SECRET in .env is set:\n"
            "1. Generate a new one: openssl rand -hex 32\n"
            "2. Put it in .env as BUNNY_ORIGIN_SECRET_NEXT, then\n"
            "       ./scripts/validate_gateway_config.sh\n"
            "       docker compose up -d gateway\n"
            "   The check stops a mistyped secret from taking the gateway\n"
            "   down. The tenant hosts now accept the old secret and the new one.\n"
            "3. In every tenant pull zone, put the new value into the edge rule\n"
            "   that sets the X-Origin-Secret request header, and give Bunny a\n"
            "   few minutes to roll it out.\n"
            "4. Move the new value to BUNNY_ORIGIN_SECRET, empty\n"
            "   BUNNY_ORIGIN_SECRET_NEXT, and run both commands of step 2 again.\n"
            "5. Check that every tenant host still loads, and save the new\n"
            "   secret in your password manager."
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
