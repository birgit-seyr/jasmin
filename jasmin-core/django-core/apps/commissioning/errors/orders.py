"""Errors of resellers, orders, delivery notes and invoices."""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

# --------------------------------------------------------------------------- #
# Resellers                                                                    #
# --------------------------------------------------------------------------- #


class ResellerNotFound(NotFoundError):
    code = "reseller.not_found"


class ResellerEmailMissing(BadRequestError):
    """A document could not be sent because the reseller has no
    ``invoice_email`` configured."""

    code = "reseller.email_missing"


class ResellerInvoiceEmailDisabled(BadRequestError):
    """An invoice could not be sent to the reseller because the reseller takes
    invoices on paper only (``invoice_via_email`` is off)."""

    code = "reseller.invoice_email_disabled"


class AccountingEmailMissing(BadRequestError):
    """An invoice could not be sent to accounting because the tenant has no
    ``accounting_email`` configured."""

    code = "accounting.email_missing"


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


class OrderableItemReferenceInvalid(BadRequestError):
    """An order / delivery-note / invoice line must reference EXACTLY one item:
    an ``offer`` or a ``share_article``, never both and never neither. A line
    with both is ambiguous about what was sold; one with neither prices at zero
    and prints as an empty position on a legally binding document."""

    code = "orderable_item.reference_invalid"


class InvoiceNotFound(NotFoundError):
    code = "invoice.not_found"


class OfferGroupNotFound(NotFoundError):
    code = "offer_group.not_found"


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
