"""Single source of truth for user roles.

Keep in sync with the frontend `src/shared/auth/roles.ts`.

This module is intentionally framework-free (no Django, no DRF imports) so it
stays trivially portable between projects.
"""

from __future__ import annotations


class Role:
    GARDENER = "gardener"
    OFFICE = "office"
    STAFF = "staff"
    MANAGEMENT = "management"
    MEMBER = "member"
    ADMIN = "admin"
    CUSTOMER = "customer"


ROLE_CHOICES = [
    (Role.GARDENER, "Gardener"),
    (Role.OFFICE, "Office"),
    (Role.STAFF, "Staff"),
    (Role.MANAGEMENT, "Management"),
    (Role.MEMBER, "Member"),
    (Role.ADMIN, "Admin"),
    (Role.CUSTOMER, "Customer"),
]

VALID_ROLES = frozenset(key for key, _ in ROLE_CHOICES)


# A "customer" can only co-exist with "member". Any other role combined with
# "customer" is rejected. Keep in sync with `src/shared/auth/roles.ts`.
CUSTOMER_COMPATIBLE_ROLES = frozenset({Role.CUSTOMER, Role.MEMBER})


def validate_role_combination(roles):
    """Return an error message string if the role set is invalid, else None."""
    role_set = set(roles or [])
    if Role.CUSTOMER in role_set and not role_set.issubset(CUSTOMER_COMPATIBLE_ROLES):
        offenders = sorted(role_set - CUSTOMER_COMPATIBLE_ROLES)
        return (
            "Role 'customer' is exclusive and can only be combined with "
            f"'member'. Remove: {', '.join(offenders)}"
        )
    return None
