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

This is exactly what slipped past code review on
``_TheoreticalBaseViewSet`` until an authorization audit caught it.
This test would have caught it at write time.

How it works
------------

1. Walk every Django app under ``apps/``.
2. Import every ``viewsets`` / ``views`` module (both ``foo/viewsets.py``
   single-file and ``foo/viewsets/`` package layouts).
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
     decision (e.g. ``CurrentTenantView``).
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
from collections.abc import Iterable

from rest_framework import viewsets
from rest_framework.views import APIView

from apps.authz.permissions import (
    APIViewRolePermissionsMixin,
    RolePermissionsMixin,
)

# Modules where viewset / APIView classes typically live in this repo.
_VIEW_MODULE_NAMES: tuple[str, ...] = ("viewsets", "views")


def _iter_app_view_modules() -> Iterable[str]:
    """Yield dotted module names under ``apps.*`` that look like view modules.

    Handles both ``apps/foo/viewsets.py`` (single file) and
    ``apps/foo/viewsets/*.py`` (package).
    """
    import apps as apps_pkg

    for _finder, app_name, is_pkg in pkgutil.iter_modules(apps_pkg.__path__):
        if not is_pkg:
            continue
        for view_name in _VIEW_MODULE_NAMES:
            dotted = f"apps.{app_name}.{view_name}"
            try:
                module = importlib.import_module(dotted)
            except ImportError:
                continue
            yield dotted
            # If it's a package (``foo/viewsets/``), walk submodules too.
            if hasattr(module, "__path__"):
                for _f, sub_name, sub_is_pkg in pkgutil.iter_modules(module.__path__):
                    if sub_is_pkg:
                        continue
                    yield f"{dotted}.{sub_name}"


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
       its non-DRF ancestors).

    Falling through to the project-default ``[IsAuthenticated]`` is
    NOT acceptable — that admits every authenticated user (including
    customer- and member-role) to writes.
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
