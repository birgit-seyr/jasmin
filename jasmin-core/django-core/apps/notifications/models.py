"""EmailLog — tenant-scoped log of every outbound email.

GDPR note: this model contains personal data (recipient address, possibly
subject contents), so it lives **inside the tenant schema**, not in
``public``. ``DROP SCHEMA tenant_x CASCADE`` automatically erases it on
tenant deletion (Art. 17). Cross-tenant queries are physically impossible
because the ``email_log`` table only exists in the tenant's own schema.

Updated by ESP webhooks via Anymail's ``tracking`` signal — see
``apps/notifications/signals.py``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class EmailTemplate(models.Model):
    """Tenant override of a default email template.

    The shipped defaults live as ``.html`` / ``.txt`` files inside each
    app (``apps/accounts/templates/accounts/emails/...``). When a tenant
    customizes a template via the admin UI, a row is created here and
    used in preference to the on-disk default. Removing the row (or
    setting ``is_customized=False``) reverts to the shipped version.

    Stored body is rendered through the safe Mustache renderer in
    ``template_renderer.py`` — only ``{{ var.path }}`` substitutions are
    honoured. No Django template tags, no filters.

    Lives in the tenant schema (``apps.notifications`` is a TENANT_APP).
    Per-language overrides: a tenant can customize each ``(slug, language)``
    independently. The default fallback language is English; see
    ``apps.notifications.template_renderer`` for the lookup order.
    """

    slug = models.CharField(max_length=64)
    language = models.CharField(max_length=8, default="en")
    subject = models.CharField(max_length=512, blank=True)
    body_html = models.TextField(blank=True)
    body_text = models.TextField(blank=True)
    is_customized = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "email_template"
        ordering = ["slug", "language"]
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "language"], name="email_template_slug_language_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.slug} [{self.language}]"


class EmailLog(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),  # row created, not yet handed to provider
        ("sent", "Sent"),  # provider accepted the API request
        ("delivered", "Delivered"),  # recipient mailserver accepted
        ("bounced", "Bounced"),  # hard bounce: bad address, blocked, ...
        ("deferred", "Deferred"),  # soft bounce: provider will retry
        ("complained", "Complained"),  # marked as spam by recipient
        ("rejected", "Rejected"),  # provider refused (unverified domain ...)
        ("failed", "Failed"),  # network / unknown error during send
    ]

    # Recipient + content snapshot. We do NOT store the rendered HTML body
    # (could contain reset tokens / PII); just enough metadata to debug.
    recipient = models.EmailField(db_index=True)
    subject = models.CharField(max_length=512)
    template = models.CharField(max_length=255, blank=True)
    # Free-form purpose tag, e.g. "invitation" / "password_reset" / "invoice".
    purpose = models.CharField(max_length=64, blank=True, db_index=True)

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default="pending", db_index=True
    )
    # Provider's message-id, captured after a successful send. Used as a
    # secondary key when the webhook can't surface our metadata header.
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    # Bounce reason / API error text. Capped by the writer to 2000 chars.
    error = models.TextField(blank=True)

    # Optional pointer to the affected domain object (kept loose so we don't
    # couple this app to commissioning / accounts).
    related_object_type = models.CharField(max_length=64, blank=True)
    related_object_id = models.CharField(max_length=64, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "email_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["purpose", "-created_at"]),
        ]
        constraints = [
            # A mail can't be sent before its row was created, nor delivered
            # before it was sent. NULL-tolerant: only enforced once both
            # stamps in a pair are present. The webhook path uses bulk
            # updates that bypass clean(), so these DB constraints are the
            # real guard.
            models.CheckConstraint(
                name="emaillog_sent_after_created",
                condition=(
                    Q(sent_at__isnull=True)
                    | Q(created_at__isnull=True)
                    | Q(sent_at__gte=F("created_at"))
                ),
            ),
            models.CheckConstraint(
                name="emaillog_delivered_after_sent",
                condition=(
                    Q(delivered_at__isnull=True)
                    | Q(sent_at__isnull=True)
                    | Q(delivered_at__gte=F("sent_at"))
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.recipient} / {self.subject[:40]} [{self.status}]"

    def clean(self) -> None:
        super().clean()
        if (
            self.sent_at is not None
            and self.created_at is not None
            and self.sent_at < self.created_at
        ):
            raise ValidationError(
                {"sent_at": "sent_at cannot be earlier than created_at."}
            )
        if (
            self.delivered_at is not None
            and self.sent_at is not None
            and self.delivered_at < self.sent_at
        ):
            raise ValidationError(
                {"delivered_at": "delivered_at cannot be earlier than sent_at."}
            )


class BackgroundJob(models.Model):
    """Generic record of an enqueued long-running job (Huey-backed).

    Tenant-scoped (lives in TENANT_APPS like ``EmailLog``) so results and
    progress are isolated per coop. The model is intentionally generic —
    one row per kicked-off task, regardless of what kind of work it
    represents. The ``kind`` field tells the polling frontend which
    result shape to expect (e.g. ``"offer.bulk_send"`` produces a
    ``{total_processed, successful, failed, results: [...]}`` payload
    matching the old synchronous shape of
    ``OfferService.bulk_send_offers_via_email``).

    Why a model rather than relying on Huey's result store directly:
      * Huey's result store TTL is short and not survival-safe across
        worker restarts. A DB row is persistent — the office can come
        back tomorrow and still see what happened.
      * Tenant isolation: Huey results are global; this table is
        per-tenant schema, so an office user can only see jobs from
        their own coop.
      * Adds a ``created_by`` audit trail for free.

    Lifecycle (status transitions, no other shape is valid):

        queued -> running -> done
        queued -> running -> failed
        queued -> failed             (worker rejected before starting)

    ``progress`` is a free-form JSON blob the task writes to in flight
    (e.g. ``{"processed": 23, "total": 50, "successful": 22, "failed":
    1}``). The polling endpoint surfaces it verbatim so a React drawer
    can render a progress bar without a per-kind serializer.

    ``result`` is the final payload — same shape the synchronous view
    used to return, so the frontend's success handler maps over with
    minimal change.
    """

    import uuid as _uuid

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    # Stable short string identifying which kind of work this is.
    # Convention: ``<app>.<verb>`` — e.g. ``offer.bulk_send``,
    # ``invoice_reminder.bulk_send``.
    kind = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_QUEUED,
        db_index=True,
    )
    # In-flight progress. Worker writes periodically; polling endpoint
    # reads. Empty dict before the task starts running.
    progress = models.JSONField(default=dict, blank=True)
    # Final result payload on success. Empty dict until ``status=done``.
    result = models.JSONField(default=dict, blank=True)
    # Short error text on failure (capped at 2000 chars by the writer
    # for parity with EmailLog.error). Empty unless ``status=failed``.
    error = models.TextField(blank=True)

    # Who kicked the job off, if known. ``None`` for cron-initiated jobs
    # that hit this table from periodic tasks (none today; future-proof).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="background_jobs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Last time the worker reported liveness — stamped on mark_running and on
    # every update_progress tick (a live bulk task heartbeats per item). NULL
    # while the job is still queued (no worker has picked it up yet). Drives the
    # stale-job reconciliation sweep: a heartbeat older than the timeout means a
    # crashed/OOM-killed/hung worker (or a queued row whose Redis dispatch never
    # landed), so the row is marked failed instead of stranding "running"/
    # "queued" forever with a frozen progress snapshot.
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "background_job"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["kind", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        constraints = [
            # A job can't complete before it was created. NULL-tolerant:
            # only enforced once completed_at is set. The worker stamps
            # completed_at via bulk .update() (bypassing clean()), so this
            # DB constraint is the load-bearing guard.
            models.CheckConstraint(
                name="backgroundjob_completed_after_created",
                condition=(
                    Q(completed_at__isnull=True)
                    | Q(created_at__isnull=True)
                    | Q(completed_at__gte=F("created_at"))
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} [{self.status}] {self.id}"

    def clean(self) -> None:
        super().clean()
        if (
            self.completed_at is not None
            and self.created_at is not None
            and self.completed_at < self.created_at
        ):
            raise ValidationError(
                {"completed_at": "completed_at cannot be earlier than created_at."}
            )
