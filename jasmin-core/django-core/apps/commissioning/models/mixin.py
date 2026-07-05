from __future__ import annotations

import datetime
import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import JasminUser
from apps.shared.money import round_money, to_decimal
from core.db_locks import acquire_advisory_xact_lock

from .managers import (
    ActiveOnlyManager,
    CurrentActiveManager,
)


class AdminConfirmableMixin(models.Model):
    # mixin that adds admin confirmation functionality to models.
    # adds fields and methods for admin approval workflow.

    admin_confirmed = models.BooleanField(default=False)
    admin_confirmed_by = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_confirmations",
    )
    admin_confirmed_at = models.DateTimeField(null=True, blank=True)
    admin_rejected_at = models.DateTimeField(null=True, blank=True)
    admin_rejection_reason = models.TextField(blank=True, null=True)

    class Meta:
        abstract = True

    def confirm(self, admin_user: JasminUser, *, save: bool = True) -> None:
        """Mark this row as admin-confirmed and run post-confirm side-effects.

        Subclasses opt in to side-effects by overriding ``_post_confirm()``
        (e.g. ``Member`` generates a member-number, ``Subscription``
        materialises shares + deliveries + charge schedule). This replaces
        the previous ``admin_confirmed`` Signal dispatch.
        """
        self.admin_confirmed = True
        self.admin_confirmed_by = admin_user
        self.admin_confirmed_at = timezone.now()
        self.admin_rejection_reason = None
        if save:
            self.save()
        self._post_confirm(admin_user=admin_user)

    def _post_confirm(self, *, admin_user: JasminUser) -> None:
        """Hook for subclasses — called after a successful ``confirm()``.

        Default is a no-op. Override to attach side-effects to confirmation.
        """
        return None

    def reject(
        self, admin_user: JasminUser, reason: str | None = None, *, save: bool = True
    ) -> None:

        self.admin_confirmed = False
        self.admin_confirmed_by = admin_user
        self.admin_confirmed_at = None
        self.admin_rejected_at = timezone.now()
        self.admin_rejection_reason = reason
        if save:
            self.save()

    @property
    def is_confirmed(self) -> bool:
        return self.admin_confirmed

    @property
    def is_rejected(self) -> bool:

        return self.admin_rejected_at is not None

    @property
    def is_pending(self) -> bool:
        return not self.admin_confirmed and self.admin_rejected_at is None


class TimeBoundMixin(models.Model):
    """Abstract model for objects with time-bound validity.

    Set ``overlap_unique_fields`` on subclasses to a tuple of field names
    that define the "group" within which periods must not overlap.
    When set, ``clean()`` will automatically reject overlapping records.

    Three states:

    * ``None`` (the default) — succession OFF; rows may freely overlap.
    * ``("field", ...)`` — one open row per distinct combination of those
      fields (e.g. one open ShareType per ``share_option``).
    * ``()`` (empty tuple) — a single GLOBAL group: at most one open row in
      the whole table at a time (e.g. one active ``Season``).

    Example::

        class SharesDeliveryDay(JasminModel, TimeBoundMixin):
            overlap_unique_fields = ("day_number",)
    """

    overlap_unique_fields: tuple[str, ...] | None = None

    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)

    objects = models.Manager()
    current = CurrentActiveManager()

    class Meta:
        abstract = True
        # Reverse relations and refresh_from_db should always use the
        # unfiltered manager — never the date-filtered ``current``.
        base_manager_name = "objects"
        ordering = ["-valid_from"]
        # The ``valid_until >= valid_from`` DB CheckConstraint is deliberately
        # NOT declared here: an abstract base's ``Meta.constraints`` does not
        # propagate to a concrete subclass whose Meta resolves from a different
        # base, and ``JasminModel.Meta`` shadows this one in the
        # ``(JasminModel, TimeBoundMixin)`` MRO every subclass uses. So EVERY
        # concrete subclass (Subscription included) wires the check explicitly
        # via ``time_bound_valid_range_constraint(<name>)`` in its own
        # ``Meta.constraints`` — see the helper just below this class.

    def clean(self) -> None:
        super().clean()
        self.validate_week_boundaries(self.valid_from, self.valid_until)
        self.validate_date_range(self.valid_from, self.valid_until)
        if self.overlap_unique_fields is not None:
            self._validate_no_overlap()

    def save(self, *args, **kwargs) -> None:
        """Run ``full_clean()`` so the overlap / date-range checks always fire.

        Without this, calls coming through DRF (``serializer.save()``),
        the shell, or anything that bypasses ModelForm/admin would skip
        ``clean()`` and silently allow overlapping ranges.

        Also auto-closes any currently-open predecessor in the same overlap
        group on creation, so callers don't have to remember to invoke
        ``handle_succession`` themselves.

        Note: ``bulk_create`` / ``bulk_update`` / ``QuerySet.update()`` still
        bypass this — for a hard guarantee, add a Postgres
        ``ExclusionConstraint`` (requires ``btree_gist``) on the subclass.
        """
        # Atomic so a later full_clean()/INSERT failure rolls back the
        # predecessor close: a TimeBound slot must never end up with a closed
        # predecessor and no successor. handle_succession closes the open
        # predecessor (committing it on its own @transaction.atomic), but
        # full_clean() (non-Monday valid_from, opt-in/packing guards) and the
        # INSERT (partial-unique race) run AFTER it — without this wrapper a
        # failure there strands the just-closed predecessor with no successor.
        # handle_succession's own atomic degrades to a savepoint inside this.
        with transaction.atomic():
            # Auto-succession on create: if a sibling in the same overlap group
            # is still open (``valid_until IS NULL``), close it the day before
            # this new record starts. Siblings that already have an end date
            # are left alone (gaps are allowed).
            if (
                self._state.adding
                and self.overlap_unique_fields is not None
                and self.valid_from is not None
            ):
                new_data = {
                    field: getattr(self, field) for field in self.overlap_unique_fields
                }
                new_data["valid_from"] = self.valid_from
                self.__class__.handle_succession(new_data)

            self.full_clean()
            super().save(*args, **kwargs)

    # NOTE: The CheckConstraint in Meta enforces ``valid_until >= valid_from``
    # at the DB level for the bulk paths that bypass ``save()``.

    @staticmethod
    def validate_week_boundaries(valid_from, valid_until) -> None:
        """Ensure valid_from is a Monday and valid_until is a Sunday (or null).

        Exposed as a staticmethod so service-layer bulk operations can call
        the same logic that ``clean()`` uses.
        """
        if valid_from and valid_from.weekday() != 0:
            raise ValidationError(
                {"valid_from": "The 'valid_from' date must be a Monday."}
            )
        if valid_until and valid_until.weekday() != 6:
            raise ValidationError(
                {"valid_until": "The 'valid_until' date must be a Sunday."}
            )

    @staticmethod
    def validate_date_range(valid_from, valid_until) -> None:
        """Ensure valid_until is same or after valid_from.

        Exposed as a staticmethod so service-layer bulk operations can call
        the same logic that ``clean()`` uses.
        """
        if valid_from and valid_until:
            if valid_until < valid_from:
                raise ValidationError(
                    {
                        "valid_until": "End date must be same or after start date.",
                        "valid_from": "Start date must be same or before end date.",
                    }
                )

    def _validate_no_overlap(self) -> None:
        """Reject overlapping time periods within the same group.

        The group is defined by ``overlap_unique_fields``.

        WARNING: this is a TOCTOU check. For a hard guarantee, add a
        Postgres ExclusionConstraint (requires btree_gist) on the subclass.
        """
        _sentinel = datetime.date(9999, 12, 31)

        filter_kwargs = {
            field: getattr(self, field) for field in self.overlap_unique_fields
        }
        siblings = self.__class__.objects.filter(**filter_kwargs).exclude(pk=self.pk)

        self_until = self.valid_until or _sentinel

        for existing in siblings:
            existing_until = existing.valid_until or _sentinel
            if self.valid_from <= existing_until and self_until >= existing.valid_from:
                raise ValidationError(
                    f"Overlapping period detected with existing record "
                    f"({existing.valid_from} to {existing.valid_until})"
                )

    @classmethod
    @transaction.atomic
    def handle_succession(cls, new_data: dict):
        """Close the currently-open record in the same overlap group so the
        new record can take over without violating the no-overlap constraint.

        ``new_data`` must contain values for every field listed in
        ``overlap_unique_fields`` plus ``valid_from``.

        Returns the previous (now closed) record, or ``None`` when there is
        nothing to succeed.
        """
        if cls.overlap_unique_fields is None:
            raise ValueError(f"{cls.__name__} does not define overlap_unique_fields")

        new_valid_from = new_data.get("valid_from")
        if new_valid_from is None:
            raise ValueError("new_data must include 'valid_from'")

        filter_kwargs = {field: new_data[field] for field in cls.overlap_unique_fields}

        existing = cls.objects.filter(**filter_kwargs, valid_until__isnull=True).first()

        if existing is None:
            return None

        # Nothing to do when the existing record starts on the same date
        if existing.valid_from == new_valid_from:
            return None

        # A new record may not start *before* the open record it succeeds:
        # closing the predecessor at ``new_valid_from - 1 day`` would give it an
        # end date before its own start. Reject with a clear error instead of
        # the confusing valid_until/valid_from ValidationError that full_clean
        # would otherwise raise on the predecessor row.
        if new_valid_from < existing.valid_from:
            from apps.commissioning.errors import SuccessionStartBeforePredecessor

            raise SuccessionStartBeforePredecessor(
                new_valid_from=new_valid_from,
                existing_valid_from=existing.valid_from,
            )

        existing.valid_until = new_valid_from - timedelta(days=1)
        existing.save()
        return existing


def time_bound_valid_range_constraint(name: str) -> models.CheckConstraint:
    """``valid_until IS NULL OR valid_until >= valid_from`` as a DB CheckConstraint.

    ``TimeBoundMixin.Meta`` declares this same check, but Django does NOT
    propagate an abstract base's ``Meta.constraints`` to a concrete subclass
    whose resolved Meta comes from a different base — and every subclass is
    declared ``(JasminModel, TimeBoundMixin)``, so ``JasminModel.Meta`` shadows
    ``TimeBoundMixin.Meta`` and the check is silently dropped. The Python
    ``clean()`` range validation (run from ``save()``) does NOT cover the
    ``bulk_create`` / ``bulk_update`` / ``QuerySet.update()`` / raw-SQL paths,
    so this DB backstop must be added to each concrete subclass's OWN
    ``Meta.constraints`` with a per-model ``name`` — Subscription included
    (it keeps inheriting ordering / base_manager_name from
    ``TimeBoundMixin.Meta`` but wires the check via this helper like the rest).
    """
    return models.CheckConstraint(
        condition=models.Q(valid_until__isnull=True)
        | models.Q(valid_until__gte=models.F("valid_from")),
        name=name,
    )


class PricingMixin:
    """Mixin for models that have a related 'pricing' queryset with TimeBoundMixin entries."""

    def get_pricing_on_date(self, date: datetime.date):
        # newest-effective-wins tie-break: the pricing models declare their own
        # Meta (so TimeBoundMixin's ordering isn't inherited) and the no-overlap
        # guard is a TOCTOU check with no DB exclusion backstop — so order
        # explicitly to stay deterministic if two windows ever overlap (matches
        # the sibling resolvers in basics_viewsets). This is the canonical
        # tax_rate / net-price read for invoices.
        from .managers import active_on_date_q

        return (
            self.pricing.filter(active_on_date_q(date)).order_by("-valid_from").first()
        )


# ---------------------------------------------------------------------------
# Netto / Brutto pricing helpers (single source of truth for line/document totals)
# ---------------------------------------------------------------------------

_PRICE_ZERO = Decimal("0.00")
_PRICE_ONE = Decimal("1")
_PRICE_HUNDRED = Decimal("100")
_PRICE_QUANTIZE = Decimal("0.01")
# Public alias for cross-module reuse (e.g. crate_summary, member_register_export)
# so other commissioning modules don't redeclare the cent constant or import the
# underscore-private name.
PRICE_QUANTIZE = _PRICE_QUANTIZE


# Float-safe coercer — the shared primitive (apps.shared.money.to_decimal),
# re-exported under the historical name so existing imports keep working.
_to_decimal = to_decimal


def _calc_line_netto(*, amount, price_per_unit, rabatt=None) -> Decimal:
    """Net price for one line item: ``amount * price_per_unit * (1 - rabatt/100)``.

    ``amount`` is in physical units (kg/pcs/bunch) and ``price_per_unit`` is
    €/unit — there is intentionally NO ``amount_per_pu`` factor (that is a
    PU-conversion quantity for stock / ``ordered_amount``, never a price
    multiplier). EVERY reseller line model — order / delivery-note / invoice /
    storno / crate content — uses this one formula, so the net reconciles
    across the order → delivery-note → invoice chain.
    """
    if amount is None or price_per_unit is None:
        return _PRICE_ZERO
    a = _to_decimal(amount)
    p = _to_decimal(price_per_unit)
    r = _to_decimal(rabatt)
    return round_money(a * p * (_PRICE_ONE - r / _PRICE_HUNDRED))


def _calc_line_brutto(netto: Decimal, *, tax_rate=None) -> Decimal:
    """Gross = ``netto * (1 + tax_rate/100)``."""
    t = _to_decimal(tax_rate)
    return round_money(netto * (_PRICE_ONE + t / _PRICE_HUNDRED))


# Public aliases — same names used on serializers/properties for consistency.
line_netto = _calc_line_netto
line_brutto = _calc_line_brutto


def sum_netto(items) -> Decimal:
    return sum((item.line_netto for item in items), _PRICE_ZERO).quantize(
        _PRICE_QUANTIZE, rounding=ROUND_HALF_UP
    )


def sum_brutto(items) -> Decimal:
    """Total gross derived from ``tax_breakdown`` so per-rate rounding is
    legally consistent (one tax rounding per VAT rate, not per line)."""
    return sum(
        (group["brutto"] for group in tax_breakdown(items)), _PRICE_ZERO
    ).quantize(_PRICE_QUANTIZE, rounding=ROUND_HALF_UP)


def tax_breakdown(*item_iterables) -> list[dict]:
    """Group line items by ``tax_rate`` and return per-rate totals.

    Each group: ``{"rate": Decimal, "netto": Decimal, "tax": Decimal,
    "brutto": Decimal}``. Tax and brutto are quantized once per group
    (sum of nettos × rate, then rounded). Accepts one or many iterables of
    line items so callers can mix article and crate items.
    """
    buckets: dict[Decimal, Decimal] = {}
    for items in item_iterables:
        for item in items:
            rate = _to_decimal(getattr(item, "tax_rate", None))
            buckets[rate] = buckets.get(rate, _PRICE_ZERO) + item.line_netto

    breakdown = []
    for rate in sorted(buckets):
        netto = buckets[rate].quantize(_PRICE_QUANTIZE, rounding=ROUND_HALF_UP)
        tax = (netto * rate / _PRICE_HUNDRED).quantize(
            _PRICE_QUANTIZE, rounding=ROUND_HALF_UP
        )
        breakdown.append(
            {
                "rate": rate,
                "netto": netto,
                "tax": tax,
                "brutto": (netto + tax).quantize(
                    _PRICE_QUANTIZE, rounding=ROUND_HALF_UP
                ),
            }
        )
    return breakdown


class LinePricingMixin:
    """Adds ``line_netto`` / ``line_brutto`` properties to a line-item model.

    Requires ``amount``, ``price_per_unit``, ``rabatt`` and ``tax_rate``
    attributes. The net is ``amount × price_per_unit × (1 − rabatt/100)`` for
    EVERY reseller line model (amount in units, price €/unit) — do NOT
    re-introduce an ``amount_per_pu`` price multiplier: that quantity is for PU
    conversion (stock / ``ordered_amount``), not pricing, and a multiplier here
    would diverge the order net from the legally-issued invoice (DOC-1).
    """

    @property
    def line_netto(self) -> Decimal:
        return _calc_line_netto(
            amount=getattr(self, "amount", None),
            price_per_unit=getattr(self, "price_per_unit", None),
            rabatt=getattr(self, "rabatt", None),
        )

    @property
    def line_brutto(self) -> Decimal:
        return _calc_line_brutto(
            self.line_netto, tax_rate=getattr(self, "tax_rate", None)
        )


class ArchivableMixin(models.Model):
    """Mixin to add archive functionality to models with CreatedMixin"""

    objects = models.Manager()
    active = ActiveOnlyManager(archive_months=2)

    class Meta:
        abstract = True
        # Reverse relations and refresh_from_db should always use the
        # unfiltered manager — never the date-filtered ``active``.
        base_manager_name = "objects"
        indexes = [
            models.Index(fields=["created_at"]),
        ]

    @classmethod
    def get_archive_cutoff_date(cls, months_back: int = 2) -> datetime.datetime:
        return timezone.now() - timedelta(days=30 * months_back)

    def is_archived(self, months_back: int = 2) -> bool:
        cutoff_date = self.get_archive_cutoff_date(months_back)
        return self.created_at < cutoff_date if self.created_at else False


class CreatedMixin(models.Model):
    """Adds ``created_at`` / ``created_by``."""

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_created_by",
    )

    class Meta:
        abstract = True


class CancellableMixin(models.Model):
    """Adds cancellation fields."""

    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancelled_effective_at = models.DateField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_cancelled_by",
    )

    class Meta:
        abstract = True

    # NB: no cancelled_effective_at >= cancelled_at order guard here on purpose.
    # The office cancel flow legitimately BACKDATES — recording today a
    # cancellation whose legal exit date already passed (a member who left last
    # month) — so the effective date may precede the recorded timestamp.


class PayableMixin(models.Model):
    """Adds ``paid_at``."""

    due_date = models.DateField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True

    # NOTE: there is intentionally NO paid_at >= due_date invariant. ``due_date``
    # is a payment DEADLINE, not an earliest-payment date — paying before the due
    # date is normal and legal (e.g. a reseller settling an invoice well within
    # its 14-day terms). Stamping ``paid_at`` to "now" when "now" is before the
    # due date is correct, so no clean()/constraint guard is added here.


class SourceSnapshotMixin(models.Model):
    """Snapshot of the upstream document row at creation time.

    Used by ``DifferenceTrackingMixin`` (serializer side) to compute
    ``*_differs`` / ``original_*`` flags locally without N+1 lookups.

    All fields are nullable: ``NULL`` means "no upstream source" (e.g.
    manual lines, or backfilled rows where the source could not be uniquely
    identified). Summary invoices that merge multiple DN lines DO snapshot:
    their grouping key pins price/unit/size/rabatt, and ``source_amount``
    carries the merged total.

    ``source_amount`` uses ``Decimal(10, 3)`` so the same column type fits
    both integer crate amounts and decimal share/extra-article amounts.
    """

    source_amount = models.DecimalField(
        max_digits=10, decimal_places=3, blank=True, null=True
    )
    source_unit = models.CharField(max_length=10, blank=True, null=True)
    source_size = models.CharField(max_length=1, blank=True, null=True)
    source_price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    source_rabatt = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )

    class Meta:
        abstract = True


class FinalizableMixin(models.Model):
    """
    Mixin that adds finalization fields and basic finalization functionality.
    """

    is_finalized = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(blank=True, null=True)
    finalized_by = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )

    class Meta:
        abstract = True

    def assert_not_finalized(self, *, label: str, code: str) -> None:
        """Raise ``FinalizedError`` if this record is already finalized — the
        opening guard of the ``finalize_*`` service methods (Order /
        DeliveryNote / Invoice). ``finalize()`` itself also re-checks under a
        lock; this is the early, explicit service-layer guard."""
        if self.is_finalized:
            from apps.commissioning.errors import FinalizedError

            raise FinalizedError(f"{label} is already finalized", code=code)

    def finalize(self, user: JasminUser | None = None) -> bool:
        """Finalize this record using a locked, two-step save.

        The row is ``select_for_update``-locked and ``is_finalized`` is
        re-checked INSIDE the transaction, so two concurrent ``finalize()``
        calls serialise: the second to acquire the lock observes the row
        already finalized and returns ``False`` instead of re-stamping
        ``finalized_at`` / ``finalized_by`` (a corrupt double-finalization of
        a legally-significant record). The two-step save is preserved — audit
        columns are written first, while ``is_finalized`` is still ``False`` so
        the BEFORE UPDATE protection trigger permits them, then ``is_finalized``
        is flipped.
        """
        # Cheap fast-path so the common already-finalized case skips the
        # transaction; the authoritative check is under the row lock below.
        if self.is_finalized:
            return False

        with transaction.atomic():
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.is_finalized:
                # Lost the race — another transaction finalized between the
                # fast-path check and acquiring the lock. Reconcile the
                # in-memory instance and bail without touching a protected
                # column on the already-finalized row.
                self.is_finalized = True
                self.finalized_at = locked.finalized_at
                self.finalized_by_id = locked.finalized_by_id
                return False

            # STEP 1: stamp the audit columns while is_finalized is still False
            # (the trigger short-circuits ``IF NOT OLD.is_finalized RETURN NEW``).
            locked.finalized_at = timezone.now()
            locked.finalized_by = user
            locked.save(update_fields=["finalized_at", "finalized_by"])

            # STEP 2: flip is_finalized (trigger + the Python save() fast-path
            # both allow update_fields == ["is_finalized"]).
            locked.is_finalized = True
            locked.save(update_fields=["is_finalized"])

            # Keep the caller's in-memory instance consistent — callers keep
            # using ``self`` to traverse relations after finalize() returns.
            self.is_finalized = True
            self.finalized_at = locked.finalized_at
            self.finalized_by_id = locked.finalized_by_id
            return True

    def unfinalize(self) -> None:
        """Reverse :meth:`finalize` using a locked, two-step save.

        The row is ``select_for_update``-locked so concurrent unfinalizes
        serialise. The Postgres ``finalized_protect`` triggers reject any
        UPDATE that touches ``finalized_at`` / ``finalized_by`` while
        ``OLD.is_finalized`` is still TRUE, so we clear ``is_finalized`` first
        (the trigger whitelists it) and only then null the audit columns.
        """
        with transaction.atomic():
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.is_finalized:
                locked.is_finalized = False
                locked.save(update_fields=["is_finalized"])

            locked.finalized_at = None
            locked.finalized_by = None
            locked.save(update_fields=["finalized_at", "finalized_by"])

            # Reconcile the caller's in-memory instance.
            self.is_finalized = False
            self.finalized_at = None
            self.finalized_by_id = None


class FinalizedProtectedQuerySet(models.QuerySet):
    """QuerySet that protects finalized rows from bulk ``update()`` and
    ``delete()``.

    Pairs with ``FinalizedProtectedMixin``. Together with the per-table
    Postgres triggers installed by migration ``0002_finalized_protection_triggers.py``
    this gives three layers of defence:

    1. ``FinalizedProtectedMixin`` — per-instance ``save()`` / ``delete()``.
    2. ``FinalizedProtectedQuerySet`` (this class) — ORM bulk paths
       (``QuerySet.update()``, ``QuerySet.delete()``, ``bulk_update`` which
       internally calls ``update()``).
    3. Postgres triggers — catches raw SQL and any ORM path that bypasses
       both Python layers.
    """

    def update(self, **kwargs):
        # One-way enforcement, mirroring the save() layer: a bulk
        # ``update(is_finalized=False)`` on a legally-immutable model must be
        # refused when the queryset touches any finalized row. The generic
        # whitelist check below subtracts ``is_finalized`` unconditionally, so
        # without this the unfinalize bulk path would slip past the Python
        # layer and rely on the Postgres trigger alone.
        if (
            getattr(self.model, "IS_FINALIZED_ONE_WAY", False)
            and kwargs.get("is_finalized") is False
            and self.filter(is_finalized=True).exists()
        ):
            from apps.commissioning.errors import FinalizedError

            raise FinalizedError(
                f"Cannot bulk-unfinalize {self.model.__name__} — finalized "
                "documents of this type are legally immutable. To reverse, "
                "create a storno; to revise, issue a correction document."
            )

        allowed = set(getattr(self.model, "ALLOWED_FINALIZED_UPDATES", []))
        disallowed = set(kwargs) - allowed - {"is_finalized"}
        # Only block when the queryset actually touches finalized rows AND the
        # caller is updating fields that are not whitelisted.
        if disallowed and self.filter(is_finalized=True).exists():
            raise ValidationError(
                f"Cannot bulk-update {self.model.__name__} — queryset includes "
                f"finalized rows. Disallowed fields: "
                f"{', '.join(sorted(disallowed))}. Only these fields can be "
                f"updated when finalized: "
                f"{', '.join(sorted(allowed)) or '(none)'}"
            )
        return super().update(**kwargs)

    def delete(self):
        if self.filter(is_finalized=True).exists():
            raise ValidationError(
                f"Cannot bulk-delete {self.model.__name__} — queryset includes "
                f"finalized rows."
            )
        return super().delete()


class FinalizedProtectedMixin:
    """Mixin that prevents modification/deletion when finalized.

    Must be used together with ``FinalizableMixin`` on a concrete Model.
    Place it *before* the Model class in the MRO so save()/delete() intercept.

    Per-instance protection only. To also protect bulk ORM operations
    (``QuerySet.update()``, ``QuerySet.delete()``, ``bulk_update()``),
    concrete subclasses should attach the manager explicitly::

        class Order(... FinalizedProtectedMixin, JasminModel):
            objects = FinalizedProtectedQuerySet.as_manager()

    Raw SQL still bypasses both layers — for absolute safety, add a
    Postgres trigger.

    Insert-into-finalized-parent protection
    ---------------------------------------
    Set ``PARENT_FK_FIELDS`` on a content model (e.g. ``OrderContent``,
    ``InvoiceResellerContent``) to a list of FK field names that point
    at a finalizable parent. ``save()`` will refuse to INSERT a new row
    whose parent is currently finalized — closing the gap in the
    Postgres ``BEFORE UPDATE OR DELETE`` trigger which by design does
    not fire on INSERT.
    """

    ALLOWED_FINALIZED_UPDATES: list[str] = []
    #: FK field names whose target object must NOT be finalized at INSERT.
    PARENT_FK_FIELDS: list[str] = []
    #: When ``True``, ``is_finalized = True → False`` flips are refused at
    #: the ``save()`` layer (in addition to the existing ``unfinalize()``
    #: override that raises ``FinalizedError``). Closes the bypass where a
    #: shell paste or rogue service does
    #: ``obj.is_finalized = False; obj.save(update_fields=["is_finalized"])``
    #: directly, skipping ``unfinalize()``. Set ``True`` on Order /
    #: DeliveryNoteReseller / InvoiceReseller — the GoBD / HGB §257 /
    #: UStG §14 "legally immutable once issued" documents. The matching
    #: Postgres trigger refuses the same transition.
    IS_FINALIZED_ONE_WAY: bool = False

    def _check_no_finalized_parent_on_insert(self) -> None:
        from apps.commissioning.errors import FinalizedError

        for field_name in self.PARENT_FK_FIELDS:
            # ``PARENT_FK_FIELDS`` lists real FKs on the model — drop
            # the default so a typo in the class-level allowlist
            # crashes during insert rather than silently letting the
            # write past the finalized-parent guard.
            parent = getattr(self, field_name)
            if parent is not None and getattr(parent, "is_finalized", False):
                raise FinalizedError(
                    f"Cannot add {self.__class__.__name__} to a finalized "
                    f"{parent.__class__.__name__} (id={parent.pk})."
                )

    def save(self, *args, **kwargs) -> None:
        from apps.commissioning.errors import FinalizedError

        update_fields: list[str] | None = kwargs.get("update_fields")
        is_insert = self._state.adding

        # One-way enforcement: refuse the unfinalize transition for models
        # where finalization is legally one-way. We can't rely on the
        # ``self.is_finalized`` check below because the caller has already
        # flipped it to ``False`` in memory; the DB row is still
        # ``True``. Inspect the persisted state directly.
        if (
            not is_insert
            and self.IS_FINALIZED_ONE_WAY
            and update_fields
            and "is_finalized" in update_fields
            and not self.is_finalized
        ):
            was_finalized = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("is_finalized", flat=True)
                .first()
            )
            if was_finalized:
                raise FinalizedError(
                    f"Cannot unfinalize {self.__class__.__name__} via save() — "
                    "finalized documents of this type are legally immutable. "
                    "To reverse, create a storno; to revise, issue a correction "
                    "document."
                )

        if not is_insert and self.is_finalized:
            # Allow the finalization step itself
            if update_fields == ["is_finalized"]:
                super().save(*args, **kwargs)
                return

            if update_fields:
                disallowed = set(update_fields) - set(self.ALLOWED_FINALIZED_UPDATES)
                if disallowed:
                    raise FinalizedError(
                        f"Cannot modify {self.__class__.__name__} — it has been finalized. "
                        f"Only these fields can be updated: "
                        f"{', '.join(sorted(self.ALLOWED_FINALIZED_UPDATES))}"
                    )
            else:
                raise FinalizedError(
                    f"Cannot modify {self.__class__.__name__} — it has been finalized"
                )

        if is_insert and self.PARENT_FK_FIELDS:
            self._check_no_finalized_parent_on_insert()

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> None:
        from apps.commissioning.errors import FinalizedError

        if self.is_finalized:
            raise FinalizedError(
                f"Cannot delete {self.__class__.__name__} — it has been finalized"
            )
        super().delete(*args, **kwargs)


class NumberedDocumentMixin(models.Model):
    """
    Mixin that provides automatic number generation for documents.
    Subclasses should define DOCUMENT_TYPE to specify the document type.
    """

    # ``prefix`` must NOT be nullable: PostgreSQL treats NULL as distinct
    # in the ``UNIQUE (prefix, number)`` constraints declared on each
    # subclass, so a tenant without TenantSettings (empty prefix) would
    # be able to write duplicate numbers concurrently without the DB
    # ever raising IntegrityError. Empty string is a real value the
    # constraint can compare on.
    prefix = models.CharField(max_length=10, blank=True, default="")
    number = models.IntegerField(blank=True, null=True)

    # Subclasses must define this
    DOCUMENT_TYPE = None  # e.g., 'order', 'delivery_note', 'invoice'

    class Meta:
        abstract = True

    def _get_tenant_settings_fields(self) -> tuple[str, str]:
        mapping: dict[str, tuple[str, str]] = {
            "order": (
                "order_numbers_start_new_at_year_change",
                "order_number_prefix",
            ),
            "delivery_note": (
                "delivery_note_numbers_start_new_at_year_change",
                "delivery_note_number_prefix",
            ),
            "invoice_reseller": (
                "invoice_numbers_start_new_at_year_change",
                "invoice_number_prefix",
            ),
        }
        try:
            return mapping[self.DOCUMENT_TYPE]
        except KeyError as exc:
            raise ValueError(f"Unknown DOCUMENT_TYPE: {self.DOCUMENT_TYPE}") from exc

    def _get_filter_for_year_based(self) -> dict[str, int]:
        if self.DOCUMENT_TYPE == "order":
            return {"year": self.year}
        if self.DOCUMENT_TYPE in ("delivery_note", "invoice_reseller"):
            year = self.date.year if self.date else timezone.now().year
            return {"date__year": year}
        raise ValueError(f"Unknown DOCUMENT_TYPE: {self.DOCUMENT_TYPE}")

    def _get_document_year(self) -> int:
        """Get the relevant year for this document."""
        if self.DOCUMENT_TYPE == "order":
            return self.year
        if self.DOCUMENT_TYPE in ("delivery_note", "invoice_reseller"):
            return self.date.year if self.date else timezone.now().year
        raise ValueError(f"Unknown DOCUMENT_TYPE: {self.DOCUMENT_TYPE}")

    def _base_number_queryset(self) -> models.QuerySet:
        """Return the queryset that defines this document's number sequence.

        Subclasses can override this to scope the sequence further
        (e.g. ``InvoiceReseller`` separates invoices from stornos by
        ``document_type``). Serialisation of concurrent writers is
        handled by ``pg_advisory_xact_lock`` in ``save_with_number_retry``,
        not by row-level FOR UPDATE — which Postgres ignores when the
        query carries aggregates.
        """
        return self.__class__.objects.all()

    def _compute_next_number(self, qs: models.QuerySet) -> int:
        """Compute the next sequence number from ``qs`` and update ``self.prefix``.

        Reads tenant settings to decide whether numbering is year-based and
        what prefix to apply. Returns the integer to assign to ``self.number``.
        """
        from django.db import connection

        from apps.shared.tenants.models import TenantSettings

        tenant = connection.tenant
        current_settings = TenantSettings.get_current_settings(tenant)

        if current_settings:
            year_based_field, prefix_setting_field = self._get_tenant_settings_fields()
            prefix_value = getattr(current_settings, prefix_setting_field, None)

            if getattr(current_settings, year_based_field, False):
                qs = qs.filter(**self._get_filter_for_year_based())
                # Year-reset bakes the year INTO the prefix so the per-year
                # counter (which resets to 1 each January) can't collide across
                # years on UNIQUE(prefix, number[, document_type]). This must hold
                # even with an EMPTY base prefix — otherwise every year shares
                # prefix='' and the second year's number=1 collides with the
                # first's (a delayed-fuse IntegrityError at the new year).
                year = self._get_document_year()
                self.prefix = f"{prefix_value}-{year}" if prefix_value else str(year)
            elif prefix_value:
                self.prefix = prefix_value

        last_number = qs.aggregate(max_number=models.Max("number"))["max_number"]
        return (last_number or 0) + 1

    def _advisory_lock_key(self) -> str:
        """Identifier for the per-sequence Postgres advisory lock.

        Two writers competing for the *same* sequence must produce the
        same key so they serialise; writers on independent sequences
        (different model, or invoice vs storno) must produce *different*
        keys so they don't block each other.

        Subclasses with multiple sequences per table (e.g. InvoiceReseller
        with invoice/storno) should override this to include the
        sequence discriminator.
        """
        return f"numbered_doc:{self.__class__.__name__}"

    def generate_number(self) -> None:
        if self.number:
            return
        self.number = self._compute_next_number(self._base_number_queryset())

    def save_with_number_retry(self, *args, **kwargs) -> None:
        """Generate ``number`` then save, serialising concurrent writers
        via a Postgres advisory lock scoped to the transaction.

        ``pg_advisory_xact_lock`` blocks any other writer holding the
        same key until our transaction commits — at which point the
        next writer sees our row and computes our number+1. This
        replaces the previous ``Max(number)+1 → IntegrityError → retry``
        loop, which was O(N) under contention and could exhaust its
        retry budget at scale.

        The DB-level ``UNIQUE (prefix, number[, document_type])``
        constraint stays as a belt-and-suspenders safety net: if the
        lock ever fails (migration mismatch, manual SQL writer, etc.)
        the unique constraint still refuses duplicate numbers.

        Name kept for historical reference (callers grep for it).
        """
        with transaction.atomic():
            acquire_advisory_xact_lock(self._advisory_lock_key())
            self.generate_number()
            super().save(*args, **kwargs)

    def assign_final_number(self) -> None:
        """Reassign the document number based on finalized objects only.

        Called at finalization time so that the gap-free sequence only
        counts documents that have actually been issued. If the target
        number is currently held by an unfinalized draft (which can happen
        when documents are finalized out of creation order), we bump the
        conflicting draft(s) above the current max so the unique
        ``(prefix, number)`` constraint stays satisfied.

        Holds the same advisory lock as ``save_with_number_retry`` so a
        finalisation can never race with a parallel create/finalise on
        the same sequence.
        """
        with transaction.atomic():
            acquire_advisory_xact_lock(self._advisory_lock_key())
            base_qs = self._base_number_queryset()
            qs = base_qs.filter(is_finalized=True)
            target = self._compute_next_number(qs)

            # Find any unfinalized draft already sitting on the target slot
            # for this prefix. Exclude self in case the number didn't change.
            conflict_qs = base_qs.filter(
                prefix=self.prefix,
                number=target,
                is_finalized=False,
            ).exclude(pk=self.pk)

            conflicts = list(conflict_qs)
            if conflicts:
                # Scope the bump to THIS prefix (mirrors conflict_qs above): under
                # year-reset the year is baked into the prefix, so an unscoped
                # cross-year MAX would bump a draft hundreds of numbers ahead
                # (e.g. RE-2026-501v while 2026 is only at 3). Per-prefix keeps
                # the provisional number in its plausible per-year range and stays
                # unique under UNIQUE(prefix, number[, document_type]).
                max_number = (
                    base_qs.filter(prefix=self.prefix).aggregate(
                        m=models.Max("number")
                    )["m"]
                    or 0
                )
                # Bypass the per-instance save() (which calls full_clean
                # and would raise on the very collision we're resolving).
                for offset, draft in enumerate(conflicts, start=1):
                    draft.number = max_number + offset
                    models.Model.save(draft, update_fields=["number"])

            self.number = target

    @property
    def display_number(self) -> str:
        """Return the document number with a 'v' suffix if not finalized."""
        if not self.number:
            return "–"
        if not self.is_finalized:
            return f"{self.number}v"
        return str(self.number)

    @property
    def full_number(self) -> str:
        """Canonical commercial-document number for display: the prefix and
        ``display_number`` joined by ``-`` (e.g. ``"INV-42"`` / ``"INV-42v"``).

        The single source of truth for this format — views, serializers and
        services must use this instead of hand-building ``f"{prefix}-..."``.
        When there is no prefix (e.g. an unfinalized draft before the number is
        assigned) it returns just ``display_number``, so the empty-prefix case
        is handled once here rather than via ad-hoc ``.strip("-")`` /
        ``if prefix else`` variants at call sites.
        """
        if self.prefix:
            return f"{self.prefix}-{self.display_number}"
        return self.display_number


class DateDocumentMixin(models.Model):
    """Mixin that adds a nullable ``date`` field for legal documents.

    Field is nullable at the DB level so the document can be constructed
    in stages, but consumers are expected to set ``date`` before saving.
    Concrete models (e.g. ``DeliveryNoteReseller``, ``InvoiceReseller``)
    raise ``DocumentDateRequired`` in their own ``save()`` when ``date``
    is still ``None`` — silently defaulting to "today" is a GoBD / UStG
    audit hazard for legal documents.
    """

    date = models.DateField(blank=True, null=True)

    class Meta:
        abstract = True


# this is here for future use - leave it right now
class WaitingListMixin(models.Model):
    """
    Mixin that adds waiting list functionality to models.
    """

    class WaitingListStatus(models.TextChoices):
        NOT_ON_LIST = "not_on_list", "Not on Waiting List"
        PENDING = "pending", "Pending - Waiting for Spot"
        SPOT_AVAILABLE = "spot_available", "Spot Available - Awaiting Confirmation"
        CONFIRMED = "confirmed", "Confirmed - Will Take Spot"
        DECLINED = "declined", "Declined - No Longer Interested"
        EXPIRED = "expired", "Expired - Did Not Respond"

    on_waiting_list = models.BooleanField(default=False)
    waiting_list_status = models.CharField(
        max_length=20,
        choices=WaitingListStatus.choices,
        default=WaitingListStatus.NOT_ON_LIST,
    )
    waiting_list_position = models.PositiveIntegerField(
        blank=True, null=True, editable=False
    )
    notification_sent_at = models.DateTimeField(blank=True, null=True)
    notification_expires_at = models.DateTimeField(blank=True, null=True)
    response_received_at = models.DateTimeField(blank=True, null=True)
    # Single-use magic-link token for the "a spot is available" email — the
    # member accepts/declines their offer WITHOUT logging in (mirrors the
    # invitation flow). Set when the offer is made; cleared on accept / decline /
    # expiry so a stale link can't be replayed.
    notification_token = models.UUIDField(
        blank=True, null=True, db_index=True, editable=False
    )

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        # The spot-available notification cannot expire, nor can a response
        # arrive, before the notification was sent. All three are DateTimeFields
        # so the comparison is direct. NULL-tolerant: each pair is only enforced
        # when both members are set. No DB CheckConstraint here — this is an
        # abstract mixin (its Meta.constraints would not propagate to concrete
        # subclasses).
        if (
            self.notification_sent_at is not None
            and self.notification_expires_at is not None
            and self.notification_expires_at < self.notification_sent_at
        ):
            raise ValidationError(
                {
                    "notification_expires_at": (
                        "Notification expiry must be on or after the date the "
                        "notification was sent."
                    )
                }
            )
        if (
            self.notification_sent_at is not None
            and self.response_received_at is not None
            and self.response_received_at < self.notification_sent_at
        ):
            raise ValidationError(
                {
                    "response_received_at": (
                        "Response date must be on or after the date the "
                        "notification was sent."
                    )
                }
            )

    def add_to_waiting_list(self) -> None:
        self.on_waiting_list = True
        self.waiting_list_status = self.WaitingListStatus.PENDING
        self.save()

    def notify_spot_available(self, expiry_days: int = 7) -> None:
        self.waiting_list_status = self.WaitingListStatus.SPOT_AVAILABLE
        self.notification_sent_at = timezone.now()
        self.notification_expires_at = timezone.now() + timedelta(days=expiry_days)
        # Fresh single-use token per offer — a re-offer invalidates any old link.
        self.notification_token = uuid.uuid4()
        self.save()

    def confirm_spot(self) -> None:
        self.waiting_list_status = self.WaitingListStatus.CONFIRMED
        self.response_received_at = timezone.now()
        self.on_waiting_list = False
        self.notification_token = None  # link consumed
        self.save()

    def decline_spot(self) -> None:
        self.waiting_list_status = self.WaitingListStatus.DECLINED
        self.response_received_at = timezone.now()
        self.on_waiting_list = False
        self.notification_token = None  # link consumed
        self.save()

    def mark_as_expired(self) -> None:
        self.waiting_list_status = self.WaitingListStatus.EXPIRED
        self.on_waiting_list = False
        self.notification_token = None  # link dead
        self.save()

    @property
    def is_awaiting_confirmation(self) -> bool:
        return self.waiting_list_status == self.WaitingListStatus.SPOT_AVAILABLE

    @property
    def has_expired_notification(self) -> bool:
        return (
            self.notification_expires_at is not None
            and timezone.now() > self.notification_expires_at
            and self.waiting_list_status == self.WaitingListStatus.SPOT_AVAILABLE
        )
