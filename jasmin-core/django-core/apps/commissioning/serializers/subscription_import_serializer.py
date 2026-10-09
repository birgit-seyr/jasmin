"""CSV import serializer for Subscriptions (data-list onboarding).

A Subscription carries several FKs — ``member``, ``share_type_variation``,
``payment_cycle``, ``default_delivery_station_day`` — so a bulk onboarding CSV
references each by a human-readable **natural key**, resolved here, never by DB
id. Time-bound FKs (variation, station-day) are resolved to the version active
at the row's ``valid_from``.

Imported rows are created as **unconfirmed drafts** (``admin_confirmed=False``):
they hold no deliveries/charges and are not capacity-gated. The office
materialises + bills them by CONFIRMING through the normal flow — the single
place where capacity gates + charge generation belong. This importer therefore
deliberately does NOT run:

  * the live-only guards in ``SubscriptionSerializer.validate`` (start
    lead-time, trial policy, solidarity floor) — historical rows legitimately
    violate them; and
  * the capacity reservation in ``SubscriptionService.create_bare_subscription``
    — a bulk load of REAL existing subscriptions must not compete for slots.

It still respects the hard model invariants (``TimeBoundMixin`` Monday/Sunday
date rules, DB constraints) via ``Subscription.save() → full_clean()``.

A row that starts the day after a term of the same member and share type ends
is that term's next term: it is linked as its renewal (``term_predecessor``),
continuing its renewal chain, so the renewal sweep doesn't draft a second one.
A term that already has its next term refuses the row. The import runs the
rows in start-date order, so the terms of one chain may come in any order.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from ..errors import (
    DeliveryDayNumberUnknown,
    DeliveryStationDayAmbiguous,
    DeliveryStationDayUnknown,
    PaymentCycleUnknown,
    ShareTypeNameAmbiguous,
    ShareTypeNameUnknown,
    ShareTypeVariationSizeAmbiguous,
    ShareTypeVariationSizeUnknown,
    SubscriptionAlreadyImported,
    SubscriptionImportStationDayIncomplete,
    SubscriptionImportTermPredecessorAmbiguous,
    SubscriptionTermAlreadyImported,
    SubscriptionTermAlreadyRenewed,
    SubscriptionTermPredecessorAmbiguous,
)
from ..models import (
    DeliveryStationDay,
    PaymentCycle,
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
    Subscription,
)
from ..models.managers import active_on_date_q
from .import_natural_keys import resolve_member_by_number


class SubscriptionImportSerializer(serializers.Serializer):
    """Resolve one CSV row → a draft ``Subscription``.

    Column contract (the downloadable template mirrors this):

      member_number         int   — Member.member_number (unique)
      share_type            str   — ShareType.name
      size                  str   — ShareTypeVariation.size (with share_type,
                                    resolves the variation active at valid_from)
      payment_cycle         str   — PaymentCycle.choice (e.g. MONTHLY)
      delivery_station      str   — DeliveryStation.short_name (optional)
      delivery_day          int   — SharesDeliveryDay.day_number (optional, 0=Mon…)
      valid_from            date   — Monday (YYYY-MM-DD)
      valid_until           date   — Sunday (YYYY-MM-DD), required
                                    (open-ended subscriptions are not allowed)
      quantity              int   — default 1
      price_per_delivery    dec   — optional
      is_trial              bool  — default false
      subscription_number   int   — optional (source reference)
    """

    member_number = serializers.IntegerField()
    share_type = serializers.CharField()
    size = serializers.CharField()
    payment_cycle = serializers.CharField()
    delivery_station = serializers.CharField(required=False, allow_blank=True)
    delivery_day = serializers.IntegerField(required=False, allow_null=True)
    valid_from = serializers.DateField()
    # Required: the domain forbids open-ended subscriptions
    # (``OpenEndedSubscriptionNotAllowed``), so an end date is mandatory here
    # rather than deferred to a model-level error at save.
    valid_until = serializers.DateField()
    quantity = serializers.IntegerField(required=False, default=1, min_value=1)
    # >= 0, like the office grid: a negative price bills nothing. 0 stays valid
    # (e.g. a free trial).
    price_per_delivery = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    is_trial = serializers.BooleanField(required=False, default=False)
    subscription_number = serializers.IntegerField(required=False, allow_null=True)

    # ── FK resolvers (each raises a coded error the row loop reports) ──

    @staticmethod
    def _resolve_payment_cycle(choice: str) -> PaymentCycle:
        cycle = PaymentCycle.objects.filter(choice=choice).first()
        if cycle is None:
            raise PaymentCycleUnknown(
                f"No payment cycle '{choice}'.",
                field="payment_cycle",
                details={"payment_cycle": choice},
            )
        return cycle

    @staticmethod
    def _resolve_variation(
        share_type_name: str, size: str, on_date
    ) -> ShareTypeVariation:
        share_types = list(ShareType.objects.filter(name=share_type_name))
        if not share_types:
            raise ShareTypeNameUnknown(
                f"No share type named '{share_type_name}'.",
                field="share_type",
                details={"share_type": share_type_name},
            )
        if len(share_types) > 1:
            raise ShareTypeNameAmbiguous(
                f"Share type name '{share_type_name}' is ambiguous "
                f"({len(share_types)} matches).",
                field="share_type",
                details={"share_type": share_type_name, "matches": len(share_types)},
            )
        share_type = share_types[0]
        matches = list(
            ShareTypeVariation.objects.filter(
                active_on_date_q(on_date), share_type=share_type, size=size
            )
        )
        details = {
            "share_type": share_type_name,
            "size": size,
            "date": on_date.isoformat(),
        }
        if not matches:
            raise ShareTypeVariationSizeUnknown(
                f"No '{share_type_name}' variation of size '{size}' "
                f"active on {on_date}.",
                field="size",
                details=details,
            )
        if len(matches) > 1:
            raise ShareTypeVariationSizeAmbiguous(
                f"'{share_type_name}' / size '{size}' is ambiguous on "
                f"{on_date} ({len(matches)} active variations).",
                field="size",
                details={**details, "matches": len(matches)},
            )
        return matches[0]

    @staticmethod
    def _resolve_station_day(
        station_name: str, day_number: int, on_date
    ) -> DeliveryStationDay:
        day = (
            SharesDeliveryDay.objects.filter(
                active_on_date_q(on_date), day_number=day_number
            )
            .order_by("-valid_from")
            .first()
        )
        if day is None:
            raise DeliveryDayNumberUnknown(
                f"No delivery day {day_number} active on {on_date}.",
                field="delivery_day",
                details={"delivery_day": day_number, "date": on_date.isoformat()},
            )
        # ``short_name`` is NOT unique, so resolve the station-day directly by
        # joining on it (rather than picking one station with ``.first()``): the
        # active DSD for this day disambiguates. >1 match ⇒ genuinely ambiguous.
        matches = list(
            DeliveryStationDay.objects.filter(
                active_on_date_q(on_date),
                delivery_station__short_name=station_name,
                delivery_day=day,
            )
        )
        details = {
            "delivery_station": station_name,
            "delivery_day": day_number,
            "date": on_date.isoformat(),
        }
        if not matches:
            raise DeliveryStationDayUnknown(
                f"No station '{station_name}' with day {day_number} "
                f"active on {on_date}.",
                field="delivery_station",
                details=details,
            )
        if len(matches) > 1:
            raise DeliveryStationDayAmbiguous(
                f"Station '{station_name}' / day {day_number} is "
                f"ambiguous on {on_date} ({len(matches)} active matches).",
                field="delivery_station",
                details={**details, "matches": len(matches)},
            )
        return matches[0]

    def validate(self, attrs):
        valid_from = attrs["valid_from"]
        attrs["_member"] = resolve_member_by_number(attrs["member_number"])
        attrs["_payment_cycle"] = self._resolve_payment_cycle(attrs["payment_cycle"])
        attrs["_variation"] = self._resolve_variation(
            attrs["share_type"], attrs["size"], valid_from
        )

        station = (attrs.get("delivery_station") or "").strip()
        day = attrs.get("delivery_day")
        if station and day is not None:
            attrs["_station_day"] = self._resolve_station_day(station, day, valid_from)
        elif station or day is not None:
            raise SubscriptionImportStationDayIncomplete(
                missing="delivery_day" if station else "delivery_station"
            )
        else:
            attrs["_station_day"] = None

        # Idempotency: ``subscription_number`` is the renewal-chain identifier,
        # NOT a unique key (renewals deliberately share it), so it can't be a
        # DB unique constraint. But re-uploading the same file must not double
        # the drafts — skip a row whose (member, subscription_number, valid_from)
        # already exists. The valid_from in the triple still lets a genuine
        # renewal (same number, later start) import. Only guards when a number
        # is given; blank numbers auto-assign and each row is a new draft.
        subscription_number = attrs.get("subscription_number")
        if (
            subscription_number is not None
            and Subscription.objects.filter(
                member=attrs["_member"],
                subscription_number=subscription_number,
                valid_from=valid_from,
            ).exists()
        ):
            raise SubscriptionAlreadyImported(
                subscription_number=subscription_number,
                valid_from=valid_from.isoformat(),
                member_number=attrs["member_number"],
            )
        attrs["_previous_subscription"] = (
            None if attrs["is_trial"] else self._resolve_previous_term(attrs)
        )
        return attrs

    @staticmethod
    def _resolve_previous_term(attrs) -> Subscription | None:
        """The term this row continues, if any (see ``term_predecessor``)."""
        from ..services.renewal import term_predecessor

        valid_from = attrs["valid_from"]
        try:
            return term_predecessor(
                member_id=attrs["_member"].pk,
                share_type_id=attrs["_variation"].share_type_id,
                valid_from=valid_from,
                subscription_number=attrs.get("subscription_number"),
            )
        except SubscriptionTermAlreadyRenewed as exc:
            if exc.details["renewal_valid_from"] == valid_from.isoformat():
                raise SubscriptionTermAlreadyImported(**exc.details) from exc
            raise SubscriptionTermAlreadyRenewed(
                **exc.details, field="valid_from"
            ) from exc
        except SubscriptionTermPredecessorAmbiguous as exc:
            raise SubscriptionImportTermPredecessorAmbiguous(**exc.details) from exc

    def create(self, validated_data) -> Subscription:
        # Draft only — no capacity reservation, no live guards, no
        # materialisation. Confirmation (through the normal flow) is what
        # creates deliveries + charges under the proper gates.
        predecessor = validated_data["_previous_subscription"]
        return Subscription.objects.create(
            member=validated_data["_member"],
            share_type_variation=validated_data["_variation"],
            payment_cycle=validated_data["_payment_cycle"],
            default_delivery_station_day=validated_data["_station_day"],
            valid_from=validated_data["valid_from"],
            valid_until=validated_data.get("valid_until"),
            quantity=validated_data["quantity"],
            price_per_delivery=validated_data.get("price_per_delivery"),
            is_trial=validated_data["is_trial"],
            previous_subscription=predecessor,
            # A next term continues its predecessor's chain — ``save()`` takes
            # the number from it; a row's own number names a chain's first term.
            subscription_number=(
                None if predecessor else validated_data.get("subscription_number")
            ),
            admin_confirmed=False,
        )
