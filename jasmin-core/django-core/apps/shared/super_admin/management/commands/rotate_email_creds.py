"""Force a tenant SMTP credential rotation by clearing the stored
``TenantEmailConfig.smtp_password`` on every tenant.

Unlike the other rotations in this batch, the credential lives in
this codebase's DB (as an ``EncryptedCharField`` on
``TenantEmailConfig``) — so Django CAN act unilaterally. Clearing
the field + flipping ``is_verified=False`` forces the tenant
office to re-enter the password via Configuration → Email before
the next outbound email leaves the platform.

Same service function backs the super-admin UI's "Run rotation"
button — see ``apps/shared/super_admin/services/rotation.py``.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.shared.super_admin.services.rotation import rotate

logger = logging.getLogger("super_admin")


class Command(BaseCommand):
    help = (
        "Clear every tenant's SMTP password + mark unverified. "
        "Forces re-entry by tenant office before next outbound email."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report how many tenants would be touched without writing. "
                "Safe to run anytime to preview impact."
            ),
        )

    def handle(self, *args, dry_run: bool = False, **options) -> None:
        result = rotate("rotate_email_creds", dry_run=dry_run)
        logger.info(
            "ops.rotation.email_creds.completed actor=cli dry_run=%s "
            "items_affected=%s",
            dry_run,
            result.items_affected,
        )
        self.stdout.write(result.instructions)
