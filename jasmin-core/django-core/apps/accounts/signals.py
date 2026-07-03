"""Signal handlers for security/audit events on the accounts app."""

from __future__ import annotations

import logging

from django.dispatch import receiver

from apps.shared.request_utils import client_ip

logger = logging.getLogger("axes")


try:
    from axes.signals import user_locked_out
except ImportError:  # axes not installed in some envs (e.g. docs)
    user_locked_out = None


if user_locked_out is not None:

    @receiver(user_locked_out)
    def on_user_locked_out(sender, request, username=None, ip_address=None, **kwargs):
        logger.warning(
            "account.locked user=%s ip=%s",
            username or "-",
            ip_address or client_ip(request),
        )
