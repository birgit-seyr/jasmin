"""Domain-specific queryset scoping for commissioning.

Wraps the generic helper from `apps.authz.scoping` with the field names that
exist on commissioning's user-facing relations:

    user.linked_reseller    -> Reseller
    user.member_profile     -> Member
    user.linked_reseller.offer_group_id -> OfferGroup id

If you ever lift commissioning into another host app, only this file
needs to change to match the host's user model.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.authz.scoping import (
    enforce_owner,
    enforce_privileged,
    get_owner_id,
    is_privileged,
    scope_by_user_attr,
)

# Re-export the role-bypass predicate so call sites can use a single
# `from ..scoping import is_privileged` import.
__all__ = [
    "is_privileged",
    "enforce_privileged",
    "scope_to_reseller",
    "scope_to_offer_group",
    "scope_to_member",
    "own_reseller_id",
    "own_member_id",
    "enforce_own_reseller",
    "enforce_own_member",
]


def scope_to_reseller(qs: QuerySet, request, *, path: str) -> QuerySet:
    """Restrict `qs` to the caller's linked reseller (privileged roles bypass).

    `path` is the lookup from `qs.model` to a `Reseller` row,
    e.g. ``"reseller"`` or ``"order__reseller"``.
    """
    return scope_by_user_attr(qs, request, user_attr="linked_reseller", path=path)


def scope_to_offer_group(qs: QuerySet, request, *, path: str) -> QuerySet:
    """Restrict `qs` to offers in the caller's reseller's offer group."""
    return scope_by_user_attr(
        qs,
        request,
        user_attr="linked_reseller",
        attr_path="offer_group_id",
        path=path,
    )


def scope_to_member(qs: QuerySet, request, *, path: str) -> QuerySet:
    """Restrict `qs` to the caller's member profile."""
    return scope_by_user_attr(qs, request, user_attr="member_profile", path=path)


# --- Per-action ownership helpers ----------------------------------------
#
# These wrap the generic `apps.authz.scoping.enforce_owner` /
# `get_owner_id` with the user-attr names commissioning uses, so call
# sites read as `enforce_own_member(request, member_id)` rather than
# leaking the attribute string into every view.


def own_reseller_id(request) -> str | None:
    """PK of the caller's linked reseller, or None."""
    return get_owner_id(request, user_attr="linked_reseller")


def own_member_id(request) -> str | None:
    """PK of the caller's member profile, or None."""
    return get_owner_id(request, user_attr="member_profile")


def enforce_own_reseller(request, target_id) -> None:
    """Reject a non-privileged caller targeting another reseller."""
    enforce_owner(request, target_id, user_attr="linked_reseller")


def enforce_own_member(request, target_id) -> None:
    """Reject a non-privileged caller targeting another member."""
    enforce_owner(request, target_id, user_attr="member_profile")
