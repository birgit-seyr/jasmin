"""Generate a new Postgres password candidate + the ALTER USER SQL.

Like ``rotate_django_secret``, the command can't apply the new
credential itself — it's an operator step. This command's job is to
(a) generate the candidate, (b) print the matching SQL, and (c)
print the next-steps runbook.

Same service function backs the super-admin UI's "Run rotation"
button — see ``apps/shared/super_admin/services/rotation.py``.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.shared.super_admin.services.rotation import rotate

logger = logging.getLogger("super_admin")


class Command(BaseCommand):
    help = "Generate a new Postgres password and print operator next-steps."

    def handle(self, *args, **options) -> None:
        result = rotate("rotate_db_password")
        logger.info("ops.rotation.db_password.generated actor=cli")

        self.stdout.write(self.style.WARNING("=" * 64))
        self.stdout.write(self.style.WARNING("New Postgres password (save securely):"))
        self.stdout.write(self.style.WARNING("=" * 64))
        self.stdout.write(result.generated_secret or "")
        self.stdout.write(self.style.WARNING("=" * 64))
        self.stdout.write("")
        self.stdout.write(result.instructions)
