"""Suite-wide pytest fixtures, loaded for every test under ``apps/``.

The app fixtures live in each app's ``tests/conftest.py``, most of them
re-exported from the commissioning one. Only what has to hold for every test,
whichever conftest it sits under, goes here.
"""

from __future__ import annotations

import pytest
from django.db import connection


@pytest.fixture(autouse=True)
def _end_on_public_schema():
    """Switch the connection back to the public schema after every test.

    ``TenantMainMiddleware`` switches it to the schema a request resolves and
    never switches back, so a routed request made without the ``tenant``
    fixture (``anon_client``, a bare ``APIClient()``) would leave the next test
    on ``test_pytest``. That test would then find tenant data it never asked
    for, and a session fixture it sets up could not create its Tenant, which
    django-tenants allows only on the public schema. ``set_schema_to_public``
    runs no query, so this holds for tests without database access too.
    """
    yield
    connection.set_schema_to_public()
