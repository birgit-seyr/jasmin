"""The retention sweep erases a login with its ex-member only when the login is
there for the membership alone.

The member create and the CSV import link any login whose email matches, an
admin's included, and the office dates a member's exit, to any past day while
the member has no entry date. A login with a staff or customer role outlives
the member: the sweep erases the member, releases the login from it, and the
login keeps its email, its account status and its other roles. Erasing such a
login is an admin's decision, made with step-up.
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
from apps.commissioning.models import Member
from apps.commissioning.services.data_import import (
    ImportOptions,
    import_rows_from_csv,
)
from apps.commissioning.services.member_cancellation import (
    cancel_member_with_coop_shares,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
    ResellerFactory,
)
from apps.gdpr.models import DeletionLog
from apps.gdpr.tasks import _retention_cutoff, _run_for_current_schema
from apps.shared.tenants.models import TenantSettings

ADMIN_EMAIL = "only.admin@example.com"
ENTRY = datetime.date(1995, 4, 1)
EXIT = datetime.date(2000, 1, 1)


@pytest.fixture
def only_admin(tenant) -> JasminUser:
    """An admin login that is the tenant's only active admin."""
    admin = JasminUserFactory(email=ADMIN_EMAIL, roles=[Role.ADMIN])
    for other in JasminUser.objects.filter(
        roles__contains=[Role.ADMIN], is_active=True
    ).exclude(pk=admin.pk):
        other.account_status = "inactive"
        other.save(update_fields=["account_status"])
    return admin


def _settings(tenant, *, onboarding_mode: bool) -> None:
    """At least three coop shares, so a member created without any stays
    pending."""
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings.objects.create(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    row.min_number_coop_shares = 3
    row.onboarding_mode = onboarding_mode
    row.save()


def _bearer_client(user, tenant) -> APIClient:
    token = AccessToken.for_user(user)
    token["tenant_id"] = tenant.schema_name
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _long_gone_member(login: JasminUser) -> Member:
    member = MemberFactory(user=login, entry_date=ENTRY)
    cancel_member_with_coop_shares(
        member,
        cancelled_at=timezone.make_aware(
            datetime.datetime.combine(EXIT, datetime.time.min)
        ),
        cancelled_effective_at=EXIT,
        notify=False,
    )
    return member


def _sweep() -> None:
    _run_for_current_schema(_retention_cutoff())


def _assert_erased_and_released(member: Member) -> None:
    member.refresh_from_db()
    assert member.first_name == "Gelöscht"
    assert member.email is None
    assert member.user_id is None
    log = DeletionLog.objects.get(member_pk=member.pk)
    assert log.user_pk == ""


def _assert_still_the_only_admin(admin: JasminUser, tenant) -> None:
    admin.refresh_from_db()
    assert admin.email == ADMIN_EMAIL
    assert admin.account_status == "active"
    assert admin.is_active is True
    assert admin.roles == [Role.ADMIN]
    assert list(
        JasminUser.objects.filter(roles__contains=[Role.ADMIN], is_active=True)
    ) == [admin]
    # The admin's tokens still authenticate, on an admin-only endpoint.
    admin_users = _bearer_client(admin, tenant).get(reverse("admin-users-list"))
    assert admin_users.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestOfficeCancelOnTheOnlyAdminsEmail:
    """The office creates a member with the only active admin's email and no
    coop shares, so it is linked to the admin's login and stays pending, then
    cancels it with an exit long past the retention period."""

    @pytest.mark.parametrize("onboarding_mode", [False, True])
    def test_the_sweep_erases_the_member_and_keeps_the_admin(
        self, api_client, tenant, only_admin, onboarding_mode
    ):
        _settings(tenant, onboarding_mode=onboarding_mode)
        created = api_client.post(
            reverse("member-list"),
            {"first_name": "Ada", "last_name": "Lovelace", "email": ADMIN_EMAIL},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        member = Member.objects.get(pk=created.data["id"])
        assert member.user_id == only_admin.pk
        assert member.entry_date is None

        cancelled = api_client.post(
            reverse("member-cancel", kwargs={"pk": member.pk}),
            {"effective_at": EXIT.isoformat()},
            format="json",
        )
        assert cancelled.status_code == status.HTTP_200_OK, cancelled.data

        _sweep()

        _assert_erased_and_released(member)
        _assert_still_the_only_admin(only_admin, tenant)


@pytest.mark.django_db
class TestImportedExMemberOnTheOnlyAdminsEmail:
    def test_the_sweep_erases_the_member_and_keeps_the_admin(
        self, tenant, user, only_admin
    ):
        header = "first_name,last_name,email,entry_date,cancelled_effective_at"
        csv_bytes = (
            "First,Last,Email,Entry,Exit\n"
            f"{header}\n"
            "text,text,email,date,date\n"
            f"Ada,Lovelace,{ADMIN_EMAIL},{ENTRY.isoformat()},{EXIT.isoformat()}\n"
        ).encode()

        result = import_rows_from_csv(
            "member",
            csv_bytes,
            importing_user=user,
            options=ImportOptions(confirm_active_users=False),
        )

        assert result.failed == 0, result.errors
        member = Member.objects.get(last_name="Lovelace", user=only_admin.pk)

        _sweep()

        _assert_erased_and_released(member)
        _assert_still_the_only_admin(only_admin, tenant)


@pytest.mark.django_db
class TestLoginsWithOtherRolesOutliveTheMember:
    @pytest.mark.parametrize(
        ("roles", "account_status"),
        [
            ([Role.OFFICE, Role.GARDENER], "active"),
            ([Role.MANAGEMENT], "active"),
            ([Role.STAFF], "inactive"),
        ],
    )
    def test_a_staff_login_keeps_its_roles_and_status(
        self, tenant, roles, account_status
    ):
        login = JasminUserFactory(roles=roles, account_status=account_status)
        email = login.email
        member = _long_gone_member(login)

        with mock.patch("apps.gdpr.tasks.log") as gdpr_log:
            _sweep()

        _assert_erased_and_released(member)
        login.refresh_from_db()
        assert login.email == email
        assert login.account_status == account_status
        assert sorted(login.roles) == sorted(roles)
        assert (
            "gdpr.ex_member_login_kept member_id=%s user_id=%s",
            member.pk,
            login.pk,
        ) in [call.args for call in gdpr_log.info.call_args_list]

    def test_a_customer_login_keeps_its_reseller(self, tenant):
        login = JasminUserFactory(roles=[Role.CUSTOMER])
        reseller = ResellerFactory(linked_user=login)
        reseller_name = reseller.name_for_member_pages
        member = _long_gone_member(login)

        _sweep()

        _assert_erased_and_released(member)
        login.refresh_from_db()
        reseller.refresh_from_db()
        assert login.account_status == "active"
        assert login.roles == [Role.CUSTOMER]
        assert reseller.linked_user_id == login.pk
        assert reseller.is_active_reseller is True
        assert reseller.name_for_member_pages == reseller_name

    def test_a_retention_block_leaves_the_link_in_place(self, tenant):
        login = JasminUserFactory(roles=[Role.OFFICE])
        member = MemberFactory(user=login, entry_date=ENTRY, first_name="Blocked")
        # An open coop share the office forgot to close blocks the erasure.
        CoopShareFactory(member=member)
        member.cancelled_at = timezone.now()
        member.cancelled_effective_at = EXIT
        member.save(update_fields=["cancelled_at", "cancelled_effective_at"])

        _sweep()

        member.refresh_from_db()
        login.refresh_from_db()
        assert member.first_name == "Blocked"
        assert member.user_id == login.pk
        assert sorted(login.roles) == sorted([Role.OFFICE, Role.MEMBER])


@pytest.mark.django_db
class TestAMemberPortalLoginIsErasedWithTheMember:
    def test_the_login_is_erased_too(self, tenant):
        login = JasminUserFactory(email="portal.member@example.com")
        member = _long_gone_member(login)
        login.refresh_from_db()
        assert login.roles == [Role.MEMBER]

        _sweep()

        login.refresh_from_db()
        member.refresh_from_db()
        assert login.email.endswith("@deleted.invalid")
        assert login.account_status == "inactive"
        assert member.first_name == "Gelöscht"
        assert member.user_id == login.pk
        assert DeletionLog.objects.get(member_pk=member.pk).user_pk == login.pk
