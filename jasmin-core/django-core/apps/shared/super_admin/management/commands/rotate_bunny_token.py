"""Print the BunnyCDN token rotation runbook.

There is no BunnyCDN integration in code today, so the platform has
nothing to rotate from a button — the rotation is entirely operator-
side (log into Bunny dashboard, reset, update .env, restart). This
command exists so the super-admin UI button has a backing surface
and so the runbook lives somewhere queryable from the CLI.

Replace this stub with a real rotation if/when BunnyCDN gets an
integration.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.shared.super_admin.services.rotation import rotate

logger = logging.getLogger("super_admin")


class Command(BaseCommand):
    help = "Print the BunnyCDN token rotation runbook (no code-side rotation)."

    def handle(self, *args, **options) -> None:
        result = rotate("rotate_bunny_token")
        logger.info("ops.rotation.bunny_token.runbook_emitted actor=cli")
        self.stdout.write(result.instructions)
