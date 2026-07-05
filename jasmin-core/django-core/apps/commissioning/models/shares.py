from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import (
    DateRangeField,
    RangeBoundary,
    RangeOperators,
)
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Func

from .base import JasminModel

if TYPE_CHECKING:
    from .days import SharesDeliveryDay
from .choices_text import (
    DayNumberOptions,
    DeliveryCycleOptions,
    ShareOptions,
    SizeOptions,
    SizeVegetableOptions,
    UnitOptions,
)
from .mixin import (
    ArchivableMixin,
    CreatedMixin,
    FinalizableMixin,
    TimeBoundMixin,
    time_bound_valid_range_constraint,
)


class _InclusiveDateRange(Func):
    """``daterange(valid_from, valid_until, '[]')`` — both bounds inclusive,
    matching the domain's whole-week semantics (``valid_until`` is an inclusive
    Sunday; a NULL upper bound means open-ended). Used by the GiST exclusion
    constraint below so ADJACENT windows (A ends the day before B starts) do
    NOT conflict while genuinely overlapping ones do."""

    function = "DATERANGE"
    output_field = DateRangeField()


class ShareType(JasminModel, TimeBoundMixin):
    # this is the type of the share, e.g. harvest share, chicken share, ...
    overlap_unique_fields = ("share_option",)

    name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=500, blank=True, null=True)
    share_option = models.CharField(
        max_length=200, choices=ShareOptions.choices, blank=True, null=True
    )
    delivery_cycle = models.CharField(
        max_length=16, choices=DeliveryCycleOptions.choices, blank=True, null=True
    )
    # is the sharetype like a harvest_share with complex planning that changes each week
    # or is it like a honey share 500g honey each month...
    # from this the frontend derives a different ui ...
    needs_complex_planning = models.BooleanField(default=True)
    # this determines whethe this is packed on its own or put together with something.
    is_additional_share_type = models.BooleanField(default=False)
    amount_of_jokers = models.IntegerField(default=0)
    amount_of_donation_jokers = models.IntegerField(default=0)

    class Meta:
        constraints = [
            # At most one OPEN ShareType per share_option — succession is
            # allowed (a closed predecessor + a new open one may share the
            # option). Mirrors ShareTypeVariation's partial-unique net: closes
            # the open-vs-open race (two concurrent creates, or a bulk path
            # that skips save()) at the DB, since share_option-scoped planning
            # (forecast, demand aggregation, stock synthesis) assumes at most
            # one active ShareType per option. Full time-overlap across closed
            # ranges is still only enforced in Python by
            # ``TimeBoundMixin._validate_no_overlap``.
            models.UniqueConstraint(
                fields=["share_option"],
                condition=models.Q(valid_until__isnull=True),
                name="sharetype_one_open_per_option",
            ),
            time_bound_valid_range_constraint("sharetype_valid_range"),
        ]

    def __str__(self) -> str:
        return self.name or self.get_display_id()

    def clean(self) -> None:
        super().clean()
        # A child variation must stay nested in this share type's validity
        # window. Shortening (or closing) the parent must not strand a child
        # that is open (valid_until=None) or ends after the new parent end —
        # it would outlive its parent. ``handle_succession`` guards the
        # create/succession path (and runs only then); this guards a direct
        # edit of an existing parent's end date.
        if self.valid_until and not self._state.adding:
            stranded = self.sharetypevariation_set.filter(
                models.Q(valid_until__isnull=True)
                | models.Q(valid_until__gt=self.valid_until)
            )
            stranded_count = stranded.count()
            if stranded_count:
                from apps.commissioning.errors import (
                    ShareTypeShorteningStrandsVariation,
                )

                raise ShareTypeShorteningStrandsVariation(
                    share_type=str(self),
                    new_valid_until=self.valid_until,
                    stranded_count=stranded_count,
                )

        # Reverse of the ShareTypeVariation.clean guard: jokers (per-period
        # opt-OUT) and on-off opt-in (per-period opt-IN) are mutually
        # exclusive, so block adding jokers to a share type that already has
        # an on-off variation.
        if (self.amount_of_jokers or self.amount_of_donation_jokers) and self.pk:
            if self.sharetypevariation_set.filter(requires_optin=True).exists():
                raise ValidationError(
                    {
                        "amount_of_jokers": (
                            "This share type has an on-off (per-delivery "
                            "opt-in) variation; jokers are the opt-out "
                            "mechanism and can't be combined with opt-in. "
                            "Remove the variation's opt-in flag first."
                        )
                    }
                )

    # NOTE: deliberately NO ``save()`` override. ``TimeBoundMixin.save()`` runs
    # ``handle_succession()`` (closing the open predecessor in the same
    # ``share_option`` group) BEFORE ``full_clean()``. A local ``save()`` that
    # called ``full_clean()`` first would raise the no-overlap error before
    # succession could close the predecessor. ``full_clean()`` (and thus the
    # circular-packing ``clean()`` above) still runs via the inherited save.

    @classmethod
    def handle_succession(cls, new_data: dict):
        """Refuse to succeed a share type while the predecessor still has
        active variations.

        Creating a new share type for a ``share_option`` closes the open
        predecessor on ``new_valid_from - 1``. If that predecessor still has
        ``ShareTypeVariation`` children that are open or end on/after
        ``new_valid_from``, closing it would strand those variations (and the
        subscriptions on them) outliving their parent. Block the succession —
        end the variations first, or pick a later start date.
        """
        from apps.commissioning.errors import (
            ShareTypeSuccessionHasActiveVariations,
        )

        new_valid_from = new_data.get("valid_from")
        filter_kwargs = {field: new_data[field] for field in cls.overlap_unique_fields}
        predecessor = cls.objects.filter(
            **filter_kwargs, valid_until__isnull=True
        ).first()
        if (
            predecessor is not None
            and new_valid_from is not None
            and predecessor.valid_from != new_valid_from
        ):
            blocking = predecessor.sharetypevariation_set.filter(
                models.Q(valid_until__isnull=True)
                | models.Q(valid_until__gte=new_valid_from)
            )
            blocking_count = blocking.count()
            if blocking_count:
                raise ShareTypeSuccessionHasActiveVariations(
                    share_option=predecessor.share_option,
                    new_valid_from=new_valid_from,
                    active_variation_count=blocking_count,
                )
        return super().handle_succession(new_data)


class ShareTypeVariation(JasminModel, TimeBoundMixin):
    class VariationType(models.TextChoices):
        PHYSICAL = (
            "physical",
            "Physical Share Type Variation - Needs Content Planning",
        )
        VIRTUAL = (
            "virtual",
            "Virtual Share Type Variation - Combination of Others",
        )

    # One OPEN variation per (share_type, size) at a time; a new one with a
    # later valid_from auto-closes the open predecessor (no time overlap).
    overlap_unique_fields = ("share_type", "size")

    share_type = models.ForeignKey("ShareType", on_delete=models.PROTECT)
    variation_type = models.CharField(
        max_length=10, choices=VariationType.choices, default=VariationType.PHYSICAL
    )

    used_crate = models.ForeignKey(
        "Crate", on_delete=models.PROTECT, null=True, blank=True
    )
    size = models.CharField(
        max_length=8,
        choices=SizeOptions.choices,
    )

    picture = models.FileField(
        blank=True, null=True, upload_to="pictures_share_type_variation"
    )  # shows up in the order process of shares of members
    description = models.TextField(blank=True, null=True)
    average_weight = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )  # what should be achieved, like 2.5kg vegetable for a small harvest share
    # How many of this variation may be ordered at once. NULL = no limit.
    capacity = models.IntegerField(default=100)
    sort_order = models.PositiveIntegerField(default=0)

    physical_components = models.ManyToManyField(
        "self",
        through="VirtualVariationComponent",
        symmetrical=False,
        blank=True,
        related_name="+",
    )
    # Per-variation override used in MIXED packing mode. Only consulted
    # when ``TenantSettings.packing_mode == "MIXED"``: variations with
    # ``is_packed_bulk=True`` go onto the bulk packing list and ones with
    # ``False`` go onto the boxes packing list. Ignored in pure BULK or
    # BOXES modes (everything goes onto the single matching list).
    is_packed_bulk = models.BooleanField(default=False)

    # ---- On-off (per-delivery opt-in) semantics --------------------
    # When ``requires_optin=True``, each ``ShareDelivery`` for the
    # variation is independently toggled by the member or office.
    # ``OptinService`` enforces the per-variation deadline and stamps
    # the audit fields on ``ShareDelivery``. When ``False`` (the
    # default), variations behave like today — deliveries are
    # automatic, the member can skip via ``joker_taken``.
    #
    # ``default_optin_state`` is the value ``ShareDelivery.is_opted_in``
    # starts at when a delivery row is created — only meaningful when
    # ``requires_optin=True``. False = "off by default, member must
    # opt in" (one-off boxes); True = "on by default, member must
    # opt out" (unlimited-joker style).
    #
    # ``optin_deadline_days_before_delivery`` is the cutoff after
    # which ``is_opted_in`` is locked. 3 = "by Wednesday for
    # Saturday's box". Tweak per variation when production lead time
    # differs.
    requires_optin = models.BooleanField(default=False)
    default_optin_state = models.BooleanField(default=False)
    optin_deadline_days_before_delivery = models.PositiveSmallIntegerField(default=3)

    class Meta:
        constraints = [
            # At most one OPEN variation per (share_type, size) — succession is
            # allowed (a closed predecessor + a new open one may share the
            # pair). Full time-overlap is enforced in Python by
            # ``TimeBoundMixin._validate_no_overlap`` via ``overlap_unique_fields``.
            models.UniqueConstraint(
                fields=["share_type", "size"],
                condition=models.Q(valid_until__isnull=True),
                name="sharetypevariation_one_open_per_type_size",
            ),
            time_bound_valid_range_constraint("sharetypevariation_valid_range"),
        ]

    def __str__(self) -> str:
        return f"{self.share_type} - {self.get_size_display()} ({self.variation_type})"

    def clean(self) -> None:
        super().clean()

        if self.share_type and self.valid_from:
            if self.valid_from < self.share_type.valid_from:
                raise ValidationError(
                    {
                        "valid_from": f"Variation start date must be on or after the share type's start date ({self.share_type.valid_from})."
                    }
                )

            # When the parent share type is CLOSED, the variation must not
            # outlive it: it may neither end after the parent nor stay OPEN
            # (valid_until=None runs forever). The old guard required
            # ``self.valid_until`` to be truthy, so an open variation under a
            # closed parent slipped through.
            if self.share_type.valid_until and (
                self.valid_until is None
                or self.valid_until > self.share_type.valid_until
            ):
                raise ValidationError(
                    {
                        "valid_until": (
                            "Variation must end on or before the share type's "
                            f"end date ({self.share_type.valid_until}); an "
                            "open-ended variation cannot have a closed parent."
                        )
                    }
                )

        # The components M2M check requires a saved row. Skip only that part
        # on first insert; date checks above always run.
        if self.variation_type == "physical" and self.pk:
            if self.physical_components.exists():
                raise ValidationError("Physical variations cannot have components")

        # Tenant-wide kill switch for the on-off feature. When the
        # tenant hasn't opted into per-delivery opt-in semantics, a
        # variation cannot be saved with ``requires_optin=True``.
        # Belt-and-braces — the office UI also hides the field, but
        # this keeps the model honest against admin saves and direct
        # API writes from someone who didn't notice the gate.
        if self.requires_optin:
            from django.db import connection

            from apps.shared.tenants.models import TenantSettings

            tenant = connection.tenant
            current_settings = TenantSettings.get_current_settings(tenant)
            if (
                current_settings
                and not current_settings.allows_share_type_variation_optin
            ):
                raise ValidationError(
                    {
                        "requires_optin": (
                            "Per-delivery opt-in is not enabled for this "
                            "tenant. Enable "
                            "``allows_share_type_variation_optin`` in tenant "
                            "settings before flagging a variation as on-off."
                        )
                    }
                )

            # Jokers (per-period opt-OUT) and on-off opt-in (per-period
            # opt-IN) are mutually exclusive on the same share type — a member
            # can't both actively confirm each delivery AND skip deliveries via
            # jokers. Forbid the combination (mirror guard on ShareType.clean
            # for the reverse direction).
            share_type = self.share_type
            if share_type and (
                share_type.amount_of_jokers or share_type.amount_of_donation_jokers
            ):
                raise ValidationError(
                    {
                        "requires_optin": (
                            "On-off (per-delivery opt-in) can't be combined "
                            "with jokers on the same share type — jokers are "
                            "the opt-out mechanism and make no sense on an "
                            "opt-in variation. Set the share type's jokers to "
                            "0 first."
                        )
                    }
                )

        # A direct shorten/close of this variation's window must not strand
        # subscriptions that are open or end after the new end date — the
        # subscription→variation link is locked once subscriptions exist, so
        # they'd outlive their variation (mirrors ShareType.clean).
        # handle_succession guards the succession-create path; this guards a
        # direct edit of an existing variation's end date.
        if self.valid_until and not self._state.adding:
            from apps.commissioning.models.members import Subscription

            stranded_count = (
                Subscription.objects.filter(share_type_variation=self)
                .filter(
                    models.Q(valid_until__isnull=True)
                    | models.Q(valid_until__gt=self.valid_until)
                )
                .count()
            )
            if stranded_count:
                from apps.commissioning.errors import (
                    ShareTypeVariationShorteningStrandsSubscriptions,
                )

                raise ShareTypeVariationShorteningStrandsSubscriptions(
                    variation=str(self),
                    new_valid_until=self.valid_until,
                    stranded_count=stranded_count,
                )

    def get_occupied_capacity(self, at_date=None) -> int:
        """Farm-wide quantity of this variation actively subscribed on
        ``at_date`` (default today) — the occupancy side of ``capacity``.

        Quantity-weighted count of admin-confirmed, non-cancelled,
        non-waiting_listed subscriptions whose term covers the date. The production
        twin of ``DeliveryStationDay.get_occupied_capacity`` — farm-wide, with
        no per-week / per-station dimension.
        """
        from django.db.models import Sum
        from django.utils import timezone

        from apps.commissioning.models.members import Subscription

        on = at_date or timezone.localdate()
        return int(
            Subscription.objects.filter(
                share_type_variation=self,
                admin_confirmed=True,
                cancelled_at__isnull=True,
                on_waiting_list=False,
                valid_from__lte=on,
            )
            .filter(models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=on))
            .aggregate(q=Sum("quantity"))["q"]
            or 0
        )

    # NOTE: deliberately NO ``save()`` override — same reason as ShareType.
    # ``TimeBoundMixin.save()`` runs ``handle_succession()`` (closing the open
    # predecessor in the same ``(share_type, size)`` group) BEFORE
    # ``full_clean()``; calling ``full_clean()`` first would raise the overlap
    # error before succession could close the predecessor. The date-bound
    # ``clean()`` above still runs via the inherited save.

    @classmethod
    def handle_succession(cls, new_data: dict):
        """Refuse to succeed a variation while the predecessor still has live
        subscriptions.

        Creating a new variation for a ``(share_type, size)`` slot closes the
        open predecessor on ``new_valid_from - 1``. The subscription→variation
        link is locked once subscriptions exist
        (``SubscriptionVariationLocked``) and future Shares are
        materialized against that locked variation, so closing the predecessor
        while a subscription still delivers on it would strand that subscription
        on a closed variation — dropping it out of harvest/packing/demand
        planning. The successor may therefore only start once the LAST
        subscription on the predecessor has ended: block while any subscription
        on it is open (never ends) or still runs on/after ``new_valid_from``.
        End the subscriptions first, or pick a later start date. Mirrors
        ``ShareType.handle_succession`` one rung down.
        """
        from apps.commissioning.errors import (
            ShareTypeVariationSuccessionHasActiveSubscriptions,
        )
        from apps.commissioning.models.members import Subscription

        new_valid_from = new_data.get("valid_from")
        filter_kwargs = {field: new_data[field] for field in cls.overlap_unique_fields}
        predecessor = cls.objects.filter(
            **filter_kwargs, valid_until__isnull=True
        ).first()
        if (
            predecessor is not None
            and new_valid_from is not None
            and predecessor.valid_from != new_valid_from
        ):
            blocking_count = (
                Subscription.objects.filter(share_type_variation=predecessor)
                .filter(
                    models.Q(valid_until__isnull=True)
                    | models.Q(valid_until__gte=new_valid_from)
                )
                .count()
            )
            if blocking_count:
                raise ShareTypeVariationSuccessionHasActiveSubscriptions(
                    share_type=predecessor.share_type,
                    size=predecessor.size,
                    new_valid_from=new_valid_from,
                    active_subscription_count=blocking_count,
                )
        return super().handle_succession(new_data)


class VirtualVariationComponent(JasminModel):
    virtual_variation = models.ForeignKey(
        "ShareTypeVariation",
        on_delete=models.CASCADE,
        related_name="+",
    )
    physical_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.CASCADE, related_name="+"
    )
    quantity = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.0,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["virtual_variation", "physical_variation"],
                name="virtualvariationcomponent_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.virtual_variation} <- {self.physical_variation} x{self.quantity}"

    def clean(self) -> None:
        super().clean()
        if self.virtual_variation.variation_type != "virtual":
            raise ValidationError("Only virtual variations can have components")
        if self.physical_variation.variation_type != "physical":
            raise ValidationError("Components must be physical variations")

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ShareTypeVariationGrossPrice(JasminModel, TimeBoundMixin):
    overlap_unique_fields = ("share_type_variation",)

    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.CASCADE
    )
    price_per_delivery = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True
    )
    # Solidarity pricing: the lowest per-delivery price a member may choose when
    # the tenant enables ``allows_solidarity_pricing``. NULL = no explicit floor
    # (the guard falls back to the reference ``price_per_delivery``). No upper
    # bound on purpose — paying MORE is the whole point of solidarity pricing.
    solidarity_min_price_per_delivery = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    price_sum_articles = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True
    )  # sum of the prices of the articles (vegetables) in the share - for comparison for the weekly planning team

    def clean(self) -> None:
        super().clean()
        # The solidarity floor cannot exceed the reference price it floors.
        if (
            self.solidarity_min_price_per_delivery is not None
            and self.price_per_delivery is not None
            and self.solidarity_min_price_per_delivery > self.price_per_delivery
        ):
            raise ValidationError(
                {
                    "solidarity_min_price_per_delivery": (
                        "The solidarity minimum cannot exceed the reference price."
                    )
                }
            )

    class Meta:
        constraints = [
            # One open price window per variation (DB backstop; see
            # ShareArticleNetPrice).
            models.UniqueConstraint(
                fields=["share_type_variation"],
                condition=models.Q(valid_until__isnull=True),
                name="sharetypevariationgrossprice_one_open_per_variation",
            ),
            time_bound_valid_range_constraint(
                "sharetypevariationgrossprice_valid_range"
            ),
            # DB backstop for TimeBoundMixin's Python overlap check (which is
            # TOCTOU-racy: two concurrent saves can both pass full_clean and
            # insert overlapping windows). Two windows for the SAME variation
            # whose inclusive [valid_from, valid_until] ranges overlap are
            # rejected by Postgres itself; billing/renewal price resolution can
            # then never see two active windows on one date. Requires the
            # btree_gist extension (installed by the accompanying migration).
            ExclusionConstraint(
                name="sharetypevariationgrossprice_no_overlap",
                expressions=[
                    ("share_type_variation", RangeOperators.EQUAL),
                    (
                        _InclusiveDateRange(
                            "valid_from",
                            "valid_until",
                            RangeBoundary(inclusive_lower=True, inclusive_upper=True),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.share_type_variation} - {self.price_per_delivery}"


class Share(JasminModel):
    year = models.PositiveSmallIntegerField(db_index=True)
    delivery_week = models.PositiveSmallIntegerField(
        db_index=True,
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    delivery_day = models.ForeignKey(
        "SharesDeliveryDay",
        on_delete=models.CASCADE,
    )
    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.CASCADE
    )
    changed_day_number = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    harvesting_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    packing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    washing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    cleaning_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    get_current_stock_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )

    weight1 = models.DecimalField(
        max_digits=10, decimal_places=3, default=0, blank=True, null=True
    )
    weight2 = models.DecimalField(
        max_digits=10, decimal_places=3, default=0, blank=True, null=True
    )
    weight3 = models.DecimalField(
        max_digits=10, decimal_places=3, default=0, blank=True, null=True
    )
    weight4 = models.DecimalField(
        max_digits=10, decimal_places=3, default=0, blank=True, null=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "delivery_day",
                    "share_type_variation",
                ],
                name="share_unique_year_week_day_variation",
            ),
        ]

    # Day field -> the SharesDeliveryDay default it falls back to when NULL.
    # A NULL day field silently drops the Share from every day-filtered list
    # (packing / harvesting / washing / cleaning), so these must always be
    # populated whenever there's a delivery_day to source them from.
    DAY_FIELD_DEFAULTS = {
        "harvesting_day": "default_harvesting_day",
        "packing_day": "default_packing_day",
        "washing_day": "default_washing_day",
        "cleaning_day": "default_cleaning_day",
        "get_current_stock_day": "default_get_current_stock_day",
    }

    def __str__(self) -> str:
        return f"Share W{self.delivery_week}/{self.year} - {self.share_type_variation}"

    def _apply_default_day_fields(self) -> list[str]:
        """Fill any NULL day field from the delivery_day defaults, in memory.

        Returns the names of the fields that were changed (so callers can
        pass them to ``save(update_fields=...)``).
        """
        if not self.delivery_day_id:
            return []
        changed: list[str] = []
        for field, source in self.DAY_FIELD_DEFAULTS.items():
            if getattr(self, field) is None:
                setattr(self, field, getattr(self.delivery_day, source))
                changed.append(field)
        return changed

    def save(self, *args, **kwargs) -> None:
        self._apply_default_day_fields()
        super().save(*args, **kwargs)

    def ensure_day_fields(self) -> bool:
        """Heal a Share whose day fields are NULL and persist if needed.

        ``bulk_create`` and ``get_or_create`` on a *reused* row both bypass
        the defaulting in ``save()``, so a Share can end up with NULL day
        fields and vanish from day-filtered queries. Call this after
        fetching/reusing a Share to self-heal. No-op (no write) when there's
        no delivery_day or every field is already set.

        Returns True if anything was changed and saved.
        """
        changed = self._apply_default_day_fields()
        if changed:
            self.save(update_fields=changed)
        return bool(changed)

    @classmethod
    def get_or_create_for_delivery(
        cls,
        *,
        year: int,
        delivery_week: int,
        delivery_day: SharesDeliveryDay,
        share_type_variation: ShareTypeVariation,
    ) -> tuple[Share, bool]:
        """``get_or_create`` on the natural key that also heals day fields.

        Prefer this over ``Share.objects.get_or_create`` everywhere a Share
        is materialized (subscriptions, forecasts, share content): a reused
        row created NULL-day by an earlier ``bulk_create`` would otherwise
        leak straight through and break the packing/harvesting lists.
        """
        share, created = cls.objects.get_or_create(
            year=year,
            delivery_week=delivery_week,
            delivery_day=delivery_day,
            share_type_variation=share_type_variation,
        )
        if not created:
            share.ensure_day_fields()
        return share, created

    @classmethod
    def heal_day_fields(cls, shares: Iterable[Share]) -> int:
        """Bulk-fill NULL day fields on already-loaded Shares in one UPDATE.

        For paths that reuse a batch of prefetched Shares (default content
        regeneration) rather than calling ``get_or_create_for_delivery`` per
        row. Each Share must have its ``delivery_day`` loaded
        (``select_related``). Returns the number of Shares healed.
        """
        to_update: list[Share] = []
        fields: set[str] = set()
        for share in shares:
            changed = share._apply_default_day_fields()
            if changed:
                to_update.append(share)
                fields.update(changed)
        if to_update:
            cls.objects.bulk_update(to_update, sorted(fields))
        return len(to_update)


class ShareContent(CreatedMixin, FinalizableMixin, ArchivableMixin, JasminModel):
    share = models.ForeignKey("Share", on_delete=models.CASCADE)
    share_article = models.ForeignKey(
        "ShareArticle", on_delete=models.PROTECT, related_name="+"
    )
    forecast = models.ForeignKey(
        "Forecast", on_delete=models.CASCADE, blank=True, null=True
    )
    seller = models.ForeignKey(
        "Reseller", on_delete=models.PROTECT, blank=True, null=True
    )
    unit = models.CharField(max_length=10, choices=UnitOptions.choices)
    size = models.CharField(
        max_length=1,
        choices=SizeVegetableOptions.choices,
        default=SizeVegetableOptions.M,
    )
    amount = models.DecimalField(max_digits=5, decimal_places=3, blank=True, null=True)
    kg_per_piece = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    price_per_unit = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True
    )
    backup_share_article = models.ForeignKey(
        "ShareArticle",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
    )
    backup_unit = models.CharField(
        max_length=10, choices=UnitOptions.choices, blank=True, null=True
    )
    backup_size = models.CharField(
        max_length=1,
        choices=SizeVegetableOptions.choices,
        default=SizeVegetableOptions.M,
    )
    backup_amount = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    percentage_without_backup = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    available_for_all = models.BooleanField(default=False)

    note = models.CharField(max_length=500, blank=True, null=True)
    packing_station = models.PositiveSmallIntegerField(default=1)
    packing_station_backup = models.PositiveSmallIntegerField(default=1)

    # if there is an object with tour or delivery_station not blank/null, this is ADDITIONAL
    # otherwise we create too many objects for nothing
    delivery_station = models.ForeignKey(
        "DeliveryStation",
        on_delete=models.PROTECT,
        related_name="+",
    )

    cleaning = models.BooleanField(default=False, blank=True, null=True)
    washing = models.BooleanField(default=False, blank=True, null=True)
    comes_from_long_term_storage = models.BooleanField(
        default=False, blank=True, null=True
    )
    cleaning_backup = models.BooleanField(default=False, blank=True, null=True)
    washing_backup = models.BooleanField(default=False, blank=True, null=True)

    class Meta:
        # ``unit`` and ``size`` are nullable, so the unique check only runs
        # when both are set — otherwise NULL != NULL in Postgres makes the
        # constraint useless.
        constraints = [
            models.UniqueConstraint(
                fields=["share", "share_article", "delivery_station", "unit", "size"],
                name="sharecontent_unique_share_article_station_unit_size",
            ),
            # A line is washed OR cleaned, never both — the planning grid enforces
            # this in the UI (checking one clears the other). Mirror it at the DB so
            # the API / imports / bulk paths can't drift: both flags true makes the
            # goods-flow relocate a long-term line long→short TWICE (phantom stock).
            # NULL/False combos pass; only (True, True) is rejected.
            models.CheckConstraint(
                condition=~(models.Q(washing=True) & models.Q(cleaning=True)),
                name="sharecontent_washing_cleaning_mutually_exclusive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.share_article} x{self.amount} ({self.share})"

    def clean(self) -> None:
        super().clean()
        self._validate_forecast_dimensions()

    def save(self, *args, **kwargs) -> None:
        # ``JasminModel.save`` does NOT call ``full_clean``, so enforce the
        # forecast-dimension invariant here too — otherwise serializer.save() /
        # .objects.create() / factories would skip it (clean() only fires on an
        # explicit full_clean()). Bulk paths (bulk_create/bulk_update) still
        # bypass this; the forecast service builds matching dimensions there.
        self._validate_forecast_dimensions()
        super().save(*args, **kwargs)

    def _validate_forecast_dimensions(self) -> None:
        """A linked Forecast is this content's harvest-planning source, so the
        two must describe the SAME produce: the theoretical HARVEST is derived
        on the forecast while the actual-harvest correction lands on the
        content's own (share_article, unit, size). If they diverge the two sit
        on different ledger dimensions and the produce is double-counted (the
        actual never offsets the theoretical). Keep them identical.
        """
        if not self.forecast_id:
            return
        forecast = self.forecast
        mismatched = []
        if self.share_article_id != forecast.share_article_id:
            mismatched.append("share_article")
        if self.unit != forecast.unit:
            mismatched.append("unit")
        if self.size != forecast.size:
            mismatched.append("size")
        if mismatched:
            raise ValidationError(
                "A ShareContent linked to a Forecast must match it on "
                + ", ".join(mismatched)
                + "."
            )


class DefaultShareContent(JasminModel):
    year = models.PositiveSmallIntegerField()
    delivery_week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.PROTECT
    )
    share_article = models.ForeignKey("ShareArticle", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=5, decimal_places=3)
    unit = models.CharField(max_length=10, choices=UnitOptions.choices)
    size = models.CharField(
        max_length=1,
        choices=SizeVegetableOptions.choices,
        default=SizeVegetableOptions.M,
    )
    seller = models.ForeignKey(
        "Reseller", on_delete=models.SET_NULL, blank=True, null=True
    )
    note = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "share_type_variation",
                    "share_article",
                    "size",
                    "unit",
                ],
                condition=models.Q(unit__isnull=False, size__isnull=False),
                name="defaultsharecontent_unique_year_week_var_article_size_unit",
            ),
        ]
        indexes = [
            models.Index(fields=["year", "delivery_week"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.share_article} x{self.amount} (W{self.delivery_week}/{self.year})"
        )


class ShareDeliveryQuerySet(models.QuerySet):
    def shippable(self) -> ShareDeliveryQuerySet:
        """Rows that actually ship: joker not taken AND (no opt-in required OR
        opted in) — the single ship predicate as a named, hard-to-forget
        queryset (wraps :meth:`ShareDelivery.delivery_counts_q`). Use this
        instead of re-spelling ``.filter(joker_taken=False).exclude(
        opted_out_q())`` or, worse, forgetting the filter — which silently
        over-counts jokered / opted-out deliveries on demand, billing, and
        station pickup sheets."""
        return self.filter(ShareDelivery.delivery_counts_q())


class ShareDelivery(JasminModel):
    subscription = models.ForeignKey(
        "Subscription", on_delete=models.CASCADE, blank=True, null=True
    )

    share = models.ForeignKey("Share", on_delete=models.CASCADE)

    delivery_station_day = models.ForeignKey(
        "DeliveryStationDay", on_delete=models.CASCADE, blank=True, null=True
    )

    joker_taken = models.BooleanField(default=False)
    # A "donation joker": the member donates this week's box (it goes to the
    # donation pool) instead of receiving it. Unlike ``joker_taken`` (a skip),
    # the member is STILL billed for the share — so this flag deliberately does
    # NOT feed into delivery-count or billing logic; it only records the
    # donation. Mutually exclusive with ``joker_taken`` (see ``clean``).
    donation_joker_taken = models.BooleanField(default=False)
    note = models.TextField(blank=True, null=True)

    # ---- On-off opt-in fields ---------------------------------------
    # Only consulted when this delivery's variation has
    # ``requires_optin=True``. ``is_opted_in`` decides whether the
    # delivery actually happens AND whether it's billable (see
    # ``ChargeScheduleService.regenerate_for_subscription``).
    # ``optin_decided_at`` is NULL while the row is still inside the
    # deadline window AND nobody's toggled it explicitly — i.e. it's
    # sitting at its variation-default. Office can sort by NULLs to
    # find rows that nobody's confirmed yet.
    is_opted_in = models.BooleanField(default=False)
    optin_decided_at = models.DateTimeField(blank=True, null=True)
    optin_decided_by = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )

    objects = ShareDeliveryQuerySet.as_manager()

    class Meta:
        # Replaces the old ``unique_together = (share, subscription, delivery_station_day)``
        # which was effectively useless when subscription / delivery_station_day are NULL
        # (NULL != NULL in Postgres). The partial constraint applies only when both
        # nullable FKs are set, which is the case we actually want to deduplicate.
        constraints = [
            models.UniqueConstraint(
                fields=["share", "subscription", "delivery_station_day"],
                condition=models.Q(
                    subscription__isnull=False, delivery_station_day__isnull=False
                ),
                name="sharedelivery_unique_share_sub_dsd",
            ),
        ]
        indexes = [
            # Powers the ``deliveries_count`` annotation on
            # ``SubscriptionViewSet._build_subscription_queryset`` —
            # ``Count("sharedelivery", filter=Q(joker_taken=False))``
            # at ~1000+ subscriptions per tenant. Without this index
            # the Count runs as a seq scan on ShareDelivery per row.
            # Column order (joker_taken first, subscription second)
            # matches the filter→group shape of the subquery.
            models.Index(
                fields=["joker_taken", "subscription"],
                name="sharedelivery_joker_sub_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Delivery {self.share} - {self.subscription}"

    # ------------------------------------------------------------------ #
    # "Does this delivery count?" — single source of truth for the rule  #
    # once hand-encoded across share_demand_service, members_viewsets,    #
    # and payments.services. A delivery counts for demand/billing unless  #
    # the joker was taken, or it's an on-off variation the member opted   #
    # out of. (joker_taken / is_opted_in / requires_optin are all         #
    # non-null BooleanFields, so there's no NULL handling.)               #
    # ------------------------------------------------------------------ #
    @staticmethod
    def opted_out_q(*, prefix: str = "") -> models.Q:
        """``Q`` for 'opted OUT of an on-off delivery' — the variation requires
        opt-in AND the member did not opt in. Such a delivery never ships, so it
        counts for neither demand nor billing. ``prefix`` targets the relation
        for reverse/``Count`` callers (e.g. ``prefix="sharedelivery__"``)."""
        p = prefix
        return models.Q(
            **{f"{p}share__share_type_variation__requires_optin": True}
        ) & models.Q(**{f"{p}is_opted_in": False})

    @staticmethod
    def delivery_counts_q(*, prefix: str = "") -> models.Q:
        """``Q`` for 'this delivery counts for demand/billing': joker not taken
        AND not opted out (see :meth:`opted_out_q`)."""
        p = prefix
        return models.Q(**{f"{p}joker_taken": False}) & ~ShareDelivery.opted_out_q(
            prefix=prefix
        )

    @property
    def is_opted_in_for_delivery(self) -> bool:
        """Row-level, joker-agnostic opt-in check for Python-loop callers (the
        billing run): ``True`` unless this is an on-off variation the member
        opted out of."""
        variation = self.share.share_type_variation
        return (not variation.requires_optin) or self.is_opted_in

    def clean(self) -> None:
        super().clean()
        # A delivery is either skipped (joker) OR donated (donation joker),
        # never both — the two states are contradictory.
        if self.joker_taken and self.donation_joker_taken:
            raise ValidationError(
                "A delivery cannot be both a joker (skip) and a donation joker."
            )
        if self.delivery_station_day and self.share:
            if self.delivery_station_day.delivery_day != self.share.delivery_day:
                raise ValidationError(
                    "Delivery day of Share and DeliveryStationDay must match."
                )
        # The subscription's group must be for the same share_type_variation
        # as the share itself — otherwise we'd be delivering, e.g., a fruit
        # share against a vegetable subscription.
        if self.subscription_id and self.share_id:
            if (
                self.subscription.share_type_variation_id
                != self.share.share_type_variation_id
            ):
                raise ValidationError(
                    "Subscription's share_type_variation must match the share's "
                    "share_type_variation."
                )

    def save(self, *args, **kwargs) -> None:
        # On insert: stamp ``is_opted_in`` from the variation's
        # configured default state. Off-by-default variations (one-
        # off boxes) leave the value at ``False``; on-by-default
        # variations (unlimited-joker style) flip it to ``True``.
        # Audit columns stay NULL — they only get stamped when
        # someone (member or office) explicitly toggles via
        # ``OptinService.toggle``.
        if self._state.adding and self.share_id:
            variation = self.share.share_type_variation
            if variation and variation.requires_optin:
                self.is_opted_in = variation.default_optin_state
        self.full_clean()
        super().save(*args, **kwargs)
