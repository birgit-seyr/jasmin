"""
Dev script: seed Member and Reseller rows in every user-account status so
the Members and ListResellers pages can showcase all StatusButton variants
and the UserInfoModal flows.

Usage:
    python manage.py seed_user_status_demo --schema=<tenant_schema>
    python manage.py seed_user_status_demo --schema=<tenant_schema> --clean

Creates (idempotent — re-running deletes the previous batch first):
    - 1 Member + 1 Reseller in each of:
        active, pending_approval, pending_invitation, inactive
    - 1 Member + 1 Reseller with NO linked user (userNotInvited)
    - 1 Reseller + 1 Member whose pending_invitation has already EXPIRED
      (so the resend-tooltip + disabled state can be demoed)

All demo emails follow ``demo_user_status_*@example.com`` and demo Reseller
``customer_number`` values are 90001..90099. Delete when no longer needed.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.accounts.models import JasminUser
from apps.commissioning.models import Member, Reseller, UserInvitation
from apps.commissioning.models.basics import ContactEntity
from apps.shared.tenants.models import Tenant

EMAIL_PREFIX = "demo_user_status_"
DEMO_CUSTOMER_NUMBER_START = 90001


# (suffix, account_status, member_number, customer_number, label,
#  include_reseller)
# Customers/Resellers never go through ``pending_approval`` (they only get
# invited by an admin), so that scenario only seeds a Member.
SCENARIOS: list[tuple[str, str | None, int | None, int | None, str, bool]] = [
    ("active", "active", 9001, 90001, "Active", True),
    ("pending_approval", "pending_approval", 9002, None, "Pending Approval", False),
    (
        "pending_invitation",
        "pending_invitation",
        9003,
        90003,
        "Pending Invitation",
        True,
    ),
    (
        "invitation_expired",
        "pending_invitation",
        9004,
        90004,
        "Invitation Expired",
        True,
    ),
    ("inactive", "inactive", 9005, 90005, "Inactive", True),
    ("no_user", None, 9006, 90006, "No Linked User", True),
]


class Command(BaseCommand):
    help = "Seed demo Members + Resellers covering all user-account statuses (dev only)"

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="Tenant schema name")
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Only remove the demo data created by this command",
        )

    def handle(self, *args, **options):
        schema = options["schema"]
        clean = options["clean"]

        try:
            Tenant.objects.get(schema_name=schema)
        except Tenant.DoesNotExist:
            self.stderr.write(f"Tenant with schema '{schema}' not found.")
            return

        with schema_context(schema):
            self._clean()
            if clean:
                self.stdout.write(self.style.SUCCESS("Demo data removed."))
                return
            self._seed()
            n_members, n_resellers = self._seed_counts
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded {n_members} member(s) + {n_resellers} reseller(s) "
                    f"covering all user_status variants."
                )
            )

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #
    def _clean(self) -> None:
        invitations = UserInvitation.objects.filter(email__startswith=EMAIL_PREFIX)
        n_inv = invitations.count()
        invitations.delete()

        resellers = Reseller.objects.filter(
            customer_number__gte=DEMO_CUSTOMER_NUMBER_START,
            customer_number__lt=DEMO_CUSTOMER_NUMBER_START + 100,
        )
        contacts = ContactEntity.objects.filter(id__in=resellers.values("contact_id"))
        n_res = resellers.count()
        resellers.delete()
        n_contacts = contacts.count()
        contacts.delete()

        members = Member.objects.filter(email__startswith=EMAIL_PREFIX)
        n_mem = members.count()
        members.delete()

        users = JasminUser.objects.filter(email__startswith=EMAIL_PREFIX)
        n_users = users.count()
        users.delete()

        if n_inv or n_res or n_mem or n_users or n_contacts:
            self.stdout.write(
                f"Cleaned: {n_users} users, {n_inv} invitations, {n_mem} members, "
                f"{n_res} resellers, {n_contacts} contacts."
            )

    # ------------------------------------------------------------------ #
    # Seed
    # ------------------------------------------------------------------ #
    @transaction.atomic
    def _seed(self) -> None:
        n_members = 0
        n_resellers = 0
        for (
            suffix,
            status,
            member_number,
            customer_number,
            label,
            include_reseller,
        ) in SCENARIOS:
            user = self._create_user(suffix, status, label) if status else None
            if status == "pending_invitation":
                self._create_invitation(user, expired=(suffix == "invitation_expired"))
            self._create_member(suffix, label, member_number, user)
            n_members += 1
            if include_reseller and customer_number is not None:
                self._create_reseller(suffix, label, customer_number, user)
                n_resellers += 1
        self._seed_counts = (n_members, n_resellers)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _create_user(self, suffix: str, status: str, label: str) -> JasminUser:
        email = f"{EMAIL_PREFIX}{suffix}@example.com"
        user = JasminUser(
            username=email.lower(),
            email=email,
            first_name=f"Demo {label}",
            last_name="User",
            language="en",
            roles=[],
            account_status=status,
        )
        if status == "pending_invitation":
            user.set_unusable_password()
        else:
            user.set_password("demo-pass-not-for-login")
        user.save()
        return user

    def _create_invitation(self, user: JasminUser, *, expired: bool) -> None:
        if expired:
            expires_at = timezone.now() - timedelta(days=1)
        else:
            expires_at = timezone.now() + timedelta(days=7)
        UserInvitation.objects.create(
            user=user,
            email=user.email,
            status="sent",
            expires_at=expires_at,
        )

    def _create_member(
        self,
        suffix: str,
        label: str,
        member_number: int,
        user: JasminUser | None,
    ) -> Member:
        return Member.objects.create(
            first_name=f"Demo {label}",
            last_name="Member",
            email=f"{EMAIL_PREFIX}member_{suffix}@example.com",
            member_number=member_number,
            is_active=True,
            user=user,
        )

    def _create_reseller(
        self,
        suffix: str,
        label: str,
        customer_number: int,
        user: JasminUser | None,
    ) -> Reseller:
        contact = ContactEntity.objects.create(
            company_name=f"Demo {label} Reseller",
            first_name=f"Demo {label}",
            last_name="Reseller",
            email=f"{EMAIL_PREFIX}reseller_{suffix}@example.com",
            address="Demoweg 1",
            zip_code="10115",
            city="Berlin",
            country="DE",
        )
        return Reseller.objects.create(
            contact=contact,
            customer_number=customer_number,
            is_reseller=True,
            is_active_reseller=True,
            linked_user=user,
        )
