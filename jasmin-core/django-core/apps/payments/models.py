"""Models for the member-billing subsystem.

See `text/payments_design.md` in the repo root for the full design rationale.

Source-of-truth ledger lives in `ChargeSchedule`. One row per
(subscription, billing period). The generator (services.py) computes
`expected_amount` from `ShareDelivery` rows that fall in the period.

CoopShares are intentionally NOT billed through this system — they are
paid by the member manually (no SEPA), and `apps.commissioning.models.CoopShare`
keeps its own `due_date` / `paid_at` columns.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from encrypted_model_fields.fields import EncryptedCharField

from apps.commissioning.models.base import JasminModel
from apps.shared.iban_validator import validate_iban

from .constants import (
    BillingRunStatus,
    ChargeStatus,
    PaymentMethodOptions,
)


class BillingProfile(JasminModel):
    """Per-member payment-method record. One per Member."""

    member = models.OneToOneField(
        "commissioning.Member",
        # PROTECT (not CASCADE): a hard member delete must not silently wipe the
        # SEPA mandate + encrypted bank PII. PROTECT forces the GDPR
        # anonymize-in-place path (scrubs the columns, keeps the row + audit
        # trail) and is consistent with the other member FKs (CoopShare /
        # MemberLoan / ChargeSchedule / ConsentRecord all PROTECT).
        on_delete=models.PROTECT,
        related_name="billing_profile",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethodOptions.choices,
        default=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
    )

    # SEPA mandate fields. Required when payment_method == SEPA_DIRECT_DEBIT.
    # Bank-identifier fields are encrypted at rest (Fernet via
    # ``encrypted_model_fields``). ``sepa_mandate_reference`` is left
    # plaintext on purpose: encryption uses a random IV, so the column
    # would never match identically and the ``unique=True`` constraint
    # would be silently neutered. The mandate reference is an opaque
    # token we generate, not a bank-account identifier.
    iban = EncryptedCharField(
        max_length=34, blank=True, default="", validators=[validate_iban]
    )
    account_holder = EncryptedCharField(max_length=200, blank=True, default="")
    sepa_mandate_reference = models.CharField(
        max_length=35, unique=True, blank=True, null=True
    )
    sepa_mandate_signed_at = models.DateField(blank=True, null=True)
    sepa_mandate_first_use_at = models.DateField(
        blank=True,
        null=True,
        help_text="Set when first SEPA debit is exported. Drives FRST→RCUR.",
    )
    # Office stamp: when the signed PAPER SEPA mandate was physically received.
    # Only relevant when the tenant requires a paper signature for the mandate;
    # the office ticks a checkbox that sets this to today.
    sepa_mandate_paper_received_at = models.DateField(blank=True, null=True)

    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            # A SEPA mandate cannot be used before it was signed.
            models.CheckConstraint(
                condition=(
                    Q(sepa_mandate_first_use_at__isnull=True)
                    | Q(sepa_mandate_signed_at__isnull=True)
                    | Q(
                        sepa_mandate_first_use_at__gte=models.F(
                            "sepa_mandate_signed_at"
                        )
                    )
                ),
                name="billingprofile_first_use_after_signed",
            ),
        ]

    def __str__(self) -> str:
        return f"BillingProfile<{self.member_id}>"

    def clean(self) -> None:
        super().clean()
        if (
            self.payment_method == PaymentMethodOptions.SEPA_DIRECT_DEBIT
            and self.is_active
        ):
            missing = [
                name
                for name, value in (
                    ("iban", self.iban),
                    ("account_holder", self.account_holder),
                    ("sepa_mandate_reference", self.sepa_mandate_reference),
                    ("sepa_mandate_signed_at", self.sepa_mandate_signed_at),
                )
                if not value
            ]
            if missing:
                raise ValidationError(
                    {f: "Required for active SEPA Direct Debit." for f in missing}
                )
        if (
            self.sepa_mandate_first_use_at is not None
            and self.sepa_mandate_signed_at is not None
            and self.sepa_mandate_first_use_at < self.sepa_mandate_signed_at
        ):
            raise ValidationError(
                {
                    "sepa_mandate_first_use_at": (
                        "First SEPA use cannot be before the mandate was signed."
                    )
                }
            )

    @staticmethod
    def _generate_sepa_mandate_reference() -> str:
        """A unique, opaque SEPA Mandatsreferenz.

        ≤35 chars, SEPA-charset-safe (A-Z 0-9 -), NOT derived from the IBAN
        (which is encrypted PII). uuid4 makes collisions astronomically
        unlikely; the ``unique=True`` column is the hard backstop.
        """
        return f"MND-{uuid.uuid4().hex[:18].upper()}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Assign the Mandatsreferenz the first time this becomes a SEPA mandate
        # with bank details. Generated once and kept stable (never regenerated),
        # because ``is_sepa_ready`` + the pain.008 export both require it and a
        # changing reference would break an in-flight mandate at the bank.
        if (
            not self.sepa_mandate_reference
            and self.payment_method == PaymentMethodOptions.SEPA_DIRECT_DEBIT
            and self.iban
        ):
            self.sepa_mandate_reference = self._generate_sepa_mandate_reference()
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_sepa_ready(self) -> bool:
        return (
            self.is_active
            and self.payment_method == PaymentMethodOptions.SEPA_DIRECT_DEBIT
            and bool(self.iban)
            and bool(self.sepa_mandate_reference)
            and bool(self.sepa_mandate_signed_at)
        )


class ChargeSchedule(JasminModel):
    """Single line in the member ledger.

    One row per (subscription, billing period). The status column is the
    only mutable surface after a row leaves PLANNED. Amount + period are
    immutable once ISSUED, enforced in :meth:`save`.
    """

    member = models.ForeignKey(
        "commissioning.Member",
        on_delete=models.PROTECT,
        related_name="charge_schedules",
        db_index=True,
    )
    subscription = models.ForeignKey(
        "commissioning.Subscription",
        on_delete=models.PROTECT,
        related_name="charge_schedules",
    )

    period_start = models.DateField(db_index=True)
    period_end = models.DateField()
    due_date = models.DateField(db_index=True)

    expected_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="EUR")

    description = models.CharField(
        max_length=140,
        blank=True,
        default="",
        help_text="Appears as Verwendungszweck on the bank statement.",
    )

    status = models.CharField(
        max_length=10,
        choices=ChargeStatus.choices,
        default=ChargeStatus.PLANNED,
        db_index=True,
    )

    billing_run = models.ForeignKey(
        "BillingRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="charges",
    )
    end_to_end_id = models.CharField(
        max_length=35,
        blank=True,
        default="",
        help_text="SEPA EndToEndId; used to match incoming statement lines.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "period_start"],
                name="chargeschedule_unique_subscription_period",
            ),
            models.CheckConstraint(
                condition=Q(period_end__gte=models.F("period_start")),
                name="chargeschedule_period_end_gte_start",
            ),
            # The due date must fall inside the billing period.
            models.CheckConstraint(
                condition=(
                    Q(due_date__gte=models.F("period_start"))
                    & Q(due_date__lte=models.F("period_end"))
                ),
                name="chargeschedule_due_date_within_period",
            ),
        ]
        indexes = [
            models.Index(fields=["member", "due_date"]),
            models.Index(fields=["status", "due_date"]),
        ]
        ordering = ["due_date", "id"]

    def __str__(self) -> str:
        return (
            f"Charge<{self.member_id} {self.period_start}..{self.period_end} "
            f"{self.expected_amount}{self.currency} [{self.status}]>"
        )

    def clean(self) -> None:
        super().clean()
        if (
            self.due_date is not None
            and self.period_start is not None
            and self.due_date < self.period_start
        ):
            raise ValidationError(
                {"due_date": "Due date cannot be before the period start."}
            )
        if (
            self.due_date is not None
            and self.period_end is not None
            and self.due_date > self.period_end
        ):
            raise ValidationError(
                {"due_date": "Due date cannot be after the period end."}
            )

    def save(
        self, *args: Any, allow_immutable_change: bool = False, **kwargs: Any
    ) -> None:
        # Once a row leaves PLANNED its amount/period/subscription are frozen.
        # Status / billing_run / end_to_end_id stay editable.
        #
        # ``not self._state.adding`` gates this to genuine UPDATEs. JasminModel
        # assigns the CharField PK in Python at construction (default=
        # generate_jasmin_id), so ``self.pk`` is truthy even on a brand-new row
        # — without the ``adding`` guard, every create() fired a wasted SELECT
        # for a row that doesn't exist yet. Loaded instances (the only update
        # path) have adding=False, so the immutability check still runs there.
        if self.pk and not self._state.adding and not allow_immutable_change:
            existing = (
                type(self)
                .objects.filter(pk=self.pk)
                .only(
                    "status",
                    "expected_amount",
                    "period_start",
                    "period_end",
                    "subscription_id",
                )
                .first()
            )
            if existing and existing.status != ChargeStatus.PLANNED:
                frozen_changed = (
                    existing.expected_amount != self.expected_amount
                    or existing.period_start != self.period_start
                    or existing.period_end != self.period_end
                    or existing.subscription_id != self.subscription_id
                )
                if frozen_changed:
                    raise ValidationError(
                        "Cannot modify amount/period/subscription on a non-PLANNED charge "
                        f"(current status={existing.status})."
                    )
        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status in {
            ChargeStatus.PLANNED,
            ChargeStatus.ISSUED,
            ChargeStatus.PARTIAL,
        }


class BillingRun(JasminModel):
    """A batch export of ChargeSchedule rows to the bank.

    Once the run is EXPORTED, its charges flip PLANNED→ISSUED and the
    ``sepa_xml_export`` file is an immutable pain.008.001.02 XML
    artifact ready to upload to any SEPA-zone bank. We used to emit a
    bank-specific CSV here; the move to pain.008 standardizes the
    output across banks (see ``docs/tenant-settings-audit.md`` for
    the rationale).
    """

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    period_start = models.DateField(
        help_text="Charges with due_date in [period_start, period_end] are eligible.",
    )
    period_end = models.DateField()
    collection_date = models.DateField(
        help_text="Requested execution date sent to the bank (RequestedCollectionDate).",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethodOptions.choices,
        default=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
    )

    sepa_xml_export = models.FileField(upload_to="billing_runs/", blank=True, null=True)

    status = models.CharField(
        max_length=10,
        choices=BillingRunStatus.choices,
        default=BillingRunStatus.DRAFT,
        db_index=True,
    )

    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    charge_count = models.PositiveIntegerField(default=0)

    # SEPA message identifier. Stable across re-exports of the same run.
    msg_id = models.CharField(max_length=35, blank=True, default="")

    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "collection_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(period_end__gte=models.F("period_start")),
                name="billingrun_period_end_gte_start",
            ),
            # Hard lower bound only: collection cannot predate the period start.
            # collection_date < period_end stays an intentional soft warning
            # (advance / prepaid collection is legitimate), so it is NOT a
            # constraint here.
            models.CheckConstraint(
                condition=(
                    Q(collection_date__isnull=True)
                    | Q(period_start__isnull=True)
                    | Q(collection_date__gte=models.F("period_start"))
                ),
                name="billingrun_collection_after_period_start",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"BillingRun<{self.collection_date} {self.payment_method} "
            f"{self.charge_count}x {self.total_amount} [{self.status}]>"
        )

    def clean(self) -> None:
        super().clean()
        if (
            self.collection_date is not None
            and self.period_start is not None
            and self.collection_date < self.period_start
        ):
            raise ValidationError(
                {
                    "collection_date": "Collection date cannot be before the period start."
                }
            )
