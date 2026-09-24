"""Admin user management service used by the Configuration → Users page.

Business rules enforced here:
- A created user must carry at least one explicit role — this surface never
  defaults one in.
- Roles must be in VALID_ROLES.
- Role combinations must satisfy ``validate_role_combination``.
- The "member" role can only be granted via the membership flow (a Member
  row must exist for the user). The Configuration → Users screens never
  create members.
- Account status updates from this surface are restricted to
  active/inactive transitions.
- The last active admin can be neither demoted nor deactivated. Either would
  leave the tenant with no administrator and no in-app recovery.
- ``reseller_id`` is wired onto the linked Reseller object.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch

from apps.authz.roles import VALID_ROLES, Role, validate_role_combination
from core.db_locks import acquire_advisory_xact_lock

from ..errors import AdminUserError, AdminUserRolesRequired
from ..models import JasminUser

logger = logging.getLogger("authentication")


# --------------------------------------------------------------------------- #
# Serialization                                                                #
# --------------------------------------------------------------------------- #


def serialize_user_row(user: JasminUser) -> dict:
    from apps.commissioning.models.choices import InvitationStatus

    # If callers prefetched the relevant invitations under
    # ``_prefetched_sent_invitations`` (see MemberViewSet.get_queryset),
    # use that to avoid an N+1; otherwise fall back to a query.
    prefetched = getattr(user, "_prefetched_sent_invitations", None)
    if prefetched is not None:
        invitation = prefetched[0] if prefetched else None
    else:
        invitation = (
            user.invitations.filter(status=InvitationStatus.SENT)
            .order_by("-created_at")
            .first()
        )
    linked_reseller = getattr(user, "linked_reseller", None)
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "roles": user.roles or [],
        "user_language": user.user_language,
        "account_status": user.account_status,
        "is_active": user.is_active,
        "date_joined": user.date_joined,
        "last_login": user.last_login,
        "activated_at": user.activated_at,
        "inactivated_at": user.inactivated_at,
        "invitation_expires_at": invitation.expires_at if invitation else None,
        "is_invitation_expired": bool(invitation and invitation.is_expired),
        "reseller_id": str(linked_reseller.id) if linked_reseller else None,
    }


def list_active_users() -> list[dict]:
    # Mirror the commissioning members/resellers viewsets that serve the same
    # ``serialize_user_row``: select_related the reverse ``linked_reseller``
    # OneToOne and Prefetch only the sent invitations under the attr the
    # serializer reads — otherwise each row fires a fresh invitation query
    # (``.filter()`` on a plain prefetch bypasses the cache) plus a
    # reverse-OneToOne lookup. Local import keeps the accounts→commissioning
    # dependency off the module-load path.
    from apps.commissioning.models.choices import InvitationStatus
    from apps.commissioning.models.members import UserInvitation

    sent_invitations_qs = UserInvitation.objects.filter(
        status=InvitationStatus.SENT
    ).order_by("-created_at")
    qs = (
        JasminUser.objects.all()
        .select_related("linked_reseller")
        .prefetch_related(
            Prefetch(
                "invitations",
                queryset=sent_invitations_qs,
                to_attr="_prefetched_sent_invitations",
            )
        )
        .order_by("first_name", "last_name")
    )
    return [serialize_user_row(user) for user in qs]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _ensure_no_member_role(roles: list[str]) -> None:
    if Role.MEMBER in roles:
        raise AdminUserError(
            "The 'member' role is granted automatically when a Member "
            "record is linked to the user. Use the Members page to add a "
            "person as a member."
        )


def _validate_roles(roles: list[str]) -> None:
    if not isinstance(roles, list):
        raise AdminUserError("roles must be a list")
    invalid = [r for r in roles if r not in VALID_ROLES]
    if invalid:
        raise AdminUserError(f"Invalid roles: {', '.join(sorted(set(invalid)))}")
    combo_err = validate_role_combination(roles)
    if combo_err:
        raise AdminUserError(combo_err)


def _link_reseller(user: JasminUser, reseller_id: str) -> None:
    from apps.commissioning.models import Reseller

    try:
        reseller = Reseller.objects.get(id=reseller_id)
    except Reseller.DoesNotExist as exc:
        raise AdminUserError(f"Reseller '{reseller_id}' not found") from exc
    if reseller.linked_user_id and str(reseller.linked_user_id) != str(user.id):
        raise AdminUserError(
            "This reseller is already linked to another user",
            code="reseller.already_linked",
        )
    Reseller.objects.filter(linked_user=user).update(linked_user=None)
    reseller.linked_user = user
    reseller.save(update_fields=["linked_user"])


def _unlink_reseller(user: JasminUser) -> None:
    from apps.commissioning.models import Reseller

    Reseller.objects.filter(linked_user=user).update(linked_user=None)


# --------------------------------------------------------------------------- #
# Create                                                                       #
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_user_with_invite(*, data: dict[str, Any], created_by: JasminUser) -> dict:
    from apps.shared.invitations import create_user_with_invitation

    required = ("first_name", "last_name", "email")
    missing = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        raise AdminUserError(f"Missing required fields: {', '.join(missing)}")

    roles = list(data.get("roles") or [])
    if not roles:
        # Never fall through to the invitation helper's member default: this
        # surface does not create members, so an empty list here would mint a
        # member login nobody asked for.
        raise AdminUserRolesRequired(
            "Select at least one role for the new user.", field="roles"
        )
    _validate_roles(roles)
    _ensure_no_member_role(roles)

    reseller_id = data.get("reseller_id") or None
    if reseller_id and Role.CUSTOMER not in roles:
        raise AdminUserError(
            "reseller_id can only be set when 'customer' is in roles",
            code="reseller.customer_role_required",
        )

    try:
        # The USER_CREATION volume cap lives inside create_user_with_invitation
        # (the shared choke point for every provisioning path), so it is enforced
        # here without a call site of its own.
        user, _invitation = create_user_with_invitation(
            email=data["email"],
            first_name=data["first_name"].strip(),
            last_name=data["last_name"].strip(),
            roles=roles,
            user_language=data.get("user_language"),
            created_by=created_by,
        )
    except ValidationError as exc:
        msg = getattr(exc, "message_dict", None) or {"error": exc.messages}
        raise AdminUserError(str(msg)) from exc

    if reseller_id:
        _link_reseller(user, reseller_id)

    return serialize_user_row(user)


# --------------------------------------------------------------------------- #
# Update                                                                       #
# --------------------------------------------------------------------------- #


_ADMIN_SETTABLE_STATUSES = {"active", "inactive"}


def _refuse_if_last_active_admin(*, user: JasminUser, attempted: str) -> None:
    """Refuse an action that would leave the tenant with no administrator.

    Demotion and deactivation both reach zero admins, so both take this guard
    and the SAME lock. Serialising matters: without it, a concurrent demote-A
    and deactivate-B each read the OTHER as "another active admin" under READ
    COMMITTED, both pass, and both commit. The xact-scoped lock makes the
    second block until the first commits, then re-read the reduced admin set
    and be correctly refused. There is no in-app recovery from zero admins —
    only an out-of-band super-admin grant.
    """
    acquire_advisory_xact_lock("admin_role:mutation")
    another_active_admin_exists = (
        JasminUser.objects.filter(roles__contains=[Role.ADMIN], is_active=True)
        .exclude(pk=user.pk)
        .exists()
    )
    if not another_active_admin_exists:
        raise AdminUserError(
            f"Cannot {attempted} the last active admin — the tenant would be "
            "left without an administrator."
        )


def _log_user_update(
    *,
    actor: JasminUser,
    user: JasminUser,
    updated_fields: list[str],
    previous_roles: list[str] | None,
) -> None:
    """Write the operational record of an admin edit to auth.log.

    A role change gets its own line carrying before AND after: ``fields=
    ['roles']`` cannot answer the question anyone actually asks of it. The
    durable record is the auditlog row the save emits; this is the line an
    operator greps.
    """
    logger.info(
        "admin.user_updated by=%s target=%s fields=%s",
        actor.email,
        user.email,
        sorted(set(updated_fields)),
    )
    if previous_roles is not None:
        logger.info(
            "admin.user_roles_changed by=%s target=%s before=%s after=%s",
            actor.email,
            user.email,
            sorted(previous_roles),
            sorted(user.roles or []),
        )


def _apply_role_change(
    *, user: JasminUser, data: dict[str, Any], updated_fields: list[str]
) -> list[str] | None:
    """Validate and apply a requested role change, returning the prior list.

    ``None`` means the payload carried no ``roles`` key at all — which is
    what tells the caller there is no role change to log, as distinct from a
    change that happened to end at the same set.
    """
    if "roles" not in data:
        return None

    new_roles = list(dict.fromkeys(data.get("roles") or []))
    _validate_roles(new_roles)

    currently_member = Role.MEMBER in (user.roles or [])
    wants_member = Role.MEMBER in new_roles

    if wants_member and not currently_member:
        # Office can't grant the member role through this surface.
        from apps.commissioning.models import Member

        if not Member.objects.filter(user=user).exists():
            raise AdminUserError(
                "Cannot add 'member' role: this user is not linked to "
                "a Member record. Create the member from the Members "
                "page instead."
            )
    if not wants_member and currently_member:
        from apps.commissioning.models import Member

        if Member.objects.filter(user=user).exists():
            raise AdminUserError(
                "Cannot remove 'member' role while a Member record is "
                "linked. Delete the member first."
            )

    # Self-demotion counts: the actor may be the last admin themselves.
    removing_admin = Role.ADMIN in (user.roles or []) and Role.ADMIN not in new_roles
    if removing_admin:
        _refuse_if_last_active_admin(
            user=user, attempted="remove the 'admin' role from"
        )

    previous_roles = list(user.roles or [])
    user.roles = new_roles
    updated_fields.append("roles")
    return previous_roles


@transaction.atomic
def update_user_admin(
    *, user: JasminUser, data: dict[str, Any], actor: JasminUser
) -> dict:
    updated_fields: list[str] = []
    previous_roles = _apply_role_change(
        user=user, data=data, updated_fields=updated_fields
    )

    for field in ("first_name", "last_name", "user_language"):
        if field in data:
            value = data.get(field)
            if value is None:
                continue
            setattr(user, field, str(value).strip())
            updated_fields.append(field)

    if "account_status" in data:
        new_status = data.get("account_status")
        if new_status not in _ADMIN_SETTABLE_STATUSES:
            raise AdminUserError("account_status must be 'active' or 'inactive'")
        if user.account_status in {"pending_invitation", "pending_approval"}:
            raise AdminUserError(
                f"Cannot change account_status while user is in "
                f"'{user.account_status}'."
            )
        # Deactivating reaches zero admins just as demotion does.
        deactivating_admin = (
            new_status == "inactive"
            and user.is_active
            and Role.ADMIN in (user.roles or [])
        )
        if deactivating_admin:
            _refuse_if_last_active_admin(user=user, attempted="deactivate")
        user.account_status = new_status
        updated_fields.append("account_status")

    if updated_fields:
        # save() will sync is_active; pass updated_at so the timestamp moves.
        user.save(update_fields=[*updated_fields, "updated_at"])
        _log_user_update(
            actor=actor,
            user=user,
            updated_fields=updated_fields,
            previous_roles=previous_roles,
        )

    # Reseller link is handled separately because it lives on Reseller, not
    # JasminUser. Field is allowed only when "customer" is in the resulting
    # role set; if "customer" was removed, drop any link.
    current_roles = user.roles or []
    customer_in_roles = Role.CUSTOMER in current_roles

    if "roles" in data and not customer_in_roles:
        _unlink_reseller(user)

    if "reseller_id" in data:
        new_reseller_id = data.get("reseller_id") or None
        if new_reseller_id and not customer_in_roles:
            raise AdminUserError(
                "reseller_id can only be set when 'customer' is in roles"
            )
        _unlink_reseller(user)
        if new_reseller_id:
            _link_reseller(user, new_reseller_id)

    return serialize_user_row(user)
