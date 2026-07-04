from django.db import models


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


class SizeOptions(models.TextChoices):
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


class SizeVegetableOptions(models.TextChoices):
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
