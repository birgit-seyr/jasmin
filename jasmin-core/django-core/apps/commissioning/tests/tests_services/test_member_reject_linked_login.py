"""Rejecting a member ends only what the login linked to it holds as that member.

The member create and the CSV import link any login whose email matches, staff
logins included, and a member below the coop-share minimum, or one created in
onboarding mode, stays pending for the office to reject. A login there for the
membership alone is deactivated. A login with a staff or customer role keeps
those roles and its account status: it is unlinked from the rejected member and
loses only the member role. Deactivating it is an admin's decision with step-up
on the admin-users endpoints, where the last active admin can't be deactivated.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import JasminUser
from apps.authz.roles import Role
from apps.commissioning.models import Member, UserInvitation
from apps.commissioning.models.choices import InvitationStatus
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.tests.factories import (
    JasminUserFactory,
    MemberFactory,
    ResellerFactory,
)
from apps.shared.tenants.models import TenantSettings

ADMIN_EMAIL = "the.only.admin@example.com"


def _settings(tenant, *, min_number_coop_shares: int, onboarding_mode: bool) -> None:
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings.objects.create(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    row.min_number_coop_shares = min_number_coop_shares
    row.onboarding_mode = onboarding_mode
    row.save()


def _bearer_client(user, tenant) -> APIClient:
    token = AccessToken.for_user(user)
    token["tenant_id"] = tenant.schema_name
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _reject(member: Member, *, office) -> None:
    MemberService().reject_and_notify(member, admin_user=office, reason="Duplicate")


@pytest.mark.django_db
class TestOfficeRejectOnTheOnlyAdminsEmail:
    """The office creates a member with the only active admin's email and no
    coop shares, so it is linked to the admin's login and stays pending, then
    rejects it."""

    @pytest.fixture(autouse=True)
    def _only_active_admin(self, tenant):
        self.admin = JasminUserFactory(email=ADMIN_EMAIL, roles=[Role.ADMIN])
        for other in JasminUser.objects.filter(
            roles__contains=[Role.ADMIN], is_active=True
        ).exclude(pk=self.admin.pk):
            other.account_status = "inactive"
            other.save(update_fields=["account_status"])

    @pytest.mark.parametrize("onboarding_mode", [False, True])
    def test_the_admin_keeps_access_and_loses_only_the_membership(
        self, api_client, tenant, onboarding_mode
    ):
        _settings(tenant, min_number_coop_shares=3, onboarding_mode=onboarding_mode)
        created = api_client.post(
            reverse("member-list"),
            {"first_name": "Ada", "last_name": "Lovelace", "email": ADMIN_EMAIL},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        member = Member.objects.get(pk=created.data["id"])
        assert member.user_id == self.admin.pk
        assert member.admin_confirmed is False

        rejected = api_client.post(
            reverse("member-reject", kwargs={"pk": member.pk}),
            {"reason": "Duplicate"},
            format="json",
        )

        assert rejected.status_code == status.HTTP_200_OK, rejected.data
        assert rejected.data["user"] is None
        member.refresh_from_db()
        assert member.admin_rejected_at is not None
        assert member.user_id is None
        self.admin.refresh_from_db()
        assert self.admin.account_status == "active"
        assert self.admin.is_active is True
        assert self.admin.roles == [Role.ADMIN]
        assert list(
            JasminUser.objects.filter(roles__contains=[Role.ADMIN], is_active=True)
        ) == [self.admin]
        # The admin's tokens still authenticate, on an admin-only endpoint.
        admin_users = _bearer_client(self.admin, tenant).get(
            reverse("admin-users-list")
        )
        assert admin_users.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestRejectKeepsALoginWithOtherRoles:
    def test_a_staff_login_keeps_its_roles_and_loses_member(self, tenant, user):
        login = JasminUserFactory(roles=[Role.OFFICE, Role.GARDENER])
        member = MemberFactory(user=login, admin_confirmed=False)
        login.refresh_from_db()
        assert Role.MEMBER in login.roles

        _reject(member, office=user)

        login.refresh_from_db()
        member.refresh_from_db()
        assert login.account_status == "active"
        assert login.is_active is True
        assert sorted(login.roles) == sorted([Role.OFFICE, Role.GARDENER])
        assert member.user_id is None
        assert member.admin_rejected_at is not None

    def test_a_customer_login_stays_active_with_its_reseller(self, tenant, user):
        login = JasminUserFactory(roles=[Role.CUSTOMER])
        reseller = ResellerFactory(linked_user=login)
        member = MemberFactory(user=login, admin_confirmed=False)

        _reject(member, office=user)

        login.refresh_from_db()
        reseller.refresh_from_db()
        member.refresh_from_db()
        assert login.account_status == "active"
        assert login.roles == [Role.CUSTOMER]
        assert reseller.linked_user_id == login.pk
        assert member.user_id is None

    def test_an_inactive_staff_login_is_unlinked_and_stays_inactive(self, tenant, user):
        login = JasminUserFactory(roles=[Role.STAFF], account_status="inactive")
        member = MemberFactory(user=login, admin_confirmed=False)

        _reject(member, office=user)

        login.refresh_from_db()
        member.refresh_from_db()
        assert login.account_status == "inactive"
        assert login.roles == [Role.STAFF]
        assert member.user_id is None

    def test_an_invitation_sent_for_this_membership_is_cancelled(self, tenant, user):
        login = JasminUserFactory(
            roles=[Role.OFFICE], account_status="pending_invitation"
        )
        member = MemberFactory(user=login, admin_confirmed=False)
        invitation = UserInvitation.objects.create(
            user=login, member=member, email=login.email, created_by=user
        )

        _reject(member, office=user)

        invitation.refresh_from_db()
        login.refresh_from_db()
        assert invitation.status == InvitationStatus.CANCELLED
        assert login.account_status == "pending_invitation"
        assert login.roles == [Role.OFFICE]

    def test_the_logins_own_invitation_stays_usable(self, tenant, user):
        login = JasminUserFactory(
            roles=[Role.OFFICE], account_status="pending_invitation"
        )
        invitation = UserInvitation.objects.create(
            user=login, email=login.email, created_by=user
        )
        member = MemberFactory(user=login, admin_confirmed=False)

        _reject(member, office=user)

        invitation.refresh_from_db()
        assert invitation.status == InvitationStatus.SENT

    def test_the_rejection_email_renders_in_the_logins_language(self, tenant, user):
        login = JasminUserFactory(roles=[Role.OFFICE], user_language="de")
        member = MemberFactory(user=login, admin_confirmed=False)

        with mock.patch(
            "apps.commissioning.services.member_email.schedule_deferred_email"
        ) as schedule:
            _reject(member, office=user)

        schedule.assert_called_once()
        assert schedule.call_args.kwargs["slug"] == "accounts.application_rejected"
        assert schedule.call_args.kwargs["language"] == "de"


@pytest.mark.django_db
class TestRejectDeactivatesAMemberPortalLogin:
    def test_the_login_is_deactivated_and_stays_linked(self, tenant, user):
        login = JasminUserFactory(roles=[Role.MEMBER])
        member = MemberFactory(user=login, admin_confirmed=False)

        _reject(member, office=user)

        login.refresh_from_db()
        member.refresh_from_db()
        assert login.account_status == "inactive"
        assert login.is_active is False
        assert login.roles == [Role.MEMBER]
        # The link stays: re-inviting the member is how the office reopens it.
        assert member.user_id == login.pk

    def test_its_open_invitation_is_cancelled(self, tenant, user):
        login = JasminUserFactory(
            roles=[Role.MEMBER], account_status="pending_invitation"
        )
        member = MemberFactory(user=login, admin_confirmed=False)
        invitation = UserInvitation.objects.create(
            user=login, member=member, email=login.email, created_by=user
        )

        _reject(member, office=user)

        invitation.refresh_from_db()
        login.refresh_from_db()
        assert invitation.status == InvitationStatus.CANCELLED
        assert login.account_status == "inactive"
