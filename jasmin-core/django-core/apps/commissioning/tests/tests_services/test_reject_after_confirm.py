"""A reject and a confirm of the same member or subscription decide under one lock.

One office user rejects a pending member or subscription while another confirms
it. Each reject reads the row before it takes the lock; deciding on that read,
it would undo a confirm committed in between: a subscription shown as rejected
whose deliveries and PLANNED charges are still billed, or a member whose member
number and entry date are reset, whose login is deactivated again and who gets
a rejection mail after the approval mail. Each reject re-reads the row FOR
UPDATE and refuses a confirmed one with 409; what it writes back is the row as
committed, plus the decision. A subscription confirm that comes after the
reject refuses the rejected subscription, which it would otherwise materialise
and bill.

The reject tests hand the reject a read taken before the confirm committed,
which is the interleaving a real race produces.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
import time_machine
from django.db import connection
from django.db.models import Max
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.authz.roles import Role
from apps.commissioning.errors import MemberAlreadyConfirmed
from apps.commissioning.models import Member, ShareDelivery, Subscription
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.tests.factories import (
    JasminUserFactory,
    MemberFactory,
    SubscriptionFactory,
)
from apps.commissioning.viewsets.members_viewsets import SubscriptionViewSet
from apps.payments.models import ChargeSchedule

VALID_FROM = datetime.date(2026, 11, 2)
VALID_UNTIL = datetime.date(2027, 10, 31)
CONFIRMED_ON = datetime.date(2026, 10, 12)


@pytest.fixture(autouse=True)
def _frozen_clock():
    with time_machine.travel(datetime.datetime(2026, 10, 12, 12, 0), tick=False):
        yield


def _pending_member(**fields) -> Member:
    return MemberFactory(
        admin_confirmed=False, member_number=None, entry_date=None, **fields
    )


def _pending_subscription(member: Member) -> Subscription:
    return SubscriptionFactory(
        member=member,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
        admin_confirmed=False,
    )


def _confirm_elsewhere(model, pk: str, office, **columns) -> None:
    """The other office user's confirm, committed after the reject's read."""
    model.objects.filter(pk=pk).update(
        admin_confirmed=True,
        admin_confirmed_by=office,
        admin_confirmed_at=timezone.now(),
        **columns,
    )


def _read_for_update(queries, table: str) -> bool:
    return any(
        f'FROM "{table}"' in query["sql"] and "FOR UPDATE" in query["sql"]
        for query in queries
    )


def _reject_through_the_api(api_client, subscription, *, read: Subscription):
    """The office's reject, with ``read`` as the view's unlocked read."""
    with mock.patch.object(SubscriptionViewSet, "get_object", return_value=read):
        return api_client.post(
            reverse("abos-reject", kwargs={"pk": subscription.pk}),
            {"reason": "Duplicate"},
            format="json",
        )


@pytest.mark.django_db
class TestSubscriptionReject:
    def test_a_confirm_committed_after_the_read_is_kept(self, tenant, user, api_client):
        subscription = _pending_subscription(MemberFactory())
        read_before_the_confirm = Subscription.objects.get(pk=subscription.pk)
        _confirm_elsewhere(Subscription, subscription.pk, user)

        with CaptureQueriesContext(connection) as queries:
            response = _reject_through_the_api(
                api_client, subscription, read=read_before_the_confirm
            )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "subscription.already_confirmed"
        assert _read_for_update(queries, "commissioning_subscription")
        subscription.refresh_from_db()
        assert subscription.admin_confirmed is True
        assert subscription.admin_rejected_at is None

    def test_an_edit_committed_after_the_read_survives_the_reject(
        self, tenant, user, api_client
    ):
        subscription = _pending_subscription(MemberFactory())
        read_before_the_edit = Subscription.objects.get(pk=subscription.pk)
        Subscription.objects.filter(pk=subscription.pk).update(notice_period_duration=4)

        response = _reject_through_the_api(
            api_client, subscription, read=read_before_the_edit
        )

        assert response.status_code == status.HTTP_200_OK
        subscription.refresh_from_db()
        assert subscription.notice_period_duration == 4
        assert subscription.admin_confirmed is False
        assert subscription.admin_rejected_at is not None
        assert subscription.admin_rejection_reason == "Duplicate"
        assert subscription.admin_confirmed_by_id == user.pk

    def test_a_confirm_after_the_reject_is_refused(self, tenant, user, api_client):
        subscription = _pending_subscription(MemberFactory())
        reject = api_client.post(
            reverse("abos-reject", kwargs={"pk": subscription.pk}),
            {"reason": "Duplicate"},
            format="json",
        )
        assert reject.status_code == status.HTTP_200_OK

        response = api_client.post(
            reverse("abos-confirm", kwargs={"pk": subscription.pk}), {}, format="json"
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "subscription.already_rejected"
        subscription.refresh_from_db()
        assert subscription.admin_confirmed is False
        assert not ShareDelivery.objects.filter(subscription=subscription).exists()
        assert not ChargeSchedule.objects.filter(subscription=subscription).exists()


@pytest.mark.django_db
class TestMemberReject:
    def test_a_confirm_committed_after_the_read_is_kept(self, tenant, user):
        login = JasminUserFactory(roles=[Role.MEMBER], account_status="active")
        member = _pending_member(user=login)
        open_subscription = _pending_subscription(member)
        read_before_the_confirm = Member.objects.get(pk=member.pk)
        member_number = (
            Member.objects.aggregate(highest=Max("member_number"))["highest"] or 0
        ) + 1
        _confirm_elsewhere(
            Member,
            member.pk,
            user,
            member_number=member_number,
            entry_date=CONFIRMED_ON,
        )

        with (
            mock.patch(
                "apps.commissioning.services.member_service.schedule_member_email"
            ) as schedule,
            CaptureQueriesContext(connection) as queries,
            pytest.raises(MemberAlreadyConfirmed),
        ):
            MemberService().reject_and_notify(
                read_before_the_confirm, admin_user=user, reason="Duplicate"
            )

        assert _read_for_update(queries, "commissioning_member")
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.admin_rejected_at is None
        assert member.member_number == member_number
        assert member.entry_date == CONFIRMED_ON
        login.refresh_from_db()
        assert login.account_status == "active"
        # The member's subscriptions are rejected in the same transaction, so
        # the refusal takes their rejection back too.
        open_subscription.refresh_from_db()
        assert open_subscription.admin_rejected_at is None
        schedule.assert_not_called()

    def test_an_edit_committed_after_the_read_survives_the_reject(self, tenant, user):
        member = _pending_member(note="Read by the reject")
        read_before_the_edit = Member.objects.get(pk=member.pk)
        Member.objects.filter(pk=member.pk).update(note="Saved by another user")

        with mock.patch(
            "apps.commissioning.services.member_service.schedule_member_email"
        ):
            MemberService().reject_and_notify(
                read_before_the_edit, admin_user=user, reason="Duplicate"
            )

        member.refresh_from_db()
        assert member.note == "Saved by another user"
        assert member.admin_rejected_at is not None
        assert member.admin_rejection_reason == "Duplicate"
