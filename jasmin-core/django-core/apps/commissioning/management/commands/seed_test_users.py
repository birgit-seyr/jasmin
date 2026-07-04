"""Create (or reset) named test users in a tenant for manual UX testing.

Run with ``tenant_command`` because JasminUser / Member / Reseller all
live in tenant schemas:

    poetry run python manage.py tenant_command seed_test_users \\
        --schema=test_tenant

Idempotent: re-running just resets the passwords to ``Test-Test-2026`` and
refreshes the role / activation state. Safe to run as many times as
you like.

Users seeded — every account uses password ``Test-Test-2026``:

    test-admin@example.com          roles=[admin]
    test-member@example.com         roles=[member]
        + linked Member row
    test-customer@example.com       roles=[customer]
        + linked Reseller row
    test-staff@example.com          roles=[staff]
    test-office@example.com         roles=[office]
    test-staff-member@example.com   roles=[staff, member]
        + linked Member row (so the UserMenu "Meine Seite" entry —
        which only shows for the staff+member combo — has a target).

Tied-record fields are set to the minimum the office UI requires to
render the user as a real member / reseller:

  * ``Member`` — ``is_active=True``, first/last name + email copied
    from the user (the model duplicates these on purpose; see
    ``members.py:42``).
  * ``Reseller`` — ``is_reseller=True`` AND ``is_active_reseller=True``
    so the office Offers / OrderContent pages actually surface them.
    The contact / customer-number / invoice address fields are left
    blank; ``Reseller.__str__`` falls back to ``Reseller #<id>``.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.accounts.models import JasminUser
from apps.authz.roles import Role
from apps.commissioning.models import Member, Reseller

# ``link``: which domain row to attach to the user. ``None`` skips the
# link (pure staff / office logins have no member / reseller side).
SPECS = [
    {
        "email": "test-admin@example.com",
        "first_name": "Test",
        "last_name": "Admin",
        "roles": [Role.ADMIN],
        "link": None,
    },
    {
        "email": "test-member@example.com",
        "first_name": "Test",
        "last_name": "Member",
        "roles": [Role.MEMBER],
        "link": "member",
    },
    {
        "email": "test-customer@example.com",
        "first_name": "Test",
        "last_name": "Customer",
        "roles": [Role.CUSTOMER],
        "link": "reseller",
    },
    {
        "email": "test-staff@example.com",
        "first_name": "Test",
        "last_name": "Staff",
        "roles": [Role.STAFF],
        "link": None,
    },
    {
        "email": "test-office@example.com",
        "first_name": "Test",
        "last_name": "Office",
        "roles": [Role.OFFICE],
        "link": None,
    },
    {
        "email": "test-staff-member@example.com",
        "first_name": "Test",
        "last_name": "Staff-Member",
        "roles": [Role.STAFF, Role.MEMBER],
        "link": "member",
    },
]

PASSWORD = "Test-Test-2026"


class Command(BaseCommand):
    help = (
        "Seed named test users covering the member / customer / staff / "
        "office / staff+member personas. Password 'Test-Test-2026' for all. "
        "Idempotent."
    )

    def handle(self, *args: Any, **opts: Any) -> None:
        for spec in SPECS:
            self._seed_one(spec)

    def _seed_one(self, spec: dict[str, Any]) -> None:
        user, user_created = JasminUser.objects.get_or_create(
            email=spec["email"],
            defaults={
                "first_name": spec["first_name"],
                "last_name": spec["last_name"],
                "username": spec["email"].lower(),
                "roles": spec["roles"],
                "account_status": "active",
            },
        )
        if not user_created:
            user.first_name = spec["first_name"]
            user.last_name = spec["last_name"]
            user.roles = spec["roles"]
            user.account_status = "active"
        user.set_password(PASSWORD)
        user.save()

        link_kind = spec.get("link")
        if link_kind == "member":
            row, row_created = Member.objects.get_or_create(
                user=user,
                defaults={
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                    "email": spec["email"],
                    "is_active": True,
                },
            )
            link_label = f"member_id={row.id} ({'new' if row_created else 'existing'})"
        elif link_kind == "reseller":
            row, row_created = Reseller.objects.get_or_create(
                linked_user=user,
                defaults={
                    "name_for_member_pages": (
                        f"{spec['first_name']} {spec['last_name']}"
                    ),
                    "is_reseller": True,
                    "is_active_reseller": True,
                },
            )
            link_label = (
                f"reseller_id={row.id} ({'new' if row_created else 'existing'})"
            )
        elif link_kind is None:
            link_label = "no-link"
        else:
            raise ValueError(f"Unknown link kind: {link_kind!r}")

        action = "CREATED" if user_created else "RESET  "
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} user={user.email}  roles={user.roles}  {link_label}"
            )
        )
