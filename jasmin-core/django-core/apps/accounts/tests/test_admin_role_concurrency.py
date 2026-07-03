"""Concurrency test for the last-active-admin demotion guard.

``update_user_admin`` refuses to remove the ADMIN role from the last active
admin via a check-and-demote. Without serialisation, two concurrent requests
each demoting a DIFFERENT admin both read the OTHER as "another active admin"
(Postgres READ COMMITTED), both pass the guard, and both commit — leaving the
tenant with ZERO admins and no in-app recovery.

The fix is a transaction-scoped, tenant-local advisory lock
(``acquire_advisory_xact_lock("admin_role:mutation")``) around the
check-and-demote: the second mutation blocks until the first commits, re-reads
the now-reduced admin set, and is refused.

``@pytest.mark.django_db(transaction=True)`` is required: worker threads open
their own connections and the advisory lock only serialises across committed
transactions.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from django.db import connection, connections

from apps.accounts.models import JasminUser
from apps.accounts.services.user_admin_service import update_user_admin
from apps.authz.roles import Role
from apps.commissioning.tests.factories import JasminUserFactory


def _demote_in_thread(tenant, target_pk, actor_pk):
    """Worker: remove the ADMIN role from ``target`` on a fresh connection.

    Returns ``"demoted"`` when the role was removed, or ``"refused"`` when the
    last-admin guard (AdminUserError) blocked it. Closes thread-local
    connections in a finally so the post-test flush isn't blocked.
    """
    from django_tenants.utils import tenant_context

    from apps.accounts.errors import AdminUserError

    connection.close()
    try:
        with tenant_context(tenant):
            target = JasminUser.objects.get(pk=target_pk)
            actor = JasminUser.objects.get(pk=actor_pk)
            try:
                update_user_admin(
                    user=target, data={"roles": [Role.OFFICE]}, actor=actor
                )
                return "demoted"
            except AdminUserError:
                return "refused"
    finally:
        for conn in connections.all():
            conn.close()


@pytest.mark.django_db(transaction=True)
class TestAdminDemotionConcurrency:
    @pytest.fixture(autouse=True)
    def _isolate_admins(self, tenant):
        # transaction=True shares committed rows across tests; neutralise any
        # pre-existing active admins so this test's two are the only ones.
        JasminUser.objects.filter(roles__contains=[Role.ADMIN], is_active=True).update(
            is_active=False
        )

    def test_two_admins_demoting_each_other_keeps_one(self, tenant):
        admin_a = JasminUserFactory(roles=[Role.ADMIN])
        admin_b = JasminUserFactory(roles=[Role.ADMIN])

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_demote_in_thread, tenant, admin_a.pk, admin_b.pk),
                pool.submit(_demote_in_thread, tenant, admin_b.pk, admin_a.pk),
            ]
            results = sorted(f.result() for f in as_completed(futures))

        # Exactly one demotion went through; the other was refused by the guard
        # (without the lock both would commit, leaving zero admins).
        assert results == ["demoted", "refused"]
        admin_a.refresh_from_db()
        admin_b.refresh_from_db()
        still_admin = [u for u in (admin_a, admin_b) if Role.ADMIN in (u.roles or [])]
        assert len(still_admin) == 1
