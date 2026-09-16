"""Discovery-level guard: every concrete ViewSet / APIView in apps/
must declare permission gating.

Why this exists
---------------

The mistake is easy to make: subclass ``viewsets.ModelViewSet``,
declare ``read_permission = IsStaff`` on a base class, and forget
``write_permission``. Result: the mixin's ``get_permissions`` returns
``[IsAuthenticated]`` (the project default) for every write action,
and any authenticated user — including a customer- or member-role
user — can POST / PATCH / DELETE.

How it works
------------

1. Walk every Django app under ``apps/``, at any depth — some apps are
   nested (``apps/shared/tenants``, ``apps/shared/super_admin``,
   ``apps/shared/support``).
2. Import every view module: the ``viewsets`` / ``views`` names (both
   ``foo/viewsets.py`` single-file and ``foo/viewsets/`` package layouts)
   plus the ``*_viewsets`` / ``*_views`` spellings (``admin_viewsets.py``).
3. For each class defined IN that module (not imported):
   - Skip if it's not a ``ViewSet`` / ``APIView`` subclass.
   - Skip if its name starts with ``_`` (abstract-base convention).
   - Skip if it's defined in ``apps.authz`` (the mixin layer itself).
4. For each remaining concrete class, assert ONE of:
   - It inherits ``RolePermissionsMixin`` /
     ``APIViewRolePermissionsMixin`` AND both ``read_permission``
     and ``write_permission`` resolve to a non-None value, OR
   - ``permission_classes`` is set explicitly on the class (or one
     of its non-DRF ancestors). An explicit ``permission_classes
     = []`` counts — that's a conscious "anonymous on purpose"
     decision (e.g. ``CurrentTenantView``), OR
   - ``write_permission`` is set AND ``read_permission`` is spelled
     out as ``None`` on the viewset itself — a recorded "any logged-in
     user may read this" decision (e.g. ``TenantViewSet``), as opposed
     to a read side nobody thought about.
5. Surface every gap in a single consolidated assertion so one
   test run lists them all.

Out of scope
------------

- Function-based ``@api_view`` endpoints. They use the decorator
  ``@permission_classes([...])`` directly and aren't introspectable
  the same way. They're rare in this codebase (~17) and easily
  greppable.
- Whether the *right* permission was chosen for a given route.
  ``test_route_permission_matrix.py`` is the per-route × per-role
  HTTP matrix that proves the actual wiring.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from collections.abc import Iterable

from rest_framework import viewsets
from rest_framework.views import APIView

from apps.authz.permissions import (
    APIViewRolePermissionsMixin,
    RolePermissionsMixin,
)

# Modules where viewset / APIView classes typically live in this repo.
_VIEW_MODULE_NAMES: tuple[str, ...] = ("viewsets", "views")
_VIEW_MODULE_SUFFIXES: tuple[str, ...] = ("_viewsets", "_views")

# Nested app view modules that exist today. A one-level ``apps/*`` walk reaches
# none of them, so they are named here: this guard is worth exactly as much as
# its reach, and a reach that narrows unnoticed leaves endpoints ungated with
# every test still green.
_EXPECTED_VIEW_MODULES = frozenset(
    {
        "apps.accounts.views",
        "apps.accounts.views.auth_views",
        "apps.accounts.views.two_factor_views",
        "apps.accounts.viewsets",
        "apps.commissioning.views",
        "apps.commissioning.views.data_import_views",
        "apps.commissioning.views.delivery_views",
        "apps.commissioning.views.documentation_views",
        "apps.commissioning.views.email_distribution_views",
        "apps.commissioning.views.finalize_views",
        "apps.commissioning.views.my_data_views",
        "apps.commissioning.views.reseller_views",
        "apps.commissioning.views.share_options_views",
        "apps.commissioning.views.share_views",
        "apps.commissioning.views.statistic_views",
        "apps.commissioning.views.stock_views",
        "apps.commissioning.views.waiting_list_offer_views",
        "apps.commissioning.viewsets",
        "apps.commissioning.viewsets.badge_viewsets",
        "apps.commissioning.viewsets.base_viewsets",
        "apps.commissioning.viewsets.basics_viewsets",
        "apps.commissioning.viewsets.choices_models_viewsets",
        "apps.commissioning.viewsets.consents_viewsets",
        "apps.commissioning.viewsets.crates_viewsets",
        "apps.commissioning.viewsets.delivery_viewsets",
        "apps.commissioning.viewsets.documentation_viewsets",
        "apps.commissioning.viewsets.imports_viewsets",
        "apps.commissioning.viewsets.logs_viewsets",
        "apps.commissioning.viewsets.members_viewsets",
        "apps.commissioning.viewsets.resellers_viewsets",
        "apps.commissioning.viewsets.share_content_viewsets",
        "apps.commissioning.viewsets.shares_viewsets",
        "apps.gdpr.views",
        "apps.notifications.viewsets",
        "apps.payments.viewsets",
        "apps.shared.super_admin.views",
        "apps.shared.super_admin.views.auth_views",
        "apps.shared.super_admin.views.authentication",
        "apps.shared.super_admin.views.backup_views",
        "apps.shared.super_admin.viewsets",
        "apps.shared.support.admin_viewsets",
        "apps.shared.support.viewsets",
        "apps.shared.tenants.views",
        "apps.shared.tenants.viewsets",
        "apps.staff.viewsets",
        "apps.staff.viewsets.basics",
        "apps.staff.viewsets.weekly_plan",
    }
)


def _is_view_module_name(name: str) -> bool:
    return name in _VIEW_MODULE_NAMES or name.endswith(_VIEW_MODULE_SUFFIXES)


def _reraise_unless_import_error(name: str) -> None:
    """Fail the walk on anything that is not a missing import.

    ``pkgutil.walk_packages`` re-raises non-ImportError exceptions only while
    ``onerror`` is None. With a callback installed it swallows every exception,
    so a view package that blows up on import would drop out of permission
    coverage without a sound — the blindness this guard exists to prevent.
    """
    exc = sys.exc_info()[1]
    if not isinstance(exc, ImportError):
        raise AssertionError(
            f"Walking {name} raised {type(exc).__name__}: {exc}. "
            "Its view modules are not permission-checked."
        ) from exc


def _iter_app_view_modules() -> Iterable[str]:
    """Yield dotted module names under ``apps.*`` that look like view modules.

    The walk recurses rather than listing ``apps/*``: apps sit at more than one
    depth (``apps/shared/tenants``, ``apps/shared/super_admin``,
    ``apps/shared/support``), and a one-level scan reaches none of the nested
    ones — their endpoints would never be permission-checked here.

    Handles ``apps/foo/viewsets.py`` (single file), ``apps/foo/viewsets/*.py``
    (package — its submodules carry their own names, e.g. ``authentication``,
    so they're enumerated directly) and ``admin_viewsets.py``-style spellings.
    """
    import apps as apps_pkg

    seen: set[str] = set()
    for _finder, dotted, is_pkg in pkgutil.walk_packages(
        apps_pkg.__path__, prefix="apps.", onerror=_reraise_unless_import_error
    ):
        parts = dotted.split(".")
        if "tests" in parts or "migrations" in parts:
            continue
        if not _is_view_module_name(parts[-1]):
            continue
        if dotted not in seen:
            seen.add(dotted)
            yield dotted
        if not is_pkg:
            continue
        try:
            module = importlib.import_module(dotted)
        except ImportError:
            continue
        for _f, sub_name, sub_is_pkg in pkgutil.iter_modules(module.__path__):
            if sub_is_pkg:
                continue
            sub_dotted = f"{dotted}.{sub_name}"
            if sub_dotted not in seen:
                seen.add(sub_dotted)
                yield sub_dotted


# DRF / framework classes we must never consider "concrete" — these are
# the base classes themselves, not user-written views.
_FRAMEWORK_BASES: frozenset[type] = frozenset(
    {
        viewsets.ViewSet,
        viewsets.GenericViewSet,
        viewsets.ModelViewSet,
        viewsets.ReadOnlyModelViewSet,
        APIView,
        RolePermissionsMixin,
        APIViewRolePermissionsMixin,
    }
)


def _is_concrete_viewlike(cls: type) -> bool:
    """Return True if ``cls`` is a concrete ViewSet / APIView subclass
    that needs permission gating verified.
    """
    if cls in _FRAMEWORK_BASES:
        return False
    if cls.__name__.startswith("_"):
        # Project convention: abstract bases are named ``_FooBase``.
        # Subclasses inherit through them and are checked individually.
        return False
    module = cls.__module__ or ""
    if module.startswith("apps.authz"):
        # The mixin layer itself.
        return False
    if module.startswith("rest_framework"):
        return False
    return issubclass(cls, (viewsets.ViewSet, viewsets.GenericViewSet, APIView))


def _declares_read_fallthrough(cls: type) -> bool:
    """True iff ``read_permission = None`` is written on ``cls`` itself.

    The mixin layer declares ``read_permission = None`` as its own default, so
    ``getattr`` cannot tell "deliberately open to every authenticated user"
    from "nobody set a read permission". The class body can: a forgotten read
    side is ABSENT from every app-level ``__dict__``, a decided one is there
    in writing. Ancestors in ``apps.authz`` are skipped for that reason.
    """
    for ancestor in cls.__mro__:
        if (ancestor.__module__ or "").startswith(("apps.authz", "rest_framework")):
            continue
        if "read_permission" in ancestor.__dict__:
            return ancestor.__dict__["read_permission"] is None
    return False


def _has_role_permission_pair(cls: type) -> bool:
    """True iff ``cls`` (or an ancestor) uses
    ``RolePermissionsMixin`` / ``APIViewRolePermissionsMixin`` AND
    both standard read AND write paths are gated.

    Standard case: both ``read_permission`` and ``write_permission``
    resolve to a non-None value. Uses ``getattr`` so an inherited
    declaration (e.g. on ``BaseArchivableViewSet``) counts for its
    subclasses — that's the point of having a base class with the
    defaults set.

    Public-read case: ``write_permission`` is set AND
    ``public_read_actions`` covers both ``"list"`` and ``"retrieve"``.
    The mixin short-circuits those actions to ``AllowAny`` before
    ``read_permission`` is consulted, so ``read_permission`` is
    genuinely unused — declaring it would be misleading. This is
    ``ConsentDocumentViewSet``'s pattern: the registration wizard
    fetches privacy/SEPA text anonymously, but writes (publishing a
    new version) stay office-only.
    """
    if not issubclass(cls, (RolePermissionsMixin, APIViewRolePermissionsMixin)):
        return False

    has_write = getattr(cls, "write_permission", None) is not None
    has_read = getattr(cls, "read_permission", None) is not None

    if has_read and has_write:
        return True

    # Public-read short-circuit covers the read side.
    public_reads = getattr(cls, "public_read_actions", frozenset())
    if has_write and {"list", "retrieve"}.issubset(public_reads):
        return True

    # Authenticated-read case: writes are gated and the viewset states
    # ``read_permission = None``, so reads layer nothing on top of the
    # project-wide ``IsAuthenticated``. That is a decision someone wrote
    # down — ``TenantViewSet``'s pattern, where every logged-in user of the
    # tenant needs to read its own tenant row — not an unguarded read side.
    if has_write and _declares_read_fallthrough(cls):
        return True

    return False


def _has_explicit_permission_classes(cls: type) -> bool:
    """True iff ``permission_classes`` is set somewhere in the MRO
    *above* the DRF base classes — i.e. user code (or a Jasmin mixin)
    explicitly chose it, rather than inheriting the global
    ``DEFAULT_PERMISSION_CLASSES`` from settings.

    ``permission_classes = []`` counts — that's a conscious "open to
    anonymous" decision (``CurrentTenantView``).
    """
    for ancestor in cls.__mro__:
        if ancestor in (APIView, object):
            continue
        if (ancestor.__module__ or "").startswith("rest_framework"):
            continue
        if "permission_classes" in ancestor.__dict__:
            return True
    return False


def _collect_concrete_viewlike_classes() -> list[type]:
    """Walk every ``apps/*/(viewsets|views).py`` and yield the
    concrete view-like classes defined there (not imported)."""
    seen: set[type] = set()
    out: list[type] = []
    for module_name in _iter_app_view_modules():
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            # Reject classes that are merely imported into this module.
            if (obj.__module__ or "") != module_name:
                continue
            if obj in seen:
                continue
            seen.add(obj)
            if _is_concrete_viewlike(obj):
                out.append(obj)
    return out


def test_every_viewset_declares_permission_gating() -> None:
    """Every concrete ViewSet / APIView must EITHER:

    1. Inherit ``RolePermissionsMixin`` / ``APIViewRolePermissionsMixin``
       AND set both ``read_permission`` and ``write_permission``, OR
    2. Set ``permission_classes`` explicitly on the class (or one of
       its non-DRF ancestors), OR
    3. Set ``write_permission`` and spell out ``read_permission =
       None`` on the class — reads then deliberately fall through to
       ``IsAuthenticated`` while writes stay gated.

    Falling through to the project-default ``[IsAuthenticated]`` on the
    WRITE side is NOT acceptable — that admits every authenticated user
    (including customer- and member-role) to writes.
    """
    failures: list[str] = []
    for cls in _collect_concrete_viewlike_classes():
        if _has_role_permission_pair(cls):
            continue
        if _has_explicit_permission_classes(cls):
            continue
        failures.append(f"{cls.__module__}.{cls.__name__}")

    assert not failures, (
        "ViewSets / APIViews without explicit permission gating "
        f"({len(failures)} found). Each one falls through to the "
        "global IsAuthenticated default, which admits customer / "
        "member-role users to writes. Add a RolePermissionsMixin "
        "read/write_permission pair or an explicit permission_classes:"
        "\n  - " + "\n  - ".join(sorted(failures))
    )


def test_discovery_reaches_every_view_module() -> None:
    """Scope guard for the guard above, which can only check what it finds.

    Pinning the full set rather than a count: a module that stops being
    discovered takes its endpoints out of permission coverage silently, and a
    threshold only notices when enough of them vanish at once.
    """
    discovered = set(_iter_app_view_modules())
    missing = sorted(_EXPECTED_VIEW_MODULES - discovered)
    assert not missing, (
        f"{len(missing)} view module(s) out of scope:\n  - "
        + "\n  - ".join(missing)
        + "\nTheir ViewSets / APIViews are no longer permission-checked. "
        "Widen the walk, or update _EXPECTED_VIEW_MODULES if the module moved."
    )
    added = sorted(discovered - _EXPECTED_VIEW_MODULES)
    assert not added, (
        f"{len(added)} view module(s) are not pinned:\n  - "
        + "\n  - ".join(added)
        + "\nAdd them to _EXPECTED_VIEW_MODULES so a later disappearance is caught."
    )
