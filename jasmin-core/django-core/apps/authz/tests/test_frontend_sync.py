"""Contract test: backend role catalogue must match the frontend.

Parses ``react-core/src/shared/auth/roles.ts`` and asserts the role list and
the customer-compatibility set match the Python source of truth in
``apps.authz.roles``.

If anyone adds/removes a role on either side without updating the other,
this test fails — preventing silently divergent behaviour between the UI
and backend authorization.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.authz.roles import CUSTOMER_COMPATIBLE_ROLES, VALID_ROLES

# Walk up from this file until we find the ``react-core`` package, then
# locate ``roles.ts`` within it. We skip ONLY when react-core is absent
# (backend-only checkout); if react-core exists but roles.ts has moved, fail
# loudly rather than silently skipping the contract.
_HERE = Path(__file__).resolve()
_REACT_CORE = None
_ROLES_TS = None
for parent in _HERE.parents:
    react_core = parent / "react-core"
    if react_core.is_dir():
        _REACT_CORE = react_core
        candidate = react_core / "src" / "shared" / "auth" / "roles.ts"
        if candidate.exists():
            _ROLES_TS = candidate
        break


@pytest.fixture(scope="module")
def roles_ts_source() -> str:
    if _REACT_CORE is None:
        pytest.skip("react-core package not present (backend-only checkout)")
    if _ROLES_TS is None:
        pytest.fail(
            "react-core is present but src/shared/auth/roles.ts is missing — "
            "the frontend role catalogue moved. Update _ROLES_TS in this "
            "contract test so the role-sync check runs again."
        )
    return _ROLES_TS.read_text(encoding="utf-8")


def _frontend_roles(src: str) -> set[str]:
    """Extract the role string values from the ``ROLES`` const object."""
    block_match = re.search(r"export const ROLES\s*=\s*\{(.*?)\}", src, re.S)
    assert block_match, "Could not locate ROLES const in roles.ts"
    return set(re.findall(r'"([a-z_]+)"', block_match.group(1)))


def _frontend_customer_compatible(src: str) -> set[str]:
    """Extract the role string values from CUSTOMER_COMPATIBLE_ROLES."""
    block_match = re.search(r"CUSTOMER_COMPATIBLE_ROLES[^=]*=\s*\[(.*?)\]", src, re.S)
    assert block_match, "Could not locate CUSTOMER_COMPATIBLE_ROLES in roles.ts"
    block = block_match.group(1)
    keys = re.findall(r"ROLES\.([A-Z_]+)", block)
    # Map the constant names back to their values via the ROLES object.
    roles_obj_match = re.search(r"export const ROLES\s*=\s*\{(.*?)\}", src, re.S)
    pairs = dict(re.findall(r"([A-Z_]+):\s*\"([a-z_]+)\"", roles_obj_match.group(1)))
    return {pairs[k] for k in keys}


class TestFrontendBackendRoleSync:
    def test_role_values_match(self, roles_ts_source):
        assert _frontend_roles(roles_ts_source) == set(VALID_ROLES), (
            "Backend VALID_ROLES and frontend ROLES diverged. "
            "Update both apps/authz/roles.py and "
            "react-core/src/shared/auth/roles.ts."
        )

    def test_customer_compatible_set_matches(self, roles_ts_source):
        assert _frontend_customer_compatible(roles_ts_source) == set(
            CUSTOMER_COMPATIBLE_ROLES
        ), (
            "Backend CUSTOMER_COMPATIBLE_ROLES and frontend "
            "CUSTOMER_COMPATIBLE_ROLES diverged."
        )
