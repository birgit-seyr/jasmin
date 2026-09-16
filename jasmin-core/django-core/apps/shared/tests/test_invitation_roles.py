"""Re-inviting an existing account must not strip its membership.

``create_user_with_invitation`` rolls the caller's roles forward onto a user who
never accepted their first invitation. The member role is not the caller's to
overwrite while a Member row points at that user — ``update_user_admin`` refuses
the removal outright, and this path keeps the role for the same reason.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.authz.roles import Role
from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory
from apps.shared.invitations import create_user_with_invitation

pytestmark = pytest.mark.django_db


def _invite(email: str, roles):
    with patch("apps.shared.invitations._send_invitation_email"):
        user, _invitation = create_user_with_invitation(
            email=email,
            first_name="Re",
            last_name="Invited",
            roles=roles,
            user_language="en",
        )
    user.refresh_from_db()
    return user


class TestReinviteRolePreservation:
    def test_member_role_survives_a_staff_role_reinvite(self, tenant):
        user = JasminUserFactory(
            email="linked-member@example.com",
            roles=[Role.STAFF],
            account_status="pending_invitation",
        )
        # Linking the Member grants the member role (member_role_sync).
        MemberFactory(user=user, email="linked-member@example.com")
        user.refresh_from_db()
        assert Role.MEMBER in user.roles

        reinvited = _invite("linked-member@example.com", [Role.OFFICE])

        assert Role.OFFICE in reinvited.roles
        assert Role.MEMBER in reinvited.roles
        assert Role.STAFF not in reinvited.roles

    def test_reinvite_without_a_member_row_does_not_add_the_role(self, tenant):
        JasminUserFactory(
            email="plain-staff@example.com",
            roles=[Role.STAFF],
            account_status="pending_invitation",
        )

        reinvited = _invite("plain-staff@example.com", [Role.OFFICE])

        assert reinvited.roles == [Role.OFFICE]

    def test_member_linked_reinvite_without_roles_stays_a_member(self, tenant):
        user = JasminUserFactory(
            email="default-member@example.com",
            roles=[],
            account_status="pending_invitation",
        )
        MemberFactory(user=user, email="default-member@example.com")

        reinvited = _invite("default-member@example.com", None)

        assert reinvited.roles == [Role.MEMBER]

    def test_an_invalid_role_does_not_drop_the_membership(self, tenant):
        # An unknown role is filtered out, so the normalised list is empty and
        # resolves to the bare member default — the Member link keeps the role
        # whichever way the normalisation lands.
        user = JasminUserFactory(
            email="bogus-role@example.com",
            roles=[Role.STAFF],
            account_status="pending_invitation",
        )
        MemberFactory(user=user, email="bogus-role@example.com")

        reinvited = _invite("bogus-role@example.com", ["not_a_role"])

        assert reinvited.roles == [Role.MEMBER]


class TestNewUserRoleDefault:
    def test_a_brand_new_invitation_without_roles_is_a_member(self, tenant):
        """The member-linked callers rely on this default; it stays put."""
        created = _invite("brand-new-invitee@example.com", None)

        assert created.roles == [Role.MEMBER]
