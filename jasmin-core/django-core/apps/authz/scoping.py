"""Generic queryset-scoping helper.

Domain-agnostic primitive used by app-specific scoping helpers
(e.g. `apps.commissioning.scoping`). The pattern:

    privileged caller -> see everything
    non-privileged caller with a link -> see only their own rows
    non-privileged caller without a link -> see nothing (fail closed)

The "link" is read off `request.user` via a configurable attribute name.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db.models import QuerySet

from .permissions import has_any_role
from .roles import Role

# Default "internal users see everything" set.
DEFAULT_PRIVILEGED_ROLES: tuple[str, ...] = (
    Role.OFFICE,
    Role.ADMIN,
    Role.MANAGEMENT,
)


def scope_by_user_attr(
    qs: QuerySet,
    request,
    *,
    user_attr: str,
    path: str,
    privileged_roles: Iterable[str] = DEFAULT_PRIVILEGED_ROLES,
    attr_path: str | None = None,
) -> QuerySet:
    """Filter `qs` to rows owned by the calling user.

    Args:
        qs: Queryset to narrow.
        request: DRF request.
        user_attr: Attribute on `request.user` that points to the owning
            object (e.g. `"linked_reseller"`, `"member_profile"`).
        path: ORM lookup from `qs.model` to the owning object
            (e.g. `"reseller"`, `"order__reseller"`,
            `"subscription__member"`).
        privileged_roles: Roles that bypass the filter and see everything.
        attr_path: Optional dotted path to traverse from the user attr to a
            scalar value used in the filter (e.g. `"offer_group_id"`).
            If unset, the user attribute itself is used.

    Returns:
        Filtered queryset, or `qs.none()` if the caller has no link.
    """
    if has_any_role(request, *privileged_roles):
        return qs

    user = getattr(request, "user", None)
    if user is None:
        return qs.none()

    # The ``, None`` default on ``user_attr`` is LOAD-BEARING — keep
    # it even though the attribute name is dynamic. Two real callers
    # need it:
    #   * ``AnonymousUser`` doesn't carry the linked-reseller /
    #     member-profile descriptors at all → AttributeError.
    #   * A ``JasminUser`` WITH the descriptor but no linked row raises
    #     ``RelatedObjectDoesNotExist``, which Django constructs as
    #     ``class RelatedObjectDoesNotExist(DoesNotExist, AttributeError)``.
    # Both paths must collapse to "no link → return ``qs.none()``".
    # ``getattr(..., None)`` catches AttributeError and its subclasses,
    # giving us that single exit. A typo at the call site silently
    # scoping to nothing is the cost; the alternative (drop the
    # default) crashes every anonymous request and every
    # not-yet-linked user.
    owner = getattr(user, user_attr, None)
    if owner is None:
        return qs.none()

    if attr_path:
        for part in attr_path.split("."):
            owner = getattr(owner, part, None)
            if owner is None:
                return qs.none()

    # Unwrap Model instances to their PK. ``CharField``-based PKs (used by
    # ``JasminModel``) do not auto-unwrap model instances the way standard
    # integer/UUID PKs do — passing the instance would coerce via ``str()``
    # and silently match nothing.
    filter_value = getattr(owner, "pk", owner)
    return qs.filter(**{path: filter_value})


def is_privileged(
    request,
    *,
    privileged_roles: Iterable[str] = DEFAULT_PRIVILEGED_ROLES,
) -> bool:
    """Return True for callers in any of the privileged roles.

    Defaults to OFFICE/ADMIN/MANAGEMENT — the same set used by
    `scope_by_user_attr` to bypass ownership filtering.
    """
    return has_any_role(request, *privileged_roles)


def enforce_privileged(
    request,
    message: str = "This action is restricted to office staff.",
    *,
    privileged_roles: Iterable[str] = DEFAULT_PRIVILEGED_ROLES,
) -> None:
    """Raise ``ForbiddenError`` unless the caller has a privileged role.

    Sugar over ``is_privileged`` for the very common viewset pattern
    of office-only side-effects (create, destroy, custom @action).

    Raises the Jasmin ``ForbiddenError`` (canonical ``{code: "forbidden",
    message}`` 403) rather than DRF ``PermissionDenied`` (``code:
    "permission_denied"``) so every 403 this platform emits shares one
    stable shape — this helper funnels the office-only viewset paths.
    """
    from .errors import PrivilegeRequired

    if not is_privileged(request, privileged_roles=privileged_roles):
        raise PrivilegeRequired(message)


def get_owner_id(request, *, user_attr: str) -> str | None:
    """Return the PK of the caller's owning object, or None.

    Mirrors the link-resolution that `scope_by_user_attr` performs.
    `user_attr` is the attribute on `request.user` pointing to the
    owning row (e.g. ``"linked_reseller"``, ``"member_profile"``).
    """
    user = getattr(request, "user", None)
    if user is None:
        return None
    # Keep the ``, None`` default — same load-bearing reason as
    # ``scope_by_user_attr``: AnonymousUser and not-yet-linked
    # JasminUser both need this to collapse to "no owner".
    owner = getattr(user, user_attr, None)
    pk = getattr(owner, "pk", None)
    return str(pk) if pk is not None else None


def enforce_owner(
    request,
    target_id,
    *,
    user_attr: str,
    privileged_roles: Iterable[str] = DEFAULT_PRIVILEGED_ROLES,
) -> None:
    """Raise ``ForbiddenError`` if a non-privileged caller targets another owner.

    Privileged roles bypass. Non-privileged callers must either pass
    ``target_id is None`` (caller will fall back to their own id) or pass
    a value that matches their own owner PK. Callers with no link are
    rejected outright.

    Like :func:`enforce_privileged`, raises the Jasmin ``ForbiddenError``
    so the 403 body matches the platform-wide canonical shape.

    Args:
        request: DRF request.
        target_id: Value coming from the request payload / query (e.g. a
            ``reseller`` or ``member`` id). Compared as string.
        user_attr: Attribute on ``request.user`` pointing to the owning row.
    """
    # Imported lazily to keep this module import-light and avoid a cycle
    # with views that import permissions before settings are ready.
    from .errors import CrossOwnerAccess, NoLinkedOwner

    if is_privileged(request, privileged_roles=privileged_roles):
        return
    own = get_owner_id(request, user_attr=user_attr)
    if own is None:
        raise NoLinkedOwner("No linked owner for this user.")
    if target_id is not None and str(target_id) != own:
        raise CrossOwnerAccess("Cannot act on another owner's data.")
