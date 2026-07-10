"""Cross-cutting permission classes for the accounts app.

Right now this carries ``RequiresStepUp`` — the "did you re-prove
identity recently?" gate on irreversible endpoints. Other auth-flavour
permissions (role-based ``IsOffice`` / ``IsAdmin`` etc.) live in
``apps/authz/permissions.py``; this module stays focused on the
identity-freshness dimension so the two concerns don't tangle.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings
from rest_framework.permissions import BasePermission

from apps.accounts.errors import SelfRegistrationDisabled, StepUpRequired

logger = logging.getLogger("authentication")


class SelfRegistrationEnabled(BasePermission):
    """Allow the public self-registration endpoints ONLY when the current
    tenant has ``TenantSettings.allows_self_registration`` True.

    Server-side half of the feature flag: the login page hides the register
    buttons when the setting is off, and this makes the ``/api/register/*``
    endpoints refuse too — so a hidden button can't be bypassed by posting
    straight to the API. Anonymous callers are fine when the flag is on (it
    gates the FEATURE, not authentication), so it composes with / replaces
    ``AllowAny``. Raises (not returns False) so the canonical
    ``{code, message}`` body reaches the client.
    """

    def has_permission(self, request, view) -> bool:
        from django.db import connection

        from apps.shared.tenants.models import TenantSettings

        current = TenantSettings.get_current_settings(connection.tenant)
        if current is None or not current.allows_self_registration:
            logger.info(
                "auth.self_registration_refused tenant=%s path=%s",
                getattr(connection.tenant, "schema_name", "?"),
                request.path,
            )
            raise SelfRegistrationDisabled(
                "Self-registration is disabled for this organisation."
            )
        return True


class RequiresStepUp(BasePermission):
    """Require a fresh ``step_up_verified_at`` claim on the access token.

    The claim is a Unix timestamp set by ``POST /api/auth/step-up/``.
    Tokens missing the claim, or whose claim is older than
    ``settings.STEP_UP_TTL_SECONDS``, are rejected with
    ``StepUpRequired``. The frontend axios interceptor catches the
    error code (``auth.step_up_required``), pops a password modal,
    re-validates, and retries the original request with the rotated
    access token.

    Compose with role permissions, not in place of them. The canonical
    shape on a function-based view::

        @permission_classes([IsAdmin, RequiresStepUp])

    Or on a ViewSet action::

        def get_permissions(self):
            if self.action == "irreversible_thing":
                return [IsSuperAdmin(), RequiresStepUp()]
            return super().get_permissions()

    Why raise instead of returning False? Returning False gives the
    caller a generic 403 with no machine-readable code, so the
    frontend can't tell "you need step-up" apart from "you lack the
    role". Raising ``StepUpRequired`` produces the canonical Jasmin
    error body with a stable ``code`` the interceptor matches on.
    """

    def has_permission(self, request, view) -> bool:
        # IsAuthenticated should have rejected before this point; if
        # the caller is anonymous we have nothing to inspect. Return
        # False (not raise) so the upstream auth-required response
        # wins and clients don't confuse "log in" with "step up".
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return False

        # ``request.auth is None`` means the caller is authenticated but
        # not via a token we can decorate (session auth, force_authenticate
        # in tests). They genuinely have no claim — treat the same as
        # "missing claim" and raise so the canonical error reaches the
        # client. In production this path is only hit by session-auth
        # callers; those aren't expected to use the destructive
        # endpoints, but failing loud is safer than silently denying.
        payload = (
            getattr(request.auth, "payload", None) if request.auth else None
        ) or {}
        verified_at = payload.get("step_up_verified_at")
        ttl = settings.STEP_UP_TTL_SECONDS

        if not verified_at:
            logger.info(
                "step_up.required path=%s user=%s reason=missing_claim",
                request.path,
                getattr(request.user, "email", "-"),
            )
            raise StepUpRequired(
                "This action requires fresh authentication.",
                details={"ttl_seconds": ttl},
            )

        elapsed = int(time.time()) - int(verified_at)
        if elapsed > ttl:
            logger.info(
                "step_up.required path=%s user=%s reason=expired age=%ss",
                request.path,
                getattr(request.user, "email", "-"),
                elapsed,
            )
            raise StepUpRequired(
                "Your step-up session has expired. Please re-authenticate.",
                details={"ttl_seconds": ttl},
            )

        return True


def requires_step_up_for_fields(*field_names: str) -> type[BasePermission]:
    """Factory: step-up gate that ONLY fires when sensitive fields are touched.

    Use this on viewsets where most writes are benign (name, address,
    note) and only a handful of fields warrant the modal. The returned
    permission class:

      * Short-circuits to True on read methods (GET/HEAD/OPTIONS).
      * Short-circuits to True on writes whose payload does NOT include
        any of ``field_names``.
      * Defers to ``RequiresStepUp`` when one of the listed fields IS
        in the payload — raising ``StepUpRequired`` if the claim is
        missing or expired.

    Example::

        class MemberViewSet(...):
            def get_permissions(self):
                perms = super().get_permissions()
                if self.action in {"update", "partial_update"}:
                    perms.append(
                        requires_step_up_for_fields("iban", "account_owner")()
                    )
                return perms

    A user editing the member's name PATCHes through unprompted; the
    same user editing the IBAN gets the step-up modal.
    """

    sensitive = frozenset(field_names)

    class _ConditionalStepUp(RequiresStepUp):
        def has_permission(self, request, view) -> bool:
            method = (getattr(request, "method", "") or "").upper()
            if method in {"GET", "HEAD", "OPTIONS"}:
                return True
            data = getattr(request, "data", None) or {}
            if not any(field in data for field in sensitive):
                return True
            # For updates (PATCH/PUT) defer the value-comparison check to
            # has_object_permission where the current instance is available.
            # Optimistically pass here; raise there if a field actually changed.
            if method in {"PATCH", "PUT"}:
                return True
            # For creates (POST) there is no existing instance to compare
            # against — any sensitive field in the payload triggers step-up.
            return super().has_permission(request, view)

        def has_object_permission(self, request, view, obj) -> bool:
            method = (getattr(request, "method", "") or "").upper()
            if method in {"GET", "HEAD", "OPTIONS"}:
                return True
            data = getattr(request, "data", None) or {}

            def _norm(val: object) -> str:
                return str(val).strip() if val is not None else ""

            # Only trigger step-up when a sensitive field is actually
            # changing — i.e. the submitted value differs from the stored one.
            # This prevents the modal from firing when EditableTable sends
            # all form fields (including unchanged iban/account_owner) in a
            # PATCH that only touched name/address.
            changing = any(
                field in data and _norm(data[field]) != _norm(getattr(obj, field, None))
                for field in sensitive
            )
            if not changing:
                return True
            return super().has_permission(request, view)

    _ConditionalStepUp.__name__ = f"RequiresStepUpFor_{'_'.join(sorted(field_names))}"
    return _ConditionalStepUp
