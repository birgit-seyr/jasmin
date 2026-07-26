"""Cooperative-share CSV import — member resolution, unconfirmed create,
per-row isolation.

``CoopShare`` (member equity) is created via natural-key member resolution and
lands unconfirmed (the office confirms afterwards, which is where the GenG
min/max window is enforced for confirmed members).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

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
