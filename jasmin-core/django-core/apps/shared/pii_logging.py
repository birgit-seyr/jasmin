"""Shared DRF mixin for PII-read accountability logging.

``PIIReadLoggingMixin`` — Art. 5(2) accountability: writes one structured
``pii.read`` log line per successful ``.retrieve()`` on a PII-bearing
viewset. The brute-force / mass-delete / SAR burst alerts already cover
anomalous traffic; this fills the "routine office curiosity" gap that
auditlog (which only records writes) doesn't catch.

Lives in the always-shared layer so any app can mount it without crossing a
feature boundary — it's used by ``commissioning`` (Member / Reseller
viewsets) and ``payments`` (BillingProfile). It has no GDPR-app dependency:
its only first-party import is ``apps.shared.request_utils.client_ip``, and
it logs to the ``gdpr`` logger purely by name (routing lives in
``config/settings.py``), so the entries still land next to the other
GDPR-flow records.

Design choices baked in:

  * Logs ONLY on the detail ``.retrieve()`` action. List endpoints surface
    only ``name + member_number + status`` columns and are hit on every
    office page-load — including them would drown the signal in noise
    without a SIEM to query against.
  * Logs ONLY on success (HTTP 2xx). 403 / 404 paths never produce a
    ``pii.read`` line, because the office didn't actually see the PII.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import connection
from rest_framework import status as drf_status

from apps.shared.request_utils import client_ip

logger = logging.getLogger("gdpr")


class PIIReadLoggingMixin:
    """Mount in front of ``RolePermissionsMixin`` on viewsets serving
    PII-bearing models (Member, BillingProfile, Reseller, …).

    The ``super().retrieve(...)`` call dispatches through the rest of
    the MRO (permission check + ModelViewSet.retrieve) — we only
    write the log line if that returned successfully. Failures
    (403 / 404 / 500) propagate unchanged with no ``pii.read`` row
    written, because the actor didn't actually see anything.

    The subject identifier is taken from the URL kwarg (``pk`` by
    default), and the model name from the viewset's ``queryset``.
    Neither requires a custom override per viewset.
    """

    # Override on the viewset if the URL uses a different lookup
    # kwarg (e.g. ``slug``) and ``pk`` isn't populated.
    pii_read_subject_kwarg: str = "pk"

    def retrieve(self, request: Any, *args: Any, **kwargs: Any):
        response = super().retrieve(request, *args, **kwargs)
        if drf_status.is_success(response.status_code):
            self._log_pii_read(request, kwargs)
        return response

    def _log_pii_read(self, request: Any, url_kwargs: dict[str, Any]) -> None:
        try:
            subject_kind = self._pii_subject_kind()
            subject_id = url_kwargs.get(self.pii_read_subject_kwarg, "?")
            actor = getattr(request.user, "email", None) or "anonymous"
            logger.info(
                "pii.read actor=%s subject_kind=%s subject_id=%s " "tenant=%s ip=%s",
                actor,
                subject_kind,
                subject_id,
                getattr(connection, "schema_name", "?"),
                client_ip(request),
            )
        except Exception:
            # Logging must NEVER mask a successful retrieve. If
            # something goes wrong assembling the log line, swallow
            # it and move on — the response is already on its way to
            # the office user.
            logger.exception("pii.read.logging_failed")

    def _log_pii_list_read(self, request: Any, subject_id: str) -> None:
        """Opt-in accountability log for a LIST endpoint that *does* surface PII.

        ``retrieve`` is logged automatically; ``list`` is deliberately NOT (most
        lists show only name / member_number / status — see the module docstring).
        The rare list that decrypts PII into the payload — BillingProfile's IBAN /
        account holder — calls this from its own ``list()`` override so a bulk read
        still leaves an Art. 5(2) trail. ``subject_id`` describes the scope (e.g.
        ``"list(all)"`` / ``"list(member=ab12)"``).
        """
        try:
            logger.info(
                "pii.read actor=%s subject_kind=%s subject_id=%s tenant=%s ip=%s",
                getattr(request.user, "email", None) or "anonymous",
                self._pii_subject_kind(),
                subject_id,
                getattr(connection, "schema_name", "?"),
                client_ip(request),
            )
        except Exception:
            logger.exception("pii.read.logging_failed")

    def _pii_subject_kind(self) -> str:
        """Lowercased ``app_label.model_name`` for the viewset's
        primary model — e.g. ``"commissioning.member"``.

        Priority:
          1. Class-level ``queryset`` attribute (when the viewset
             declares it directly).
          2. ``serializer_class.Meta.model`` — works for the common
             DRF pattern where the viewset overrides
             ``get_queryset()`` instead of declaring ``queryset``.
          3. Class name fallback (defensive — none of the
             currently-mounted viewsets hit this path).
        """
        qs = getattr(self, "queryset", None)
        if qs is not None and getattr(qs, "model", None) is not None:
            meta = qs.model._meta
            return f"{meta.app_label}.{meta.model_name}"
        serializer_class = getattr(self, "serializer_class", None)
        if serializer_class is not None:
            meta = getattr(serializer_class, "Meta", None)
            model = getattr(meta, "model", None) if meta is not None else None
            if model is not None:
                return f"{model._meta.app_label}.{model._meta.model_name}"
        return type(self).__name__
