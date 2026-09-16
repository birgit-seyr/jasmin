"""Drift guard: every documented query parameter comes from a ParamSpec.

A query parameter is declared ONCE, as a ``ParamSpec`` in an app's catalogue.
``validate_query_params`` enforces that spec at runtime and
``catalogue_parameter`` publishes it to the OpenAPI schema, so the documented
type, ``enum``, bounds and ``default`` are the validated ones.

A parameter declared inline next to its endpoint can drift from the catalogue
the validator enforces. Two halves close that off:

* :class:`TestDocumentedParamsComeFromTheCatalogue` reads the emitted schema and
  matches every query parameter against the catalogue its path is served from;
* :class:`TestNoInlineQueryParameters` reads the SOURCE, so a hand-rolled
  parameter is caught even on an endpoint that is unrouted, unreachable or
  simply not exercised by any other test.

Run: ``poetry run pytest apps/shared/tests/test_query_param_catalogue_drift.py``
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from apps.shared.openapi_params import param_schema
from apps.shared.query_params import PAGINATION_PARAM_CATALOGUE, ParamSpec

# This file is apps/shared/tests/<file>, so django-core is parents[3].
DJANGO_CORE = Path(__file__).resolve().parents[3]

#: Which catalogue(s) serve each API subtree. Pagination is added to all of
#: them (every paginated list shares ``limit``/``offset``). A path prefix that
#: appears in the schema without an entry here fails the test rather than
#: passing unchecked — a new app declares where its params are catalogued.
_CATALOGUES_BY_PREFIX: dict[str, tuple[str, ...]] = {
    "/api/commissioning/": ("commissioning",),
    "/api/payments/": ("payments",),
    "/api/notifications/": ("notifications",),
    # ``apps/staff/viewsets/basics.py`` validates ``is_active`` through the
    # commissioning catalogue; the week/year params are staff's own.
    "/api/staff/": ("staff", "commissioning"),
    "/api/gdpr/": (),
}

#: Parameters documented against a catalogue entry filed under ANOTHER name,
#: with the reason. Each maps ``(path, parameter name)`` to the catalogue key
#: whose spec the endpoint actually enforces, so the published schema is still
#: checked against a real spec — an exemption from the NAME rule, not from the
#: matching rule.
_DOCUMENTED_AS_ANOTHER_SPEC: dict[tuple[str, str], tuple[str, str]] = {
    ("/api/commissioning/resellers/", "delivery_day"): (
        "day_number",
        "A deprecated alias of day_number on this endpoint only: the value is "
        "matched against Order.day_number and is coerced with that spec, not "
        "with the SharesDeliveryDay id the name means everywhere else.",
    ),
}

#: Which catalogue entry each path publishes, where two entries share one wire
#: name. ``kind`` is a consent kind on one endpoint and a mapping kind on
#: another; without a pin either enum would match on either path.
_SPEC_BY_PATH: dict[tuple[str, str], str] = {
    ("/api/commissioning/consent_documents/", "kind"): "commissioning.consent_kind",
    (
        "/api/commissioning/consent_documents/current/",
        "kind",
    ): "commissioning.consent_kind",
    (
        "/api/commissioning/external_code_mappings/",
        "kind",
    ): "commissioning.mapping_kind",
}

#: Modules allowed to construct a QUERY ``OpenApiParameter``, with the reason.
#: Both build it FROM a catalogue, which is the point of the rule.
_BRIDGE_MODULES: dict[str, str] = {
    "apps/shared/openapi_params.py": "the catalogue-to-OpenAPI bridge itself",
    "core/pagination.py": (
        "hands limit/offset to views that paginate by hand; both are built "
        "from PAGINATION_PARAM_CATALOGUE and are checked by the schema half "
        "of this test"
    ),
}


@cache
def _catalogues() -> dict[str, dict[str, ParamSpec]]:
    from apps.commissioning.utils.query_params import PARAM_CATALOGUE as COMMISSIONING
    from apps.notifications.query_params import PARAM_CATALOGUE as NOTIFICATIONS
    from apps.payments.viewsets import PARAM_CATALOGUE as PAYMENTS
    from apps.staff.query_params import STAFF_PARAM_CATALOGUE as STAFF

    return {
        "commissioning": COMMISSIONING,
        "payments": PAYMENTS,
        "notifications": NOTIFICATIONS,
        "staff": STAFF,
        "pagination": PAGINATION_PARAM_CATALOGUE,
    }


@cache
def _schema() -> dict[str, Any]:
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


def _documented_query_parameters() -> list[tuple[str, str, dict[str, Any]]]:
    """Every documented query parameter as ``(path, name, schema object)``.

    Deduplicated across methods: one path documents a parameter identically for
    every verb that takes it.
    """
    seen: set[tuple[str, str, str]] = set()
    parameters: list[tuple[str, str, dict[str, Any]]] = []
    for path, methods in (_schema().get("paths") or {}).items():
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters") or []:
                if parameter.get("in") != "query":
                    continue
                schema = parameter.get("schema") or {}
                key = (path, parameter["name"], json.dumps(schema, sort_keys=True))
                if key in seen:
                    continue
                seen.add(key)
                parameters.append((path, parameter["name"], schema))
    return parameters


def _distinct(
    candidates: Iterable[tuple[str, ParamSpec]],
) -> list[tuple[str, ParamSpec]]:
    """Candidates with duplicate specs collapsed. Two catalogues declaring a
    parameter from the same shared spec (``year`` is one object for every app)
    is the same answer twice, not an ambiguity."""
    distinct: list[tuple[str, ParamSpec]] = []
    for label, spec in candidates:
        if any(spec == already for _label, already in distinct):
            continue
        distinct.append((label, spec))
    return distinct


def _specs_for(path: str, name: str) -> list[tuple[str, ParamSpec]] | None:
    """The catalogue entry a parameter at ``path`` is published from, as
    ``(label, spec)``.

    ``None`` means the subtree is unmapped and an empty list that nothing
    catalogues the name. More than one entry means two different specs answer
    to the same wire name here and nothing records which is published — an
    ambiguity, not a choice: a menu of candidates passes whichever one the
    schema happens to match.
    """
    for prefix, catalogue_names in _CATALOGUES_BY_PREFIX.items():
        if not path.startswith(prefix):
            continue
        catalogues = _catalogues()
        entries = [
            (catalogue_name, key, spec)
            for catalogue_name in (*catalogue_names, "pagination")
            for key, spec in catalogues[catalogue_name].items()
        ]

        exemption = _DOCUMENTED_AS_ANOTHER_SPEC.get((path, name))
        if exemption is not None:
            # ONLY the exempted spec. The entry filed under the wire name is
            # the one the endpoint does NOT enforce — that is why the exemption
            # exists — so leaving it in the running would let it match and
            # excuse exactly the drift being exempted.
            return _distinct(
                (f"{catalogue_name}.{key}", spec)
                for catalogue_name, key, spec in entries
                if key == exemption[0]
            )

        pinned = _SPEC_BY_PATH.get((path, name))
        if pinned is not None:
            return _distinct(
                (f"{catalogue_name}.{key}", spec)
                for catalogue_name, key, spec in entries
                if f"{catalogue_name}.{key}" == pinned
            )

        return _distinct(
            (f"{catalogue_name}.{key}", spec)
            for catalogue_name, key, spec in entries
            if (spec.wire_name or key) == name
        )
    return None


def _comparable(schema: dict[str, Any]) -> dict[str, Any]:
    """A schema object with its ``enum`` order normalised — drf-spectacular
    sorts the values it emits, the catalogue keeps its own order, and an enum
    is a SET of allowed values either way."""
    if "enum" not in schema:
        return schema
    return {**schema, "enum": sorted(schema["enum"], key=str)}


@pytest.mark.django_db
class TestDocumentedParamsComeFromTheCatalogue:
    def test_every_api_subtree_declares_its_catalogue(self):
        unmapped = sorted(
            {
                path
                for path, name, _schema in _documented_query_parameters()
                if _specs_for(path, name) is None
            }
        )
        assert not unmapped, (
            "These paths document query parameters but no catalogue is "
            "declared for their subtree. Add the prefix to "
            "_CATALOGUES_BY_PREFIX in this file, pointing at the catalogue "
            "that app validates with:\n  " + "\n  ".join(unmapped)
        )

    def test_every_documented_param_is_catalogued(self):
        uncatalogued = sorted(
            f"{name}  ({path})"
            for path, name, _schema in _documented_query_parameters()
            if not _specs_for(path, name)
        )
        assert not uncatalogued, (
            f"{len(uncatalogued)} documented query parameter(s) have no "
            "ParamSpec. Add one to the app's catalogue and build the "
            "parameter with catalogue_parameter(...), so the documented type "
            "is the validated one:\n  " + "\n  ".join(uncatalogued)
        )

    def test_documented_schema_matches_the_spec(self):
        """Type, ``enum``, bounds and ``default`` as published must be the ones
        the validator enforces — the whole point of deriving the parameter from
        the catalogue rather than re-typing it."""
        drifted: list[str] = []
        for path, name, schema in _documented_query_parameters():
            specs = _specs_for(path, name) or []
            if len(specs) != 1:
                continue  # reported by the other tests in this class
            label, spec = specs[0]
            if _comparable(param_schema(spec)) == _comparable(schema):
                continue
            drifted.append(
                f"{name}  ({path})\n"
                f"      documented: {json.dumps(schema, sort_keys=True)}\n"
                f"      spec:       {label} -> "
                f"{json.dumps(param_schema(spec), sort_keys=True)}"
            )
        assert not drifted, (
            f"{len(drifted)} documented query parameter(s) disagree with their "
            "ParamSpec. Fix the catalogue entry (if the server changed) or "
            "drop the per-endpoint override (if the docs did):\n  "
            + "\n  ".join(drifted)
        )

    def test_a_shared_wire_name_is_pinned_to_one_spec(self):
        """Two catalogue entries may share a wire name, but a given path
        publishes exactly one of them. Which one has to be recorded in
        ``_SPEC_BY_PATH``, or either spec matches on either endpoint."""
        ambiguous: list[str] = []
        for path, name, _schema in _documented_query_parameters():
            specs = _specs_for(path, name) or []
            if len(specs) < 2:
                continue
            ambiguous.append(
                f"{name}  ({path})\n      candidates: "
                + ", ".join(label for label, _spec in specs)
            )
        assert not ambiguous, (
            f"{len(ambiguous)} documented query parameter(s) match more than "
            "one ParamSpec. Record the one the endpoint publishes in "
            "_SPEC_BY_PATH in this file:\n  " + "\n  ".join(sorted(ambiguous))
        )

    def test_recorded_exemptions_still_apply(self):
        """An exemption or a pin that no longer names a live parameter is stale
        and would silently excuse the next one that takes its place."""
        documented = {
            (path, name) for path, name, _schema in _documented_query_parameters()
        }
        stale = sorted(
            key
            for key in (*_DOCUMENTED_AS_ANOTHER_SPEC, *_SPEC_BY_PATH)
            if key not in documented
        )
        assert not stale, (
            "These _DOCUMENTED_AS_ANOTHER_SPEC / _SPEC_BY_PATH entries no "
            f"longer match a documented parameter — delete them:\n  {stale}"
        )


def _open_api_parameter_names(tree: ast.AST) -> set[str]:
    """Every local name bound to ``OpenApiParameter`` in this module.

    An import is free to rename what it binds (``import OpenApiParameter as
    P``), so matching the canonical spelling alone would let a renamed import
    declare a parameter past the rule.
    """
    names = {"OpenApiParameter"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "OpenApiParameter":
                names.add(alias.asname or alias.name)
    return names


class TestTheSpecMatcherItself:
    """The schema half only bites if it resolves exactly ONE spec per
    documented parameter; a menu of candidates passes whichever one matches."""

    def test_an_exemption_excludes_the_specs_own_name(self):
        """``delivery_day`` is catalogued as a free string. The exemption says
        this endpoint enforces ``day_number`` instead, so the string spec must
        not stay in the running and excuse a reverted override."""
        specs = _specs_for("/api/commissioning/resellers/", "delivery_day") or []
        assert [label for label, _spec in specs] == ["commissioning.day_number"]

    def test_a_shared_wire_name_resolves_per_path(self):
        consent = _specs_for("/api/commissioning/consent_documents/", "kind") or []
        mapping = _specs_for("/api/commissioning/external_code_mappings/", "kind") or []
        assert [label for label, _spec in consent] == ["commissioning.consent_kind"]
        assert [label for label, _spec in mapping] == ["commissioning.mapping_kind"]

    def test_one_spec_reached_through_two_catalogues_is_one_answer(self):
        """``/api/staff/`` reads from two catalogues and both declare ``year``
        — from the same spec object, which is an answer twice over, not an
        ambiguity."""
        assert len(_specs_for("/api/staff/weekly_plan/grid/", "year") or []) == 1

    def test_an_unmapped_subtree_is_reported_as_unmapped(self):
        assert _specs_for("/api/cultivation/beds/", "year") is None


def _query_parameter_declarations(tree: ast.AST) -> list[int]:
    """Line numbers of every ``OpenApiParameter(...)`` call in ``tree`` that
    declares a QUERY parameter (the location drf-spectacular defaults to)."""
    callees = _open_api_parameter_names(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = (
            func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        )
        if callee not in callees:
            continue
        location = next(
            (kw.value for kw in node.keywords if kw.arg == "location"), None
        )
        if location is None:
            lines.append(node.lineno)  # QUERY is the default
            continue
        if isinstance(location, ast.Attribute):
            named = location.attr
        elif isinstance(location, ast.Constant):
            named = str(location.value)
        else:
            named = "QUERY"  # computed: assume the strict reading
        if named.upper() == "QUERY":
            lines.append(node.lineno)
    return lines


class TestNoInlineQueryParameters:
    def test_query_params_are_declared_through_the_bridge(self):
        offenders: list[str] = []
        for directory in ("apps", "core"):
            for path in sorted((DJANGO_CORE / directory).rglob("*.py")):
                relative = path.relative_to(DJANGO_CORE).as_posix()
                if relative in _BRIDGE_MODULES:
                    continue
                for lineno in _query_parameter_declarations(
                    ast.parse(path.read_text())
                ):
                    offenders.append(f"{relative}:{lineno}")

        assert not offenders, (
            f"{len(offenders)} inline QUERY OpenApiParameter declaration(s). "
            "Declare the parameter as a ParamSpec in the app's catalogue and "
            "build it with catalogue_parameter(...) instead, so the documented "
            "type cannot drift from the validated one. (A PATH or HEADER "
            "parameter is fine — the catalogue does not model those.)\n  "
            + "\n  ".join(offenders)
        )


class TestTheDetectorItself:
    """The source scan is only worth having if it actually fires, and only
    usable if it leaves PATH parameters alone."""

    def test_an_inline_query_parameter_is_flagged(self):
        source = "p = OpenApiParameter(name='language', type=str)"
        assert _query_parameter_declarations(ast.parse(source)) == [1]

    def test_a_renamed_import_is_flagged(self):
        """The rule is about the call, not the spelling of the import."""
        source = (
            "from drf_spectacular.utils import OpenApiParameter as P\n"
            "p = P(name='x', type=str)\n"
        )
        assert _query_parameter_declarations(ast.parse(source)) == [2]

    def test_an_explicit_query_location_is_flagged(self):
        source = "p = OpenApiParameter(name='x', location=OpenApiParameter.QUERY)"
        assert _query_parameter_declarations(ast.parse(source)) == [1]

    @pytest.mark.parametrize("location", ["OpenApiParameter.PATH", "'header'"])
    def test_a_non_query_parameter_is_left_alone(self, location):
        """The catalogue models query parameters only, so a path or header
        declaration is the one legitimate inline use."""
        source = f"p = OpenApiParameter(name='x', location={location})"
        assert _query_parameter_declarations(ast.parse(source)) == []
