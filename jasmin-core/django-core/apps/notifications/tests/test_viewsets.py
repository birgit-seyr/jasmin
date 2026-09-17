"""Contract: the email-template operations publish the failures they return.

Every action that reads ``?language=`` refuses an unmappable value with a 400,
so each of those operations must carry a 400 in the generated schema — the
typed client is derived from it, and an undeclared status has no error shape.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import pytest

_EMAIL_TEMPLATE_PATH_MARKER = "email-templates"


@cache
def _schema() -> dict[str, Any]:
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


def _language_operations() -> list[tuple[str, str, dict[str, Any]]]:
    """Every email-template operation declaring a ``language`` query param."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path, methods in (_schema().get("paths") or {}).items():
        if _EMAIL_TEMPLATE_PATH_MARKER not in path:
            continue
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            query_names = {
                parameter.get("name")
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "query"
            }
            if "language" in query_names:
                found.append((method.upper(), path, operation))
    return found


@pytest.mark.django_db
def test_every_language_operation_declares_400():
    operations = _language_operations()
    assert operations, "no email-template operation declares a language parameter"

    missing = [
        f"{method} {path}"
        for method, path, operation in operations
        if "400" not in (operation.get("responses") or {})
    ]

    assert not missing, (
        "These email-template operations can return a 400 for an unmappable "
        "``?language=`` but do not declare it: " + ", ".join(missing)
    )
