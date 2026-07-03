"""Generate a new ``DJANGO_SECRET_KEY`` candidate and print the
operator runbook.

The command itself doesn't change anything in the running system —
the SECRET_KEY lives in environment variables, not in the database,
so the operator has to apply the new value out-of-band. This
command's job is to (a) generate the candidate and (b) print the
exact next steps the operator must follow.

Same service function backs the super-admin UI's "Run rotation"
button — see ``apps/shared/super_admin/services/rotation.py``.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.shared.super_admin.services.rotation import rotate

logger = logging.getLogger("super_admin")


class Command(BaseCommand):
    help = "Generate a new DJANGO_SECRET_KEY and print operator next-steps."

    def handle(self, *args, **options) -> None:
        result = rotate("rotate_django_secret")
        # NEVER log the generated secret value — only the event.
        logger.info("ops.rotation.django_secret.generated actor=cli")

        self.stdout.write(self.style.WARNING("=" * 64))
        self.stdout.write(self.style.WARNING("New DJANGO_SECRET_KEY (save securely):"))
        self.stdout.write(self.style.WARNING("=" * 64))
        self.stdout.write(result.generated_secret or "")
        self.stdout.write(self.style.WARNING("=" * 64))
        self.stdout.write("")
        self.stdout.write(result.instructions)
