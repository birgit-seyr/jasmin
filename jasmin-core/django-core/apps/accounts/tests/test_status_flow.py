"""Tests for the user/member status flow.

Covers:
- JasminUser.is_active stays in sync with account_status
- Login is blocked for non-active statuses with the right error message
- Self-registration creates pending_approval + Member, blocks login
- Member.confirm() flips a pending_approval user to active
- Invitation accept activates user AND auto-confirms the linked Member
- Member ↔ "member" role signals (post_save / pre_delete)
- pre_delete on Member auto-deactivates a user left with no roles
- Configuration → Users surface refuses the "member" role
- Configuration → Users active/inactive toggle, with whitelist enforcement
- MemberViewSet.create handles the existing-user enrolment flow
- Member.email uniqueness (DB constraint)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import JasminUser
from apps.accounts.services.auth_service import (
    AccountBlocked,
    InvalidCredentials,
    authenticate_for_tenant,
)
from apps.accounts.services.registration_service import (
    RegistrationError,
    register_public_applicant,
)
from apps.accounts.services.user_admin_service import (
    AdminUserError,
    create_user_with_invite,
    update_user_admin,
)
from apps.authz.roles import Role
from apps.commissioning.models import Member
from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory
from apps.shared.invitations import (
    accept_invitation,
    create_user_with_invitation,
)

# --------------------------------------------------------------------------- #
# Model-level invariants                                                       #
# --------------------------------------------------------------------------- #


class TestJasminUserStatus:
    def test_is_active_derived_from_active_status(self, tenant):
        user = JasminUserFactory(account_status="active")
        assert user.is_active is True

    @pytest.mark.parametrize(
        "status_value",
        ["pending_invitation", "pending_approval", "inactive"],
    )
    def test_is_active_false_for_non_active(self, tenant, status_value):
        user = JasminUserFactory(account_status=status_value)
        assert user.is_active is False

    def test_save_keeps_is_active_synced(self, tenant):
        user = JasminUserFactory(account_status="active")
        user.account_status = "inactive"
        user.save(update_fields=["account_status"])
        user.refresh_from_db()
        assert user.is_active is False
        assert user.account_status == "inactive"

    def test_manually_setting_is_active_is_overridden(self, tenant):
        """is_active is *derived*; manual writes are clobbered by save()."""
        user = JasminUserFactory(account_status="inactive")
        user.is_active = True
        user.save()
        user.refresh_from_db()
        assert user.is_active is False

    def test_set_roles_rejects_invalid(self, tenant):
        from django.core.exceptions import ValidationError

        user = JasminUserFactory()
        with pytest.raises(ValidationError):
            user.set_roles(["notarealrole"])

    def test_set_roles_dedupes_and_preserves_order(self, tenant):
        user = JasminUserFactory()
        user.set_roles([Role.STAFF, Role.OFFICE, Role.STAFF])
        assert user.roles == [Role.STAFF, Role.OFFICE]


# --------------------------------------------------------------------------- #
# Login service                                                                #
# --------------------------------------------------------------------------- #


class TestLoginService:
    def test_active_user_can_login(self, tenant, rf):
        user = JasminUserFactory(account_status="active")
        user.set_password("S3cretPasswort!xyz")
        user.save()
        request = rf.post("/")
        result = authenticate_for_tenant(
            request=request,
            email=user.email,
            password="S3cretPasswort!xyz",
            tenant=tenant,
        )
        assert result.user.id == user.id
        assert result.access
        assert result.refresh

    def test_invalid_password_raises(self, tenant, rf):
        user = JasminUserFactory(account_status="active")
        user.set_password("right-password-XYZ123")
        user.save()
        with pytest.raises(InvalidCredentials):
            authenticate_for_tenant(
                request=rf.post("/"),
                email=user.email,
                password="wrong",
                tenant=tenant,
            )

    @pytest.mark.parametrize(
        "status_value,expected_substr",
        [
            ("pending_approval", "pending admin approval"),
            ("pending_invitation", "complete registration"),
            ("inactive", "deactivated"),
        ],
    )
    def test_blocked_statuses_have_helpful_message(
        self, tenant, rf, status_value, expected_substr
    ):
        user = JasminUserFactory(account_status=status_value)
        user.set_password("anything-XYZ123!")
        user.save()
        with pytest.raises(AccountBlocked) as exc:
            authenticate_for_tenant(
                request=rf.post("/"),
                email=user.email,
                password="anything-XYZ123!",
                tenant=tenant,
            )
        assert expected_substr.lower() in exc.value.message.lower()


# --------------------------------------------------------------------------- #
# Self-registration                                                            #
# --------------------------------------------------------------------------- #


class TestSelfRegistration:
    @pytest.fixture
    def payload(self):
        return {
            "first_name": "Selma",
            "last_name": "Selfreg",
            "email": "selma@example.com",
            "password": "L0ngEnoughPwd!Solid",
            "user_language": "en",
        }

    def test_creates_pending_approval_user_and_member(self, tenant, payload):
        result = register_public_applicant(data=payload, tenant=tenant)
        user = JasminUser.objects.get(email="selma@example.com")
        assert user.account_status == "pending_approval"
        assert user.is_active is False
        # Member exists, linked, unconfirmed
        member = Member.objects.get(id=result["member_id"])
        assert member.user_id == user.id
        assert member.admin_confirmed is False
        # Signal: linked Member ⇒ member role
        assert Role.MEMBER in user.roles

    def test_login_blocked_until_office_confirms(self, tenant, payload, rf):
        register_public_applicant(data=payload, tenant=tenant)
        with pytest.raises(AccountBlocked):
            authenticate_for_tenant(
                request=rf.post("/"),
                email=payload["email"],
                password=payload["password"],
                tenant=tenant,
            )

    def test_member_confirm_flips_user_active(self, tenant, payload):
        register_public_applicant(data=payload, tenant=tenant)
        member = Member.objects.get(email="selma@example.com")
        admin = JasminUserFactory(roles=[Role.OFFICE])
        member.confirm(admin_user=admin, save=True)
        member.user.refresh_from_db()
        assert member.user.account_status == "active"
        assert member.user.is_active is True
        assert member.member_number is not None  # auto-assigned

    def test_email_collision_returns_generic_message(self, tenant, payload):
        JasminUserFactory(email=payload["email"])
        with pytest.raises(RegistrationError) as exc:
            register_public_applicant(data=payload, tenant=tenant)
        assert "could not register" in exc.value.message.lower()

    def test_missing_required_fields(self, tenant):
        with pytest.raises(RegistrationError) as exc:
            register_public_applicant(data={"first_name": "x"}, tenant=tenant)
        assert "missing required" in exc.value.message.lower()

    # ----- extended payload (2026-05-21) ------------------------------------

    def test_creates_one_coop_share_when_count_provided(self, tenant, payload):
        from apps.commissioning.models import CoopShare

        result = register_public_applicant(
            data={**payload, "coop_shares_count": 3}, tenant=tenant
        )
        member = Member.objects.get(id=result["member_id"])
        shares = CoopShare.objects.filter(member=member)
        assert shares.count() == 1
        assert int(shares.first().amount_of_coop_shares) == 3
        assert shares.first().admin_confirmed is False
        assert result["coop_shares_created"] == 1

    def test_coop_share_snapshots_configured_value(self, tenant, payload):
        """With a configured TenantSettings row, the share snapshots the
        whole-unit ``value_one_coop_share``. Regression: registration used to
        call ``.quantize()`` on this (now ``PositiveIntegerField``) value and
        crash whenever a TenantSettings row existed — the common prod case,
        masked here only because other tests create no settings row."""
        import datetime

        from django.utils import timezone

        from apps.commissioning.models import CoopShare
        from apps.shared.tenants.models import TenantSettings

        TenantSettings.objects.create(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(seconds=1),
            value_one_coop_share=250,
        )
        result = register_public_applicant(
            data={**payload, "coop_shares_count": 2}, tenant=tenant
        )
        share = CoopShare.objects.get(member_id=result["member_id"])
        assert int(share.value_one_coop_share) == 250
        assert int(share.amount_of_coop_shares) == 2

    def test_zero_or_missing_coop_shares_creates_none(self, tenant, payload):
        from apps.commissioning.models import CoopShare

        # Explicit zero.
        result = register_public_applicant(
            data={**payload, "coop_shares_count": 0}, tenant=tenant
        )
        member = Member.objects.get(id=result["member_id"])
        assert CoopShare.objects.filter(member=member).count() == 0
        assert result["coop_shares_created"] == 0

    def test_creates_consent_records_for_accepted_documents(self, tenant, payload):
        import datetime

        from apps.commissioning.models import ConsentDocument, ConsentRecord

        privacy = ConsentDocument.objects.create(
            kind="privacy",
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="privacy",
        )
        withdrawal = ConsentDocument.objects.create(
            kind="withdrawal",
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="withdrawal",
        )

        result = register_public_applicant(
            data={
                **payload,
                "accepted_consent_documents": {
                    "privacy": str(privacy.id),
                    "withdrawal": str(withdrawal.id),
                },
            },
            tenant=tenant,
        )
        member = Member.objects.get(id=result["member_id"])
        records = ConsentRecord.objects.filter(member=member)
        assert records.count() == 2
        assert {r.document_id for r in records} == {privacy.id, withdrawal.id}
        assert result["consent_records_created"] == 2

    def test_registration_consent_syncs_cache_and_captures_forensics(
        self, tenant, payload
    ):
        """GDPR-CON-3: registration routes consent through ConsentService.record,
        so the denormalized Member consent-cache column is synced (was NULL on
        the old raw-create path) and the forensic ip_address / user_agent are
        captured — the public web signup is where that provenance matters most."""
        import datetime

        from apps.commissioning.models import ConsentDocument, ConsentRecord

        privacy = ConsentDocument.objects.create(
            kind="privacy",
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="privacy",
        )
        result = register_public_applicant(
            data={
                **payload,
                "accepted_consent_documents": {"privacy": str(privacy.id)},
            },
            tenant=tenant,
            ip_address="203.0.113.9",
            user_agent="UA/1.0",
        )
        member = Member.objects.get(id=result["member_id"])
        # Cache column synced from the ConsentRecord (was NULL before).
        assert member.privacy_consent is not None
        # Forensic provenance captured on the record.
        record = ConsentRecord.objects.get(member=member, document=privacy)
        assert record.ip_address == "203.0.113.9"
        assert record.user_agent == "UA/1.0"

    def test_bogus_consent_document_id_is_silently_skipped(self, tenant, payload):
        from apps.commissioning.models import ConsentRecord

        # No ConsentDocument with this id exists — should land 0 records,
        # not crash. Protects against a malicious / stale client.
        result = register_public_applicant(
            data={
                **payload,
                "accepted_consent_documents": {"privacy": "does-not-exist"},
            },
            tenant=tenant,
        )
        assert ConsentRecord.objects.filter(member_id=result["member_id"]).count() == 0
        assert result["consent_records_created"] == 0

    def test_subscription_intent_lands_in_member_note(self, tenant, payload):
        result = register_public_applicant(
            data={
                **payload,
                "share_type_variation_id": "stv_abc",
                "quantity": 2,
            },
            tenant=tenant,
        )
        member = Member.objects.get(id=result["member_id"])
        assert "[Subscription intent]" in (member.note or "")
        assert "share_type_variation_id=stv_abc" in member.note
        assert "quantity=2" in member.note

    def test_no_intent_note_when_variation_id_missing(self, tenant, payload):
        # quantity alone (no variation) should NOT produce an intent block.
        result = register_public_applicant(
            data={**payload, "quantity": 2}, tenant=tenant
        )
        member = Member.objects.get(id=result["member_id"])
        assert "[Subscription intent]" not in (member.note or "")


# --------------------------------------------------------------------------- #
# Invitation accept                                                            #
# --------------------------------------------------------------------------- #


class TestInvitationAccept:
    def test_accept_activates_user(self, tenant):
        admin = JasminUserFactory(roles=[Role.OFFICE])
        with patch("apps.shared.invitations._send_invitation_email") as send_mock:
            user, invitation = create_user_with_invitation(
                email="invitee@example.com",
                first_name="Invite",
                last_name="Tee",
                roles=[Role.OFFICE],
                user_language="en",
                created_by=admin,
            )
        assert send_mock.called
        assert user.account_status == "pending_invitation"
        assert user.is_active is False

        accept_invitation(token=str(invitation.token), password="N3wPass!Long123")
        user.refresh_from_db()
        assert user.account_status == "active"
        assert user.is_active is True

    def test_accept_auto_confirms_linked_member(self, tenant):
        admin = JasminUserFactory(roles=[Role.OFFICE])
        member = MemberFactory(email="m@example.com", user=None)
        assert member.admin_confirmed is False
        with patch("apps.shared.invitations._send_invitation_email"):
            user, invitation = create_user_with_invitation(
                email="m@example.com",
                first_name="M",
                last_name="X",
                roles=[Role.MEMBER],
                user_language="en",
                member=member,
                created_by=admin,
            )
        accept_invitation(token=str(invitation.token), password="N3wPass!Long123")
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.admin_confirmed_by_id == admin.id
        assert member.member_number is not None
        user.refresh_from_db()
        assert user.account_status == "active"

    def test_accept_schedules_welcome_email(self, tenant):
        """P2-1: accepting the invitation must schedule an
        ``accounts.welcome_user`` dispatch via on_commit. The membership
        side (``application_approved``) is a different event handled
        elsewhere — we only assert the user-account welcome here.
        """
        admin = JasminUserFactory(roles=[Role.OFFICE])
        with patch("apps.shared.invitations._send_invitation_email"):
            _user, invitation = create_user_with_invitation(
                email="newcomer@example.com",
                first_name="New",
                last_name="Comer",
                roles=[Role.OFFICE],
                user_language="en",
                created_by=admin,
            )
        with patch("apps.shared.invitations._send_welcome_email") as welcome_mock:
            accept_invitation(
                token=str(invitation.token),
                password="N3wPass!Long123",
            )
        welcome_mock.assert_called_once()
        call_kwargs = welcome_mock.call_args.kwargs
        assert call_kwargs["user"].email == "newcomer@example.com"


# --------------------------------------------------------------------------- #
# Member ↔ role sync (services/member_role_sync.py via Member.save/delete)     #
# --------------------------------------------------------------------------- #


class TestMemberRoleSync:
    def test_creating_member_with_user_adds_member_role(self, tenant):
        user = JasminUserFactory(roles=[Role.STAFF])
        MemberFactory(user=user)
        user.refresh_from_db()
        assert Role.MEMBER in user.roles
        assert Role.STAFF in user.roles

    def test_deleting_member_removes_member_role(self, tenant):
        user = JasminUserFactory(roles=[Role.STAFF])
        member = MemberFactory(user=user)
        user.refresh_from_db()
        assert Role.MEMBER in user.roles
        member.delete()
        user.refresh_from_db()
        assert Role.MEMBER not in user.roles
        # Other roles untouched, user stays active
        assert Role.STAFF in user.roles
        assert user.account_status == "active"

    def test_deleting_only_member_role_deactivates_user(self, tenant):
        user = JasminUserFactory(roles=[])  # member-only via signal
        member = MemberFactory(user=user)
        user.refresh_from_db()
        assert user.roles == [Role.MEMBER]
        member.delete()
        user.refresh_from_db()
        assert user.roles == []
        assert user.account_status == "inactive"
        assert user.is_active is False


# --------------------------------------------------------------------------- #
# Admin user surface (Configuration → Users)                                   #
# --------------------------------------------------------------------------- #


class TestAdminUserCreate:
    def test_rejects_member_role(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        with pytest.raises(AdminUserError) as exc:
            create_user_with_invite(
                data={
                    "first_name": "X",
                    "last_name": "Y",
                    "email": "x@example.com",
                    "roles": [Role.MEMBER],
                },
                created_by=admin,
            )
        assert "members page" in exc.value.message.lower()

    def test_creates_pending_invitation_user(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        with patch("apps.shared.invitations._send_invitation_email"):
            payload = create_user_with_invite(
                data={
                    "first_name": "X",
                    "last_name": "Y",
                    "email": "newstaff@example.com",
                    "roles": [Role.STAFF],
                },
                created_by=admin,
            )
        assert payload["account_status"] == "pending_invitation"
        assert payload["is_active"] is False
        assert Role.STAFF in payload["roles"]


class TestAdminUserUpdate:
    def test_can_deactivate_active_user(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="active", roles=[Role.STAFF])
        payload = update_user_admin(
            user=target, data={"account_status": "inactive"}, actor=admin
        )
        assert payload["account_status"] == "inactive"
        assert payload["is_active"] is False

    def test_can_reactivate_inactive_user(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="inactive", roles=[Role.STAFF])
        payload = update_user_admin(
            user=target, data={"account_status": "active"}, actor=admin
        )
        assert payload["account_status"] == "active"
        assert payload["is_active"] is True

    def test_cannot_skip_pending_invitation_via_status(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="pending_invitation")
        with pytest.raises(AdminUserError):
            update_user_admin(
                user=target, data={"account_status": "active"}, actor=admin
            )

    def test_cannot_skip_pending_approval_via_status(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="pending_approval")
        with pytest.raises(AdminUserError):
            update_user_admin(
                user=target, data={"account_status": "active"}, actor=admin
            )

    def test_status_must_be_in_whitelist(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="active")
        with pytest.raises(AdminUserError):
            update_user_admin(
                user=target,
                data={"account_status": "pending_approval"},
                actor=admin,
            )

    def test_cannot_grant_member_role_without_member_row(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(roles=[Role.STAFF])
        with pytest.raises(AdminUserError) as exc:
            update_user_admin(
                user=target,
                data={"roles": [Role.STAFF, Role.MEMBER]},
                actor=admin,
            )
        assert "not linked to a member record" in exc.value.message.lower()

    def test_cannot_remove_member_role_while_member_exists(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(roles=[Role.STAFF])
        MemberFactory(user=target)
        target.refresh_from_db()
        assert Role.MEMBER in target.roles
        with pytest.raises(AdminUserError) as exc:
            update_user_admin(user=target, data={"roles": [Role.STAFF]}, actor=admin)
        assert "delete the member first" in exc.value.message.lower()


# --------------------------------------------------------------------------- #
# Member.email uniqueness                                                      #
# --------------------------------------------------------------------------- #


class TestMemberEmailUnique:
    def test_duplicate_email_rejected(self, tenant):
        MemberFactory(email="dup@example.com")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                MemberFactory(email="dup@example.com")

    def test_multiple_null_emails_allowed(self, tenant):
        MemberFactory(email=None)
        MemberFactory(email=None)
        assert Member.objects.filter(email__isnull=True).count() == 2


# --------------------------------------------------------------------------- #
# MemberViewSet.create — enrol-existing-user flow                              #
# --------------------------------------------------------------------------- #


@pytest.fixture
def office_client(tenant):
    user = JasminUserFactory(roles=[Role.OFFICE])
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


class TestMemberViewSetCreateEnrol:
    URL = "/api/commissioning/members/"

    def _payload(self, **overrides):
        base = {
            "first_name": "New",
            "last_name": "Member",
            "email": "fresh@example.com",
            "is_active": True,
            "is_trial": False,
            "number_of_rates": 0,
            "is_student": False,
        }
        base.update(overrides)
        return base

    def test_links_existing_active_user_and_confirms(self, office_client, tenant):
        client, _ = office_client
        existing = JasminUserFactory(
            email="alice@example.com",
            account_status="active",
            roles=[Role.STAFF],
        )
        resp = client.post(
            self.URL,
            data=self._payload(email="alice@example.com", notify_user=False),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        member = Member.objects.get(email="alice@example.com")
        assert member.user_id == existing.id
        assert member.admin_confirmed is True
        existing.refresh_from_db()
        assert Role.MEMBER in existing.roles
        assert existing.account_status == "active"

    def test_rejects_pending_approval_user(self, office_client, tenant):
        client, _ = office_client
        JasminUserFactory(
            email="pending@example.com", account_status="pending_approval"
        )
        resp = client.post(
            self.URL,
            data=self._payload(email="pending@example.com"),
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert not Member.objects.filter(email="pending@example.com").exists()

    def test_rejects_inactive_user(self, office_client, tenant):
        client, _ = office_client
        JasminUserFactory(email="inactive@example.com", account_status="inactive")
        resp = client.post(
            self.URL,
            data=self._payload(email="inactive@example.com"),
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_links_pending_invitation_user_without_confirm(self, office_client, tenant):
        client, _ = office_client
        invited = JasminUserFactory(
            email="invited@example.com",
            account_status="pending_invitation",
        )
        resp = client.post(
            self.URL,
            data=self._payload(email="invited@example.com"),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        member = Member.objects.get(email="invited@example.com")
        assert member.user_id == invited.id
        assert member.admin_confirmed is False  # waits for accept

    def test_user_with_existing_member_rejected(self, office_client, tenant):
        client, _ = office_client
        u = JasminUserFactory(email="dup@example.com", account_status="active")
        MemberFactory(user=u, email="dup@example.com")
        resp = client.post(
            self.URL,
            data=self._payload(email="dup@example.com"),
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
class TestMemberUserLinkRoleSync:
    """MEM-7: ``Member.save`` keeps ``Role.MEMBER`` in sync BIDIRECTIONALLY.
    Granting on link was already covered; here we lock the retraction side —
    unlinking or relinking the member's user strips the role from the user it
    no longer points at (else an offboarded/relinked user keeps member access).
    """

    def test_linking_grants_member_role(self, tenant):
        user = JasminUserFactory(roles=[])
        MemberFactory(user=user)
        user.refresh_from_db()
        assert Role.MEMBER in user.roles

    def test_unlinking_user_retracts_member_role(self, tenant):
        user = JasminUserFactory(roles=[])
        member = MemberFactory(user=user)
        user.refresh_from_db()
        assert Role.MEMBER in user.roles

        member.user = None
        member.save()

        user.refresh_from_db()
        assert Role.MEMBER not in user.roles

    def test_relinking_to_new_user_moves_member_role(self, tenant):
        user_a = JasminUserFactory(roles=[])
        user_b = JasminUserFactory(roles=[])
        member = MemberFactory(user=user_a)
        user_a.refresh_from_db()
        assert Role.MEMBER in user_a.roles

        member.user = user_b
        member.save()

        user_a.refresh_from_db()
        user_b.refresh_from_db()
        assert Role.MEMBER not in user_a.roles  # old user loses it
        assert Role.MEMBER in user_b.roles  # new user gains it


# --------------------------------------------------------------------------- #
# Pytest tweak: provide a request factory fixture name `rf`                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def rf():
    from rest_framework.test import APIRequestFactory

    return APIRequestFactory()
