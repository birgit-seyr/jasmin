"""Authz-app domain errors.

Subclasses of :class:`core.errors.ForbiddenError`, so the global exception
handler renders them as the canonical ``{code, message}`` 403 body — but with
a STABLE per-case ``code`` instead of the generic ``forbidden``, so clients can
tell an owner-scope violation apart from a missing-privilege rejection. Raised
by ``apps.authz.scoping``'s owner / privilege guards.
"""

from __future__ import annotations

from core.errors import ForbiddenError


class PrivilegeRequired(ForbiddenError):
    """A non-privileged caller hit an office-only path (create / destroy /
    side-effecting ``@action``)."""

    code = "authz.privilege_required"


class NoLinkedOwner(ForbiddenError):
    """The caller has no linked owning row (e.g. reseller / member), so
    owner-scoped access can't be resolved."""

    code = "authz.no_linked_owner"


class CrossOwnerAccess(ForbiddenError):
    """A non-privileged caller tried to act on another owner's data."""

    code = "authz.cross_owner_access"


__all__ = [
    "PrivilegeRequired",
    "NoLinkedOwner",
    "CrossOwnerAccess",
]
