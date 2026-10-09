"""The super-admin API has no backup endpoints.

Backups belong to the ``backup`` sidecar: it holds the dump script, the
tools and the ``./backups`` volume, and the backend container has none of
them, so an endpoint here could neither list nor create a backup.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.urls import Resolver404, resolve


@pytest.mark.parametrize(
    "path",
    ["/api/super-admin/backups/", "/api/super-admin/backups/trigger/"],
)
def test_backup_routes_are_not_served(path):
    with pytest.raises(Resolver404):
        resolve(path, urlconf=settings.PUBLIC_SCHEMA_URLCONF)


def test_super_admin_routes_still_resolve():
    # Guards the test above against passing for a wrong urlconf.
    assert resolve(
        "/api/super-admin/ops-checklist/", urlconf=settings.PUBLIC_SCHEMA_URLCONF
    )
