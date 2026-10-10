"""Sentry/GlitchTip initialisation, called from settings when a DSN is set."""

from __future__ import annotations

import logging

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.huey import HueyIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from core.sentry_scrub import before_breadcrumb, before_send


def init_sentry(dsn: str, *, debug: bool) -> None:
    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            DjangoIntegration(),
            # INFO and WARNING log lines become Sentry breadcrumbs; ERROR
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
        # The Django integration attaches request bodies whatever
        # send_default_pii says, so a 500 on a member form would ship the
        # email address and IBAN typed into it.
        max_request_body_size="never",
        # send_default_pii=False does not cover PII the app put into a log
        # message or an exception; these hooks scrub email/IP/IBAN substrings.
        before_breadcrumb=before_breadcrumb,
        before_send=before_send,
        environment="development" if debug else "production",
    )
