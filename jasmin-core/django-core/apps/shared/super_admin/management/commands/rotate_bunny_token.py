"""Print the Bunny rotation runbook: the account's API key and the origin secret.

Both are changed by hand — the key in Bunny's dashboard, the origin secret in
``.env`` and the pull zones' edge rules — so the platform has nothing to rotate
from a button. This command gives the super-admin UI button a backing surface
and keeps the runbook queryable from the CLI.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.shared.super_admin.services.rotation import rotate

logger = logging.getLogger("super_admin")


class Command(BaseCommand):
    help = "Print the Bunny API key and origin secret rotation runbook."

    def handle(self, *args, **options) -> None:
        result = rotate("rotate_bunny_token")
        logger.info("ops.rotation.bunny_token.runbook_emitted actor=cli")
        self.stdout.write(result.instructions)
