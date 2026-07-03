"""Contract test: the OpenAPI schema must build cleanly with no warnings.

This test runs `manage.py spectacular --validate --fail-on-warn` in a
subprocess and asserts a zero exit code.

Why it exists:
    drf-spectacular silently warns when an endpoint can't be introspected
    (missing serializer, ambiguous return type, undocumented action, ...).
    Those warnings become broken TypeScript types after orval regenerates
    the frontend client.

Run cost is ~3-6s. Guard the rest of the suite from accidentally breaking
the public contract by leaving this in CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Resolve the django-core project root (contains manage.py).
PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.django_db
def test_openapi_schema_builds_without_warnings(tmp_path):
    """`spectacular --validate --fail-on-warn` must exit 0."""
    out_file = tmp_path / "schema.yml"

    # Inherit env so the same DJANGO_SETTINGS_MODULE / DB config is used.
    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    proc = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "manage.py"),
            "spectacular",
            "--validate",
            "--file",
            str(out_file),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if proc.returncode != 0:
        pytest.fail(
            "drf-spectacular schema generation failed.\n"
            "STDOUT:\n"
            f"{proc.stdout}\n"
            "STDERR:\n"
            f"{proc.stderr}"
        )

    assert out_file.exists(), "Schema file was not produced."
    assert out_file.stat().st_size > 0, "Schema file is empty."


# --------------------------------------------------------------------------- #
# Error-response discoverability guard
#
# Every mutation (POST/PATCH/PUT/DELETE) declared in the OpenAPI schema
# should document a ``400`` response, so the orval-generated TypeScript
# client carries a typed error shape for validation failures. We use
# ``core.serializers.ErrorResponseSerializer`` as the canonical body.
#
# Today this rule is enforced ONLY for the apps that have been swept:
# accounts, payments, economics, notifications, gdpr, shared. The
# ``_PENDING_SWEEP`` allowlist holds the URL prefixes we haven't gotten
# to yet — primarily ``/api/commissioning/...``. As you sweep those
# endpoints and add ``400: ErrorResponseSerializer`` to their
# ``responses=`` dicts, shrink the allowlist. When the list goes to
# zero, drop the filter and the rule applies everywhere.
#
# The point is to ratchet — catching the NEXT person who adds a new
# endpoint without an error response in the already-swept areas.
# --------------------------------------------------------------------------- #


_PENDING_SWEEP: tuple[str, ...] = (
    # Empty: ``core.openapi.inject_canonical_error_responses`` runs as a
    # POSTPROCESSING_HOOK and auto-injects 400/401/403/404 into every
    # operation that can produce them. Add a prefix here only if some
    # subtree legitimately has non-canonical error shapes.
)

_MUTATION_METHODS = {"post", "patch", "put", "delete"}


@pytest.mark.django_db
def test_mutations_declare_400_error_response():
    """Each routed mutation must document a 400 response in its schema.

    drf-spectacular generates the OpenAPI dict from ``@extend_schema``
    decorators + serializer introspection. If a POST/PATCH/PUT/DELETE
    endpoint omits 400 from its ``responses=`` dict, the generated
    TypeScript client has no typed shape for validation errors and the
    frontend ends up doing ``error.message`` style guessing. The
    canonical body shape is ``core.serializers.ErrorResponseSerializer``.

    The allowlist (``_PENDING_SWEEP``) covers prefixes we haven't
    swept yet — shrink it as you sweep more apps. Don't add entries
    to silence specific failures; instead, fix the decorator.
    """
    from drf_spectacular.generators import SchemaGenerator

    generator = SchemaGenerator()
    schema = generator.get_schema(request=None, public=True)
    paths = schema.get("paths", {}) or {}

    missing: list[str] = []
    for path, methods in paths.items():
        if any(path.startswith(prefix) for prefix in _PENDING_SWEEP):
            continue
        for method, op in methods.items():
            if method.lower() not in _MUTATION_METHODS:
                continue
            if not isinstance(op, dict):
                continue
            # Mutations without a request body have no validation surface
            # to 400 on (logout, refresh, idempotent regenerate, no-body
            # admin actions, DELETE…). Forcing them to declare 400 would
            # only make the schema lie. The principled rule is "if you
            # accept input, declare what bad input looks like."
            if not op.get("requestBody"):
                continue
            responses = op.get("responses", {}) or {}
            if "400" in responses:
                continue
            op_id = op.get("operationId") or "<no operationId>"
            missing.append(f"{method.upper():6s} {path}  ({op_id})")

    if missing:
        lines = "\n  ".join(missing)
        pytest.fail(
            f"{len(missing)} mutation(s) are missing a 400 response in their "
            "OpenAPI schema. Add ``400: ErrorResponseSerializer`` to the "
            "``responses=`` dict on the ``@extend_schema`` decorator.\n"
            "Why this matters: the orval-generated TypeScript client uses "
            "the schema to derive an error-shape for each endpoint; without "
            "400 declared, the frontend has no typed validation-error "
            "payload to work against.\n\n"
            f"  {lines}"
        )
