"""Domain errors raised by the commissioning app.

Translated to HTTP responses by ``core.exception_handler`` — views/viewsets
do not need to catch them. Use the closest existing class; add new ones
freely when a new failure mode is introduced.
"""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    InvalidQueryParam,
    NotFoundError,
)

# --------------------------------------------------------------------------- #
# Generic / cross-cutting                                                     #
# --------------------------------------------------------------------------- #


class CommissioningError(BadRequestError):
    """Base for any commissioning-domain validation failure (400)."""

    code = "commissioning.invalid"


class CompositeIdInvalid(BadRequestError):
    """A composite URL id (e.g. ``year_week_share_article_unit_size``) was
    malformed — wrong number of parts, or a non-numeric year/week. Callers pass
    a per-resource ``code`` so the failure is still attributable."""

    code = "composite_id.invalid"


class FinalizedError(ConflictError):
    """Operation rejected because the target document is already finalized."""

    code = "commissioning.already_finalized"


class BulkFinalizeModelInvalid(BadRequestError):
    """The generic bulk (un)finalize ``model`` is not a finalizable commissioning
    model: an unknown name, a model without finalization, or not a string."""

    code = "finalize.model_invalid"


class BulkFinalizeAppLabelInvalid(BadRequestError):
    """The generic bulk (un)finalize ``app_label`` is anything other than
    ``"commissioning"``, the only app whose models carry finalization."""

    code = "finalize.app_label_invalid"


class BulkIdsInvalid(BadRequestError):
    """A bulk-by-ids ``ids`` entry is not a non-empty string id."""

    code = "bulk.ids_invalid"


class BulkFinalizeIdsInvalid(BulkIdsInvalid):
    """A generic bulk (un)finalize ``ids`` entry is not a string id."""

    code = "finalize.ids_invalid"


class DocumentNotFinalized(BadRequestError):
    """A PDF upload was attempted before the document was finalized.

    The inverse of ``FinalizedError``: ``upload_pdf`` requires the invoice /
    delivery note to be finalized first, since the stored file is the legal
    artifact of a finalized document.
    """

    code = "document.not_finalized"


class InvalidUploadedDocument(BadRequestError):
    """An uploaded document failed validation: wrong extension, content that is
    not a PDF / XML, or larger than the upload size limit."""

    code = "uploaded_document.invalid"


class DocumentPdfMissing(BadRequestError):
    """A send action was attempted before the document's PDF was uploaded.

    The document is finalized but no PDF file is stored yet, so there is
    nothing to attach to the reseller email.
    """

    code = "document.pdf_missing"


class PastWeekError(ConflictError):
    """Operation rejected because the target week is in the past.

    ``Conflict`` (409) rather than 400: the request itself is well-formed —
    it's the state of the targeted week (already past/current) that forbids
    the change. Callers may override with ``force=True`` where the endpoint
    supports it.
    """

    code = "commissioning.past_week"


# ``InvalidQueryParam`` (code ``query.invalid_param``) is re-exported from
# ``core.errors`` above — single-sourced there so commissioning + payments
# emit the identical code. Kept in ``__all__`` for ``from ..errors import`` use.


# --------------------------------------------------------------------------- #
# Delivery stations / days / tours                                            #
# --------------------------------------------------------------------------- #


class DeliveryDayNotFound(NotFoundError):
    code = "delivery_day.not_found"


class SharesDeliveryDayNotFound(NotFoundError):
    """No active SharesDeliveryDay exists for the requested day."""

    code = "shares_delivery_day.not_found"


class PictureInvalid(BadRequestError):
    """An uploaded ``picture`` (share-type variation or delivery station) is not
    a PNG/JPEG/WEBP/GIF image within the byte and pixel caps. Raised by
    ``apps.shared.image_upload.normalize_uploaded_picture`` so a non-image
    (HTML, SVG, …) can never be stored and served from the tenant origin."""

    code = "commissioning.picture_invalid"


class DeliveryStationError(BadRequestError):
    code = "delivery_station.invalid"


class DeliveryStationNotFound(BadRequestError):
    """A referenced ``delivery_station_id`` does not exist — raised by the
    tour-update input serializer so a bogus id is a field-level 400 instead of
    a generic IntegrityError-derived 409 from ``update_or_create``."""

    code = "delivery_station.not_found"


class DeliveryDayRequired(BadRequestError):
    """The ``delivery_day`` parameter is missing on an endpoint that
    needs it to resolve the SharesDeliveryDay."""

    code = "delivery_day.required"


class DeliveryDayValidFromInPast(BadRequestError):
    """A delivery day was created with a ``valid_from`` date in the past.

    400 (not the 409 ``PastWeekError``): the request is malformed input — a
    new delivery day must take effect today or later. ``field="valid_from"``.
    """

    code = "delivery_day.valid_from_in_past"


class DeliveryExceptionInvalidRange(BadRequestError):
    """A delivery-exception ("Lieferpause") range is malformed: ``valid_from``
    is not a Monday, ``valid_until`` is not a Sunday, or the range is inverted.
    The pause covers whole delivery weeks, so its bounds must align to them.
    """

    code = "delivery_exception.invalid_range"


class DeliveryExceptionOverlap(ConflictError):
    """A delivery-exception period would overlap an existing one for the same
    ShareTypeVariation. A variation may have several pauses, but they must not
    overlap in time (409: the request is well-formed, the state forbids it).
    """

    code = "delivery_exception.overlap"


class DeliveryExceptionPeriodLocked(ConflictError):
    """A delivery-exception period that has already started (active or past) may
    not be edited or deleted — its deliveries/billing for the started portion
    already stand. Only future, not-yet-started pauses are mutable (409).
    """

    code = "delivery_exception.locked"


class DeliveryStationOverCapacity(ConflictError):
    """A delivery-station-day has no free slots for one of the weeks being
    assigned (a subscription's period week, or a single ShareDelivery's week).

    ``Conflict`` (409) rather than 400: the request is well-formed, but the
    resource state (the station-day is full for that week) prevents it. The
    frontend greys out full station-days, so this is the race-time backstop
    when two saves target the last slot — the second gets this.
    """

    code = "delivery_station.over_capacity"

    def __init__(
        self,
        *,
        station_day_id: str,
        year: int,
        week: int,
        capacity: int | None = None,
        occupied: int | None = None,
    ) -> None:
        super().__init__(
            f"Delivery station day {station_day_id} is full for week "
            f"{year}-{week} ({occupied}/{capacity}).",
            details={
                "station_day_id": str(station_day_id),
                "year": year,
                "week": week,
                "capacity": capacity,
                "occupied": occupied,
            },
        )


class ShareTypeVariationOverCapacity(ConflictError):
    """A share-type variation is sold out for the requested term — its
    farm-wide production cap (``ShareTypeVariation.capacity``) is exhausted.

    ``Conflict`` (409), not 400: the request is well-formed, but the state
    (the variation is full) forbids it. Twin of ``DeliveryStationOverCapacity``
    on the OTHER capacity axis — logistics (station-day) vs production
    (variation). The frontend greys out full variations from the free count; this
    is the race-time backstop when two orders target the last share.
    """

    code = "share_type_variation.over_capacity"

    def __init__(
        self,
        *,
        share_type_variation_id: str,
        capacity: int | None = None,
        occupied: int | None = None,
    ) -> None:
        super().__init__(
            f"Share type variation {share_type_variation_id} is sold out "
            f"({occupied}/{capacity}).",
            details={
                "share_type_variation_id": str(share_type_variation_id),
                "capacity": capacity,
                "occupied": occupied,
            },
        )


class WaitingListDisabled(BadRequestError):
    """The tenant has turned off the waiting list
    (``allows_waiting_list_for_subscriptions=False``), so no subscription may be
    queued and no spot offers exist. At-capacity share types are simply
    unavailable."""

    code = "waiting_list.disabled"


class WaitingListOfferNotAvailable(BadRequestError):
    """Cannot offer a freed spot for this subscription — it isn't a PENDING
    waiting-list entry (already offered, already promoted, or never queued)."""

    code = "waiting_list_offer.not_available"


class WaitingListOfferInvalid(NotFoundError):
    """The waiting-list offer link is invalid — no open (spot-available) offer
    matches the token (already used, declined, expired, or never existed)."""

    code = "waiting_list_offer.invalid"


class WaitingListOfferExpired(ConflictError):
    """The waiting-list offer link has expired — the member's response window
    elapsed before they accepted."""

    code = "waiting_list_offer.expired"


class DeliveryStationCapacityBelowOccupancy(BadRequestError):
    """Refuse setting a station-day's capacity below what's already booked for
    a current/future week.

    The office may raise or lower a station-day's ``capacity`` at will; the
    only floor is the busiest upcoming week — you can't drop the cap below the
    number of shares already committed (confirmed deliveries + active draft
    reservations) for any week from this ISO week onward. Past weeks are
    immutable and don't constrain the new value.
    """

    code = "delivery_station.capacity_below_occupancy"

    def __init__(
        self,
        *,
        capacity: int,
        peak: int,
        year: int | None = None,
        week: int | None = None,
    ) -> None:
        super().__init__(
            f"Cannot set capacity to {capacity}: {peak} share(s) are already "
            f"booked for week {year}-{week}.",
            field="capacity",
            details={
                "capacity": capacity,
                "peak": peak,
                "year": year,
                "week": week,
            },
        )


class ShareTypeVariationCapacityBelowOccupancy(BadRequestError):
    """Refuse setting a variation's farm-wide ``capacity`` below what's already
    subscribed for a current/future week.

    The production-cap twin of ``DeliveryStationCapacityBelowOccupancy``: the
    office may raise or lower a variation's cap at will, but not below the
    busiest current-or-future week's concurrent occupancy — doing so would
    instantly push existing subscribers over the cap (a silent mass-waitlist).
    Past weeks are immutable and don't constrain the new value.
    """

    code = "share_type_variation.capacity_below_occupancy"

    def __init__(self, *, capacity: int, peak: int) -> None:
        super().__init__(
            f"Cannot set capacity to {capacity}: {peak} share(s) are already "
            f"subscribed for a current or upcoming week.",
            field="capacity",
            details={"capacity": capacity, "peak": peak},
        )


# --------------------------------------------------------------------------- #
# Packing list                                                                 #
# --------------------------------------------------------------------------- #


class PackingAmountsDivergeAcrossStations(BadRequestError):
    """An all-stations packing list (no ``delivery_station`` scope) can't be
    rendered because two delivery stations carry DIFFERENT per-share amounts for
    the same (article, unit, size, variation). Collapsing them would silently
    hide one station's amount, so the caller must scope to a delivery station (or
    a tour / day where amounts are consistent — the office's granularity guard
    keeps the all-stations view to exactly those consistent cases).
    """

    code = "packing_list.amounts_diverge_across_stations"

    def __init__(
        self,
        *,
        share_article_id: str,
        unit: str,
        size: str,
        variation_id: str,
        amounts: list,
    ) -> None:
        super().__init__(
            f"Packing amounts differ across delivery stations for article "
            f"{share_article_id} ({unit}/{size}, variation {variation_id}): "
            f"{amounts}. Select a delivery station (or a tour/day where amounts "
            f"agree) to view the packing list.",
            details={
                "share_article_id": str(share_article_id),
                "unit": unit,
                "size": size,
                "variation_id": str(variation_id),
                "amounts": [str(a) for a in amounts],
            },
        )


# --------------------------------------------------------------------------- #
# Resellers                                                                    #
# --------------------------------------------------------------------------- #


class ResellerNotFound(NotFoundError):
    code = "reseller.not_found"


class ResellerError(BadRequestError):
    code = "reseller.invalid"


class ResellerEmailMissing(BadRequestError):
    """A document could not be sent because the reseller has no
    ``invoice_email`` configured."""

    code = "reseller.email_missing"


class OfferGroupCannotDeleteDefault(ConflictError):
    """The tenant's default offer group is protected — it is seeded per tenant,
    pre-selected for new resellers, and must always persist."""

    code = "offer_group.cannot_delete_default"


# --------------------------------------------------------------------------- #
# Orders / delivery notes / invoices                                          #
# --------------------------------------------------------------------------- #


class OrderNotFound(NotFoundError):
    code = "order.not_found"


class OrderContentNotFound(NotFoundError):
    code = "order_content.not_found"


class OrderContentOfferRequired(ForbiddenError):
    """A customer order line must order an offer. A free ``share_article`` line
    has no offer, so it would skip the stock check and the offer group's
    offer set; only office staff may add one."""

    code = "order_content.offer_required"


class OrderContentOfferNotInOfferGroup(ForbiddenError):
    """A customer tried to order an offer outside their own reseller's offer
    group (or their reseller has no offer group, so no offer is theirs)."""

    code = "order_content.offer_not_in_offer_group"


class OrderContentItemChangeForbidden(ForbiddenError):
    """A customer tried to re-point an existing order line at another offer or
    article. Stock was reserved on the line's current offer, so only office
    staff may change what a line orders."""

    code = "order_content.item_change_forbidden"


class DeliveryNoteNotFound(NotFoundError):
    code = "delivery_note.not_found"


class InvoiceNotFound(NotFoundError):
    code = "invoice.not_found"


class OfferGroupNotFound(NotFoundError):
    code = "offer_group.not_found"


class OfferNotFound(NotFoundError):
    code = "offer.not_found"


class StorageNotFound(NotFoundError):
    code = "storage.not_found"


class CrateNotFound(NotFoundError):
    code = "crate.not_found"


class CrateNetPriceInUse(ConflictError):
    """A currently valid ``CrateNetPrice`` cannot be deleted while its crate is
    in use (offers, crate orders, deliveries, a variation's packing crate) —
    the same rule its serializer's ``can_be_deleted`` reports. Future and past
    prices stay deletable."""

    code = "crate.net_price_in_use"


class CratesDisabledOnDocuments(BadRequestError):
    """A crate write was attempted while the tenant keeps crates OFF documents
    (``crates_should_be_on_documents=False``): crates are neither priced nor put
    on orders / delivery notes / invoices for such tenants."""

    code = "crates.disabled_on_documents"


class CrateDeliveryNoteContentMissingRequired(BadRequestError):
    """A crate delivery-note-content write is missing one of
    ``delivery_note_id`` / ``crate_type`` / ``amount``."""

    code = "crate_delivery_note_content.missing_required"


class CrateContentInvoiceMissingRequired(BadRequestError):
    """A crate invoice-content write is missing one of
    ``invoice_id`` / ``crate_type`` / ``amount``."""

    code = "crate_content_invoice.missing_required"


class InventoryEntryNotFound(NotFoundError):
    """No INVENTORY movement exists for the requested composite ID."""

    code = "inventory_entry.not_found"


class RequiredFieldMissing(BadRequestError):
    code = "required_field.missing"


class DocumentDateRequired(BadRequestError):
    """A legal document (delivery note / invoice) was saved without a date.

    The service layer normally resolves the date via ``coerce_document_date``
    (explicit → fallback_date → derived from the order's ISO week).
    Reaching ``save()`` with ``date=None`` means a caller bypassed that
    resolution — refuse loudly instead of silently dating the document
    "today", which is a GoBD / UStG audit hazard.
    """

    code = "document.date_required"


class DeliveryNoteFinalizeFailed(ConflictError):
    """A delivery note could not be finalized as a prerequisite step (e.g.
    before creating its invoice). ``Conflict`` (409): the request is
    well-formed but the document's state blocked the transition. In the bulk
    per-order flow this is caught per order and recorded, not aborting the
    batch."""

    code = "delivery_note.finalize_failed"


# --------------------------------------------------------------------------- #
# Shares / forecasts                                                          #
# --------------------------------------------------------------------------- #


class ShareArticleNotFound(NotFoundError):
    code = "share_article.not_found"


class ShareArticleNetPriceInUse(ConflictError):
    """A currently valid ``ShareArticleNetPrice`` cannot be deleted while its
    article is in use (offers, member shares, reseller orders, deliveries,
    stock, forecasts) — the same rule its serializer's ``can_be_deleted``
    reports. Future and past prices stay deletable."""

    code = "share_article.net_price_in_use"


class ShareTypeVariationNotFound(NotFoundError):
    code = "share_type_variation.not_found"


class ShareTypeVariationGrossPriceInUse(ConflictError):
    """A ``ShareTypeVariationGrossPrice`` cannot be deleted once any member has
    subscribed to its variation: the price is part of that variation's
    billable history — the same rule its serializer's ``can_be_deleted``
    reports."""

    code = "share_type_variation.gross_price_in_use"


class VirtualComponentNotPhysical(BadRequestError):
    """A variation referenced as a virtual component is itself virtual, not
    physical — only physical variations may be components."""

    code = "virtual_component.not_physical"


class ShareContentError(BadRequestError):
    code = "share_content.invalid"


class ShareContentNotFound(NotFoundError):
    """No ShareContent rows exist for the requested
    (year, week, share_article, unit, size) planning slot."""

    code = "share_content.not_found"


class InvalidAmount(BadRequestError):
    """A submitted amount could not be parsed as a number. ``field`` names the
    offending key (e.g. a ``day_{day}_variation_{var}`` planning cell or an
    ``amount_{variation}`` default-content cell)."""

    code = "amount.invalid"


class NotEnoughStock(ConflictError):
    code = "stock.insufficient"


class ForecastNotFound(NotFoundError):
    code = "forecast.not_found"


# --------------------------------------------------------------------------- #
# Subscriptions                                                               #
# --------------------------------------------------------------------------- #


class SubscriptionDeliveryStationDayOutOfRange(BadRequestError):
    """The subscription's chosen default delivery-station day doesn't cover the
    whole subscription term — it either becomes valid after the subscription
    starts, or stops being valid before the subscription ends with no successor
    day to take over. ``field`` is ``default_delivery_station_day``."""

    code = "subscription.delivery_station_day_out_of_range"


# --------------------------------------------------------------------------- #
# Documentation / exports                                                     #
# --------------------------------------------------------------------------- #


class InvalidExportDates(BadRequestError):
    code = "export.invalid_dates"


class DataImportInvalid(BadRequestError):
    """The uploaded CSV cannot be imported as a whole (unknown model,
    undecodable file, wrong extension, missing data row). Per-row failures
    are reported in the import result instead — they don't raise."""

    code = "data_import.invalid"


# --------------------------------------------------------------------------- #
# Members                                                                     #
# --------------------------------------------------------------------------- #


class MemberNotFound(NotFoundError):
    code = "member.not_found"


class MemberProfileNotLinked(NotFoundError):
    """The authenticated user has no linked Member row (``member_profile``
    reverse OneToOne) — the self-service member endpoints have no target."""

    code = "member.profile_not_linked"


class CustomerProfileNotLinked(NotFoundError):
    """The authenticated user has no linked Reseller row
    (``linked_reseller`` reverse OneToOne) — the self-service customer
    endpoints have no target."""

    code = "customer.profile_not_linked"


class MemberAlreadyConfirmed(ConflictError):
    """Confirm called on an already-confirmed member."""

    code = "member.already_confirmed"


class MemberHasActiveSubscriptions(BadRequestError):
    """A member tried to self-cancel their membership while still holding
    active (admin-confirmed, not-cancelled, not-expired) subscriptions. They
    must wind those down first; the office can still force-cancel (which
    cascades and ends the subscriptions)."""

    code = "member.has_active_subscriptions"


class MemberAlreadyCancelled(ConflictError):
    """The membership is already cancelled."""

    code = "member.already_cancelled"


class CoopShareContractAgreementRequired(BadRequestError):
    """The tenant published a coop-share contract ("Zeichnungsvertrag") but the
    member tried to self-subscribe without affirming agreement to it."""

    code = "coop_share.contract_agreement_required"


class CoopShareValueNotConfigured(BadRequestError):
    """A coop-share self-subscription was attempted but the tenant has no
    configured per-share value — refuse rather than persist a 0-valued share."""

    code = "coop_share.value_not_configured"


class MemberCoopSharesOutOfRange(BadRequestError):
    """A non-trial member is being admin-confirmed (or a CoopShare for
    such a member is being changed) but the resulting total of coop
    shares would fall outside the tenant's configured
    ``min_number_coop_shares`` / ``max_number_coop_shares`` window.

    Trial members and not-yet-confirmed members are EXEMPT — the rule
    only applies once a member is committed to the Mitgliederliste
    under GenG. Office staff must adjust the coop-share rows (add /
    remove / edit amounts) until the total lands in range before they
    can confirm the member.
    """

    code = "member.coop_shares_out_of_range"

    def __init__(
        self,
        *,
        total,
        minimum=None,
        maximum=None,
        member_id: str | None = None,
    ) -> None:
        bits = [f"Total coop shares ({total}) is outside the allowed range"]
        # ``context`` selects the i18next message variant on the frontend
        # (``errors.member.coop_shares_out_of_range_<context>``) so the
        # localized text can phrase a two-sided range, a lower bound, or an
        # upper bound correctly. The English ``message`` below stays the
        # fallback for codes the frontend hasn't translated.
        if minimum is not None and maximum is not None:
            bits.append(f"[{minimum}, {maximum}]")
            context = "range"
        elif minimum is not None:
            bits.append(f"(minimum {minimum})")
            context = "min"
        elif maximum is not None:
            bits.append(f"(maximum {maximum})")
            context = "max"
        else:
            context = "none"
        if member_id:
            bits.append(f"for member {member_id}")
        super().__init__(
            " ".join(bits) + ".",
            details={
                "total": total,
                "minimum": minimum,
                "maximum": maximum,
                "member_id": member_id,
                "context": context,
            },
        )


class MemberNumberNotAllowedForTrial(BadRequestError):
    """A CSV import row set ``member_number`` on a row with ``is_trial=True``.

    Trial members are not Mitglieder under GenG (no Geschaeftsanteil yet), so
    they carry neither a Mitgliedsnummer nor an Eintrittsdatum — the conversion
    hook stamps both when ``is_trial`` flips to False. Accepting a number here
    would put a non-member into the Mitgliederliste numbering space and then
    silently keep it on conversion (``_post_confirm`` only generates a number
    when none is set)."""

    code = "member.number_not_allowed_for_trial"


class LockedAfterAdminConfirmation(BadRequestError):
    """Caller tried to edit a field that becomes legally fixed once
    the Member is admin-confirmed (Mitglied der Genossenschaft per
    GenG). Currently applies to ``birth_date`` (biological fact +
    GDPR-classified PII whose audit trail edits would falsify) and
    ``is_trial`` (the trial → full conversion is one-way; flipping
    back would orphan the assigned Mitgliedsnummer / Eintrittsdatum).

    Typo / historical corrections to these fields after confirmation
    are real — they just need ops intervention (DB / data migration)
    rather than a casual office PATCH so the change is conscious and
    auditable."""

    code = "member.locked_after_admin_confirmation"

    def __init__(self, field_names: list[str]) -> None:
        message = (
            "Cannot edit "
            + ", ".join(field_names)
            + " after admin confirmation. Use the ops procedure for "
            "historical correction."
        )
        super().__init__(message, details={"locked_fields": field_names})


class MemberLinkConflict(ConflictError):
    """Cannot link a JasminUser to a new Member.

    Subclass per failure mode so callers can ``except`` the right one
    (``UserInBlockedStatus``, ``UserAlreadyLinked``).
    """

    code = "member.link_conflict"


class UserInBlockedStatus(MemberLinkConflict):
    """The JasminUser is mid-flow with another application or inactive."""

    code = "member.user_in_blocked_status"


class UserAlreadyLinked(MemberLinkConflict):
    """The JasminUser is already linked to a different Member."""

    code = "member.user_already_linked"


class MemberInvitationError(BadRequestError):
    """Invitation cannot be sent for the given member."""

    code = "member.invitation_invalid"


class MemberHasNoEmail(MemberInvitationError):
    code = "member.no_email"


class MemberUserAlreadyActive(MemberInvitationError):
    code = "member.user_already_active"


class MemberEmailAlreadyHasUser(MemberInvitationError):
    """Cannot invite THIS member: their email address already holds a login
    that belongs to a DIFFERENT member.

    ``Member.email`` is deliberately not unique — two members may share one
    inbox (an elderly couple with a single address). ``JasminUser.email`` is
    the ``USERNAME_FIELD`` and IS unique, so a shared inbox can carry at most
    one login. Whoever was invited first holds it; the other member is
    office-managed and simply has no self-service account.

    Raised BEFORE any user record is touched, so the existing member's account
    (name, status, open invitation) is never rewritten by an invite meant for
    their partner. ``details`` names the holder so the office sees who has it.
    """

    code = "member.email_already_has_user"

    def __init__(self, *, email: str, holder=None) -> None:
        holder_name = ""
        holder_number = None
        if holder is not None:
            holder_name = " ".join(
                bit for bit in (holder.first_name, holder.last_name) if bit
            ).strip()
            holder_number = holder.member_number
        message = (
            f"The address {email} already has a user account"
            + (f" belonging to {holder_name}" if holder_name else "")
            + (f" (#{holder_number})" if holder_number else "")
            + ". An email can hold only one login — invite that member, or "
            "give this one their own address."
        )
        # ``context`` selects the i18next variant
        # (``errors.member.email_already_has_user_<context>``) so the localized
        # text can name the holder when we know them and stay generic when we
        # don't — same mechanism as ``member.coop_shares_out_of_range``.
        if holder_name and holder_number:
            context = "named_numbered"
        elif holder_name:
            context = "named"
        else:
            context = "anonymous"
        super().__init__(
            message,
            details={
                "email": email,
                "holder_name": holder_name or None,
                "holder_member_number": holder_number,
                "holder_member_id": str(holder.id) if holder is not None else None,
                "context": context,
            },
        )


# --------------------------------------------------------------------------- #
# Consent versioning                                                          #
# --------------------------------------------------------------------------- #


class ConsentDocumentNotFound(NotFoundError):
    """No ConsentDocument exists for the requested (kind, locale) at this date."""

    code = "consent.document_not_found"


class ConsentTargetMemberUnresolved(BadRequestError):
    """A consent record could not be attributed to any Member: the payload
    carried no explicit ``member`` and the caller has no linked Member of
    their own (e.g. an office user creating a record without naming the
    member it is for)."""

    code = "consent.target_member_unresolved"


class ConsentAlreadyRevoked(ConflictError):
    """Caller tried to revoke a ConsentRecord that was already revoked."""

    code = "consent.already_revoked"


class ConsentDocumentInUse(ConflictError):
    """Caller tried to delete a ConsentDocument that has at least one
    ConsentRecord pointing at it. Documents that members have agreed
    to are append-only; publish a new version instead."""

    code = "consent.document_in_use"


class ConsentDocumentImmutable(ConflictError):
    """Caller tried to change what members consented to — ``body``, ``title``,
    ``kind``, ``locale``, ``version`` or ``valid_from`` — on a ConsentDocument
    that at least one ConsentRecord references. Consented documents are
    append-only; publish a new version instead. Drafts nobody has consented to
    yet stay editable."""

    code = "consent.document_immutable"


# --------------------------------------------------------------------------- #
# Trial members / subscriptions                                                #
# --------------------------------------------------------------------------- #


class TrialMembersNotAllowed(BadRequestError):
    """Caller tried to create a trial Member while the tenant has the
    trial-member concept effectively off — i.e. either
    ``allows_trial_subscriptions=False`` (no trial subs anywhere) or
    ``allows_trial_subscriptions_for_trial_members=False`` (trial subs only
    for full members). With nothing for a trial member to do,
    creating one is rejected."""

    code = "trial.members_not_allowed"


class TrialSubscriptionsNotAllowed(BadRequestError):
    """Caller tried to create a trial Subscription while the tenant has
    ``allows_trial_subscriptions=False``."""

    code = "trial.subscriptions_not_allowed"


class TrialSubscriptionsOnlyForFullMembers(BadRequestError):
    """Caller tried to attach a trial Subscription to a Member whose
    ``is_trial=True`` while the tenant has
    ``allows_trial_subscriptions_for_trial_members=False``."""

    code = "trial.subscriptions_only_for_full_members"


class SubscriptionAlreadyConfirmed(ConflictError):
    """Confirm called on an already-confirmed subscription. Mirrors
    ``MemberAlreadyConfirmed``."""

    code = "subscription.already_confirmed"


class SubscriptionConfirmedImmutable(ConflictError):
    """Edit/delete attempted on an admin-confirmed subscription. Confirmed
    subscriptions are immutable through CRUD — end them early via the
    ``cancel`` action instead."""

    code = "subscription.confirmed_immutable"


class MemberConfirmedImmutable(ConflictError):
    """Delete attempted on an admin-confirmed member. A confirmed member holds
    membership + equity history that must survive — cancel it (the ``cancel``
    action, which stamps ``cancelled_at``) instead of hard-deleting."""

    code = "member.confirmed_immutable"


class CoopShareConfirmedImmutable(ConflictError):
    """Delete attempted on an admin-confirmed coop share. Confirmed
    Geschäftsanteile carry statutory GenG retention — cancel the share (or the
    member) instead of hard-deleting it."""

    code = "coop_share.confirmed_immutable"


class CoopShareConfirmedFieldsLocked(ConflictError):
    """Update attempted to change the committed terms of an admin-confirmed
    coop share (amount, member, due date, increase flag). Once confirmed the
    Geschäftsanteil is part of the GenG register; only the payment / payback /
    note bookkeeping stays editable. Cancel the share and record a new one
    instead of rewriting it."""

    code = "coop_share.confirmed_fields_locked"

    def __init__(self, field_names: list[str]) -> None:
        super().__init__(
            "Cannot change "
            + ", ".join(field_names)
            + " on a confirmed coop share. Cancel it and record a new share instead.",
            field=field_names[0] if field_names else None,
            details={"fields": field_names},
        )


class CoopShareInvalidAmount(BadRequestError):
    """``amount_of_coop_shares`` is not a whole number greater than zero. A
    cooperative share is a whole Geschäftsanteil (GenG) — zero, negative and
    fractional amounts are rejected on every write path (office, CSV import,
    member self-service)."""

    code = "coop_share.invalid_amount"

    def __init__(self, message: str) -> None:
        super().__init__(message, field="amount_of_coop_shares")


class CoopShareTransferSameMember(BadRequestError):
    """A coop share transfer names the same member as giver and receiver."""

    code = "coop_share_transfer.same_member"

    def __init__(self) -> None:
        super().__init__(
            "Coop shares can't be transferred to the same member.", field="to_member"
        )


class CoopShareTransferGiverNotAdmitted(BadRequestError):
    """Only an admitted, non-trial member holds Geschäftsanteile that can be
    transferred."""

    code = "coop_share_transfer.giver_not_admitted"

    def __init__(self) -> None:
        super().__init__(
            "Coop shares can only be transferred from an admitted member.",
            field="from_member",
        )


class CoopShareTransferReceiverNotAdmitted(BadRequestError):
    """The receiving member of a coop share transfer must be admitted (full or
    trial member); a pending or rejected applicant can't hold equity."""

    code = "coop_share_transfer.receiver_not_admitted"

    def __init__(self) -> None:
        super().__init__(
            "Coop shares can only be transferred to an admitted member.",
            field="to_member",
        )


class CoopShareTransferReceiverCancelled(BadRequestError):
    """The receiving member of a coop share transfer has already left the
    cooperative; a departed member can't acquire new Geschäftsanteile."""

    code = "coop_share_transfer.receiver_cancelled"

    def __init__(self) -> None:
        super().__init__(
            "The receiving member is already cancelled.", field="to_member"
        )


class CoopShareTransferExceedsHeld(BadRequestError):
    """A coop share transfer asks for more shares than the giving member holds as
    confirmed, uncancelled shares paid by the transfer date. Pending and unpaid
    shares are not transferable."""

    code = "coop_share_transfer.exceeds_held"

    def __init__(self, *, available: int | float) -> None:
        super().__init__(
            f"The member only holds {available} confirmed, paid coop shares.",
            field="amount_of_coop_shares",
            details={"available": available},
        )


class CoopShareTransferDateInFuture(BadRequestError):
    """A coop share transfer is dated in the future; a transfer is recorded when
    it has happened."""

    code = "coop_share_transfer.date_in_future"

    def __init__(self) -> None:
        super().__init__(
            "The transfer date can't be in the future.", field="transfer_date"
        )


class CoopShareTransferDateBeforeEntry(BadRequestError):
    """A coop share transfer is dated before the giving or the receiving member's
    entry date: nobody gives or receives Geschäftsanteile before joining.
    ``details.context`` names the side (``from_member`` / ``to_member``)."""

    code = "coop_share_transfer.date_before_entry"

    def __init__(self, *, entry_date: str, member: str) -> None:
        side = "giving" if member == "from_member" else "receiving"
        super().__init__(
            f"The transfer date is before the {side} member's entry date ({entry_date}).",
            field="transfer_date",
            details={"entry_date": entry_date, "context": member},
        )


class CoopShareTransferCancellationNotConfirmed(BadRequestError):
    """The transfer leaves the giving member without confirmed shares, which
    cancels the membership, and the request didn't confirm that."""

    code = "coop_share_transfer.cancellation_not_confirmed"

    def __init__(self) -> None:
        super().__init__(
            "This transfer leaves the giving member without shares and cancels the "
            "membership; confirm it with confirm_member_cancellation.",
            field="confirm_member_cancellation",
        )


class SubscriptionPriceInvalid(BadRequestError):
    """``price_per_delivery`` is not a valid non-negative amount on a path that
    takes it outside a serializer (the waiting-list offer). A negative price
    would make the subscription produce negative or no charges."""

    code = "subscription.invalid_price"

    def __init__(self, value) -> None:
        super().__init__(
            f"Invalid price_per_delivery ({value}); it must be a number of at least 0.",
            field="price_per_delivery",
            details={"value": str(value)},
        )


class SubscriptionStartTooSoon(BadRequestError):
    """``valid_from`` is earlier than the tenant's required lead time
    (``min_weeks_from_creation_to_start_delivery`` weeks from now, snapped to
    the next Monday). The office UI's date picker already floors the choice;
    this is the backstop for direct API calls."""

    code = "subscription.start_too_soon"

    def __init__(self, *, valid_from, earliest, min_weeks: int) -> None:
        super().__init__(
            f"Subscription cannot start before {earliest} "
            f"({min_weeks} week(s) lead time required).",
            field="valid_from",
            details={
                "valid_from": str(valid_from),
                "earliest": str(earliest),
                "min_weeks": min_weeks,
            },
        )


class SolidarityPriceBelowMinimum(BadRequestError):
    """The chosen solidarity price is below the variation's floor
    (``solidarity_min_price_per_delivery``, or the reference price if no
    explicit floor is set). Only enforced when the tenant enables
    ``allows_solidarity_pricing``."""

    code = "subscription.solidarity_price_below_minimum"

    def __init__(self, *, chosen, minimum) -> None:
        super().__init__(
            f"The chosen price ({chosen}) is below the solidarity minimum "
            f"({minimum}).",
            field="price_per_delivery",
            details={"chosen": str(chosen), "minimum": str(minimum)},
        )


class OpenEndedSubscriptionNotAllowed(BadRequestError):
    """A subscription was created / updated without a ``valid_until`` end date.

    Open-ended subscriptions materialise no ShareDeliveries (the materialiser
    skips a sub with no ``valid_until``) and therefore generate only
    zero-amount charges — they silently never bill. An end date is
    required so every billable subscription has a finite, billable term. The
    office UI's date picker already requires it; this is the backstop for
    direct API calls / imports / scripts."""

    code = "subscription.open_ended_not_allowed"


class SubscriptionVariationLocked(BadRequestError):
    """``Subscription.share_type_variation`` was changed after the subscription
    was admin-confirmed (and its Shares / ShareDeliveries materialised).

    The variation is the key the materialised Shares / ShareDeliveries are
    keyed by — changing it would orphan that data (deliveries + packing lists
    would still reference the OLD variation). It is fixed once confirmed; create
    a new subscription instead. (A raw ``QuerySet.update()`` still bypasses this,
    like every Django model validator — this guards the normal ``save()`` path,
    which is the only one any caller actually uses.)"""

    code = "subscription.variation_locked"


class RenewalVariationUnavailable(BadRequestError):
    """Auto-renewal could not find a share-type variation of the same size that
    covers the whole renewal term.

    The subscription's variation has ended and no same-``(share_type, size)``
    successor reaches across the new term, so there is nothing to renew onto.
    Counted as a failure (``no_variation`` reason in the bulk-renew result);
    the office adds/extends a variation and renews again (the source stays
    renewable)."""

    code = "subscription.renewal_variation_unavailable"


class RenewalPriceUnavailable(BadRequestError):
    """Auto-renewal could not resolve a price for the renewal term.

    The successor variation has no ``ShareTypeVariationGrossPrice`` window on or
    before the new start at all — so the draft would be a fully €0-billed term.
    (The predecessor's stored price is deliberately NOT a fallback: it can be a
    member-chosen solidarity or office custom figure that must not silently
    carry into a new term.) Counted as a failure (``no_price`` reason); the
    office adds a gross-price window for the term and renews again."""

    code = "subscription.renewal_price_unavailable"


class RenewalChainNumberMissing(ConflictError):
    """A renewal's predecessor has no ``subscription_number`` to inherit.

    A renewal must NEVER become a chain root: falling through to the
    fresh-``Max()+1`` numbering branch would assign a different number at
    ``generation=0``, silently splitting the "shared number across the chain"
    invariant. Only reachable if the predecessor was created bypassing
    ``save()`` (a ``bulk_create``, a partial import) — fix the predecessor's
    number, then renew again."""

    code = "subscription.renewal_chain_number_missing"


# --------------------------------------------------------------------------- #
# Subscription cancellation                                                   #
# --------------------------------------------------------------------------- #


class SubscriptionCancellationError(BadRequestError):
    """Base for the validation failures raised by ``cancel_subscription``.

    Each concrete subclass carries a stable ``code`` so the frontend i18n
    layer can key on it and the tests can assert on the failure mode rather
    than a free-text English substring.
    """

    code = "subscription.cancel.invalid"


class SubscriptionNotConfirmed(SubscriptionCancellationError):
    """Only admin-confirmed subscriptions can be cancelled."""

    code = "subscription.cancel.not_confirmed"


class CancellationNotSunday(SubscriptionCancellationError):
    """``effective_at`` must fall on a Sunday (the end-of-delivery-week
    boundary that ``TimeBoundMixin.valid_until`` requires)."""

    code = "subscription.cancel.not_sunday"


class CancellationInPast(SubscriptionCancellationError):
    """``effective_at`` is before the next-Sunday floor — a cancellation
    cannot take effect in the past."""

    code = "subscription.cancel.in_past"


class CancellationBeforeValidFrom(SubscriptionCancellationError):
    """``effective_at`` is before the subscription's ``valid_from`` (a
    future-dated subscription cannot be cancelled before it has begun)."""

    code = "subscription.cancel.before_valid_from"


class CancellationAfterValidUntil(SubscriptionCancellationError):
    """``effective_at`` is after the subscription's ``valid_until`` — refusing
    so the office can't accidentally EXTEND the term."""

    code = "subscription.cancel.after_valid_until"


class NoSundayRemainsInTerm(SubscriptionCancellationError):
    """The next-Sunday floor is already past ``valid_until`` — there is no
    Sunday left to cancel into; let the term expire naturally."""

    code = "subscription.cancel.no_sunday_remains"


# --------------------------------------------------------------------------- #
# Additional-share (Zusatz) subscription rules                                #
# --------------------------------------------------------------------------- #


class AdditionalShareRequiresBase(BadRequestError):
    """An additional share ("Zusatz") is packed INTO a base box, so it can't be
    subscribed on its own: the member must already have a non-additional (base)
    share active over the same period."""

    code = "subscription.additional_requires_base"

    def __init__(self, *, share_type_variation_id: str) -> None:
        super().__init__(
            "This is an additional share and can only be added when the member "
            "already has a base share active for the same period.",
            field="share_type_variation",
            details={"share_type_variation_id": str(share_type_variation_id)},
        )


class AdditionalShareExceedsBase(BadRequestError):
    """The additional share would run past the end of the member's base share.
    Allowed, but only up to the base's effective end — that date is offered as
    ``suggested_valid_until`` so the frontend can prefill it."""

    code = "subscription.additional_exceeds_base"

    def __init__(self, *, suggested_valid_until) -> None:
        super().__init__(
            "An additional share cannot run longer than the base share it is "
            f"packed into. Set the end date to {suggested_valid_until} (the "
            "base share's end) to continue.",
            field="valid_until",
            details={"suggested_valid_until": str(suggested_valid_until)},
        )


# --------------------------------------------------------------------------- #
# On-off opt-in errors                                                        #
# --------------------------------------------------------------------------- #


class OptinNotApplicable(BadRequestError):
    """Caller tried to toggle ``is_opted_in`` on a ShareDelivery whose
    variation has ``requires_optin=False``. Use ``joker_taken`` (the
    opt-out path) for normal variations."""

    code = "optin.not_applicable"


class OptinDeadlinePassed(ConflictError):
    """Caller tried to toggle ``is_opted_in`` after the variation's
    ``optin_deadline_days_before_delivery`` cutoff. The decision is
    locked at the value it had when the deadline lapsed; the office
    runbook covers exceptional overrides via direct DB."""

    code = "optin.deadline_passed"


class ShareTypeSuccessionHasActiveVariations(ConflictError):
    """A new share type can't take over a ``share_option`` while the current
    one still has variations active on or after the new start date. Closing
    the predecessor would strand those variations (and any subscriptions on
    them) outliving their parent. End the variations first (set their
    ``valid_until``), or choose a later start date."""

    code = "share_type.succession_has_active_variations"

    def __init__(self, *, share_option, new_valid_from, active_variation_count) -> None:
        super().__init__(
            f"Cannot start a new '{share_option}' share type on "
            f"{new_valid_from}: the current one still has "
            f"{active_variation_count} variation(s) active on or after that "
            f"date. End those variations first, or choose a later start date.",
            details={
                "share_option": share_option,
                "new_valid_from": str(new_valid_from),
                "active_variation_count": active_variation_count,
            },
        )


class SuccessionStartBeforePredecessor(ConflictError):
    """A new time-bound record can't start *before* the open record it would
    succeed. ``TimeBoundMixin.handle_succession`` closes the predecessor at
    ``new_valid_from - 1 day``; when ``new_valid_from`` is earlier than the
    predecessor's own ``valid_from`` that would hand the predecessor an end
    date before its own start. Choose a start date on or after the existing
    record's, or close the existing record first."""

    code = "time_bound.succession_start_before_predecessor"

    def __init__(self, *, new_valid_from, existing_valid_from) -> None:
        super().__init__(
            f"Cannot start a new record on {new_valid_from}: an existing open "
            f"record already starts later, on {existing_valid_from}. Choose a "
            f"start date on or after that, or close the existing record first.",
            details={
                "new_valid_from": str(new_valid_from),
                "existing_valid_from": str(existing_valid_from),
            },
        )


class ShareTypeVariationOutsideShareTypeRange(BadRequestError):
    """A share type variation's validity must lie WITHIN its share type's
    validity: it can't start before the share type starts, nor stay open / end
    after the share type ends (that would outlive its parent)."""

    code = "share_type_variation.outside_share_type_range"

    def __init__(
        self, *, variation_from, variation_until, share_type_from, share_type_until
    ) -> None:
        super().__init__(
            f"The variation's validity ({variation_from} – "
            f"{variation_until or 'open'}) must lie within its share type's "
            f"validity ({share_type_from} – {share_type_until or 'open'}).",
            details={
                "variation_valid_from": str(variation_from),
                "variation_valid_until": (
                    str(variation_until) if variation_until else None
                ),
                "share_type_valid_from": str(share_type_from),
                "share_type_valid_until": (
                    str(share_type_until) if share_type_until else None
                ),
            },
        )


class ShareTypeShorteningStrandsVariation(ConflictError):
    """Shortening (or closing) a share type's validity would strand a child
    variation that is open or ends after the new end date — the variation
    (and any subscriptions on it) would outlive its parent. End or shorten
    those variations first, or pick a later end date."""

    code = "share_type.shortening_strands_variation"

    def __init__(self, *, share_type, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end share type '{share_type}' on {new_valid_until}: "
            f"{stranded_count} variation(s) are open or end after that date and "
            "would outlive their parent. End or shorten those variations first.",
            details={
                "share_type": share_type,
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class ShareTypeVariationSuccessionHasActiveSubscriptions(ConflictError):
    """A new share type variation can't take over a ``(share_type, size)``
    slot while the current one still has subscription groups active on or
    after the new start date. The subscription→variation link is locked once
    subscriptions exist, so closing the predecessor would strand those
    subscriptions (and their materialized shares) on a closed variation,
    dropping them out of harvest/packing/demand planning. End those
    subscriptions first, or choose a later start date."""

    code = "share_type_variation.succession_has_active_subscriptions"

    def __init__(
        self, *, share_type, size, new_valid_from, active_subscription_count
    ) -> None:
        super().__init__(
            f"Cannot start a new '{size}' variation of '{share_type}' on "
            f"{new_valid_from}: the current one still has "
            f"{active_subscription_count} subscription(s) running on or after "
            "that date. The successor can only start once the last subscription "
            "has ended — end them first, or choose a later start date.",
            details={
                "share_type": str(share_type),
                "size": size,
                "new_valid_from": str(new_valid_from),
                "active_subscription_count": active_subscription_count,
            },
        )


class ShareTypeVariationShorteningStrandsSubscriptions(ConflictError):
    """Shortening (or closing) a share type variation's validity would strand
    subscription groups that are open or end after the new end date — the
    subscriptions (and their materialized shares) would outlive their
    variation. End those subscriptions first, or pick a later end date."""

    code = "share_type_variation.shortening_strands_subscriptions"

    def __init__(self, *, variation, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end variation '{variation}' on {new_valid_until}: "
            f"{stranded_count} subscription(s) are open or end after that date "
            "and would outlive their variation. End those subscriptions first.",
            details={
                "variation": str(variation),
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class SharesDeliveryDayToursReducedWhileInUse(ConflictError):
    """The number of tours on a delivery day that is already in use (it has
    deliveries / subscriptions, i.e. it is not deletable) may only be raised,
    not lowered — reducing it would strand deliveries on the removed tours."""

    code = "shares_delivery_day.tours_reduced_while_in_use"

    def __init__(self, *, current_tours, new_tours) -> None:
        super().__init__(
            f"This delivery day is in use, so the number of tours can't be "
            f"reduced from {current_tours} to {new_tours} — only increased. "
            f"Lowering it would strand deliveries on the removed tours.",
            details={"current_tours": current_tours, "new_tours": new_tours},
        )


class SharesDeliveryDayShorteningStrandsChildren(ConflictError):
    """Shortening (or closing) a delivery day's validity would strand future
    children past the new end date — DeliveryStationDays that are open or end
    later, or Shares whose delivery week falls after it. Migrate via the
    close-then-create succession flow, or pick a later end date."""

    code = "shares_delivery_day.shortening_strands_children"

    def __init__(self, *, delivery_day, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end delivery day '{delivery_day}' on {new_valid_until}: "
            f"{stranded_count} future child object(s) (station-days or shares) "
            "would outlive it. Use a succession (close-then-create) or pick a "
            "later end date.",
            details={
                "delivery_day": delivery_day,
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class SharesDeliveryDaySuccessionCoverageGap(ConflictError):
    """A delivery-day succession can't remap a future ShareDelivery because the
    station has no DeliveryStationDay covering that week on the new day. Leaving
    the delivery on the closed old day would violate the Share/ShareDelivery
    day-match invariant — configure the station-day for the new day first, then
    retry the succession."""

    code = "shares_delivery_day.succession_coverage_gap"

    def __init__(self, *, station_id, day_number, week_monday) -> None:
        super().__init__(
            f"Cannot complete the delivery-day succession: station {station_id} "
            f"has no station-day for day {day_number} covering the week of "
            f"{week_monday}. Configure that station-day first, then retry.",
            details={
                "station_id": str(station_id),
                "day_number": day_number,
                "week_monday": str(week_monday),
            },
        )


class DeliveryStationDayShorteningStrandsChildren(ConflictError):
    """Shortening (or closing) a station-day's validity via a direct edit would
    strand its future children past the new end — ShareDeliveries or
    CapacityReservations whose delivery week falls after it. Create a successor
    station-day instead (which migrates them), or pick a later end date."""

    code = "delivery_station_day.shortening_strands_children"

    def __init__(self, *, station_day, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end station-day '{station_day}' on {new_valid_until}: "
            f"{stranded_count} future delivery/reservation(s) would outlive it. "
            "Create a successor station-day (which migrates them) or pick a later "
            "end date.",
            details={
                "station_day": station_day,
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class DeliveryStationInUse(ConflictError):
    """A DeliveryStation cannot be deleted while any of its station-days still
    carry deliveries (the billing basis) — deleting would CASCADE-wipe those
    ShareDeliveries + Share history with no recompute / charge re-plan. Move or
    wind the deliveries down first."""

    code = "delivery_station.in_use"

    def __init__(self, *, station, delivery_count) -> None:
        super().__init__(
            f"Cannot delete station '{station}': {delivery_count} delivery/ies "
            "still reference its pickup days. Move or end them first.",
            details={"station": str(station), "delivery_count": delivery_count},
        )


class DeliveryStationDayInUse(ConflictError):
    """A DeliveryStationDay cannot be deleted while it still has deliveries —
    deleting would CASCADE-wipe those ShareDeliveries with no recompute."""

    code = "delivery_station_day.in_use"

    def __init__(self, *, station_day, delivery_count) -> None:
        super().__init__(
            f"Cannot delete pickup day '{station_day}': {delivery_count} "
            "delivery/ies still reference it. Move or end them first.",
            details={
                "station_day": str(station_day),
                "delivery_count": delivery_count,
            },
        )


class SharesDeliveryDayInUse(ConflictError):
    """A SharesDeliveryDay cannot be deleted while any Share references it —
    deleting would CASCADE-wipe whole historical weeks of Shares, their
    deliveries and ShareContents in one call."""

    code = "shares_delivery_day.in_use"

    def __init__(self, *, delivery_day, share_count) -> None:
        super().__init__(
            f"Cannot delete delivery day '{delivery_day}': {share_count} "
            "share(s) still reference it. It cannot be removed once used.",
            details={
                "delivery_day": str(delivery_day),
                "share_count": share_count,
            },
        )


class OrganicPurchaseCertificateRequired(BadRequestError):
    """A purchase marked ``organic`` / ``in_conversion`` requires its seller to
    hold an OrganicCertificate valid AT the purchase's delivery week — the
    organic label can only be carried through from a currently-certified
    supplier."""

    code = "purchase.organic_certificate_required"


__all__ = [
    "CommissioningError",
    "CompositeIdInvalid",
    "FinalizedError",
    "PastWeekError",
    "InvalidQueryParam",
    "DeliveryDayNotFound",
    "SharesDeliveryDayNotFound",
    "DeliveryStationInUse",
    "DeliveryStationDayInUse",
    "SharesDeliveryDayInUse",
    "DeliveryStationError",
    "DeliveryStationNotFound",
    "DeliveryDayRequired",
    "DeliveryExceptionInvalidRange",
    "DeliveryExceptionOverlap",
    "DeliveryExceptionPeriodLocked",
    "DeliveryStationOverCapacity",
    "DeliveryStationCapacityBelowOccupancy",
    "ResellerNotFound",
    "ResellerError",
    "ResellerEmailMissing",
    "DocumentPdfMissing",
    "OrderNotFound",
    "OrderContentNotFound",
    "DeliveryNoteNotFound",
    "InvoiceNotFound",
    "DeliveryNoteFinalizeFailed",
    "OfferGroupNotFound",
    "OfferNotFound",
    "StorageNotFound",
    "CrateNotFound",
    "CrateNetPriceInUse",
    "CratesDisabledOnDocuments",
    "CrateDeliveryNoteContentMissingRequired",
    "CrateContentInvoiceMissingRequired",
    "InventoryEntryNotFound",
    "RequiredFieldMissing",
    "DocumentDateRequired",
    "ShareArticleNotFound",
    "ShareArticleNetPriceInUse",
    "ShareTypeVariationNotFound",
    "ShareTypeVariationGrossPriceInUse",
    "VirtualComponentNotPhysical",
    "ShareContentError",
    "ShareContentNotFound",
    "InvalidAmount",
    "NotEnoughStock",
    "ForecastNotFound",
    "InvalidExportDates",
    "DataImportInvalid",
    "MemberNotFound",
    "MemberProfileNotLinked",
    "CustomerProfileNotLinked",
    "MemberAlreadyConfirmed",
    "LockedAfterAdminConfirmation",
    "MemberNumberNotAllowedForTrial",
    "MemberLinkConflict",
    "UserInBlockedStatus",
    "UserAlreadyLinked",
    "MemberInvitationError",
    "MemberHasNoEmail",
    "MemberUserAlreadyActive",
    "MemberEmailAlreadyHasUser",
    "ConsentDocumentNotFound",
    "ConsentTargetMemberUnresolved",
    "ConsentAlreadyRevoked",
    "ConsentDocumentInUse",
    "ConsentDocumentImmutable",
    "TrialMembersNotAllowed",
    "TrialSubscriptionsNotAllowed",
    "TrialSubscriptionsOnlyForFullMembers",
    "SubscriptionAlreadyConfirmed",
    "SubscriptionConfirmedImmutable",
    "MemberConfirmedImmutable",
    "CoopShareConfirmedImmutable",
    "CoopShareConfirmedFieldsLocked",
    "CoopShareInvalidAmount",
    "SubscriptionPriceInvalid",
    "SubscriptionStartTooSoon",
    "SolidarityPriceBelowMinimum",
    "SubscriptionCancellationError",
    "SubscriptionNotConfirmed",
    "AdditionalShareRequiresBase",
    "AdditionalShareExceedsBase",
    "CancellationNotSunday",
    "CancellationInPast",
    "CancellationBeforeValidFrom",
    "CancellationAfterValidUntil",
    "NoSundayRemainsInTerm",
    "OptinNotApplicable",
    "OptinDeadlinePassed",
    "ShareTypeSuccessionHasActiveVariations",
    "ShareTypeVariationSuccessionHasActiveSubscriptions",
    "ShareTypeVariationShorteningStrandsSubscriptions",
    "SuccessionStartBeforePredecessor",
    "ShareTypeVariationOutsideShareTypeRange",
    "SharesDeliveryDayToursReducedWhileInUse",
    "SharesDeliveryDayShorteningStrandsChildren",
    "SharesDeliveryDaySuccessionCoverageGap",
    "DeliveryStationDayShorteningStrandsChildren",
    # Membership / coop-share / document errors.
    "MemberHasActiveSubscriptions",
    "MemberAlreadyCancelled",
    "CoopShareContractAgreementRequired",
    "CoopShareValueNotConfigured",
    "MemberCoopSharesOutOfRange",
    "OpenEndedSubscriptionNotAllowed",
    "SubscriptionVariationLocked",
    "RenewalVariationUnavailable",
    "RenewalPriceUnavailable",
    "ShareTypeShorteningStrandsVariation",
    "SubscriptionDeliveryStationDayOutOfRange",
    "OfferGroupCannotDeleteDefault",
    "PackingAmountsDivergeAcrossStations",
    "DeliveryDayValidFromInPast",
    "DocumentNotFinalized",
    "InvalidUploadedDocument",
    "OrganicPurchaseCertificateRequired",
]
