from django.db import models

from apps.shared.model_fields import iso_week_field


# the textchoices here are given by the app, are to be chosen by the tenant, but can not be changed by the tenant:
class MovementTypeOptions(models.TextChoices):
    SHARE = "SHARECONTENT"
    ORDERCONTENT = "ORDERCONTENT"
    DONATION = "DONATION"
    HARVEST = "HARVEST"
    PURCHASE = "PURCHASE"
    STOCK = "STOCK"
    WASH = "WASH"
    CLEAN = "CLEAN"
    WASTE = "WASTE"
    INVENTORY = "INVENTORY"


class CultivationOriginOptions(models.TextChoices):
    GH = "GH"  # greenhouse
    OF = "OF"  # open field


class DeliveryCycleOptions(models.TextChoices):
    # Week-stride cadences only — every value maps to a well-defined set of
    # delivery weeks. ODD/EVEN are ISO-week parity (biweekly load-split);
    # ALL_THREE/ALL_FOUR are "every Nth delivery week" from the subscription's
    # start. Month-based cycles were removed: "monthly" can't be materialised
    # without a day-of-month / week-of-month rule, so it needs its own model
    # field before it can come back (see docs/todos).
    WEEKLY = "WEEKLY"
    ODD_WEEKS = "ODD_WEEKS"
    EVEN_WEEKS = "EVEN_WEEKS"
    ALL_THREE_WEEKS = "ALL_THREE_WEEKS"
    ALL_FOUR_WEEKS = "ALL_FOUR_WEEKS"


class ShareTypeVariationSizeOptions(models.TextChoices):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "XXL"
    HALF = "HALF"
    FULL = "FULL"
    ONESIZE = "ONE_SIZE"


class UnitOptions(models.TextChoices):
    KG = "KG"
    PCS = "PCS"  # pieces
    BUNCH = "BUNCH"  # bunch / (dt.: Bund)

    L = "L"  # liter
    G = "G"  # gram


class PaymentCycleOptions(models.TextChoices):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUALLY = "SEMI_ANNUALLY"
    ANNUALLY = "ANNUALLY"


class VegetableSizeOptions(models.TextChoices):
    S = "S"
    M = "M"
    L = "L"


class ShareOptions(models.TextChoices):
    HARVEST_SHARE = "HARVEST_SHARE"
    HARVEST_SHARE_FRUITS_ONLY = "HARVEST_SHARE_FRUIT"
    CHICKEN_SHARE = "CHICKEN_SHARE"
    HONEY_SHARE = "HONEY_SHARE"
    OIL_SHARE = "OIL_SHARE"
    GRAIN_SHARE = "GRAIN_SHARE"
    BREAD_SHARE = "BREAD_SHARE"


class DayNumberOptions(models.IntegerChoices):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class ConsentKind(models.TextChoices):
    """Categories of consent the platform records (DSGVO Art. 7 + 9).

    Add to this list when a new legal text is introduced (e.g. cookie
    policy, marketing opt-in). Existing ConsentRecord rows keep their
    old value; old documents stay queryable.
    """

    PRIVACY = "privacy", "Privacy policy"
    SEPA = "sepa", "SEPA Direct Debit mandate"
    WITHDRAWAL = "withdrawal", "Withdrawal terms"
    TERMS = "terms", "Terms of service"
    COOP_CONTRACT = "coop_contract", "Cooperative-share subscription contract"
    SUBSCRIPTION_CONTRACT = "subscription_contract", "Subscription contract"


class DocumentType(models.TextChoices):
    """Kind of reseller financial document. ``STORNO`` and ``CORRECTION`` are
    both credit-note variants (an issued invoice can't be edited — GoBD/UStG —
    so it's cancelled or corrected). Values/labels mirror the former inline
    ``InvoiceReseller.document_type`` choices exactly (no data migration)."""

    INVOICE = "invoice", "Invoice"
    STORNO = "storno", "Storno/Cancellation"
    CORRECTION = "correction", "Correction"


class InvitationStatus(models.TextChoices):
    """Lifecycle status of a ``UserInvitation``. Values/labels mirror the
    former inline ``UserInvitation.status`` choices exactly (no data
    migration). There is deliberately no "pending" status — a freshly created
    invitation starts as ``SENT``."""

    SENT = "sent", "Sent"
    ACCEPTED = "accepted", "Accepted"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


# ---------------------------------------------------------------------------
# Produce-dimension field factories
#
# The size / unit / delivery-week columns are copy-pasted verbatim across the
# reseller-line, share, documentation, movement and stock-snapshot models.
# These factories are the single source of truth for those field definitions.
# Each returns a definition that is BYTE-IDENTICAL to the inline version it
# replaces (same max_length / choices / validators / default / blank / null),
# so adopting them produces no migration.
# ---------------------------------------------------------------------------


def size_vegetable_field() -> models.CharField:
    """The produce ``size`` CharField (``VegetableSizeOptions``: S / M / L),
    defaulting to M."""
    return models.CharField(
        max_length=1,
        choices=VegetableSizeOptions.choices,
        default=VegetableSizeOptions.M,
    )


def unit_field(
    *, max_length: int = 10, blank: bool = False, null: bool = False
) -> models.CharField:
    """The produce ``unit`` CharField (``UnitOptions``).

    ``max_length`` is a parameter ONLY to preserve the existing per-column
    widths byte-identically: the ``DocumentationMixin`` column is historically
    20 while every other unit column is 10. Normalising that width would
    require a migration and is out of scope here, so that one site passes
    ``max_length=20`` to keep its DDL unchanged. ``blank`` / ``null`` default
    to the required-column case; pass both ``True`` for the nullable variant.
    """
    return models.CharField(
        max_length=max_length,
        choices=UnitOptions.choices,
        blank=blank,
        null=null,
    )


def delivery_week_field(**kwargs) -> models.PositiveSmallIntegerField:
    """The ISO ``delivery_week`` field (1..53). Thin alias over the shared
    :func:`apps.shared.model_fields.iso_week_field` so the 1..53 invariant has a
    single definition; extra kwargs (e.g. ``db_index=True``) pass through."""
    return iso_week_field(**kwargs)
