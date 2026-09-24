"""Drift guards: what serializers publish, and to whom.

Two exposures in this codebase are decided in a serializer rather than in a
permission class, which is where nobody looks for an authorization decision:

* **Anonymous reads.** ``RolePermissionsMixin.public_read_actions``
  short-circuits an action to ``AllowAny``, dropping authentication entirely.
  Four of the viewsets using it pair that with ``fields = "__all__"``, so every
  column their model gains in a future migration is published to the internet
  with no review step.
* **File URLs.** ``SignedTenantFileSystemStorage`` signs every ``FileField.url``
  into a capability token that ``protected_media_view`` honours with no user
  and no role. Whichever gate guards the endpoint that HANDS OUT the URL is
  therefore the only gate on the file behind it.

Both are pinned here rather than argued about. Each registry fails in BOTH
directions, like the other registers in this repo: an exposure that appears
without an entry fails, and an entry that no longer matches anything fails as
stale. Adding to a registry is the deliberate act; forgetting is not possible.

Run: ``poetry run pytest apps/shared/tests/test_serializer_exposure_guards.py``
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

import pytest
from django.urls import get_resolver, reverse
from rest_framework import serializers as drf
from rest_framework.test import APIClient

# This file is apps/shared/tests/<file>, so django-core is parents[3].
DJANGO_CORE = Path(__file__).resolve().parents[3]
APPS_DIR = DJANGO_CORE / "apps"

URLCONFS = ("config.tenant_urls", "config.public_urls")

# A field inventory needs the database, which is not obvious: building a
# serializer can run a query. ``DeliveryStationSerializer.__init__`` calls
# ``_add_day_fields()``, which reads the current SharesDeliveryDay rows to
# decide what fields exist — so any sweep that instantiates every routed
# serializer touches the DB whether or not it means to.
pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Shared machinery                                                             #
# --------------------------------------------------------------------------- #


def _routed_view_classes() -> dict[str, type]:
    """Every view class reachable from either urlconf, by class name."""

    def walk(resolver):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern)
            else:
                yield pattern

    found: dict[str, type] = {}
    for urlconf in URLCONFS:
        for pattern in walk(get_resolver(urlconf)):
            view_class = getattr(pattern.callback, "cls", None)
            if view_class is not None:
                found[view_class.__name__] = view_class
    return found


def _fields_of(serializer):
    """``serializer_class`` may be a CLASS or an ``inline_serializer`` INSTANCE.

    ``PackingListViewSet`` is the live example of the latter — calling it like
    a class raises ``TypeError: 'PackingListPlaceholder' object is not
    callable``, so a guard that assumes a class crashes in CI on that viewset
    rather than reporting anything useful.
    """
    return (serializer() if isinstance(serializer, type) else serializer).fields


# --------------------------------------------------------------------------- #
# 1. The anonymous read surface                                                #
# --------------------------------------------------------------------------- #

#: Viewset name -> the exact field set its serializer publishes, for every
#: viewset that opens an action to unauthenticated callers. Nothing here is
#: sensitive today; the registry exists so that stops being luck. A wildcard
#: (``fields = "__all__"``) serializer grows silently with its model, and this
#: is the only thing standing between a new column and the open internet.
_ANONYMOUS_SURFACE: dict[str, frozenset[str]] = {
    # Explicit field list. ``body`` is the published policy text.
    "ConsentDocumentViewSet": frozenset(
        {
            "body",
            "body_sha256",
            "can_be_deleted",
            "created_at",
            "id",
            "kind",
            "locale",
            "title",
            "valid_from",
            "valid_until",
            "version",
        }
    ),
    # Explicit field list. ``note`` is office-internal and is dropped for
    # non-staff readers by the serializer's own ``to_representation``; the
    # behavioural half below is what actually holds that.
    "DeliveryExceptionPeriodViewSet": frozenset(
        {
            "id",
            "is_locked",
            "note",
            "share_type_variation",
            "share_type_variation_string",
            "valid_from",
            "valid_until",
        }
    ),
    # WILDCARD over DeliveryStationDay. Route logistics —
    # special_instructions / tour_number / stop_order — are masked for
    # anonymous callers, not absent from the serializer.
    "DeliveryStationDayViewSet": frozenset(
        {
            "additional_pickup_days",
            "additional_pickup_time_begin_1",
            "additional_pickup_time_begin_2",
            "additional_pickup_time_end_1",
            "additional_pickup_time_end_2",
            "can_be_deleted",
            "capacity",
            "capacity_by_week",
            "coords_lat",
            "coords_lon",
            "delivery_day",
            "delivery_day_number",
            "delivery_station",
            "delivery_station_name",
            "delivery_station_short_name",
            "delivery_time_begin",
            "delivery_time_end",
            "id",
            "pickup_time_begin",
            "pickup_time_end",
            "special_instructions",
            "stop_order",
            "tour_number",
            "valid_from",
            "valid_until",
        }
    ),
    # WILDCARD over PaymentCycle — two columns plus the pk.
    "PaymentCycleViewSet": frozenset({"choice", "id", "is_active"}),
    # WILDCARD over ShareTypeVariation. ``picture`` is a signed media URL the
    # public registration wizard renders; ``capacity`` / ``capacity_by_week``
    # are masked for anonymous callers.
    "ShareTypeVariationViewSet": frozenset(
        {
            "active_price_per_delivery",
            "active_price_per_delivery_if_trial",
            "active_price_sum_articles",
            "active_solidarity_min_price_per_delivery",
            "active_solidarity_min_price_per_delivery_if_trial",
            "allowed_for_trial_subscription",
            "average_weight",
            "can_be_deleted",
            "capacity",
            "capacity_by_week",
            "default_optin_state",
            "description",
            "has_open_ended_subscription",
            "id",
            "is_packed_bulk",
            "optin_deadline_days_before_delivery",
            "physical_components",
            "picture",
            "requires_optin",
            "share_type",
            "share_type_name",
            "size",
            "sort_order",
            "subscriptions_valid_until_max",
            "used_crate",
            "valid_from",
            "valid_until",
            "variation_type",
        }
    ),
    # WILDCARD over ShareType — catalogue text and joker counts.
    "ShareTypeViewSet": frozenset(
        {
            "amount_of_donation_jokers",
            "amount_of_jokers",
            "can_be_deleted",
            "delivery_cycle",
            "description",
            "has_open_ended_variation",
            "id",
            "is_additional_share_type",
            "name",
            "needs_complex_planning",
            "share_option",
            "share_type_variation_sizes_in_use",
            "short_name",
            "valid_from",
            "valid_until",
            "variations_valid_until_max",
        }
    ),
}


@cache
def _anonymous_surface() -> dict[str, frozenset[str]]:
    return {
        name: frozenset(_fields_of(view_class.serializer_class))
        for name, view_class in _routed_view_classes().items()
        if getattr(view_class, "public_read_actions", None)
    }


class TestAnonymousReadSurface:
    def test_every_anonymous_viewset_is_registered(self):
        """A new ``public_read_actions`` declaration must be signed off here."""
        unregistered = sorted(set(_anonymous_surface()) - set(_ANONYMOUS_SURFACE))
        assert not unregistered, (
            f"These viewsets open an action to unauthenticated callers but are "
            f"not in _ANONYMOUS_SURFACE: {unregistered}. Add each one with the "
            f"exact field set it publishes, having checked that every field is "
            f"safe for the open internet."
        )

    def test_no_registry_entry_is_stale(self):
        """An entry whose viewset no longer serves anonymous callers is noise
        that makes the registry look more load-bearing than it is."""
        stale = sorted(set(_ANONYMOUS_SURFACE) - set(_anonymous_surface()))
        assert not stale, (
            f"_ANONYMOUS_SURFACE names viewsets that no longer declare "
            f"public_read_actions: {stale}. Delete the entries."
        )

    @pytest.mark.parametrize("viewset_name", sorted(_ANONYMOUS_SURFACE))
    def test_the_published_field_set_has_not_drifted(self, viewset_name):
        live = _anonymous_surface().get(viewset_name)
        if live is None:
            pytest.skip("covered by test_no_registry_entry_is_stale")
        pinned = _ANONYMOUS_SURFACE[viewset_name]
        added, removed = sorted(live - pinned), sorted(pinned - live)
        assert live == pinned, (
            f"{viewset_name} publishes a different field set to unauthenticated "
            f"callers than this registry records.\n"
            f"  newly exposed: {added}\n"
            f"  no longer exposed: {removed}\n"
            f"If a field was ADDED, confirm it is safe for anonymous readers "
            f"before updating the registry — several of these serializers are "
            f'`fields = "__all__"`, so a model migration widens them without '
            f"touching any serializer code."
        )

    def test_route_logistics_stay_masked_for_anonymous_callers(self, tenant):
        """The declaration half above cannot see this.

        ``special_instructions`` / ``tour_number`` / ``stop_order`` ARE on the
        serializer and are removed per-response by
        ``mask_capacity_for_anonymous``. Delete that call and the registry stays
        green while the fields start shipping, so assert the behaviour.
        """
        response = APIClient().get(reverse("delivery_station_day-list"))

        assert response.status_code == 200, response.content[:200]
        for row in response.json():
            for field in ("special_instructions", "tour_number", "stop_order"):
                assert not row.get(field), (
                    f"{field} reached an unauthenticated caller — the "
                    f"mask_capacity_for_anonymous call has been lost"
                )
            assert row.get("capacity") is None


# --------------------------------------------------------------------------- #
# 2. File-URL exposure                                                         #
# --------------------------------------------------------------------------- #

#: Viewset name -> (read gate, the file fields its serializer publishes).
#: Reading one of these off the wire yields a signed ``?st=`` URL that
#: ``protected_media_view`` serves to anyone holding it, with no authentication
#: — so the gate named here is the real gate on the file's contents.
_FILE_FIELD_EXPOSURE: dict[str, tuple[str, frozenset[str]]] = {
    # Reseller documents, row-scoped to the reseller they address.
    "DeliveryNoteResellerViewSet": ("IsOfficeOrCustomer", frozenset({"file"})),
    "InvoiceResellerViewSet": ("IsOfficeOrCustomer", frozenset({"file", "xml_file"})),
    # A photo of the pickup spot; members need it for their own station.
    "DeliveryStationViewSet": ("IsStaffOrMember", frozenset({"picture"})),
    # ANONYMOUS on list: a product photo the public registration wizard shows.
    "ShareTypeVariationViewSet": ("IsStaffOrMember", frozenset({"picture"})),
    # Tenant branding, deliberately readable before login.
    "TenantViewSet": ("None", frozenset({"app_icon", "bio_logo", "logo"})),
}

#: ``serializer.method_name`` -> the read gate, for file URLs published through
#: a ``SerializerMethodField`` instead of a declared ``FileField``. These are
#: invisible to a field-type sweep: the SEPA export — every debited member's
#: name and IBAN — is published exactly this way.
_FILE_URL_METHOD_FIELDS: dict[str, str] = {
    "BillingRunSerializer.get_sepa_xml_export_url": "IsOffice",
}


@cache
def _file_field_exposure() -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for name, view_class in _routed_view_classes().items():
        serializer = getattr(view_class, "serializer_class", None)
        if serializer is None:
            continue
        files = frozenset(
            field_name
            for field_name, field in _fields_of(serializer).items()
            if isinstance(field, (drf.FileField, drf.ImageField))
        )
        if files:
            found[name] = files
    return found


@cache
def _file_url_method_fields() -> dict[str, int]:
    """``Serializer.get_x`` -> line number, for method fields reading ``.url``."""
    found: dict[str, int] = {}
    for path in sorted(APPS_DIR.rglob("*.py")):
        if {"tests", "migrations"} & set(path.relative_to(APPS_DIR).parts):
            continue
        if "serializer" not in path.name:
            continue
        tree = ast.parse(path.read_text())
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            declared = {
                stmt.targets[0].id
                for stmt in cls.body
                if isinstance(stmt, ast.Assign)
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Call)
                and getattr(stmt.value.func, "attr", None) == "SerializerMethodField"
            }
            for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                if not fn.name.startswith("get_") or fn.name[4:] not in declared:
                    continue
                reads_url = any(
                    isinstance(node, ast.Attribute) and node.attr == "url"
                    for node in ast.walk(fn)
                )
                if reads_url:
                    found[f"{cls.name}.{fn.name}"] = fn.lineno
    return found


class TestFileUrlExposure:
    def test_every_file_field_on_the_wire_is_registered(self):
        unregistered = sorted(set(_file_field_exposure()) - set(_FILE_FIELD_EXPOSURE))
        assert not unregistered, (
            f"These viewsets publish a FileField/ImageField but are not in "
            f"_FILE_FIELD_EXPOSURE: {unregistered}. Reading one yields a signed "
            f"media URL that needs no credential, so record the read gate here "
            f"and satisfy yourself it matches the file's sensitivity."
        )

    def test_no_file_field_entry_is_stale(self):
        stale = sorted(set(_FILE_FIELD_EXPOSURE) - set(_file_field_exposure()))
        assert not stale, (
            f"_FILE_FIELD_EXPOSURE names viewsets that no longer publish a file "
            f"field: {stale}. Delete the entries."
        )

    @pytest.mark.parametrize("viewset_name", sorted(_FILE_FIELD_EXPOSURE))
    def test_the_exposed_file_fields_have_not_drifted(self, viewset_name):
        live = _file_field_exposure().get(viewset_name)
        if live is None:
            pytest.skip("covered by test_no_file_field_entry_is_stale")
        _gate, pinned = _FILE_FIELD_EXPOSURE[viewset_name]
        assert live == pinned, (
            f"{viewset_name} publishes file fields {sorted(live)}, registered as "
            f"{sorted(pinned)}. Four of these serializers are "
            f'`fields = "__all__"`, so adding a FileField to the model starts '
            f"minting capability URLs at this endpoint's gate without any "
            f"serializer change."
        )

    def test_every_method_field_file_url_is_registered(self):
        """A field-type sweep cannot see these, and the sharpest instance in
        this codebase — the SEPA export — is one of them."""
        live = set(_file_url_method_fields())
        unregistered = sorted(live - set(_FILE_URL_METHOD_FIELDS))
        assert not unregistered, (
            f"These SerializerMethodFields return a file URL but are not in "
            f"_FILE_URL_METHOD_FIELDS: {unregistered}. Record the read gate of "
            f"the viewset that publishes each."
        )

    def test_no_method_field_entry_is_stale(self):
        stale = sorted(set(_FILE_URL_METHOD_FIELDS) - set(_file_url_method_fields()))
        assert not stale, (
            f"_FILE_URL_METHOD_FIELDS names methods that no longer read a file "
            f"URL: {stale}. Delete the entries."
        )
