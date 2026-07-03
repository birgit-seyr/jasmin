"""ORM-level multi-tenant isolation tests.

The django-tenants schema-per-tenant model means a row written inside
tenant A's schema must be invisible from any other schema. This is the
single most important security invariant in the platform — if it ever
broke, one tenant could see another tenant's members, payments, etc.

This file complements the JWT-level tests in
``apps/authz/tests/test_authentication.py`` (which prove the JWT layer
refuses cross-tenant tokens) by proving the ORM layer refuses to see
cross-tenant rows even if a request somehow ran in the wrong schema.
"""

from __future__ import annotations

import pytest
from django.db import ProgrammingError, connection, transaction
from django_tenants.utils import schema_context

from apps.commissioning.models import Member
from apps.commissioning.tests.factories import MemberFactory

pytestmark = pytest.mark.django_db


def _assert_member_unreachable(pk: int) -> None:
    """Assert that ``Member`` row ``pk`` is not visible on the current schema.

    ``Member`` lives in TENANT_APPS, so on the ``public`` schema the table
    literally does not exist. Either ``ProgrammingError: relation ...
    does not exist`` or an empty result set proves isolation — both are
    acceptable outcomes.
    """
    try:
        with transaction.atomic():
            assert not Member.objects.filter(pk=pk).exists()
    except ProgrammingError:
        # Table missing on this schema -> isolation guaranteed by schema.
        pass


class TestSchemaIsolation:
    def test_member_created_in_tenant_invisible_from_public(self, tenant):
        """Sanity check on the schema switcher itself."""
        m = MemberFactory()
        tenant_pk = m.pk
        assert Member.objects.filter(pk=tenant_pk).exists()

        # Switch to the public schema. The Member table doesn't exist there
        # for tenant apps. The row must NOT be reachable.
        with schema_context("public"):
            _assert_member_unreachable(tenant_pk)

        # And restoring the tenant schema brings it back.
        assert Member.objects.filter(pk=tenant_pk).exists()

    def test_set_schema_to_public_hides_tenant_rows(self, tenant):
        """The lower-level ``connection.set_schema_to_public`` must do
        the same — guards against accidental schema bleed in fixtures."""
        m = MemberFactory()
        try:
            connection.set_schema_to_public()
            _assert_member_unreachable(m.pk)
        finally:
            connection.set_tenant(tenant)
        # And the row is back after restoring the tenant.
        assert Member.objects.filter(pk=m.pk).exists()

    def test_creating_in_two_schemas_keeps_them_separate(self, tenant):
        """Write in tenant, prove the row doesn't leak into public."""
        in_tenant = MemberFactory()

        with schema_context("public"):
            # Public schema doesn't have the tenant table -> guaranteed
            # zero rows for this pk (ProgrammingError counts as proof).
            _assert_member_unreachable(in_tenant.pk)
