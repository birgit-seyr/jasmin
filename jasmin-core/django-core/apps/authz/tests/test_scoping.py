"""Tests for `apps.authz.scoping.scope_by_user_attr`.

Covers the privileged-bypass / linked-row / fail-closed pattern that all
queryset filtering in the platform relies on.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from apps.authz.roles import Role
from apps.authz.scoping import DEFAULT_PRIVILEGED_ROLES, scope_by_user_attr
from apps.commissioning.models import Member, Reseller
from apps.commissioning.tests.factories import (
    JasminUserFactory,
    MemberFactory,
    ResellerFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def rf():
    return APIRequestFactory()


def _request(rf, user):
    req = rf.get("/")
    req.user = user
    return req


class TestPrivilegedBypass:
    @pytest.mark.parametrize("role", list(DEFAULT_PRIVILEGED_ROLES))
    def test_privileged_user_sees_full_queryset(self, tenant, rf, role):
        ResellerFactory()
        ResellerFactory()
        admin = JasminUserFactory(roles=[role])
        qs = scope_by_user_attr(
            Reseller.objects.all(),
            _request(rf, admin),
            user_attr="linked_reseller",
            path="id",
        )
        assert qs.count() == Reseller.objects.count()

    def test_custom_privileged_set_overrides_default(self, tenant, rf):
        ResellerFactory()
        # OFFICE is in the default set, but we override to only allow STAFF.
        office = JasminUserFactory(roles=[Role.OFFICE])
        qs = scope_by_user_attr(
            Reseller.objects.all(),
            _request(rf, office),
            user_attr="linked_reseller",
            path="id",
            privileged_roles=[Role.STAFF],
        )
        # OFFICE is no longer privileged AND has no linked_reseller → none.
        assert qs.count() == 0


class TestFailClosed:
    def test_anonymous_returns_none(self, tenant, rf):
        ResellerFactory()
        qs = scope_by_user_attr(
            Reseller.objects.all(),
            _request(rf, AnonymousUser()),
            user_attr="linked_reseller",
            path="id",
        )
        assert qs.count() == 0

    def test_user_without_link_returns_none(self, tenant, rf):
        ResellerFactory()
        # Customer with no linked_reseller — must see nothing.
        bare = JasminUserFactory(roles=[Role.CUSTOMER])
        qs = scope_by_user_attr(
            Reseller.objects.all(),
            _request(rf, bare),
            user_attr="linked_reseller",
            path="id",
        )
        assert qs.count() == 0

    def test_no_user_on_request_returns_none(self, tenant, rf):
        ResellerFactory()
        req = rf.get("/")
        # No `user` attribute at all.
        if hasattr(req, "user"):
            delattr(req, "user")
        qs = scope_by_user_attr(
            Reseller.objects.all(),
            req,
            user_attr="linked_reseller",
            path="id",
        )
        assert qs.count() == 0


class TestOwnedRows:
    def test_user_with_link_sees_only_own_reseller(self, tenant, rf):
        owned = ResellerFactory()
        ResellerFactory()  # owned by no one
        cust = JasminUserFactory(roles=[Role.CUSTOMER])
        owned.linked_user = cust
        owned.save(update_fields=["linked_user"])
        qs = scope_by_user_attr(
            Reseller.objects.all(),
            _request(rf, cust),
            user_attr="linked_reseller",
            path="id",
            attr_path="id",
        )
        assert list(qs.values_list("id", flat=True)) == [owned.id]

    def test_filter_path_traverses_relation(self, tenant, rf):
        """Scope a Member queryset by the user's linked Member (`member_profile`)."""
        u = JasminUserFactory()
        my_member = MemberFactory(user=u)
        MemberFactory()  # noise
        qs = scope_by_user_attr(
            Member.objects.all(),
            _request(rf, u),
            user_attr="member_profile",
            path="id",
            attr_path="id",
        )
        assert list(qs.values_list("id", flat=True)) == [my_member.id]


class TestAttrPath:
    def test_attr_path_dotted_traversal(self, tenant, rf):
        """`attr_path` lets the caller pull a scalar (e.g. `offer_group_id`)
        off the linked object and use *that* in the filter."""
        from apps.commissioning.models import OfferGroup

        # number != 1: the per-tenant default offer group seeded by migration
        # 0014 already holds number=1 (unique).
        og = OfferGroup.objects.create(name="OG-A", number=2)
        owned = ResellerFactory(offer_group=og)
        ResellerFactory()  # different / no offer group
        cust = JasminUserFactory(roles=[Role.CUSTOMER])
        owned.linked_user = cust
        owned.save(update_fields=["linked_user"])

        qs = scope_by_user_attr(
            Reseller.objects.all(),
            _request(rf, cust),
            user_attr="linked_reseller",
            path="offer_group_id",
            attr_path="offer_group_id",
        )
        assert list(qs.values_list("id", flat=True)) == [owned.id]

    def test_attr_path_short_circuits_on_missing_segment(self, tenant, rf):
        """If any segment of `attr_path` resolves to None, the result is
        an empty queryset — never an unfiltered one."""
        owned = ResellerFactory(offer_group=None)
        cust = JasminUserFactory(roles=[Role.CUSTOMER])
        owned.linked_user = cust
        owned.save(update_fields=["linked_user"])
        qs = scope_by_user_attr(
            Reseller.objects.all(),
            _request(rf, cust),
            user_attr="linked_reseller",
            path="offer_group_id",
            attr_path="offer_group.id",
        )
        assert qs.count() == 0
