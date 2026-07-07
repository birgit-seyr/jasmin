"""Response serializers for the Art-15 SAR endpoint.

One serializer class per top-level section of ``GDPRService.
get_subject_access_bundle``. The field list on each serializer is
the single source of truth for "what does the SAR expose for this
model?" — adding a new column to a SAR-relevant model means adding
a line here too.

Two side-benefits over the previous ``inline_serializer(... DictField())``:

  1. drf-spectacular emits a rich OpenAPI schema; orval generates
     proper TypeScript interfaces for the frontend instead of
     ``Record<string, unknown>``.
  2. The serializer formats native Python types (datetime → ISO 8601,
     Decimal → string) so the service helpers can stop calling
     ``.isoformat()`` / ``str(...)`` everywhere.

The serializers are deliberately *plain* ``Serializer`` subclasses
(not ``ModelSerializer``), because several sections collapse FK
fields to a human-readable name (e.g. Subscription →
``share_type_variation`` as a string) — which ``ModelSerializer``
doesn't compose cleanly. Plain ``Serializer`` makes every field
explicit, which is the whole point of the audit.

Naming: every section serializer is prefixed ``Sar`` so it doesn't
clash with the canonical model serializer of the same name in
other apps (e.g. ``apps.payments.serializers.ChargeScheduleSerializer``,
``apps.commissioning.serializers.members_serializer.MemberSerializer``).
drf-spectacular emits one OpenAPI schema component per serializer
*class name*; without the prefix, orval would silently overwrite
the canonical type with this SAR-shaped one and break every
frontend page that uses the real type. The top-level
``SubjectAccessBundleSerializer`` keeps its unique name (no
collision).
"""

from __future__ import annotations

from rest_framework import serializers

# ---------------------------------------------------------------------------
# Subject + Account
# ---------------------------------------------------------------------------


class SarSubjectSerializer(serializers.Serializer):
    """Identity block at the top of the bundle — repeats the user id
    and *currently-displayed* email so the SAR is self-contained
    even if read out of context."""

    user_id = serializers.CharField()
    email = serializers.EmailField(allow_blank=True, allow_null=True)


class SarAccountSerializer(serializers.Serializer):
    """Full ``apps.accounts.models.JasminUser`` row.

    Fields kept off this serializer on purpose:
      - ``password`` — never expose, even hashed.
      - ``groups`` / ``user_permissions`` (m2m from PermissionsMixin)
        — Django-auth internals with no SAR value.
    """

    user_id = serializers.CharField()
    public_id = serializers.CharField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    avatar = serializers.CharField(allow_null=True, allow_blank=True)
    account_status = serializers.CharField()
    is_active = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    user_language = serializers.CharField()
    sidebar_collapsed = serializers.BooleanField()
    theme = serializers.CharField()
    edit_mode = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField(), allow_empty=True)
    date_joined = serializers.DateTimeField(allow_null=True)
    last_login = serializers.DateTimeField(allow_null=True)
    last_login_ip = serializers.IPAddressField(allow_null=True)
    activated_at = serializers.DateTimeField(allow_null=True)
    inactivated_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------


class SarMemberSerializer(serializers.Serializer):
    """Full ``apps.commissioning.models.Member`` row + the mixin
    fields (AdminConfirmableMixin, CreatedMixin, WaitingListMixin).

    Fields kept off on purpose:
      - ``user`` FK — the data subject IS this user; re-emitting
        their own id is noise.
    """

    member_id = serializers.CharField()
    member_number = serializers.IntegerField(allow_null=True)

    # Identity
    company_name = serializers.CharField(allow_blank=True, allow_null=True)
    first_name = serializers.CharField(allow_blank=True, allow_null=True)
    last_name = serializers.CharField(allow_blank=True, allow_null=True)
    pickup_name = serializers.CharField(allow_blank=True, allow_null=True)

    # Address
    address = serializers.CharField(allow_blank=True, allow_null=True)
    zip_code = serializers.CharField(allow_blank=True, allow_null=True)
    city = serializers.CharField(allow_blank=True, allow_null=True)
    country = serializers.CharField(allow_blank=True, allow_null=True)

    # Contact channels
    email = serializers.EmailField(allow_blank=True, allow_null=True)
    email_2 = serializers.CharField(allow_blank=True, allow_null=True)
    email_3 = serializers.CharField(allow_blank=True, allow_null=True)

    # Banking (encrypted at rest, plaintext on read)
    account_owner = serializers.CharField(allow_blank=True, allow_null=True)
    iban = serializers.CharField(allow_blank=True, allow_null=True)
    number_of_rates = serializers.IntegerField()

    # Denormalised consent timestamps (verbatim model field names —
    # frontend reader keys off the un-suffixed names; full event log
    # lives in the ``consents`` section)
    sepa_consent = serializers.DateTimeField(allow_null=True)
    withdrawal_consent = serializers.DateTimeField(allow_null=True)
    privacy_consent = serializers.DateTimeField(allow_null=True)

    # State flags + dates
    is_active = serializers.BooleanField()
    is_trial = serializers.BooleanField()
    is_student = serializers.BooleanField()
    entry_date = serializers.DateField(allow_null=True)
    birth_date = serializers.DateField(allow_null=True)
    # CancellableMixin — Austrittsdatum per GenG §30
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancelled_effective_at = serializers.DateField(allow_null=True)
    cancellation_reason = serializers.CharField(allow_blank=True, allow_null=True)

    note = serializers.CharField(allow_blank=True, allow_null=True)

    # AdminConfirmableMixin
    admin_confirmed = serializers.BooleanField()
    admin_confirmed_at = serializers.DateTimeField(allow_null=True)
    admin_rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)

    # CreatedMixin
    created_at = serializers.DateTimeField(allow_null=True)

    # WaitingListMixin
    on_waiting_list = serializers.BooleanField()
    waiting_list_status = serializers.CharField()
    waiting_list_position = serializers.IntegerField(allow_null=True)
    notification_sent_at = serializers.DateTimeField(allow_null=True)
    notification_expires_at = serializers.DateTimeField(allow_null=True)
    response_received_at = serializers.DateTimeField(allow_null=True)


# ---------------------------------------------------------------------------
# Reseller + ContactEntity
# ---------------------------------------------------------------------------


class SarContactEntitySerializer(serializers.Serializer):
    """Full ``ContactEntity`` row. Excludes ``user`` FK (same reason
    as Member: the data subject IS the user)."""

    contact_id = serializers.CharField()
    # Identity
    company_name = serializers.CharField(allow_blank=True, allow_null=True)
    first_name = serializers.CharField(allow_blank=True, allow_null=True)
    last_name = serializers.CharField(allow_blank=True, allow_null=True)
    acronym = serializers.CharField(allow_blank=True, allow_null=True)
    # Address + geocoded position
    address = serializers.CharField(allow_blank=True, allow_null=True)
    zip_code = serializers.CharField(allow_blank=True, allow_null=True)
    city = serializers.CharField(allow_blank=True, allow_null=True)
    country = serializers.CharField(allow_blank=True, allow_null=True)
    coords_lon = serializers.DecimalField(
        max_digits=12, decimal_places=10, allow_null=True
    )
    coords_lat = serializers.DecimalField(
        max_digits=12, decimal_places=10, allow_null=True
    )
    # Contact channels
    email = serializers.EmailField(allow_blank=True, allow_null=True)
    email_2 = serializers.CharField(allow_blank=True, allow_null=True)
    email_3 = serializers.EmailField(allow_blank=True, allow_null=True)
    order_email = serializers.EmailField(allow_blank=True, allow_null=True)
    phone = serializers.CharField(allow_blank=True, allow_null=True)
    phone_2 = serializers.CharField(allow_blank=True, allow_null=True)
    phone_3 = serializers.CharField(allow_blank=True, allow_null=True)
    # Tax / banking
    uid = serializers.CharField(allow_blank=True, allow_null=True)
    iban = serializers.CharField(allow_blank=True, allow_null=True)


class SarResellerSerializer(serializers.Serializer):
    """Full ``apps.commissioning.models.Reseller`` row + nested
    ContactEntity. Skips raw FK ids (``linked_user``, ``contact``,
    ``offer_group``) — ``linked_user`` IS the subject; ``contact``
    is expanded inline below; ``offer_group`` collapses to its name
    (raw FK ids are noise in a SAR for a human reader)."""

    reseller_id = serializers.CharField()
    customer_number = serializers.IntegerField(allow_null=True)
    filial_number = serializers.IntegerField(allow_null=True)
    name_for_member_pages = serializers.CharField(allow_blank=True, allow_null=True)

    # Persona-type flags ("what kind of relationship")
    is_seller = serializers.BooleanField()
    is_reseller = serializers.BooleanField()
    is_donation_recipient = serializers.BooleanField()
    is_supplier = serializers.BooleanField()
    is_active_seller = serializers.BooleanField()
    is_active_reseller = serializers.BooleanField()
    is_active_donation_recipient = serializers.BooleanField()
    is_active_supplier = serializers.BooleanField()

    # Per-document delivery channel preferences
    offer_via_email = serializers.BooleanField(allow_null=True)
    order_via_email = serializers.BooleanField(allow_null=True)
    delivery_note_via_email = serializers.BooleanField(allow_null=True)
    invoice_via_email = serializers.BooleanField(allow_null=True)

    # Pricing-tier grouping — surfaced as the group NAME
    offer_group = serializers.CharField(allow_null=True)

    # Invoice-display fields
    invoice_name = serializers.CharField(allow_blank=True, allow_null=True)
    invoice_name2 = serializers.CharField(allow_blank=True, allow_null=True)
    invoice_address = serializers.CharField(allow_blank=True, allow_null=True)
    invoice_plz = serializers.CharField(allow_blank=True, allow_null=True)
    invoice_city = serializers.CharField(allow_blank=True, allow_null=True)
    invoice_email = serializers.CharField(allow_blank=True, allow_null=True)
    note = serializers.CharField(allow_blank=True, allow_null=True)

    contact = SarContactEntitySerializer(allow_null=True)


# ---------------------------------------------------------------------------
# Consents
# ---------------------------------------------------------------------------


class SarConsentRecordSerializer(serializers.Serializer):
    """Full ``apps.commissioning.models.ConsentRecord`` row + the
    related ``ConsentDocument`` fields the user consented against.
    ``member`` + ``revoked_by`` FKs are NOT surfaced (member IS the
    subject; revoked_by exposes another user's id)."""

    id = serializers.CharField()
    kind = serializers.CharField()
    document_version = serializers.CharField()
    document_locale = serializers.CharField()
    consented_at = serializers.DateTimeField()
    ip_address = serializers.IPAddressField(allow_null=True)
    user_agent = serializers.CharField(allow_blank=True)
    revoked_at = serializers.DateTimeField(allow_null=True)
    revoked_reason = serializers.CharField(allow_blank=True)


# ---------------------------------------------------------------------------
# Coop shares + Subscriptions + Member loans + Charge schedules
# ---------------------------------------------------------------------------


class SarCoopShareSerializer(serializers.Serializer):
    """``CoopShare`` row + PayableMixin + AdminConfirmableMixin
    fields. ``member`` FK skipped (subject)."""

    id = serializers.CharField()
    amount_of_coop_shares = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    is_increase = serializers.BooleanField()
    note = serializers.CharField(allow_blank=True, allow_null=True)
    cancellation_reason = serializers.CharField(allow_blank=True, allow_null=True)
    # PayableMixin
    due_date = serializers.DateField(allow_null=True)
    paid_at = serializers.DateTimeField(allow_null=True)
    # AdminConfirmableMixin
    admin_confirmed = serializers.BooleanField()
    admin_confirmed_at = serializers.DateTimeField(allow_null=True)
    admin_rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)


class SarSubscriptionSerializer(serializers.Serializer):
    """``Subscription`` row + TimeBoundMixin + AdminConfirmableMixin
    + CreatedMixin + CancellableMixin + WaitingListMixin.
    The share-type-variation collapses to its name (the part the
    member would recognise from their dashboard); raw FK ids are
    skipped."""

    id = serializers.CharField()
    share_type_variation = serializers.CharField()
    is_trial = serializers.BooleanField()
    quantity = serializers.IntegerField()
    price_per_delivery = serializers.DecimalField(
        max_digits=8, decimal_places=2, allow_null=True
    )
    notice_period_duration = serializers.IntegerField(allow_null=True)

    # TimeBoundMixin
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True)

    # AdminConfirmableMixin
    admin_confirmed = serializers.BooleanField()
    admin_confirmed_at = serializers.DateTimeField(allow_null=True)
    admin_rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)

    # CreatedMixin
    created_at = serializers.DateTimeField(allow_null=True)

    # CancellableMixin
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancelled_effective_at = serializers.DateField(allow_null=True)
    cancellation_reason = serializers.CharField(allow_blank=True, allow_null=True)

    # WaitingListMixin
    on_waiting_list = serializers.BooleanField()
    waiting_list_status = serializers.CharField()
    waiting_list_position = serializers.IntegerField(allow_null=True)


class SarMemberLoanSerializer(serializers.Serializer):
    """``MemberLoan`` row + AdminConfirmableMixin + CreatedMixin."""

    id = serializers.CharField()
    amount = serializers.IntegerField()
    interest_rate = serializers.DecimalField(max_digits=4, decimal_places=2)
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)
    paid_back_date = serializers.DateField(allow_null=True)
    cancelled_reason = serializers.CharField(allow_blank=True, allow_null=True)
    # AdminConfirmableMixin
    admin_confirmed = serializers.BooleanField()
    admin_confirmed_at = serializers.DateTimeField(allow_null=True)
    admin_rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)
    # CreatedMixin
    created_at = serializers.DateTimeField(allow_null=True)


class SarChargeScheduleSerializer(serializers.Serializer):
    """``ChargeSchedule`` row (the member's billing ledger).
    ``member`` + ``subscription`` + ``billing_run`` FKs skipped —
    raw ids are noise. ``status`` is the visible label."""

    id = serializers.CharField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    due_date = serializers.DateField()
    expected_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    end_to_end_id = serializers.CharField(allow_blank=True)


# ---------------------------------------------------------------------------
# Reseller-scoped: Orders + Invoices
# ---------------------------------------------------------------------------


class SarOrderSerializer(serializers.Serializer):
    """``Order`` row + NumberedDocumentMixin + FinalizableMixin +
    CreatedMixin. ``reseller`` FK skipped (the parent ``reseller``
    block in the bundle already identifies them)."""

    id = serializers.CharField()
    display_number = serializers.CharField()
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField()
    day_number = serializers.IntegerField(allow_null=True)
    last_possible_ordering_day = serializers.IntegerField(allow_null=True)
    harvesting_day = serializers.IntegerField(allow_null=True)
    packing_day = serializers.IntegerField(allow_null=True)
    washing_day = serializers.IntegerField(allow_null=True)
    cleaning_day = serializers.IntegerField(allow_null=True)
    is_donation = serializers.BooleanField()
    note = serializers.CharField(allow_blank=True, allow_null=True)
    # FinalizableMixin
    is_finalized = serializers.BooleanField()
    finalized_at = serializers.DateTimeField(allow_null=True)
    # CreatedMixin
    created_at = serializers.DateTimeField(allow_null=True)


class SarInvoiceResellerSerializer(serializers.Serializer):
    """``InvoiceReseller`` row + DateDocumentMixin + PayableMixin +
    FinalizableMixin + NumberedDocumentMixin. ``cancels_invoice`` /
    ``cancelled_by_invoice`` FKs collapse to display numbers (so
    the SAR shows "this invoice was cancelled by RK-2026-0042"
    rather than a raw FK id)."""

    id = serializers.CharField()
    display_number = serializers.CharField()
    document_type = serializers.CharField()
    document_hash = serializers.CharField(allow_blank=True, allow_null=True)
    correction_reason = serializers.CharField(allow_blank=True, allow_null=True)
    items_are_grouped = serializers.BooleanField()
    note = serializers.CharField(allow_blank=True, allow_null=True)

    # Cross-references collapsed to display numbers
    cancels_invoice = serializers.CharField(allow_null=True)
    cancelled_by_invoice = serializers.CharField(allow_null=True)

    # File pointers (URL strings; surface so the user can fetch them)
    file = serializers.CharField(allow_blank=True, allow_null=True)
    xml_file = serializers.CharField(allow_blank=True, allow_null=True)

    # Dispatch state — the booleans are derived from the timestamps
    # on the model (@property), serialized for SAR human-readability.
    has_been_sent_to_reseller = serializers.BooleanField()
    has_been_sent_to_reseller_at = serializers.DateTimeField(allow_null=True)
    has_been_sent_to_accounting = serializers.BooleanField()
    has_been_sent_to_accounting_at = serializers.DateTimeField(allow_null=True)

    # DateDocumentMixin
    date = serializers.DateField(allow_null=True)
    # PayableMixin
    due_date = serializers.DateField(allow_null=True)
    paid_at = serializers.DateTimeField(allow_null=True)
    has_been_paid = serializers.BooleanField()
    # FinalizableMixin
    is_finalized = serializers.BooleanField()
    finalized_at = serializers.DateTimeField(allow_null=True)


# ---------------------------------------------------------------------------
# EmailLog (with truncation envelope)
# ---------------------------------------------------------------------------


class SarEmailLogEntrySerializer(serializers.Serializer):
    """One ``EmailLog`` row. ``provider_message_id`` is exposed so
    the user can correlate with their inbox if needed; ``related_*``
    FKs are skipped (loose pointers, no SAR value)."""

    id = serializers.CharField()
    recipient = serializers.EmailField()
    subject = serializers.CharField(allow_blank=True)
    template = serializers.CharField(allow_blank=True)
    purpose = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    provider_message_id = serializers.CharField(allow_blank=True)
    error = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField(allow_null=True)
    sent_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)


class SarEmailLogSectionSerializer(serializers.Serializer):
    """Envelope around the EmailLog entries. ``truncated`` +
    ``total_count`` flag whether the list was capped at
    ``GDPRService.SAR_EMAIL_LOG_LIMIT`` (heavy-tenure case)."""

    truncated = serializers.BooleanField()
    total_count = serializers.IntegerField()
    entries = SarEmailLogEntrySerializer(many=True)


# ---------------------------------------------------------------------------
# Login history (axes)
# ---------------------------------------------------------------------------


class _SarAccessRecordBaseSerializer(serializers.Serializer):
    """Fields shared between AccessLog (successful) and
    AccessFailureLog (failed) records — both inherit from axes's
    ``AccessBase``."""

    username = serializers.CharField(allow_null=True)
    ip_address = serializers.IPAddressField(allow_null=True)
    user_agent = serializers.CharField(allow_blank=True)
    attempt_time = serializers.DateTimeField(allow_null=True)


class SarSuccessfulLoginSerializer(_SarAccessRecordBaseSerializer):
    """``axes.models.AccessLog`` — recorded on each successful login."""

    logout_time = serializers.DateTimeField(allow_null=True)


class SarFailedAttemptSerializer(_SarAccessRecordBaseSerializer):
    """``axes.models.AccessFailureLog`` — recorded on each failed
    login attempt. ``locked_out`` flags whether the attempt
    triggered an axes lockout."""

    locked_out = serializers.BooleanField()


class SarLoginHistorySectionSerializer(serializers.Serializer):
    """Envelope around the two login-history lists."""

    truncated = serializers.BooleanField()
    successful_logins = SarSuccessfulLoginSerializer(many=True)
    failed_attempts = SarFailedAttemptSerializer(many=True)


# ---------------------------------------------------------------------------
# Deletion requests
# ---------------------------------------------------------------------------


class SarDeletionRequestSummarySerializer(serializers.Serializer):
    """``apps.gdpr.models.DeletionRequest`` row. Token + IP are
    SKIPPED — neither is meaningful to the data subject in their
    own SAR (the token is consumed by the time the SAR is read).
    ``admin_decided_by`` FK skipped (other user's id)."""

    id = serializers.CharField()
    requested_at = serializers.DateTimeField()
    requested_email = serializers.EmailField()
    state = serializers.CharField()
    requires_admin_approval = serializers.BooleanField()
    email_confirmed_at = serializers.DateTimeField(allow_null=True)
    # AdminConfirmableMixin (admin-approval branch)
    admin_confirmed = serializers.BooleanField()
    admin_confirmed_at = serializers.DateTimeField(allow_null=True)
    admin_rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)
    executed_at = serializers.DateTimeField(allow_null=True)


# ---------------------------------------------------------------------------
# Top-level bundle
# ---------------------------------------------------------------------------


class SarBillingProfileSerializer(serializers.Serializer):
    """The member's SEPA Direct Debit mandate — the mandate reference +
    signing dates live only on ``payments.BillingProfile`` (not on Member),
    so Art. 15 surfaces them here."""

    billing_profile_id = serializers.CharField()
    payment_method = serializers.CharField()
    is_active = serializers.BooleanField()
    account_holder = serializers.CharField(allow_null=True)
    iban = serializers.CharField(allow_null=True)
    sepa_mandate_reference = serializers.CharField(allow_null=True)
    sepa_mandate_signed_at = serializers.DateField(allow_null=True)
    sepa_mandate_first_use_at = serializers.DateField(allow_null=True)
    sepa_mandate_paper_received_at = serializers.DateField(allow_null=True)
    notes = serializers.CharField(allow_null=True)


class SarUserInvitationSerializer(serializers.Serializer):
    """An invitation the co-op sent to the subject. ``has_token`` is a boolean
    presence flag — the raw accept-account token is a live capability and is
    never disclosed."""

    id = serializers.CharField()
    email = serializers.EmailField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True)
    has_token = serializers.BooleanField()


class SubjectAccessBundleSerializer(serializers.Serializer):
    """Top-level Art-15 bundle. Every section is always present —
    empty list or ``None`` when not applicable — so the React
    consumer doesn't need defensive guards. Bump
    :attr:`GDPRService.SAR_FORMAT_VERSION` on any breaking change."""

    format_version = serializers.IntegerField()
    exported_at = serializers.DateTimeField()
    subject = SarSubjectSerializer()

    account = SarAccountSerializer()
    member = SarMemberSerializer(allow_null=True)
    billing_profile = SarBillingProfileSerializer(allow_null=True)
    reseller = SarResellerSerializer(allow_null=True)

    consents = SarConsentRecordSerializer(many=True)
    coop_shares = SarCoopShareSerializer(many=True)
    subscriptions = SarSubscriptionSerializer(many=True)
    member_loans = SarMemberLoanSerializer(many=True)
    charge_schedules = SarChargeScheduleSerializer(many=True)
    reseller_orders = SarOrderSerializer(many=True)
    reseller_invoices = SarInvoiceResellerSerializer(many=True)

    email_log = SarEmailLogSectionSerializer()
    login_history = SarLoginHistorySectionSerializer()
    deletion_requests = SarDeletionRequestSummarySerializer(many=True)
    user_invitations = SarUserInvitationSerializer(many=True)


# ---------------------------------------------------------------------------
# Admin deletion-management endpoints
#
# These do NOT belong to the SAR bundle (different audience: the office,
# not the data subject). Kept in this file so all GDPR-shaped response
# contracts live together. The serializers exist purely to give
# drf-spectacular / orval a typed row shape — without them the views
# would have to use ``inline_serializer(... DictField())`` and the
# frontend would lose all per-field types.
# ---------------------------------------------------------------------------


class AdminPendingDeletionSerializer(serializers.Serializer):
    """One pending-deletion row for the admin inbox."""

    id = serializers.CharField()
    requested_email = serializers.EmailField()
    requested_at = serializers.DateTimeField()
    email_confirmed_at = serializers.DateTimeField(allow_null=True)
    current_user_email = serializers.EmailField(allow_null=True)
    # Per-row retention-obligation strings computed by
    # ``GDPRService.check_retention_blocks`` — empty list = ready
    # to approve right now.
    blockers = serializers.ListField(child=serializers.CharField())


class AdminPendingDeletionListSerializer(serializers.Serializer):
    """Envelope for ``gdpr_admin_pending_deletions_view``. Kept as
    ``{pending: [...]}`` (not a bare list) for symmetry with the
    existing deletion-log endpoint and to leave room for top-level
    metadata later (e.g. ``oldest_requested_at``)."""

    pending = AdminPendingDeletionSerializer(many=True)


class AdminDecidedDeletionSerializer(serializers.Serializer):
    """One decided-deletion row (REJECTED / EXECUTED / CANCELLED /
    EXPIRED). The list endpoint paginates via
    ``OptionalLimitOffsetPagination`` so this is the row schema; the
    paginator wraps in ``{count, results}`` at runtime."""

    id = serializers.CharField()
    state = serializers.CharField()
    requested_email = serializers.EmailField()
    requested_at = serializers.DateTimeField()
    # NULL for cancelled / expired (those rows were never reviewed
    # by an admin); set to ``executed_at`` for executions and
    # ``admin_confirmed_at`` for rejections.
    decided_at = serializers.DateTimeField(allow_null=True)
    decided_by_email = serializers.EmailField(allow_null=True)
    rejection_reason = serializers.CharField(allow_null=True)


class DeletionLogEntrySerializer(serializers.Serializer):
    """One ``apps.gdpr.models.DeletionLog`` row — the append-only
    record of executed personal-data deletions (kept so deletions
    can be replayed if a database backup is restored)."""

    id = serializers.CharField()
    user_email = serializers.EmailField()
    deleted_at = serializers.DateTimeField()
    description = serializers.CharField(allow_blank=True, allow_null=True)


class DeletionLogListSerializer(serializers.Serializer):
    """Envelope for ``gdpr_deletion_log_view`` — ``{deletions: [...]}``,
    symmetric with the ``{pending: [...]}`` envelope above."""

    deletions = DeletionLogEntrySerializer(many=True)


class MyDeletionStatusSerializer(serializers.Serializer):
    """User-facing "what's the state of my deletion request?" payload.
    All fields nullable so the same shape works for "never lodged" and
    "has a decided/in-flight request"."""

    state = serializers.CharField(allow_null=True)
    requested_at = serializers.DateTimeField(allow_null=True)
    admin_confirmed_at = serializers.DateTimeField(allow_null=True)
    admin_rejection_reason = serializers.CharField(allow_null=True)


# ---------------------------------------------------------------------------
# Art. 30 Record of Processing Activities (VVT)
#
# Schema mirror of the structured export built in
# ``gdpr_processing_activities_view``. The codebase facts come from
# ``apps/gdpr/vvt.py`` (PROCESSORS, the ``Activity`` dataclass via
# ``activity_dicts()``, TOMS); the controller block is assembled inline
# in the view from the live ``Tenant`` row. These serializers are
# schema-only — they give drf-spectacular / orval a typed shape instead
# of bare ``DictField()`` (which orval renders as ``any``).
# ---------------------------------------------------------------------------


class VvtControllerSerializer(serializers.Serializer):
    """Controller-identity block. Every key is always present (the view
    fills unknown fields with ``""`` so an auditor sees what's missing).
    Mirrors ``vvt.CONTROLLER_FIELDS``."""

    organisation_name = serializers.CharField(allow_blank=True)
    legal_form = serializers.CharField(allow_blank=True)
    registered_address = serializers.CharField(allow_blank=True)
    contact_email = serializers.CharField(allow_blank=True)
    contact_phone = serializers.CharField(allow_blank=True)
    data_protection_contact = serializers.CharField(allow_blank=True)
    dpo = serializers.CharField(allow_blank=True)
    supervisory_authority = serializers.CharField(allow_blank=True)


class VvtProcessorSerializer(serializers.Serializer):
    """One sub-processor / joint-controller row. Mirrors a
    ``vvt.PROCESSORS`` entry."""

    role = serializers.CharField()
    party = serializers.CharField()


class VvtActivitySerializer(serializers.Serializer):
    """One Art. 30(1) processing-activity record. Mirrors the
    ``vvt.Activity`` dataclass (serialised via ``activity_dicts()``)."""

    key = serializers.CharField()
    label = serializers.CharField()
    purpose = serializers.CharField()
    legal_basis = serializers.CharField()
    data_subjects = serializers.CharField()
    personal_data = serializers.CharField()
    source = serializers.CharField()
    recipients = serializers.CharField()
    third_country_transfers = serializers.CharField()
    retention = serializers.CharField()
    security_measures = serializers.CharField()
    code_locations = serializers.ListField(child=serializers.CharField())


class VvtMeasureSerializer(serializers.Serializer):
    """One Art. 32 Technical & Organisational Measure. Mirrors a
    ``vvt.TOMS`` entry."""

    label = serializers.CharField()
    value = serializers.CharField()


class ProcessingActivitiesSerializer(serializers.Serializer):
    """Top-level Art. 30 VVT export. ``schema_version`` /
    ``doc_reference`` are constants set by the view; ``generated_at``
    is the request time. Every section is always present."""

    schema_version = serializers.CharField()
    doc_reference = serializers.CharField()
    generated_at = serializers.DateTimeField()
    controller = VvtControllerSerializer()
    processors = VvtProcessorSerializer(many=True)
    activities = VvtActivitySerializer(many=True)
    technical_organisational_measures = VvtMeasureSerializer(many=True)


# ---------------------------------------------------------------------------
# Deletion preview (dry-run) — Art. 17 roadmap Step 5.
# ---------------------------------------------------------------------------


class PreviewFieldSerializer(serializers.Serializer):
    """One field a deletion would scrub, with its classification action
    (``pii_immediate`` / ``tombstone``) and a human "what it becomes"."""

    field = serializers.CharField()
    action = serializers.CharField()
    becomes = serializers.CharField()


class PreviewModelSerializer(serializers.Serializer):
    """One model a deletion would touch: its ``_meta.label``, how many rows
    change, and the field-level scrub list. Named ``scrubbed_fields`` (not
    ``fields``) to avoid shadowing DRF's internal ``Serializer.fields``."""

    model = serializers.CharField()
    row_count = serializers.IntegerField()
    scrubbed_fields = PreviewFieldSerializer(many=True)


class PreviewSideChannelSerializer(serializers.Serializer):
    """A non-field-classified scrub the deletion also performs (auditlog diffs,
    axes login records, on-disk SEPA / reseller-document exports)."""

    target = serializers.CharField()
    description = serializers.CharField()


class DeletionPreviewSerializer(serializers.Serializer):
    """Dry-run of what an Art-17 deletion would do to a user — persona,
    retention blockers and the per-model field list — without writing.
    Built by :meth:`apps.gdpr.services.GDPRService.preview_deletion`."""

    user_id = serializers.CharField()
    user_email = serializers.CharField()
    persona = serializers.CharField()
    has_member = serializers.BooleanField()
    has_reseller = serializers.BooleanField()
    can_anonymize_now = serializers.BooleanField()
    retention_blocks = serializers.ListField(
        child=serializers.CharField(), allow_empty=True
    )
    model_count = serializers.IntegerField()
    field_count = serializers.IntegerField()
    models = PreviewModelSerializer(many=True)
    side_channels = PreviewSideChannelSerializer(many=True)
