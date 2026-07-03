"""Tests for `apps.authz.roles` — the framework-free role catalogue and
the customer-exclusivity validator.

These tests are pure-Python (no DB), so no fixtures.
"""

from __future__ import annotations

import pytest

from apps.authz.roles import (
    CUSTOMER_COMPATIBLE_ROLES,
    ROLE_CHOICES,
    VALID_ROLES,
    Role,
    validate_role_combination,
)


class TestRoleCatalogue:
    def test_role_choices_match_valid_roles(self):
        assert {key for key, _ in ROLE_CHOICES} == set(VALID_ROLES)

    def test_all_role_constants_are_in_valid_roles(self):
        for attr in (
            "GARDENER",
            "OFFICE",
            "STAFF",
            "MANAGEMENT",
            "MEMBER",
            "ADMIN",
            "CUSTOMER",
        ):
            assert getattr(Role, attr) in VALID_ROLES

    def test_customer_compatible_set_is_customer_plus_member(self):
        assert CUSTOMER_COMPATIBLE_ROLES == frozenset({Role.CUSTOMER, Role.MEMBER})


class TestValidateRoleCombination:
    def test_none_is_valid(self):
        assert validate_role_combination(None) is None

    def test_empty_is_valid(self):
        assert validate_role_combination([]) is None

    def test_single_non_customer_role_is_valid(self):
        assert validate_role_combination([Role.OFFICE]) is None
        assert validate_role_combination([Role.STAFF]) is None
        assert validate_role_combination([Role.ADMIN]) is None

    def test_customer_alone_is_valid(self):
        assert validate_role_combination([Role.CUSTOMER]) is None

    def test_customer_plus_member_is_valid(self):
        assert validate_role_combination([Role.CUSTOMER, Role.MEMBER]) is None

    @pytest.mark.parametrize(
        "incompatible",
        [
            Role.OFFICE,
            Role.STAFF,
            Role.ADMIN,
            Role.MANAGEMENT,
            Role.GARDENER,
        ],
    )
    def test_customer_plus_other_role_is_rejected(self, incompatible):
        msg = validate_role_combination([Role.CUSTOMER, incompatible])
        assert msg is not None
        assert "customer" in msg.lower()
        assert incompatible in msg

    def test_error_message_lists_all_offending_roles(self):
        msg = validate_role_combination([Role.CUSTOMER, Role.OFFICE, Role.STAFF])
        assert msg is not None
        assert Role.OFFICE in msg
        assert Role.STAFF in msg

    def test_duplicates_are_handled(self):
        # Duplicates should not change the verdict.
        assert validate_role_combination([Role.MEMBER, Role.MEMBER]) is None
        assert (
            validate_role_combination([Role.CUSTOMER, Role.CUSTOMER, Role.MEMBER])
            is None
        )
