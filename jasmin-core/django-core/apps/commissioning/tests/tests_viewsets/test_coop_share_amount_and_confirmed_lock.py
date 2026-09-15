"""CoopShareViewSet — the whole-Geschäftsanteil amount rule on the office path,
and the edit lock on admin-confirmed coop shares.

The office grid (``CoopSharesModal``) sends the WHOLE row on every save — the
disabled amount / due date / increase cells ride along unchanged, plus the
tenant's CURRENT ``value_one_coop_share`` — so the lock compares values, and a
bookkeeping edit of a confirmed share must keep working.

No test here depends on the wall clock: the dates are plain stored values and
no past/future guard runs on this endpoint.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import CoopShare
from apps.commissioning.tests.factories import CoopShareFactory, MemberFactory
from apps.commissioning.viewsets.members_viewsets import CoopShareViewSet

LIST_URL = reverse("coop_shares-list")
DUE_DATE = datetime.date(2026, 3, 2)


def _detail_url(share: CoopShare) -> str:
    return reverse("coop_shares-detail", kwargs={"pk": share.pk})


@pytest.mark.django_db
class TestOfficeCoopShareAmount:
    @pytest.mark.parametrize("amount", [-2, 0, "2.5"])
    def test_create_rejects_amount_that_is_not_a_whole_positive_number(
        self, api_client, tenant, amount
    ):
        member = MemberFactory()
        resp = api_client.post(
            LIST_URL,
            {
                "member": str(member.id),
                "amount_of_coop_shares": amount,
                "value_one_coop_share": 100,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "coop_share.invalid_amount"
        assert resp.data["field"] == "amount_of_coop_shares"
        assert not CoopShare.objects.filter(member=member).exists()

    def test_create_accepts_whole_positive_amount(self, api_client, tenant):
        member = MemberFactory()
        resp = api_client.post(
            LIST_URL,
            {
                "member": str(member.id),
                "amount_of_coop_shares": "3.00",
                "value_one_coop_share": 100,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        share = CoopShare.objects.get(pk=resp.data["id"])
        assert share.amount_of_coop_shares == Decimal("3")

    def test_patch_rejects_changed_invalid_amount_on_unconfirmed_share(
        self, api_client, tenant
    ):
        share = CoopShareFactory(admin_confirmed=False, amount_of_coop_shares=2)
        resp = api_client.patch(
            _detail_url(share), {"amount_of_coop_shares": "0.5"}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "coop_share.invalid_amount"
        share.refresh_from_db()
        assert share.amount_of_coop_shares == Decimal("2")

    def test_row_stored_before_the_rule_stays_editable(self, api_client, tenant):
        # Stored rows may still hold a fractional amount. Re-sending it
        # unchanged with a note edit must not force a rewrite of the amount.
        share = CoopShareFactory(
            admin_confirmed=False, amount_of_coop_shares=Decimal("1.50")
        )
        resp = api_client.patch(
            _detail_url(share),
            {"amount_of_coop_shares": "1.50", "note": "checked"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.note == "checked"


@pytest.mark.django_db
class TestConfirmedCoopShareEditLock:
    def _confirmed_share(self) -> CoopShare:
        return CoopShareFactory(
            admin_confirmed=True,
            amount_of_coop_shares=Decimal("2"),
            value_one_coop_share=100,
            due_date=DUE_DATE,
            is_increase=False,
        )

    @pytest.mark.parametrize(
        "field", ["amount_of_coop_shares", "is_increase", "due_date", "member"]
    )
    def test_patch_changing_a_committed_term_is_refused(
        self, api_client, tenant, field
    ):
        share = self._confirmed_share()
        original_member_id = share.member_id
        new_value = {
            "amount_of_coop_shares": 3,
            "is_increase": True,
            "due_date": "2026-04-06",
        }.get(field) or str(MemberFactory().id)

        resp = api_client.patch(_detail_url(share), {field: new_value}, format="json")

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "coop_share.confirmed_fields_locked"
        assert resp.data["details"]["fields"] == [field]
        share.refresh_from_db()
        assert share.amount_of_coop_shares == Decimal("2")
        assert share.is_increase is False
        assert share.due_date == DUE_DATE
        assert share.member_id == original_member_id

    def test_put_rewriting_the_amount_is_refused(self, api_client, tenant):
        share = self._confirmed_share()
        resp = api_client.put(
            _detail_url(share),
            {
                "member": str(share.member_id),
                "amount_of_coop_shares": "5.00",
                "value_one_coop_share": 100,
                "due_date": DUE_DATE.isoformat(),
                "is_increase": False,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "coop_share.confirmed_fields_locked"
        share.refresh_from_db()
        assert share.amount_of_coop_shares == Decimal("2")

    def test_office_grid_bookkeeping_save_is_allowed(self, api_client, tenant):
        # The exact body ``CoopSharesModal`` sends when the office stamps the
        # paid-back date on a confirmed share: the disabled cells unchanged, a
        # non-model column, and the tenant's CURRENT share value (changed since
        # this share was snapshotted at 100).
        share = self._confirmed_share()
        resp = api_client.patch(
            _detail_url(share),
            {
                "member": str(share.member_id),
                "amount_of_coop_shares": "2.00",
                "due_date": DUE_DATE.isoformat(),
                "is_increase": False,
                "paid_at": None,
                "pay_in_monthly_rates": False,
                "paid_back_date": "2026-06-01",
                "note": "returned in full",
                "value_one_coop_share": 120,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.paid_back_date == datetime.date(2026, 6, 1)
        assert share.note == "returned in full"
        assert share.amount_of_coop_shares == Decimal("2")
        # The GenG §31 value snapshot survives the re-sent tenant value.
        assert share.value_one_coop_share == 100
        assert share.admin_confirmed is True

    def test_unconfirmed_share_terms_stay_editable(self, api_client, tenant):
        share = CoopShareFactory(
            admin_confirmed=False, amount_of_coop_shares=2, value_one_coop_share=100
        )
        resp = api_client.patch(
            _detail_url(share),
            {
                "amount_of_coop_shares": 3,
                "is_increase": True,
                "value_one_coop_share": 120,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.amount_of_coop_shares == Decimal("3")
        assert share.is_increase is True
        assert share.value_one_coop_share == 120

    def test_confirmation_committed_after_load_still_locks_the_terms(
        self, api_client, tenant
    ):
        # The office loaded the share while it was pending; a confirm commits
        # before the PATCH saves. The update must re-read the row under its lock:
        # the amount stays, and the stale ``admin_confirmed=False`` is not
        # written back over the confirmation.
        share = CoopShareFactory(admin_confirmed=False, amount_of_coop_shares=2)
        stale = CoopShare.objects.get(pk=share.pk)
        CoopShare.objects.filter(pk=share.pk).update(admin_confirmed=True)

        with mock.patch.object(CoopShareViewSet, "get_object", return_value=stale):
            resp = api_client.patch(
                _detail_url(share), {"amount_of_coop_shares": 5}, format="json"
            )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "coop_share.confirmed_fields_locked"
        share.refresh_from_db()
        assert share.admin_confirmed is True
        assert share.amount_of_coop_shares == Decimal("2")


@pytest.mark.django_db
class TestCoopShareUpdateBoundsLock:
    def test_update_takes_the_member_bounds_lock(self, api_client, tenant):
        share = CoopShareFactory(admin_confirmed=False)
        with mock.patch("core.db_locks.acquire_advisory_xact_lock") as lock:
            resp = api_client.patch(
                _detail_url(share), {"amount_of_coop_shares": 2}, format="json"
            )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        lock.assert_called_once_with(f"coop_share_bounds:{share.member_id}")

    def test_reassignment_locks_both_members_in_sorted_order(self, api_client, tenant):
        share = CoopShareFactory(admin_confirmed=False)
        other_member = MemberFactory()
        with mock.patch("core.db_locks.acquire_advisory_xact_lock") as lock:
            resp = api_client.patch(
                _detail_url(share), {"member": str(other_member.id)}, format="json"
            )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        expected = [
            mock.call(f"coop_share_bounds:{member_id}")
            for member_id in sorted([str(share.member_id), str(other_member.id)])
        ]
        assert lock.call_args_list == expected
