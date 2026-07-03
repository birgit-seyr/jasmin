"""Explicit Member ↔ JasminUser.roles synchronisation.

Replaces the former ``post_save`` / ``pre_delete`` signal handlers in
``apps/commissioning/signals.py`` — project convention is explicit
service calls over signals. Called from ``Member.save()`` and
``Member.delete()``, the single funnel every instance-level
create/update/delete path goes through.

Queryset bulk operations (``Member.objects.filter(...).delete()`` /
``.update(user=...)``) bypass model methods entirely — unlike the old
``pre_delete`` signal, which also fired on queryset deletes. The only
such call sites are the two demo-seed ``_clean`` commands
(``seed_demo_members`` / ``seed_user_status_demo``), where the skipped
role retraction is moot because they delete the linked JasminUser rows
immediately afterwards. Any new queryset bulk call site must call
these functions itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.authz.roles import Role

if TYPE_CHECKING:
    from apps.accounts.models import JasminUser


def ensure_member_role(user: JasminUser) -> None:
    """Grant ``Role.MEMBER`` to the user linked to a Member row."""
    roles = list(user.roles or [])
    if Role.MEMBER in roles:
        return
    roles.append(Role.MEMBER)
    user.roles = roles
    user.save(update_fields=["roles", "updated_at"])


def retract_member_role(user: JasminUser) -> None:
    """Remove ``Role.MEMBER`` after the linked Member row is deleted.

    If the user is left with no roles AND no reseller link, they have
    nothing left to do on the platform — deactivate them so they cannot
    log in until an admin re-grants a role.
    """
    roles = [role for role in (user.roles or []) if role != Role.MEMBER]
    if roles == (user.roles or []):
        return
    user.roles = roles
    update_fields = ["roles", "updated_at"]
    if not roles and not getattr(user, "linked_reseller", None):
        user.account_status = "inactive"
        update_fields.append("account_status")
    user.save(update_fields=update_fields)
