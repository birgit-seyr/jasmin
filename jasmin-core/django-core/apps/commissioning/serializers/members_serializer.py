from datetime import datetime, time
from decimal import Decimal

from rest_framework import serializers

from apps.authz.permissions import IsOffice, has_any_role
from apps.shared.pii_masking import MaskedIBANFieldMixin

from ..models import CoopShare, CoopShareTransfer, Member, Subscription
from .serializers_mixin import (
    AUDIT_READONLY_FIELDS,
    DeletableMixin,
    LinkedUserInfoMixin,
    MemberStringFieldMixin,
    ShareTypeVariationStringMixin,
    UserNameFieldMixin,
)

# The confirm/reject + cancellation timestamp columns live on the
# ``AdminConfirmableMixin`` shared across the member-domain models. They are
# owned exclusively by dedicated services / actions (the admin-confirm and
# admin-reject viewset actions, and the cancellation flow) — never by a generic
# create/PATCH, which would forge ``admin_confirmed`` or erase the office
# audit trail of when / why an application was refused or a membership exited.
# Kept as module constants so a field added to the mixin can't silently stay
# writable on one of the four serializers that must lock them.
ADMIN_CONFIRMATION_READONLY_FIELDS = (
    "admin_confirmed",
    "admin_confirmed_at",
    "admin_confirmed_by",
    "admin_rejected_at",
    "admin_rejection_reason",
)
CANCELLATION_READONLY_FIELDS = (
    "cancelled_at",
    "cancelled_effective_at",
    "cancelled_by",
)
# The ``WaitingListMixin`` state stamped exclusively by the waiting-list service
# methods (enqueue, notify_spot_available, confirm_spot, decline_spot,
# mark_as_expired). Only ``on_waiting_list`` stays writable — it is the intended
# flip flag. Left writable, these let a crafted API call stamp a waiting-list
# status (even deflating variation capacity via the SPOT_AVAILABLE/CONFIRMED
# occupancy clause) without ever hitting the waiting-list gate.
WAITING_LIST_READONLY_FIELDS = (
    "waiting_list_status",
    "notification_sent_at",
    "notification_expires_at",
    "response_received_at",
)

# Locks the office grid keeps, but the CSV ONBOARDING import must not — a
# tenant migrating off another system carries these over as historical fact.
# See ``MemberImportSerializer``. ``cancelled_by`` deliberately stays locked:
# it is an FK to the staff user who performed the cancellation, which has no
# meaning for a migrated row.
IMPORT_WRITABLE_FIELDS = ("member_number", "entry_date", "cancelled_effective_at")

# Locks the office grid lifts while the tenant's onboarding mode is on. See
# ``MemberOnboardingSerializer``.
ONBOARDING_WRITABLE_FIELDS = ("member_number", "entry_date")


class MemberEmailLogSerializer(serializers.Serializer):
    """Shape of one EmailLog row in the per-member "Sent emails" modal.

    Plain serializer (not ModelSerializer) — we deliberately project
    only the audit-relevant columns. The full EmailLog model also
    stores provider_message_id / error / related_object_* which the
    office UI doesn't surface today.
    """

    id = serializers.IntegerField()
    purpose = serializers.CharField()
    subject = serializers.CharField()
    template = serializers.CharField()
    status = serializers.CharField()
    sent_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class MemberSerializer(
    DeletableMixin,
    UserNameFieldMixin,
    LinkedUserInfoMixin,
    MaskedIBANFieldMixin,
    serializers.ModelSerializer,
):
    USER_NAME_FIELDS = ["admin_confirmed_by_name", "created_by_name"]
    linked_user_info = serializers.SerializerMethodField()
    active_subscriptions_count = serializers.IntegerField(read_only=True)
    # Sum of ``CoopShare.amount_of_coop_shares`` across this member's
    # shares, annotated by ``_build_member_queryset``. Used by the
    # office UI to display the share count next to the per-row
    # coopshares button and to paint the button red when a non-trial
    # member has zero shares (violates the GenG min-equity invariant
    # enforced by ``CoopShareService.assert_member_total_within_bounds``).
    coop_shares_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    # Count of the member's coop shares still awaiting office confirmation,
    # annotated by ``_build_member_queryset``. Drives the gold pending-count
    # badge on the office Members table's coop-shares button + the detail card.
    coop_shares_pending_count = serializers.IntegerField(read_only=True)
    # Latest cooperative-equity payback date across the member's coop shares
    # (``Max(coopshare.payback_due_date)``), annotated in
    # ``_build_member_queryset``. NOT a Member model column — it's derived from
    # the per-share snapshots so the office sees the member's effective payback
    # deadline on the list / detail without joining coop shares client-side.
    payback_due_date = serializers.DateField(read_only=True, allow_null=True)
    # The encrypted SEPA columns are accepted on WRITE (see Meta.extra_kwargs
    # write_only) but never echoed in full — bulk office reads return only a
    # masked representation (country code + last 4) so a list payload can't
    # exfiltrate every member's IBAN. Full editing happens on the dedicated
    # SEPA surface, not by reading the value back out of the grid.
    # Getters come from ``MaskedIBANFieldMixin``; Member stores the holder
    # name in ``account_owner`` (BillingProfile calls it ``account_holder``),
    # hence the source override and the explicit ``method_name``.
    MASKED_ACCOUNT_HOLDER_SOURCE = "account_owner"
    iban_masked = serializers.SerializerMethodField()
    account_owner_masked = serializers.SerializerMethodField(
        method_name="get_account_holder_masked"
    )

    class Meta:
        model = Member
        fields = "__all__"
        # Fields the office must NEVER set via a direct PATCH —
        # every one of these is owned by a dedicated service / flow
        # that maintains the legal or audit-trail invariants the
        # field encodes. Allowing them through a generic PATCH would
        # bypass those invariants and falsify the trail.
        #
        # Set by ``Member._post_confirm`` + the trial-conversion hook
        # (GenG §30 Eintrittsdatum + Mitgliedsnummer trio):
        #   member_number, entry_date
        #
        # Set by the consent flow (``ConsentService``) — editing
        # would falsify the GDPR audit trail of when the member
        # actually agreed:
        #   sepa_consent, privacy_consent, withdrawal_consent
        #
        # Set by ``cancel_member_with_coop_shares`` — bypassing it would
        # leave the Member ↔ CoopShare cancellation timestamps out
        # of sync (GenG §30 Austrittsdatum + §31 equity history):
        #   cancelled_at, cancelled_effective_at, cancelled_by
        #
        # Set by the admin-confirm action on the viewset (which
        # routes through ``AdminConfirmableMixin.confirm``) so the
        # ``_post_confirm`` side-effects fire atomically:
        #   admin_confirmed, admin_confirmed_at, admin_confirmed_by
        #
        # Set by the trial-conversion hook:
        #   trial_converted_at
        #
        # ``birth_date`` and ``is_trial`` are CONDITIONALLY locked —
        # see ``validate`` below. They're editable before
        # confirmation (correction window) and locked after.
        #
        # Annotated as a variable-length tuple so ``MemberImportSerializer``
        # can narrow it with a filtered ``tuple(...)``.
        read_only_fields: tuple[str, ...] = (
            # Historical values for these two are entered through
            # ``MemberOnboardingSerializer`` (tenant onboarding mode) or
            # ``MemberImportSerializer`` (CSV import).
            "member_number",
            "entry_date",
            "sepa_consent",
            "privacy_consent",
            "withdrawal_consent",
            *CANCELLATION_READONLY_FIELDS,
            *ADMIN_CONFIRMATION_READONLY_FIELDS,
            "trial_converted_at",
            # The member↔user link is role-bearing — a generic PATCH must
            # not relink/unlink it (that would strand Role.MEMBER on the old
            # user). Linking is owned by the create-path service; Member.save
            # keeps the role in sync if it ever does change.
            "user",
            # Set by ``ConsentService`` on withdrawal / re-consent.
            "consent_withdrawn_at",
            # Set by the cancellation flow after the confirmation email is sent.
            "cancellation_email_sent_at",
            *WAITING_LIST_READONLY_FIELDS,
            # ``created_by`` is stamped by ``MemberViewSet.create``.
            *AUDIT_READONLY_FIELDS,
        )
        # The decrypted IBAN / account_owner must never ride along on a bulk
        # read — they are accepted on write (the model's IBANValidator still
        # runs) but only surfaced masked via ``iban_masked`` /
        # ``account_owner_masked`` above.
        extra_kwargs = {
            "iban": {"write_only": True},
            "account_owner": {"write_only": True},
        }

    def validate(self, attrs):
        from apps.commissioning.errors import LockedAfterAdminConfirmation
        from apps.commissioning.services.trial_policy import (
            assert_member_creation_allowed,
        )

        # Fields that become legally fixed once a Member is admin-
        # confirmed. ``birth_date`` is biological + GDPR-classified
        # PII whose audit trail edits would falsify. ``is_trial`` is
        # the one-way trial → full conversion gate — flipping it back
        # on a confirmed member would orphan the assigned
        # Mitgliedsnummer / Eintrittsdatum and falsify the
        # Mitgliederliste. Belt-and-suspenders for the
        # ``disabled``-prop guard in Members.tsx — a tech-savvy office
        # user POSTing directly to the API would otherwise bypass the
        # UI lock.
        if self.instance is not None and self.instance.admin_confirmed:
            locked_fields = ("birth_date", "is_trial")
            offending: list[str] = []
            for field in locked_fields:
                if field not in attrs:
                    continue
                current = getattr(self.instance, field)
                if attrs[field] != current:
                    offending.append(field)
            if offending:
                raise LockedAfterAdminConfirmation(offending)

        # Only validate ``is_trial`` on creation OR when the office flips
        # an existing member's trial flag back on. Toggling trial OFF
        # (trial → real) is unconditionally allowed — tenants who later
        # turn off the trial-subscription feature can still convert
        # their existing trial members to full ones.
        is_trial = attrs.get("is_trial", getattr(self.instance, "is_trial", False))
        was_trial = getattr(self.instance, "is_trial", False)
        if is_trial and not was_trial:
            assert_member_creation_allowed(is_trial=True)
        return super().validate(attrs)


class MemberImportSerializer(MemberSerializer):
    """``MemberSerializer`` for the CSV onboarding import — ``member_number``
    writable.

    A tenant migrating off another system brings its existing Mitgliedsnummern
    with it: the number is printed on the members' paperwork, and every
    follow-up onboarding import (subscriptions, coop shares, SEPA mandates)
    resolves its member by ``member_number`` as the natural key. Letting the
    server re-assign numbers on confirmation would renumber the whole
    Mitgliederliste and break those references.

    Only the import path unlocks the column — the office grid keeps it
    read-only, since renumbering a live member falsifies the Mitgliederliste.
    Making the field writable also makes DRF attach the model's
    ``unique=True`` validator, so a collision (with an existing member or with
    an earlier row of the same file) is reported as a clean per-row error
    instead of an ``IntegrityError``.

    A row that leaves the cell blank keeps the normal behaviour: no number
    until admin confirmation, then ``Member._post_confirm`` assigns
    ``Max(member_number) + 1`` — which sits above the imported block, so the
    two numbering sources don't collide.
    """

    class Meta(MemberSerializer.Meta):
        read_only_fields = tuple(
            field_name
            for field_name in MemberSerializer.Meta.read_only_fields
            if field_name not in IMPORT_WRITABLE_FIELDS
        )

    def validate(self, attrs):
        from django.utils import timezone

        from apps.commissioning.errors import MemberNumberNotAllowedForTrial

        # Trial members are not Mitglieder under GenG, so they hold no
        # Mitgliedsnummer (see ``Member._post_confirm``). Refuse the row rather
        # than persist a number that the conversion hook would then leave in
        # place forever.
        if attrs.get("member_number") is not None and attrs.get("is_trial", False):
            raise MemberNumberNotAllowedForTrial(
                "A trial member cannot carry a member number — leave the "
                "column blank for trial rows."
            )

        # Austrittsdatum (GenG §30). The office migrating a departed member has
        # ONE date on paper — the exit date — so that is the only column the
        # template offers. ``cancelled_at`` is derived from it because the two
        # are read by DIFFERENT consumers and must never disagree:
        #
        #   * ``cancelled_at`` marks the member as departed — it drives the
        #     cancelled-member count in ``services.statistics``, the
        #     ``MemberAlreadyCancelled`` guard on the cancel action, and the
        #     struck-through row in the office grid.
        #   * ``cancelled_effective_at`` drives the 10-year GenG/HGB/AO
        #     retention sweep in ``apps.gdpr.tasks``.
        #
        # An exit date on its own would leave a member the retention sweep
        # already targets while they still read as CURRENT everywhere else —
        # uncounted as cancelled, not struck through, and still cancellable.
        # Stamping the exit date's local midnight reads as "recorded as of the
        # exit date", the honest reading for a migrated row.
        #
        # ``cancelled_at`` itself stays read-only (it is not in
        # ``IMPORT_WRITABLE_FIELDS``), so the guard below is defensive: it keeps
        # the derivation from clobbering a caller-supplied value if that ever
        # changes.
        effective = attrs.get("cancelled_effective_at")
        if effective is not None and attrs.get("cancelled_at") is None:
            attrs["cancelled_at"] = timezone.make_aware(
                datetime.combine(effective, time.min),
                timezone.get_current_timezone(),
            )
        return super().validate(attrs)


class MemberOnboardingSerializer(MemberSerializer):
    """``MemberSerializer`` for office writes while the tenant's onboarding mode
    is on — ``member_number`` and ``entry_date`` writable.

    During onboarding the office types in members that already exist on paper,
    with the Mitgliedsnummer and Eintrittsdatum (GenG §30) they already carry.
    Outside onboarding both stay server-stamped by ``Member._post_confirm`` /
    the trial-conversion hook, because renumbering a live member or rewriting
    an admission date falsifies the Mitgliederliste.

    ``MemberViewSet.get_serializer_class`` returns this class for
    create/update/partial_update only when the flag is on; the schema keeps
    documenting ``MemberSerializer``. Writable ``member_number`` makes DRF
    attach the model's ``unique=True`` validator, so a duplicate number is a
    clean 400 instead of an ``IntegrityError``.
    """

    class Meta(MemberSerializer.Meta):
        read_only_fields = tuple(
            field_name
            for field_name in MemberSerializer.Meta.read_only_fields
            if field_name not in ONBOARDING_WRITABLE_FIELDS
        )

    def validate(self, attrs):
        from apps.commissioning.errors import MemberNumberNotAllowedForTrial

        # Trial members are not Mitglieder under GenG and hold no
        # Mitgliedsnummer (see ``MemberImportSerializer.validate``). A PATCH may
        # omit ``is_trial``, so fall back to the stored flag.
        is_trial = attrs.get("is_trial", getattr(self.instance, "is_trial", False))
        if attrs.get("member_number") is not None and is_trial:
            raise MemberNumberNotAllowedForTrial(
                "A trial member cannot carry a member number."
            )
        return super().validate(attrs)


class MemberSelfReadSerializer(MaskedIBANFieldMixin, serializers.ModelSerializer):
    """Member-role read of their OWN Member row on ``MemberViewSet``
    (list/retrieve).

    The office ``MemberSerializer`` serialises ``fields = "__all__"`` plus
    admin/creator name lookups and a ``linked_user_info`` snapshot — which
    exposes office-internal data a member must never read about themselves:
    the free-text ``note`` and the admin confirm/reject audit trail (who
    confirmed/rejected them, when, and why). ``read_only_fields`` only
    controls writability, not read exposure, so the office serializer leaks
    these on a member self-read. This serializer drops them; member
    self-EDIT still goes through the dedicated ``MyMemberDataView``
    allowlist, so nothing here needs to be writable."""

    # The encrypted SEPA columns (iban / account_owner) decrypt
    # transparently on access, so a plain ModelSerializer would echo them as
    # PLAINTEXT on self-read. Mirror MyMemberDataReadSerializer: expose only
    # boolean "stored" indicators and exclude the plaintext (+ sepa_consent).
    # Getters come from ``MaskedIBANFieldMixin``; Member stores the holder name
    # in ``account_owner``, hence the source override + explicit ``method_name``.
    MASKED_ACCOUNT_HOLDER_SOURCE = "account_owner"
    iban_stored = serializers.SerializerMethodField()
    account_owner_stored = serializers.SerializerMethodField(
        method_name="get_account_holder_stored"
    )

    class Meta:
        model = Member
        # Drop the office-internal columns; the SerializerMethodFields the
        # office serializer adds (linked_user_info, admin_confirmed_by_name,
        # created_by_name) are simply not declared here, so they never
        # appear. Everything else is the member's own data (Art. 15). The
        # high-sensitivity SEPA columns are excluded — see the *_stored fields.
        exclude = (
            "note",
            "admin_confirmed_at",
            "admin_confirmed_by",
            "admin_rejected_at",
            "admin_rejection_reason",
            "iban",
            "account_owner",
            "sepa_consent",
        )


class MemberCreateRequestSerializer(MemberSerializer):
    """Schema-only request body of ``MemberViewSet.create``: the Member
    fields plus the optional ``notify_user`` flag, which the view strips
    before validating with the plain :class:`MemberSerializer`."""

    notify_user = serializers.BooleanField(required=False, default=False)


class SubscriptionSerializer(
    UserNameFieldMixin,
    MemberStringFieldMixin,
    ShareTypeVariationStringMixin,
    serializers.ModelSerializer,
):
    """Read/write serializer for `Subscription`.

    The read-only ``*_name`` / ``member_*`` fields are resolved via DRF
    ``source=`` and ``SerializerMethodField``, not queryset annotations, so the
    viewset queryset stays lean. Callers must keep the matching
    ``select_related`` chain (see ``_build_subscription_queryset``) to avoid N+1.
    """

    display_id = serializers.SerializerMethodField(read_only=True)
    # Renewal-chain label (``1`` / ``1a`` / ``1b`` …). ``subscription_number``
    # + ``renewal_generation`` ride along via ``fields="__all__"``; sort the
    # abos table by that pair (NOT this string) for ``1, 1a, 1b, 2, …`` order.
    renewal_display_id = serializers.CharField(read_only=True)
    # ``member`` and ``share_type_variation`` are writable id strings on
    # input; on output their id strings are emitted via ``to_representation``
    # (the plain ``CharField`` would otherwise stringify the related object).
    member = serializers.CharField()
    share_type_variation = serializers.CharField()

    member_first_name = serializers.CharField(
        source="member.first_name", read_only=True
    )
    member_last_name = serializers.CharField(source="member.last_name", read_only=True)
    member_string = serializers.SerializerMethodField(read_only=True)
    email = serializers.CharField(source="member.email", read_only=True)
    pickup_name = serializers.CharField(
        source="member.pickup_name",
        allow_null=True,
        required=False,
        read_only=True,
    )
    # The MEMBER's own cancellation stamp (not the subscription's). Drives the
    # struck-through / muted row styling on Abos.tsx for abos of an exited
    # member, mirroring the members-table treatment. NULL when the member is
    # active. ``member`` is already select_related, so this is free.
    member_cancelled_at = serializers.DateTimeField(
        source="member.cancelled_at", read_only=True, allow_null=True
    )
    share_type_variation_string = serializers.SerializerMethodField(read_only=True)
    share_type_name = serializers.CharField(
        source="share_type_variation.share_type.name",
        read_only=True,
    )
    share_type_variation_size = serializers.CharField(
        source="share_type_variation.size", read_only=True
    )
    # DeliveryCycleOptions code (WEEKLY/ODD_WEEKS/…) of the share type — the
    # frontend localizes it. Same select_related("share_type_variation__share_type")
    # chain as share_type_name, so no extra query.
    delivery_cycle = serializers.CharField(
        source="share_type_variation.share_type.delivery_cycle",
        read_only=True,
        allow_null=True,
    )
    # Drives the "on-off" chip on the abos table — this variation bills only the
    # deliveries the member opts into (per-delivery semantics), not every period.
    requires_optin = serializers.BooleanField(
        source="share_type_variation.requires_optin",
        read_only=True,
    )
    payment_cycle_name = serializers.CharField(
        source="payment_cycle.choice", read_only=True
    )
    delivery_day_number = serializers.IntegerField(
        source="default_delivery_station_day.delivery_day.day_number",
        read_only=True,
        allow_null=True,
    )
    delivery_station_name = serializers.CharField(
        source="default_delivery_station_day.delivery_station.short_name",
        read_only=True,
        allow_null=True,
    )
    USER_NAME_FIELDS = [
        "admin_confirmed_by_name",
        "created_by_name",
        "cancelled_by_name",
    ]
    # Surface "who cancelled" + "why" on the row so ``Abos.tsx``'s
    # ``LoggingModal`` (and any downstream reader) can show the full
    # cancellation context — see ``SubscriptionService.cancel_subscription``.
    cancellation_reason = serializers.CharField(
        read_only=True,
        allow_null=True,
    )

    is_trial = serializers.BooleanField()
    # Bounded like the member self-service and CSV import paths: redeclaring
    # these drops the model-derived validators. 0 deliveries bill nothing, and a
    # negative price produces negative or no charges. A price of 0 stays valid
    # (e.g. a free trial).
    quantity = serializers.IntegerField(min_value=1)
    price_per_delivery = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0")
    )
    notice_period_duration = serializers.IntegerField(allow_null=True, read_only=True)

    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True, required=False)
    can_be_deleted = serializers.SerializerMethodField(read_only=True)
    # Materialised ShareDelivery count for this subscription, excluding
    # joker-taken weeks. Annotated in ``_build_subscription_queryset`` —
    # rationale + the on-off-opt-out caveat live next to that annotation.
    # Backs the "Lieferungen" column on Abos.tsx.
    deliveries_count = serializers.IntegerField(read_only=True)

    # Joker badge "(Jokers taken X / Y)" on the member-detail subscriptions
    # card. ``jokers_taken`` (X) is annotated in ``_build_subscription_queryset``
    # (Count of ShareDelivery rows with ``joker_taken=True``). ``amount_of_jokers``
    # (Y) is the allowance, read from the subscription's share type — the
    # per-share-type joker system is the source of truth (NOT the tenant-wide
    # ``default_amount_of_jokers``). select_related already covers this path.
    jokers_taken = serializers.IntegerField(read_only=True)
    amount_of_jokers = serializers.IntegerField(
        source="share_type_variation.share_type.amount_of_jokers",
        read_only=True,
    )
    # Donation-joker counterparts (mirrors the regular joker badge).
    donation_jokers_taken = serializers.IntegerField(read_only=True)
    amount_of_donation_jokers = serializers.IntegerField(
        source="share_type_variation.share_type.amount_of_donation_jokers",
        read_only=True,
    )

    # Cancellation deadline = ``valid_until - min_weeks_to_cancel_before_ending``
    # weeks. Pre-computed here so the Abos.tsx ``automatically_renewed_at``
    # column doesn't redo dayjs parse + subtract per row per render.
    # Returns ISO ``YYYY-MM-DD`` for the frontend's ``formatDate`` to
    # consume; ``None`` when the column should render blank (trial
    # subscription, missing ``valid_until``, deadline before
    # ``valid_from``, or the tenant has ``subscriptions_are_auto_renewed``
    # off — though in the off case the column itself is hidden, so the
    # field is a no-op).
    #
    # ``min_weeks_to_cancel_before_ending`` is fetched once per response
    # via the serializer context (see
    # ``SubscriptionViewSet.get_serializer_context``) rather than
    # ``TenantSettings.get_current_settings`` per row.
    automatically_renewed_at = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Subscription
        fields = "__all__"
        # ``admin_rejected_at`` / ``admin_rejection_reason`` are
        # stamped by ``SubscriptionViewSet.reject`` — must not be
        # editable via a plain PATCH, same lockdown as the existing
        # admin-confirm fields.
        read_only_fields = (
            # Server-inferred at enqueue (which capacity gate was full) — never
            # client-set. See ``SubscriptionService._infer_waiting_list_reason``.
            "waiting_list_reason",
            # The rest of the waiting-list state. ``on_waiting_list`` stays
            # writable and is routed through ``_enqueue_on_waiting_list`` (and
            # thus the ``allows_waiting_list_for_subscriptions`` gate).
            *WAITING_LIST_READONLY_FIELDS,
            # Renewal-chain identity: ``Subscription.save`` assigns the number
            # (inherited along a renewal chain) and ``services.renewal`` sets
            # ``previous_subscription``. A client-set predecessor or number would
            # splice a draft into another member's chain.
            "subscription_number",
            "renewal_generation",
            "previous_subscription",
            # ``created_by`` is stamped by ``SubscriptionViewSet.create``.
            *AUDIT_READONLY_FIELDS,
            # Admin-confirm/reject 5-tuple — stamped exclusively by the
            # ``POST /subscriptions/{id}/confirm/`` + ``/reject/`` actions (the
            # confirm action runs the capacity backstop, materialises
            # shares/deliveries/charges and the GenG admission cascade). Left
            # writable, a plain create/PATCH could forge ``admin_confirmed=True``
            # on a draft and skip that whole machinery (validate() only locks
            # ALREADY-confirmed rows).
            *ADMIN_CONFIRMATION_READONLY_FIELDS,
            # Cancellation triplet — stamped exclusively by
            # ``SubscriptionService.cancel_subscription`` via the
            # ``POST /api/commissioning/subscriptions/{id}/cancel/``
            # action. Letting these through a plain PATCH would:
            #   * leave ``cancelled_by`` NULL → no audit trail
            #   * skip deletion of future ShareDeliveries
            #   * skip dropping PLANNED ChargeSchedule rows
            #   * skip ``recompute_shares`` and serializer-side
            #     ``can_be_deleted`` / membership-status checks
            # The frontend Abos cancel button MUST hit the action
            # endpoint; the lockdown here is the belt-and-braces
            # guard against direct API calls.
            *CANCELLATION_READONLY_FIELDS,
        )

    def validate(self, attrs):
        # 1. Hard lockdown for confirmed subscriptions.
        #
        # Once a subscription is ``admin_confirmed``, NO field is editable
        # via a plain PATCH. The only legitimate mutation is going
        # through ``POST /abos/{id}/cancel/`` (which routes around the
        # serializer entirely — see ``SubscriptionService.cancel_subscription``
        # and the lockdown of the ``cancelled_*`` triplet in
        # ``read_only_fields`` above). The Abos.tsx UI already hides the
        # edit + delete buttons on confirmed rows; this is the
        # belt-and-braces guard against direct API calls.
        if self.instance is not None and self.instance.admin_confirmed and attrs:
            from apps.commissioning.errors import LockedAfterAdminConfirmation

            offending = sorted(attrs.keys())
            raise LockedAfterAdminConfirmation(offending)

        # 2. Trial-policy check.
        #
        # Fires only when ``is_trial`` is going to land True on the row
        # — i.e. either a new subscription with ``is_trial=True`` or an
        # existing one being flipped on. A row left at ``is_trial=False``
        # never trips this guard.
        #
        # ``Subscription.member`` is structurally never None (NOT NULL
        # FK) so we pass the resolved Member
        # instance — TrialPolicy uses ``member.is_trial`` to decide
        # whether the "only full members can hold trial subs" branch
        # applies.
        is_trial = attrs.get("is_trial", getattr(self.instance, "is_trial", False))
        was_trial = getattr(self.instance, "is_trial", False)
        if is_trial and not was_trial:
            from apps.commissioning.models import Member
            from apps.commissioning.services.trial_policy import (
                assert_subscription_creation_allowed,
            )

            member_id = attrs.get("member") or (
                self.instance.member_id if self.instance else None
            )
            member = Member.objects.filter(pk=member_id).first() if member_id else None
            assert_subscription_creation_allowed(is_trial=True, member=member)

        # 3. Start-date lead time.
        #
        # ``valid_from`` can't be earlier than ``now +
        # min_weeks_from_creation_to_start_delivery`` weeks, snapped to the
        # next Monday (valid_from is always a Monday). Only enforced when
        # valid_from is being set or changed — re-saving an existing draft
        # whose (once-valid) start has since slipped into the lead window
        # shouldn't be blocked. Mirrors the office UI date-picker floor
        # (``useSubscriptionTerm`` on the frontend). Skipped for an office write
        # while the tenant is in onboarding mode (see
        # ``_skips_start_lead_time``); the other checks still apply.
        valid_from = attrs.get("valid_from")
        if (
            valid_from is not None
            and (self.instance is None or self.instance.valid_from != valid_from)
            and not self._skips_start_lead_time()
        ):
            from datetime import timedelta

            from django.utils import timezone

            from apps.commissioning.constants import (
                get_min_weeks_from_creation_to_start_delivery,
            )
            from apps.commissioning.errors import SubscriptionStartTooSoon
            from apps.commissioning.utils.iso_week_utils import next_monday

            min_weeks = get_min_weeks_from_creation_to_start_delivery()
            if min_weeks:
                base = timezone.localdate() + timedelta(weeks=min_weeks)
                earliest = next_monday(base)
                if valid_from < earliest:
                    raise SubscriptionStartTooSoon(
                        valid_from=valid_from,
                        earliest=earliest,
                        min_weeks=min_weeks,
                    )

        # 4. End-date requirement.
        #
        # Forbid open-ended subscriptions. A sub with no ``valid_until``
        # materialises no ShareDeliveries (the materialiser skips it) and so
        # generates only zero-amount charges — it silently never bills. Check the
        # RESULTING value so this covers a create that omits the field AND a PATCH
        # that clears it; a partial PATCH that doesn't touch ``valid_until`` keeps
        # the instance's existing end date. The office UI already requires it;
        # this is the backstop for direct API calls / imports.
        final_valid_until = attrs.get(
            "valid_until", getattr(self.instance, "valid_until", None)
        )
        if final_valid_until is None:
            from apps.commissioning.errors import OpenEndedSubscriptionNotAllowed

            raise OpenEndedSubscriptionNotAllowed(
                "A subscription must have an end date (valid_until); open-ended "
                "subscriptions are not allowed.",
                field="valid_until",
            )

        # 5. Solidarity-pricing floor (``services.solidarity_pricing``, shared
        # with the waiting-list offer).
        #
        # Checked on create, and on an update whenever an input to the floor
        # changes: the price itself (whenever it is re-sent), the variation
        # (a different floor), the start date (a different price window) or
        # ``is_trial`` (the trial pair). When the update doesn't re-send the
        # price, the STORED price is checked against the new floor. An update
        # touching none of these leaves the check alone, so an unrelated edit of
        # an older draft is not blocked by a floor raised after it was priced.
        from django.utils import timezone

        from apps.commissioning.services.solidarity_pricing import (
            assert_price_meets_solidarity_floor,
        )

        instance = self.instance
        floor_inputs_changed = instance is None or (
            "price_per_delivery" in attrs
            or (
                "share_type_variation" in attrs
                and attrs["share_type_variation"] != instance.share_type_variation_id
            )
            or ("valid_from" in attrs and attrs["valid_from"] != instance.valid_from)
            or ("is_trial" in attrs and attrs["is_trial"] != instance.is_trial)
        )
        if floor_inputs_changed:
            assert_price_meets_solidarity_floor(
                price=attrs.get(
                    "price_per_delivery", getattr(instance, "price_per_delivery", None)
                ),
                share_type_variation_id=attrs.get("share_type_variation")
                or getattr(instance, "share_type_variation_id", None),
                effective_date=attrs.get("valid_from")
                or getattr(instance, "valid_from", None)
                or timezone.localdate(),
                is_trial=is_trial,
            )

        return super().validate(attrs)

    def _skips_start_lead_time(self) -> bool:
        """Whether this write may start before the lead time, in the past too.

        Only for an office user while the tenant is in onboarding mode, where
        the office enters subscriptions that are already running.
        ``SubscriptionViewSet`` puts ``onboarding_mode`` into the context from
        the tenant flag; member self-service builds this serializer without it,
        and the role check keeps the skip office-only for any other caller.
        """
        if not self.context.get("onboarding_mode"):
            return False
        return has_any_role(self.context.get("request"), *IsOffice.required_roles)

    def to_representation(self, instance):
        # ``member`` / ``share_type_variation`` are declared as plain writable
        # ``CharField()`` (the write API expects flat ids). On output emit their
        # id strings — the default ``CharField`` would stringify the related
        # model object instead.
        data = super().to_representation(instance)
        data["member"] = instance.member_id
        data["share_type_variation"] = instance.share_type_variation_id
        return data

    def get_automatically_renewed_at(self, obj) -> str | None:
        """Cancellation deadline = valid_until - N weeks. None when blank.

        Computed server-side so Abos.tsx doesn't compute it per row per render
        and the "when does this column light up" rule lives in one place.

        Skip cases (return None):
          * ``is_trial`` — trial subs don't auto-renew (see TrialPolicy).
          * No ``valid_until`` — open-ended subs have no deadline.
          * The deadline would fall before ``valid_from`` — short terms
            (4-week trials, half-season subs) shouldn't surface a
            deadline that pre-dates the subscription itself.
        Pass-through cases:
          * ``min_weeks_to_cancel_before_ending`` unset / 0 → return
            ``valid_until`` itself; the column means "you must cancel
            before this date" and a 0-week window collapses to
            valid_until.
        """
        from datetime import timedelta

        if obj.is_trial:
            return None
        if obj.valid_until is None:
            return None

        # ``min_weeks_to_cancel_before_ending`` is shipped on the
        # serializer context by the viewset so it's fetched once per
        # response instead of via ``TenantSettings.get_current_settings``
        # per row. None → tenant setting unset → display raw valid_until.
        weeks = self.context.get("min_weeks_to_cancel_before_ending")
        if not weeks or weeks <= 0:
            return obj.valid_until.isoformat()

        deadline = obj.valid_until - timedelta(weeks=weeks)
        if obj.valid_from and deadline < obj.valid_from:
            return None
        return deadline.isoformat()

    def get_can_be_deleted(self, obj) -> bool:
        # Any admin-confirmed subscription is immutable on the delete
        # path — the only legitimate way to end one is the cancel
        # action (see ``SubscriptionService.cancel_subscription``).
        # That includes confirmed-but-not-yet-started rows: only drafts
        # can be deleted.
        if obj.admin_confirmed:
            return False
        return True

    def get_display_id(self, obj) -> str:
        """Get human-readable display ID"""
        return obj.get_display_id() if hasattr(obj, "get_display_id") else obj.id


class CoopShareSerializer(
    UserNameFieldMixin, MemberStringFieldMixin, serializers.ModelSerializer
):
    """``member_string`` is a human-readable label, same contract as
    :class:`MemberLoanSerializer`. It must be a ``SerializerMethodField``:
    a plain ``CharField(read_only=True)`` has no matching model attribute,
    so DRF would silently drop the key from every payload (SkipField) while
    the schema declares it present."""

    member_string = serializers.SerializerMethodField(read_only=True)
    USER_NAME_FIELDS = ["admin_confirmed_by_name"]

    class Meta:
        model = CoopShare
        fields = "__all__"
        # These are owned by dedicated services (cancel_member_with_coop_shares
        # / the admin-confirm action) and the GenG §30/§31 audit trail — a generic
        # office PATCH must never set them (would falsify cancelled_by/audit and
        # let admin_confirmed be forged). Mirrors MemberSerializer.read_only_fields.
        # Annotated as a variable-length tuple so ``CoopShareOnboardingSerializer``
        # can narrow it with a filtered ``tuple(...)``.
        read_only_fields: tuple[str, ...] = (
            *CANCELLATION_READONLY_FIELDS,
            *ADMIN_CONFIRMATION_READONLY_FIELDS,
            # Historical payment dates are entered through
            # ``CoopShareOnboardingSerializer`` (tenant onboarding mode).
            "paid_at",
            # Snapshotted server-side at member cancellation. ``paid_back_date``
            # is intentionally NOT here — the office stamps it when the share is
            # returned.
            "payback_due_date",
            # Written only by the transfer service.
            "transfer",
            "settled_by_transfer",
        )

    def validate_amount_of_coop_shares(self, value):
        from ..services.coop_share_service import CoopShareService

        # The whole-Geschäftsanteil rule shared with the CSV import and member
        # self-service. Only a new or CHANGED amount is checked: the office grid
        # re-sends the whole row, and rows stored before this rule existed must
        # stay editable (note, payback) without first rewriting their amount.
        if self.instance is None or value != self.instance.amount_of_coop_shares:
            CoopShareService.assert_valid_amount(value)
        return value

    def validate(self, attrs):
        from ..services.coop_share_service import CoopShareService

        # Once confirmed, the committed terms are part of the GenG register.
        # ``CoopShareViewSet.perform_update`` re-applies this under the row lock.
        if self.instance is not None:
            CoopShareService.apply_confirmed_share_edit_lock(self.instance, attrs)
        return super().validate(attrs)


class CoopShareOnboardingSerializer(CoopShareSerializer):
    """``CoopShareSerializer`` for office writes while the tenant's onboarding
    mode is on — ``paid_at`` writable, so shares paid in before Jasmin carry
    their payment date.

    ``CoopShareViewSet.get_serializer_class`` returns this class for
    create/update/partial_update only when the flag is on; the schema keeps
    documenting ``CoopShareSerializer``. ``paid_at`` is a DateTimeField but
    the grid sends a calendar date: it is stored as local midnight of that day,
    the same shape the transfer service writes.
    """

    class Meta(CoopShareSerializer.Meta):
        read_only_fields = tuple(
            field_name
            for field_name in CoopShareSerializer.Meta.read_only_fields
            if field_name != "paid_at"
        )

    def validate_paid_at(self, value: datetime | None) -> datetime | None:
        from django.utils import timezone

        if value is None:
            return None
        paid_on = timezone.localtime(value).date()
        return timezone.make_aware(datetime.combine(paid_on, time.min))


class AdminConfirmationRequestSerializer(serializers.Serializer):
    """Optional body of ``POST members/{id}/confirm/`` and
    ``POST coop_shares/{id}/confirm/``. ``confirmed_at`` dates a confirmation
    that happened before the tenant used Jasmin; the viewsets accept it only
    while the tenant's onboarding mode is on."""

    confirmed_at = serializers.DateField(required=False, allow_null=True)


class CoopShareTransferRequestSerializer(serializers.Serializer):
    """Body of ``POST /api/commissioning/coop_shares/transfer/``. ``note`` is kept
    on the transfer record; ``from_member_note`` / ``to_member_note`` become the
    notes of the negative row created for the giving member and the positive row
    created for the receiving member. ``confirm_member_cancellation`` must be true
    when the transfer leaves the giving member without shares, which cancels the
    membership."""

    from_member = serializers.PrimaryKeyRelatedField(queryset=Member.objects.all())
    to_member = serializers.PrimaryKeyRelatedField(queryset=Member.objects.all())
    amount_of_coop_shares = serializers.IntegerField(min_value=1)
    transfer_date = serializers.DateField()
    note = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=2000
    )
    from_member_note = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=2000
    )
    to_member_note = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=2000
    )
    confirm_member_cancellation = serializers.BooleanField(
        required=False, default=False
    )


class CoopShareTransferSerializer(serializers.ModelSerializer):
    """A recorded coop share transfer. ``from_member_cancelled`` (passed in the
    serializer context by the transfer action) is true when the transfer left the
    giving member without shares and cancelled the membership."""

    from_member_cancelled = serializers.SerializerMethodField()

    class Meta:
        model = CoopShareTransfer
        fields = [
            "id",
            "from_member",
            "to_member",
            "amount_of_coop_shares",
            "transfer_date",
            "note",
            "created_at",
            "created_by",
            "from_member_cancelled",
        ]
        read_only_fields = [
            "id",
            "from_member",
            "to_member",
            "amount_of_coop_shares",
            "transfer_date",
            "note",
            "created_at",
            "created_by",
        ]

    def get_from_member_cancelled(self, obj: CoopShareTransfer) -> bool:
        return bool(self.context.get("from_member_cancelled", False))


class MemberLoanSerializer(MemberStringFieldMixin, serializers.ModelSerializer):
    """Per-member loan entry. Mirrors :class:`CoopShareSerializer` —
    ``member_string`` is a human-readable label the office UI shows
    next to the row when the table is filtered to "all members".
    """

    member_string = serializers.SerializerMethodField(read_only=True)

    class Meta:
        from ..models.members import MemberLoan

        model = MemberLoan
        fields = "__all__"
        # Lock the audit/confirmation stamps — a plain create/PATCH must not be
        # able to forge who approved/created the loan or when. ``created_by`` is
        # stamped server-side in the viewset's ``perform_create``. Mirrors
        # ``CoopShareSerializer.read_only_fields``.
        read_only_fields = (
            *ADMIN_CONFIRMATION_READONLY_FIELDS,
            "created_by",
            "created_at",
        )


class MemberEmailSerializer(serializers.Serializer):
    """One recipient in a subscription-based email distribution list."""

    email = serializers.EmailField()
    first_name = serializers.CharField(
        allow_blank=True, allow_null=True, required=False
    )
    last_name = serializers.CharField(allow_blank=True, allow_null=True, required=False)


class SubscriptionMemberEmailsResponseSerializer(serializers.Serializer):
    """Distinct member e-mails for a subscription filter (AbosEmails page)."""

    count = serializers.IntegerField()
    members = MemberEmailSerializer(many=True)
