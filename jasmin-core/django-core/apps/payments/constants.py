"""Choice/enum constants for the payments app."""

from __future__ import annotations

from django.db import models


class PaymentMethodOptions(models.TextChoices):
    SEPA_DIRECT_DEBIT = "SEPA_DD", "SEPA Direct Debit"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"


class ChargeStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planned"  # mutable; can be regenerated
    ISSUED = "ISSUED", "Issued"  # locked into a BillingRun, exported
    PAID = "PAID", "Paid"
    PARTIAL = "PARTIAL", "Partially paid"
    FAILED = "FAILED", "Returned by bank"
    WAIVED = "WAIVED", "Waived"


class BillingRunStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    EXPORTED = "EXPORTED", "Exported"
    SETTLED = "SETTLED", "Settled"


# Subset of statuses that count as "owed but not yet paid".
OPEN_CHARGE_STATUSES = (ChargeStatus.PLANNED, ChargeStatus.ISSUED, ChargeStatus.PARTIAL)
