"""Cooperative-share CSV import — member resolution, unconfirmed create,
per-row isolation.

``CoopShare`` (member equity) is created via natural-key member resolution and
lands unconfirmed (the office confirms afterwards, which is where the GenG
min/max window is enforced for confirmed members).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commissioning.models import CoopShare
from apps.commissioning.services.data_import import import_rows_from_csv
from apps.commissioning.tests.factories import MemberFactory

_HEADER = "member_number,amount_of_coop_shares,value_one_coop_share,is_increase,note"


def _csv(*rows: str) -> bytes:
    # 3-row template layout (titles / dataIndex / type hints), then data rows.
    return ("\n".join([_HEADER, _HEADER, _HEADER, *rows]) + "\n").encode("utf-8")


@pytest.mark.django_db
class TestCoopShareImport:
    def test_imports_unconfirmed_coop_share(self, tenant):
        member = MemberFactory(member_number=555)
        result = import_rows_from_csv("coop_share", _csv("555,3,250,false,Onboarding"))
        assert result.successful == 1, result.errors
        share = CoopShare.objects.get()
        assert share.member_id == member.pk
        assert share.amount_of_coop_shares == Decimal("3")
        assert share.value_one_coop_share == 250
        assert share.is_increase is False
        # Unconfirmed — the office confirms through the normal (GenG) flow.
        assert share.admin_confirmed is False

    def test_unknown_member_is_a_row_error(self, tenant):
        result = import_rows_from_csv("coop_share", _csv("999,1,100,false,"))
        assert result.successful == 0
        assert result.failed == 1
        assert "member" in result.errors[0]["error"].lower()
        assert CoopShare.objects.count() == 0

    def test_dry_run_persists_nothing(self, tenant):
        MemberFactory(member_number=555)
        result = import_rows_from_csv(
            "coop_share", _csv("555,2,100,false,"), dry_run=True
        )
        assert result.successful == 1
        assert CoopShare.objects.count() == 0

    def test_per_row_isolation_good_and_bad(self, tenant):
        MemberFactory(member_number=555)
        result = import_rows_from_csv(
            "coop_share",
            _csv("555,1,100,false,", "999,1,100,false,"),
        )
        assert result.successful == 1
        assert result.failed == 1
        assert CoopShare.objects.count() == 1


_PAY_HEADER = (
    "member_number,amount_of_coop_shares,value_one_coop_share,"
    "is_increase,due_date,paid_at,note"
)


def _pay_csv(*rows: str) -> bytes:
    """3-row template CSV including the ``due_date`` / ``paid_at`` columns."""
    return ("\n".join([_PAY_HEADER, _PAY_HEADER, _PAY_HEADER, *rows]) + "\n").encode(
        "utf-8"
    )


@pytest.mark.django_db
class TestCoopShareImportPaymentFields:
    """``due_date`` / ``paid_at`` (the ``PayableMixin`` pair) come over with the
    equity — a share imported without its payment history looks unpaid and
    lands in the office's outstanding list."""

    def test_due_date_and_paid_at_are_imported(self, tenant):
        MemberFactory(member_number=555)

        result = import_rows_from_csv(
            "coop_share", _pay_csv("555,3,250,false,2024-03-31,2024-03-18,ok")
        )

        assert result.failed == 0, result.errors
        share = CoopShare.objects.get(member__member_number=555)
        assert share.due_date == datetime.date(2024, 3, 31)
        assert share.paid_at is not None
        assert timezone.localtime(share.paid_at).date() == datetime.date(2024, 3, 18)

    def test_both_stay_optional(self, tenant):
        """Blank cells keep the default behaviour — an unpaid share."""
        MemberFactory(member_number=556)

        result = import_rows_from_csv("coop_share", _pay_csv("556,1,100,false,,,"))

        assert result.failed == 0, result.errors
        share = CoopShare.objects.get(member__member_number=556)
        assert share.due_date is None
        assert share.paid_at is None

    def test_paid_before_due_is_accepted(self, tenant):
        """``due_date`` is a DEADLINE, so paying early is normal and legal —
        there is deliberately no ``paid_at >= due_date`` invariant."""
        MemberFactory(member_number=557)

        result = import_rows_from_csv(
            "coop_share", _pay_csv("557,1,100,false,2024-12-31,2024-01-05,early")
        )

        assert result.failed == 0, result.errors

    def test_unparseable_date_is_a_clean_row_error(self, tenant):
        MemberFactory(member_number=558)

        result = import_rows_from_csv(
            "coop_share", _pay_csv("558,1,100,false,not-a-date,,")
        )

        assert result.successful == 0
        assert result.failed == 1
        assert "due_date" in result.errors[0]["error"]
        assert not CoopShare.objects.filter(member__member_number=558).exists()


@pytest.mark.django_db
class TestCoopShareImportAmountRule:
    """The whole-Geschäftsanteil rule shared with the office grid and member
    self-service: zero, negative and fractional amounts are per-row errors."""

    @pytest.mark.parametrize("amount", ["-2", "0", "2.5"])
    def test_amount_that_is_not_a_whole_positive_number_is_a_row_error(
        self, tenant, amount
    ):
        MemberFactory(member_number=559)

        result = import_rows_from_csv("coop_share", _csv(f"559,{amount},100,false,"))

        assert result.successful == 0
        assert result.failed == 1
        assert "CoopShareInvalidAmount" in result.errors[0]["error"]
        assert not CoopShare.objects.filter(member__member_number=559).exists()
