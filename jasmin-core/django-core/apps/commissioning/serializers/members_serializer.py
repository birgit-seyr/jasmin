from rest_framework import serializers

from apps.shared.pii_masking import MaskedIBANFieldMixin

from ..models import CoopShare, Member, Subscription
from .serializers_mixin import (
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
        read_only_fields = (
            "member_number",
            # ``entry_date`` (GenG §30 Eintrittsdatum) is normally server-stamped
            # and NOT office-editable. It is deliberately writable here so the
            # office can hand-set it during MANUAL MEMBER TRANSFER (migrating
            # members from another system with historical admission dates). Two
            # gates stand in for the removed read-only lock: the office role is
            # required to PATCH a member at all, and the members grid keeps the
            # cell disabled (out of the save payload) unless the operator turns
            # on the explicit "händische Übertragung" toggle.
            "sepa_consent",
            "privacy_consent",
            "withdrawal_consent",
            *CANCELLATION_READONLY_FIELDS,
            *ADMIN_CONFIRMATION_READONLY_FIELDS,
            "trial_converted_at",
            # MEM-7: the member↔user link is role-bearing — a generic PATCH must
            # not relink/unlink it (that would strand Role.MEMBER on the old
            # user). Linking is owned by the create-path service; Member.save
            # keeps the role in sync if it ever does change.
            "user",
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

    # MEM-6: the encrypted SEPA columns (iban / account_owner) decrypt
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

    The read-only ``*_name`` / ``member_*`` fields used to come from
    `.annotate()` calls in the viewset queryset; they're now resolved
    via DRF ``source=`` and ``SerializerMethodField`` so the viewset
    queryset stays lean. Callers must keep the matching ``select_related``
    chain (see ``_build_subscription_queryset``) to avoid N+1.
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
    quantity = serializers.IntegerField()
    price_per_delivery = serializers.DecimalField(max_digits=8, decimal_places=2)
    notice_period_duration = serializers.IntegerField(allow_null=True, read_only=True)

    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True, required=False)
    can_be_deleted = serializers.SerializerMethodField(read_only=True)
    # Materialised ShareDelivery count for this subscription, excluding
    # joker-taken weeks. Annotated in ``_build_subscription_queryset`` —
    # rationale + the on-off-opt-out caveat live next to that annotation.
    # Backs the "Lieferungen" column on Abos.tsx (replaces the prior
    # frontend calendar-arithmetic count).
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
        # admin-confirm fields. See migration 0023 for the field
        # addition.
        read_only_fields = (
            # Server-inferred at enqueue (which capacity gate was full) — never
            # client-set. See ``SubscriptionService._infer_waiting_list_reason``.
            "waiting_list_reason",
            # The rest of the waiting-list state is stamped exclusively by the
            # service / ``WaitingListMixin`` methods (enqueue, notify_spot_
            # available, confirm_spot, decline_spot, mark_as_expired). Only
            # ``on_waiting_list`` stays writable — it is the intended flip flag
            # routed through ``_enqueue_on_waiting_list`` (and thus the
            # ``allows_waiting_list_for_subscriptions`` gate). Left writable,
            # these let a crafted API call stamp a waiting-list status — even
            # deflating variation capacity via the SPOT_AVAILABLE/CONFIRMED
            # occupancy clause — WITHOUT ever hitting the gate.
            "waiting_list_status",
            "notification_sent_at",
            "notification_expires_at",
            "response_received_at",
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
        # (``useSubscriptionTerm`` on the frontend).
        valid_from = attrs.get("valid_from")
        if valid_from is not None and (
            self.instance is None or self.instance.valid_from != valid_from
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

        # 4. End-date requirement (CHG-1).
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

        # 5. Solidarity-pricing floor.
        #
        # When the tenant enables ``allows_solidarity_pricing``, the chosen
        # ``price_per_delivery`` may dip below the reference price but NOT below
        # the variation's floor (``solidarity_min_price_per_delivery``, or the
        # reference if no explicit floor). No upper bound — paying MORE is the
        # point. When solidarity is OFF this guard is a no-op here: the office
        # keeps its price discretion, and the member self-subscribe path forces
        # the reference upstream in ``MySubscriptionSubscribeView``.
        from django.db import connection

        from apps.shared.tenants.models import TenantSettings

        price = attrs.get("price_per_delivery")
        variation_id = attrs.get("share_type_variation") or (
            self.instance.share_type_variation_id if self.instance else None
        )
        current_settings = TenantSettings.get_current_settings(connection.tenant)
        if (
            price is not None
            and variation_id is not None
            and current_settings
            and current_settings.allows_solidarity_pricing
        ):
            from django.utils import timezone

            from apps.commissioning.errors import SolidarityPriceBelowMinimum
            from apps.commissioning.models import ShareTypeVariationGrossPrice

            # Resolve the floor at the subscription's START date, not today.
            # ``ShareTypeVariationGrossPrice`` is time-bound (one window per
            # variation, each with its own ``solidarity_min_price_per_delivery``),
            # and ``valid_from`` is virtually always a future Monday. Looking the
            # window up at today would (a) silently evade a future window's higher
            # floor — an under-floor price would lock into billing — and (b) miss a
            # future-price-only variation entirely. Fall back to the instance's
            # ``valid_from`` on a partial update that doesn't re-send it, then to
            # today if neither is available.
            effective_date = (
                attrs.get("valid_from")
                or getattr(self.instance, "valid_from", None)
                or timezone.localdate()
            )
            gross_price = (
                ShareTypeVariationGrossPrice.current.active_at_date(
                    effective_date.isoformat()
                )
                .filter(share_type_variation_id=variation_id)
                .first()
            )
            if gross_price is not None:
                floor = (
                    gross_price.solidarity_min_price_per_delivery
                    if gross_price.solidarity_min_price_per_delivery is not None
                    else gross_price.price_per_delivery
                )
                if floor is not None and price < floor:
                    raise SolidarityPriceBelowMinimum(chosen=price, minimum=floor)

        return super().validate(attrs)

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

        The frontend used to compute this per-row per-render via dayjs;
        moving it server-side cuts the render cost on Abos.tsx and
        centralises the "when does this column light up" rule.

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
        # This is stricter than the pre-2026-06 rule, which still
        # allowed deletion of confirmed-but-not-yet-started rows;
        # office workflow has consolidated on "delete only drafts".
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
    so DRF silently dropped the key from every payload (SkipField) while
    the schema declared it present."""

    member_string = serializers.SerializerMethodField(read_only=True)
    USER_NAME_FIELDS = ["admin_confirmed_by_name"]

    class Meta:
        model = CoopShare
        fields = "__all__"
        # MEM-8: these are owned by dedicated services (cancel_member_with_coop_shares
        # / the admin-confirm action) and the GenG §30/§31 audit trail — a generic
        # office PATCH must never set them (would falsify cancelled_by/audit and
        # let admin_confirmed be forged). Mirrors MemberSerializer.read_only_fields.
        read_only_fields = (
            *CANCELLATION_READONLY_FIELDS,
            *ADMIN_CONFIRMATION_READONLY_FIELDS,
            "paid_at",
            # Snapshotted server-side at member cancellation. ``paid_back_date``
            # is intentionally NOT here — the office stamps it when the share is
            # returned.
            "payback_due_date",
        )


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
