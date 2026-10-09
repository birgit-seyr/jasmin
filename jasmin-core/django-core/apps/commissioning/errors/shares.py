"""Errors of shares, forecasts, documentation, purchases, exports and the weekly
share-demand imports."""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
)

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


class WashingAndCleaningMutuallyExclusive(BadRequestError):
    """A planning slot was asked to carry both ``washing`` and ``cleaning``.
    ``ShareContent`` holds at most one of the two
    (``sharecontent_washing_cleaning_mutually_exclusive``), so the pair is
    refused here, naming both fields, rather than by the INSERT."""

    code = "share_content.washing_cleaning_mutually_exclusive"


class InvalidAmount(BadRequestError):
    """A submitted amount could not be parsed as a number. ``field`` names the
    offending key (e.g. a ``day_{day}_variation_{var}`` planning cell or an
    ``amount_{variation}`` default-content cell)."""

    code = "amount.invalid"


class NotEnoughStock(ConflictError):
    code = "stock.insufficient"


class InventoryEntryFinalized(ConflictError):
    """A finalized inventory entry cannot be recounted, edited or deleted.

    The counted amount is what the stock ledger builds on, so changing it under
    a finalized count rewrites history silently. Unfinalize the entry first."""

    code = "stock.inventory_finalized"


class ForecastNotFound(NotFoundError):
    code = "forecast.not_found"


# --------------------------------------------------------------------------- #
# Documentation / exports                                                     #
# --------------------------------------------------------------------------- #


class InvalidExportDates(BadRequestError):
    code = "export.invalid_dates"


class WasteAlreadyDocumented(BadRequestError):
    """A waste of this article in this unit and size is already documented for
    the day and storage — ``Waste`` holds one row per (year, week, day,
    article, unit, size, storage); the office corrects that row's amount."""

    code = "waste.already_documented"


class HarvestAlreadyDocumented(BadRequestError):
    """A harvest of this article in this unit and size is already documented
    for the day and storage — ``Harvest`` holds one row per (year, week, day,
    article, unit, size, storage); the office corrects that row's amount."""

    code = "harvest.already_documented"


class PurchaseAlreadyDocumented(BadRequestError):
    """A purchase of this article in this unit and size from this seller is
    already documented for the day — ``Purchase`` holds one row per (year,
    week, day, article, unit, size, seller) when it has a seller and a day."""

    code = "purchase.already_documented"


class PurchaseWithoutSellerAlreadyDocumented(BadRequestError):
    """A purchase of this article in this unit and size without a seller is
    already documented for the week, day and storage — a missing day counts as
    the same day here."""

    code = "purchase.already_documented_without_seller"


class DataImportInvalid(BadRequestError):
    """The uploaded CSV cannot be imported as a whole (unknown model,
    undecodable file, wrong extension, missing data row). Per-row failures
    are reported in the import result instead — they don't raise."""

    code = "data_import.invalid"


# The natural keys a data-list import row names its related rows by. Each one
# is raised for one row and comes back as that row's error, with ``field``
# naming the column and ``details`` the value it could not resolve.


class MemberNumberUnknown(BadRequestError):
    """No member carries the row's ``member_number``."""

    code = "member.number_unknown"


class PaymentCycleUnknown(BadRequestError):
    """No payment cycle carries the row's ``payment_cycle`` choice."""

    code = "payment_cycle.unknown"


class ShareTypeNameUnknown(BadRequestError):
    """No share type carries the row's ``share_type`` name."""

    code = "share_type.name_unknown"


class ShareTypeNameAmbiguous(BadRequestError):
    """More than one share type carries the row's ``share_type`` name."""

    code = "share_type.name_ambiguous"


class ShareTypeVariationSizeUnknown(BadRequestError):
    """The share type has no variation of the row's ``size`` active on the
    row's start date."""

    code = "share_type_variation.size_unknown"


class ShareTypeVariationSizeAmbiguous(BadRequestError):
    """The share type has more than one variation of the row's ``size`` active
    on the row's start date."""

    code = "share_type_variation.size_ambiguous"


class DeliveryDayNumberUnknown(BadRequestError):
    """No delivery day with the row's ``delivery_day`` number is active on the
    row's start date."""

    code = "delivery_day.number_unknown"


class DeliveryStationDayUnknown(BadRequestError):
    """No station named by the row's ``delivery_station`` is served on its
    delivery day on the row's start date."""

    code = "delivery_station_day.unknown"


class DeliveryStationDayAmbiguous(BadRequestError):
    """More than one station named by the row's ``delivery_station`` is served
    on its delivery day on the row's start date (short names are not unique)."""

    code = "delivery_station_day.ambiguous"


# --------------------------------------------------------------------------- #
# Weekly share-demand imports                                                 #
# --------------------------------------------------------------------------- #


class ShareImportBatchInTerminalStatus(BadRequestError):
    """A share-import batch whose stored status already records what it did to
    the week's demand was asked to run another stage: ``applied`` means its rows
    ARE the live demand, ``superseded`` means a later batch replaced them.
    Either way the week must not be rewritten from that file again — the office
    uploads a new one. ``details`` carries ``batch_id`` and ``status``."""

    code = "share_import.batch_in_terminal_status"


class ExternalCodeMappingTargetMissing(BadRequestError):
    """An external-code mapping names an ``internal_id`` with no object of its
    kind — a station, share type variation or delivery day. ``details``
    carries the ``kind`` and the ``internal_id``."""

    code = "share_import.mapping_target_missing"


class ShareImportFileAlreadyUsed(ConflictError):
    """The uploaded bytes belong to a batch for that week whose status already
    records what it did to the demand (``applied`` / ``superseded``). Ingest is
    idempotent on (year, week, checksum), so handing that batch back would read
    as a fresh upload while preview and apply both refuse it. ``details``
    carries ``batch_id`` and ``status``."""

    code = "share_import.file_already_used"


class ShareImportValidationFailed(BadRequestError):
    """Rows in the uploaded file failed validation, so neither the preview nor
    the apply can build the week's demand from it. The error itself only says
    the file as a whole is unusable — WHICH rows failed and why is carried in
    the batch's ``validation_report``, which the import UI renders as a per-row
    table."""

    code = "share_import.validation_failed"


# --------------------------------------------------------------------------- #
# Purchases                                                                   #
# --------------------------------------------------------------------------- #


class OrganicPurchaseCertificateRequired(BadRequestError):
    """A purchase marked ``organic`` / ``in_conversion`` requires its seller to
    hold an OrganicCertificate valid AT the purchase's delivery week — the
    organic label can only be carried through from a currently-certified
    supplier."""

    code = "purchase.organic_certificate_required"
