"""Privilege changes on Configuration → Users cost a fresh password, and an
outstanding invitation can be revoked.

``AdminUserViewSet`` is admin-only, so step-up here is not about stopping a
lesser role — it is what a *stolen admin session* runs into. The gate therefore
has to cover every payload key that grants privilege, not just ``roles``: a
deactivated account keeps its role list, so flipping ``account_status`` back to
``active`` restores whatever that row already held.

Revocation is the other half. The invitation token is the sole credential for
seven days and nothing consumed it yet, so without a cancel there is no way to
stop an invitation sent to the wrong address.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.authz.roles import Role
from apps.commissioning.models import UserInvitation
from apps.commissioning.models.choices import InvitationStatus
from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.invitations import create_user_with_invitation, get_invitation

pytestmark = pytest.mark.django_db

STEP_UP_CODE = "auth.step_up_required"


def _admin():
    return JasminUserFactory(roles=[Role.ADMIN])


def _client(user, *, stepped_up: bool = False) -> APIClient:
    client = APIClient()
    if stepped_up:
        client.force_authenticate(user=user, token=make_step_up_token(user))
    else:
        client.force_authenticate(user=user)
    return client


def _detail_url(user) -> str:
    return f"/api/auth/admin/users/{user.id}/"


def _pending_login(email: str, *, roles: list[str], created_by=None):
    """A login waiting for its invitation, created without sending the email."""
    with patch("apps.shared.invitations._send_invitation_email"):
        return create_user_with_invitation(
            email=email,
            first_name="Pat",
            last_name="Pending",
            roles=roles,
            created_by=created_by,
        )


class TestPrivilegeChangesRequireStepUp:
    def test_reactivating_a_deactivated_admin_is_gated(self, tenant):
        """The bypass this guards: no ``roles`` key, full admin restored."""
        _admin()  # a second admin, so the target is not the last active one
        target = JasminUserFactory(roles=[Role.ADMIN], account_status="inactive")

        response = _client(_admin()).patch(
            _detail_url(target), data={"account_status": "active"}, format="json"
        )

        assert response.status_code == 403
        assert response.data["code"] == STEP_UP_CODE
        target.refresh_from_db()
        assert target.account_status == "inactive"
        assert target.is_active is False

    def test_reactivation_succeeds_with_a_fresh_password(self, tenant):
        _admin()
        target = JasminUserFactory(roles=[Role.ADMIN], account_status="inactive")

        response = _client(_admin(), stepped_up=True).patch(
            _detail_url(target), data={"account_status": "active"}, format="json"
        )

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.account_status == "active"

    def test_binding_a_customer_login_to_a_reseller_is_gated(self, tenant):
        target = JasminUserFactory(roles=[Role.CUSTOMER])

        response = _client(_admin()).patch(
            _detail_url(target), data={"reseller_id": "whatever"}, format="json"
        )

        # The gate runs before the service, so an unresolvable id still 403s
        # rather than reporting whether that reseller exists.
        assert response.status_code == 403
        assert response.data["code"] == STEP_UP_CODE

    def test_a_role_grant_is_still_gated(self, tenant):
        target = JasminUserFactory(roles=[Role.MEMBER])

        response = _client(_admin()).patch(
            _detail_url(target), data={"roles": [Role.ADMIN]}, format="json"
        )

        assert response.status_code == 403
        assert response.data["code"] == STEP_UP_CODE
        target.refresh_from_db()
        assert Role.ADMIN not in target.roles

    def test_an_edit_that_grants_nothing_passes_unprompted(self, tenant):
        target = JasminUserFactory(roles=[Role.OFFICE])

        response = _client(_admin()).patch(
            _detail_url(target), data={"first_name": "Renamed"}, format="json"
        )

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.first_name == "Renamed"


class TestCancelInvitation:
    def _url(self, user) -> str:
        return f"/api/auth/admin/users/{user.id}/cancel-invitation/"

    def test_cancelling_kills_the_outstanding_link(self, tenant):
        user, invitation = _pending_login("typo@example.org", roles=[Role.OFFICE])
        assert get_invitation(str(invitation.token)) is not None

        response = _client(_admin()).post(self._url(user), data={}, format="json")

        assert response.status_code == 200
        invitation.refresh_from_db()
        assert invitation.status == InvitationStatus.CANCELLED
        # The emailed link is the whole credential — it must stop resolving.
        assert get_invitation(str(invitation.token)) is None

    def test_the_account_row_survives_so_a_resend_can_undo_it(self, tenant):
        user, _ = _pending_login("oops@example.org", roles=[Role.OFFICE])

        _client(_admin()).post(self._url(user), data={}, format="json")

        user.refresh_from_db()
        assert user.account_status == "pending_invitation"
        assert user.is_active is False

    def test_cancelling_a_user_who_is_not_pending_is_refused(self, tenant):
        target = JasminUserFactory(roles=[Role.OFFICE], account_status="active")

        response = _client(_admin()).post(self._url(target), data={}, format="json")

        assert response.status_code == 400

    def test_a_non_admin_cannot_cancel(self, tenant):
        user, invitation = _pending_login("keep@example.org", roles=[Role.OFFICE])
        office = JasminUserFactory(roles=[Role.OFFICE])

        response = _client(office).post(self._url(user), data={}, format="json")

        assert response.status_code == 403
        invitation.refresh_from_db()
        assert invitation.status == InvitationStatus.SENT

    def test_cancelling_twice_is_harmless(self, tenant):
        user, invitation = _pending_login("again@example.org", roles=[Role.OFFICE])
        admin_client = _client(_admin())

        admin_client.post(self._url(user), data={}, format="json")
        response = admin_client.post(self._url(user), data={}, format="json")

        assert response.status_code == 200
        assert (
            UserInvitation.objects.filter(
                user=user, status=InvitationStatus.SENT
            ).count()
            == 0
        )
