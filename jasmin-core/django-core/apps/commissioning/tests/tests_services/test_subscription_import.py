"""Subscription CSV import — FK resolution by natural key, draft creation,
dry-run, and per-row error isolation.

Subscriptions reference their FKs (member / variation via share_type+size /
payment-cycle / station-day) by human-readable natural keys, resolved by
``SubscriptionImportSerializer``. Rows land as unconfirmed drafts.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine

from apps.commissioning.models import PaymentCycle, Subscription
from apps.commissioning.models.choices import PaymentCycleOptions
from apps.commissioning.services.data_import import import_rows_from_csv
from apps.commissioning.tests.factories import (
    MemberFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)

_FROZEN = datetime.date(2026, 1, 5)  # Monday, before the imported dates
_VALID_FROM = "2026-01-05"  # Monday
_VALID_UNTIL = "2026-12-27"  # Sunday

_HEADER = (
    "member_number,share_type,size,payment_cycle,valid_from,"
    "valid_until,quantity,is_trial"
)


def _csv(*rows: str) -> bytes:
    # 3-row template layout: row 0 titles, row 1 the dataIndex schema (the one
    # the importer reads), row 2 type hints — then the data rows. Using the same
    # header text for the ignored title/hint rows keeps it unambiguous regardless
    # of how many data rows follow.
    return ("\n".join([_HEADER, _HEADER, _HEADER, *rows]) + "\n").encode("utf-8")


@pytest.mark.django_db
class TestSubscriptionImport:
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    def _reference_data(self):
        """A member + one variation (active at valid_from) + the MONTHLY cycle.

        Returns the (share_type name, size) natural key the CSV must reference.
        """
        member = MemberFactory(member_number=4242)
        # Factory default valid_from is 2026-01-05 (== the share type's start and
        # our subscription valid_from), so the variation is active on that date.
        variation = ShareTypeVariationFactory()
        PaymentCycle.objects.get_or_create(choice=PaymentCycleOptions.MONTHLY)
        return member, variation, variation.share_type.name, variation.size

    def test_imports_draft_with_resolved_fks(self, tenant):
        member, variation, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
        )
        assert result.successful == 1, result.errors
        assert result.failed == 0
        sub = Subscription.objects.get()
        assert sub.member_id == member.pk
        assert sub.share_type_variation_id == variation.pk
        assert sub.payment_cycle.choice == PaymentCycleOptions.MONTHLY
        # Draft — confirmation (and materialisation/billing) is a separate step.
        assert sub.admin_confirmed is False

    def test_dry_run_resolves_but_persists_nothing(self, tenant):
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
            dry_run=True,
        )
        assert result.successful == 1, result.errors
        assert Subscription.objects.count() == 0

    def test_dry_run_surfaces_model_level_failure(self, tenant):
        # A faithful dry-run runs the SAME persistence path (rolled back), so a
        # row the serializer accepts but the MODEL rejects must show as an error,
        # not a false success. ``valid_from`` on a Tuesday passes DRF's DateField
        # but fails ``TimeBoundMixin`` (Monday rule) at save().
        _, _, st, size = self._reference_data()
        tuesday = "2026-01-06"
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{tuesday},{_VALID_UNTIL},1,false"),
            dry_run=True,
        )
        assert result.successful == 0, result.results
        assert result.failed == 1
        assert "monday" in result.errors[0]["error"].lower()
        assert Subscription.objects.count() == 0

    def test_valid_until_is_required(self, tenant):
        # Open-ended subscriptions are forbidden by the domain, so a blank
        # valid_until is a clean per-row validation error (not a model crash).
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_VALID_FROM},,1,false"),
        )
        assert result.successful == 0
        assert result.failed == 1
        assert "valid_until" in result.errors[0]["error"].lower()
        assert Subscription.objects.count() == 0

    def test_reimport_same_subscription_number_is_skipped(self, tenant):
        # subscription_number is the renewal-chain id (not unique), so re-import
        # can't be blocked by a DB constraint — the importer dedups on
        # (member, subscription_number, valid_from) so uploading the same file
        # twice does not double the drafts.
        _, _, st, size = self._reference_data()
        header = (
            "member_number,share_type,size,payment_cycle,valid_from,"
            "valid_until,quantity,is_trial,subscription_number"
        )
        row = f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false,7001"
        csv_bytes = ("\n".join([header, header, header, row]) + "\n").encode("utf-8")

        first = import_rows_from_csv("subscription", csv_bytes)
        assert first.successful == 1, first.errors

        second = import_rows_from_csv("subscription", csv_bytes)
        assert second.successful == 0
        assert second.failed == 1
        assert "already" in second.errors[0]["error"].lower()
        assert Subscription.objects.count() == 1

    def test_unresolved_member_is_a_row_error_not_a_crash(self, tenant):
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"9999,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
        )
        assert result.successful == 0
        assert result.failed == 1
        assert "member" in result.errors[0]["error"].lower()
        assert Subscription.objects.count() == 0

    def test_unknown_share_type_is_a_row_error(self, tenant):
        _, _, _, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,Nope,{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
        )
        assert result.failed == 1
        assert "share type" in result.errors[0]["error"].lower()

    def test_per_row_isolation_good_and_bad_rows(self, tenant):
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(
                f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false",
                f"9999,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false",
            ),
        )
        assert result.successful == 1
        assert result.failed == 1
        assert Subscription.objects.count() == 1


_PRICE_HEADER = (
    "member_number,share_type,size,payment_cycle,valid_from,"
    "valid_until,quantity,price_per_delivery,is_trial"
)


def _price_csv(*rows: str) -> bytes:
    """3-row template CSV including the ``price_per_delivery`` column."""
    return (
        "\n".join([_PRICE_HEADER, _PRICE_HEADER, _PRICE_HEADER, *rows]) + "\n"
    ).encode("utf-8")


@pytest.mark.django_db
class TestSubscriptionImportPriceBound:
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    def _variation_key(self):
        MemberFactory(member_number=4243)
        variation = ShareTypeVariationFactory()
        PaymentCycle.objects.get_or_create(choice=PaymentCycleOptions.MONTHLY)
        return variation.share_type.name, variation.size

    def test_negative_price_is_a_row_error(self, tenant):
        share_type, size = self._variation_key()
        result = import_rows_from_csv(
            "subscription",
            _price_csv(
                f"4243,{share_type},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},"
                "1,-1.00,false"
            ),
        )
        assert result.successful == 0
        assert result.failed == 1
        assert "price_per_delivery" in result.errors[0]["error"]
        assert not Subscription.objects.exists()

    def test_price_zero_is_imported(self, tenant):
        share_type, size = self._variation_key()
        result = import_rows_from_csv(
            "subscription",
            _price_csv(
                f"4243,{share_type},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},"
                "1,0.00,true"
            ),
        )
        assert result.successful == 1, result.errors
        subscription = Subscription.objects.get()
        assert str(subscription.price_per_delivery) == "0.00"


_NEXT_FROM = "2026-12-28"  # Monday after _VALID_UNTIL
_NEXT_UNTIL = "2027-12-26"  # Sunday
_NUMBERED_HEADER = (
    "member_number,share_type,size,payment_cycle,valid_from,"
    "valid_until,quantity,is_trial,subscription_number"
)


def _numbered_csv(*rows: str) -> bytes:
    lines = [_NUMBERED_HEADER, _NUMBERED_HEADER, _NUMBERED_HEADER, *rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.mark.django_db
class TestImportedNextTermContinuesTheTermBefore:
    """A row starting the day after a term of the member and share type ends is
    that term's next term: linked as its renewal and continuing its chain, so
    the renewal sweep doesn't draft a second one."""

    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    @pytest.fixture()
    def natural_key(self, tenant):
        MemberFactory(member_number=4242)
        variation = ShareTypeVariationFactory()
        PaymentCycle.objects.get_or_create(choice=PaymentCycleOptions.MONTHLY)
        return variation.share_type.name, variation.size

    @staticmethod
    def _terms() -> tuple[Subscription, Subscription]:
        return (
            Subscription.objects.get(valid_from=datetime.date(2026, 1, 5)),
            Subscription.objects.get(valid_from=datetime.date(2026, 12, 28)),
        )

    def test_the_next_term_is_linked_to_the_term_before(self, natural_key):
        st, size = natural_key
        result = import_rows_from_csv(
            "subscription",
            _csv(
                f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false",
                f"4242,{st},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false",
            ),
        )

        assert result.successful == 2, result.errors
        first, following = self._terms()
        assert following.previous_subscription_id == first.pk
        assert following.subscription_number == first.subscription_number
        assert following.renewal_generation == 1

    def test_the_terms_may_come_in_any_order(self, natural_key):
        st, size = natural_key
        result = import_rows_from_csv(
            "subscription",
            _csv(
                f"4242,{st},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false",
                f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false",
            ),
        )

        assert result.successful == 2, result.errors
        # Reported by the file's rows, whatever order they went in.
        assert [entry["row"] for entry in result.results] == [4, 5]
        first, following = self._terms()
        assert following.previous_subscription_id == first.pk

    def test_a_term_that_already_has_its_next_refuses_the_row(self, natural_key):
        st, size = natural_key
        import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
        )
        first = Subscription.objects.get()
        # The renewal sweep's draft for it.
        Subscription.objects.create(
            member=first.member,
            share_type_variation=first.share_type_variation,
            payment_cycle=first.payment_cycle,
            previous_subscription=first,
            valid_from=datetime.date(2026, 12, 28),
            valid_until=datetime.date(2027, 12, 26),
            quantity=1,
            admin_confirmed=False,
        )

        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false"),
        )

        assert result.successful == 0
        assert "already continues" in result.errors[0]["error"]
        assert "skipped" in result.errors[0]["error"]
        assert Subscription.objects.count() == 2

    def test_reimporting_a_linked_next_term_skips_it(self, natural_key):
        st, size = natural_key
        csv_bytes = _numbered_csv(
            f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false,7001",
            f"4242,{st},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false,7001",
        )
        assert import_rows_from_csv("subscription", csv_bytes).successful == 2

        again = import_rows_from_csv("subscription", csv_bytes)

        assert again.successful == 0
        assert again.failed == 2
        assert Subscription.objects.count() == 2

    def test_the_number_tells_two_terms_ending_the_same_day_apart(self, natural_key):
        st, size = natural_key
        import_rows_from_csv(
            "subscription",
            _numbered_csv(
                f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false,7001",
                f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false,7002",
            ),
        )

        unnumbered = import_rows_from_csv(
            "subscription",
            _numbered_csv(
                f"4242,{st},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false,"
            ),
        )
        numbered = import_rows_from_csv(
            "subscription",
            _numbered_csv(
                f"4242,{st},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false,7002"
            ),
        )

        assert unnumbered.successful == 0
        assert "subscription_number" in unnumbered.errors[0]["error"]
        assert numbered.successful == 1, numbered.errors
        following = Subscription.objects.get(valid_from=datetime.date(2026, 12, 28))
        assert following.previous_subscription.subscription_number == 7002

    def test_a_trial_row_starts_a_chain_of_its_own(self, natural_key):
        st, size = natural_key
        result = import_rows_from_csv(
            "subscription",
            _csv(
                f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false",
                f"4242,{st},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,true",
            ),
        )

        assert result.successful == 2, result.errors
        _first, following = self._terms()
        assert following.previous_subscription_id is None


_STATION_HEADER = (
    "member_number,share_type,size,payment_cycle,delivery_station,delivery_day,"
    "valid_from,valid_until,quantity,is_trial"
)


def _station_csv(*rows: str) -> bytes:
    """3-row template CSV including the delivery station and day columns."""
    return (
        "\n".join([_STATION_HEADER, _STATION_HEADER, _STATION_HEADER, *rows]) + "\n"
    ).encode("utf-8")


@pytest.mark.django_db
class TestUnresolvedNaturalKeysCarryTheirCodes:
    """A natural key the import cannot resolve fails the row with a coded error
    naming the column and the value, so the office reads it in its language."""

    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    @pytest.fixture()
    def natural_key(self, tenant):
        MemberFactory(member_number=4244)
        variation = ShareTypeVariationFactory()
        PaymentCycle.objects.get_or_create(choice=PaymentCycleOptions.MONTHLY)
        return variation.share_type.name, variation.size

    @staticmethod
    def _row_error(row: str) -> dict:
        result = import_rows_from_csv("subscription", _station_csv(row))
        assert result.successful == 0, result.results
        return result.errors[0]

    def test_an_unknown_member_number(self, natural_key):
        share_type, size = natural_key
        row_error = self._row_error(
            f"9999,{share_type},{size},MONTHLY,,,{_VALID_FROM},{_VALID_UNTIL},1,false"
        )
        assert row_error["code"] == "member.number_unknown"
        assert row_error["field"] == "member_number"
        assert row_error["details"] == {"member_number": 9999}

    def test_an_unknown_payment_cycle(self, natural_key):
        share_type, size = natural_key
        row_error = self._row_error(
            f"4244,{share_type},{size},FORTNIGHTLY,,,"
            f"{_VALID_FROM},{_VALID_UNTIL},1,false"
        )
        assert row_error["code"] == "payment_cycle.unknown"
        assert row_error["field"] == "payment_cycle"
        assert row_error["details"] == {"payment_cycle": "FORTNIGHTLY"}

    def test_an_unknown_share_type(self, natural_key):
        _share_type, size = natural_key
        row_error = self._row_error(
            f"4244,Nope,{size},MONTHLY,,,{_VALID_FROM},{_VALID_UNTIL},1,false"
        )
        assert row_error["code"] == "share_type.name_unknown"
        assert row_error["field"] == "share_type"
        assert row_error["details"] == {"share_type": "Nope"}

    def test_a_size_the_share_type_has_no_variation_in(self, natural_key):
        share_type, _size = natural_key
        row_error = self._row_error(
            f"4244,{share_type},XXL,MONTHLY,,,{_VALID_FROM},{_VALID_UNTIL},1,false"
        )
        assert row_error["code"] == "share_type_variation.size_unknown"
        assert row_error["field"] == "size"
        assert row_error["details"] == {
            "share_type": share_type,
            "size": "XXL",
            "date": _VALID_FROM,
        }

    def test_a_delivery_day_no_day_is_active_on(self, natural_key):
        share_type, size = natural_key
        row_error = self._row_error(
            f"4244,{share_type},{size},MONTHLY,North,5,"
            f"{_VALID_FROM},{_VALID_UNTIL},1,false"
        )
        assert row_error["code"] == "delivery_day.number_unknown"
        assert row_error["field"] == "delivery_day"
        assert row_error["details"] == {"delivery_day": 5, "date": _VALID_FROM}

    def test_a_station_without_that_delivery_day(self, natural_key):
        share_type, size = natural_key
        SharesDeliveryDayFactory(day_number=3)
        row_error = self._row_error(
            f"4244,{share_type},{size},MONTHLY,Nowhere,3,"
            f"{_VALID_FROM},{_VALID_UNTIL},1,false"
        )
        assert row_error["code"] == "delivery_station_day.unknown"
        assert row_error["field"] == "delivery_station"
        assert row_error["details"] == {
            "delivery_station": "Nowhere",
            "delivery_day": 3,
            "date": _VALID_FROM,
        }


@pytest.mark.django_db
class TestImportRulesCarryTheirCodes:
    """A row the import refuses by one of its own rules fails with a coded error
    naming the column, so the office reads the reason in its language."""

    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    @pytest.fixture()
    def natural_key(self, tenant):
        MemberFactory(member_number=4245)
        variation = ShareTypeVariationFactory()
        PaymentCycle.objects.get_or_create(choice=PaymentCycleOptions.MONTHLY)
        return variation.share_type.name, variation.size

    def test_a_station_without_a_delivery_day(self, natural_key):
        share_type, size = natural_key
        result = import_rows_from_csv(
            "subscription",
            _station_csv(
                f"4245,{share_type},{size},MONTHLY,North,,"
                f"{_VALID_FROM},{_VALID_UNTIL},1,false"
            ),
        )
        row_error = result.errors[0]
        assert row_error["code"] == "subscription.import.station_day_incomplete"
        assert row_error["field"] == "delivery_day"

    def test_a_delivery_day_without_a_station(self, natural_key):
        share_type, size = natural_key
        result = import_rows_from_csv(
            "subscription",
            _station_csv(
                f"4245,{share_type},{size},MONTHLY,,3,"
                f"{_VALID_FROM},{_VALID_UNTIL},1,false"
            ),
        )
        row_error = result.errors[0]
        assert row_error["code"] == "subscription.import.station_day_incomplete"
        assert row_error["field"] == "delivery_station"

    def test_a_subscription_imported_before(self, natural_key):
        share_type, size = natural_key
        csv_bytes = _numbered_csv(
            f"4245,{share_type},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},"
            "1,false,7001"
        )
        assert import_rows_from_csv("subscription", csv_bytes).successful == 1

        row_error = import_rows_from_csv("subscription", csv_bytes).errors[0]

        assert row_error["code"] == "subscription.import.already_imported"
        assert row_error["field"] == "subscription_number"
        assert row_error["details"] == {
            "subscription_number": 7001,
            "valid_from": _VALID_FROM,
            "member_number": 4245,
        }

    @staticmethod
    def _import_first_term_with_next(share_type, size, next_from, next_until):
        import_rows_from_csv(
            "subscription",
            _csv(
                f"4245,{share_type},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},"
                "1,false"
            ),
        )
        first = Subscription.objects.get()
        Subscription.objects.create(
            member=first.member,
            share_type_variation=first.share_type_variation,
            payment_cycle=first.payment_cycle,
            previous_subscription=first,
            valid_from=next_from,
            valid_until=next_until,
            quantity=1,
            admin_confirmed=False,
        )

    def test_a_next_term_already_there_from_the_same_day(self, natural_key):
        share_type, size = natural_key
        self._import_first_term_with_next(
            share_type,
            size,
            datetime.date(2026, 12, 28),
            datetime.date(2027, 12, 26),
        )

        row_error = import_rows_from_csv(
            "subscription",
            _csv(
                f"4245,{share_type},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false"
            ),
        ).errors[0]

        assert row_error["code"] == "subscription.import.term_already_imported"
        assert row_error["field"] == "valid_from"
        assert row_error["details"]["renewal_valid_from"] == _NEXT_FROM
        assert set(row_error["details"]) == {
            "predecessor",
            "renewal",
            "renewal_valid_from",
        }

    def test_a_next_term_already_there_from_another_day(self, natural_key):
        share_type, size = natural_key
        self._import_first_term_with_next(
            share_type,
            size,
            datetime.date(2027, 1, 4),
            datetime.date(2027, 12, 26),
        )

        row_error = import_rows_from_csv(
            "subscription",
            _csv(
                f"4245,{share_type},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false"
            ),
        ).errors[0]

        assert row_error["code"] == "subscription.term_already_renewed"
        assert row_error["field"] == "valid_from"
        assert row_error["details"]["renewal_valid_from"] == "2027-01-04"

    def test_two_terms_the_row_may_continue(self, natural_key):
        share_type, size = natural_key
        import_rows_from_csv(
            "subscription",
            _numbered_csv(
                f"4245,{share_type},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},"
                "1,false,7001",
                f"4245,{share_type},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},"
                "1,false,7002",
            ),
        )

        row_error = import_rows_from_csv(
            "subscription",
            _numbered_csv(
                f"4245,{share_type},{size},MONTHLY,{_NEXT_FROM},{_NEXT_UNTIL},1,false,"
            ),
        ).errors[0]

        assert row_error["code"] == ("subscription.import.term_predecessor_ambiguous")
        assert row_error["field"] == "subscription_number"
        assert row_error["details"] == {"valid_until": _VALID_UNTIL, "count": 2}
