"""Tests for the limit/offset validation in :mod:`core.pagination`.

DRF swallows every parse error in ``get_limit``/``get_offset`` and falls back
to the default, so a typo'd page size reads as "no limit given" — on the
project's opt-in paginator that means the caller gets the whole table. These
lock the catalogue-backed behaviour that replaces it.
"""

from __future__ import annotations

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.errors import InvalidQueryParam
from core.pagination import (
    OptionalLimitOffsetPagination,
    ValidatedLimitOffsetPagination,
)

ROWS = list(range(25))


class _DefaultLimitPagination(ValidatedLimitOffsetPagination):
    """A paginator that always paginates — the shape the platform's support
    inbox uses."""

    default_limit = 10
    max_limit = 20


def _paginate(query: str, paginator=None):
    paginator = paginator or OptionalLimitOffsetPagination()
    request = Request(APIRequestFactory().get(f"/rows/{query}"))
    return paginator.paginate_queryset(ROWS, request), paginator


def test_no_pagination_params_returns_the_plain_list():
    page, _ = _paginate("")
    assert page is None


def test_empty_limit_counts_as_not_sent():
    page, _ = _paginate("?limit=")
    assert page is None


def test_limit_and_offset_slice_the_rows():
    page, paginator = _paginate("?limit=5&offset=10")
    assert page == ROWS[10:15]
    assert paginator.count == len(ROWS)


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "1.5", "1e3"])
def test_unusable_limit_is_refused_instead_of_dumping_everything(raw):
    with pytest.raises(InvalidQueryParam) as exc_info:
        _paginate(f"?limit={raw}")
    assert exc_info.value.field == "limit"


@pytest.mark.parametrize("raw", ["abc", "-1", "x"])
def test_unusable_offset_is_refused(raw):
    with pytest.raises(InvalidQueryParam) as exc_info:
        _paginate(f"?limit=5&offset={raw}")
    assert exc_info.value.field == "offset"


def test_unusable_offset_is_refused_even_without_a_limit():
    """``offset`` is validated on its own, although DRF would never reach it
    without a usable ``limit``."""
    with pytest.raises(InvalidQueryParam) as exc_info:
        _paginate("?offset=-1")
    assert exc_info.value.field == "offset"


def test_limit_above_the_cap_is_served_at_the_cap():
    """``max_limit`` clamps rather than refuses, which is why it is documented
    in the parameter's prose and not as an OpenAPI ``maximum``."""
    page, paginator = _paginate("?limit=999999")
    assert paginator.limit == OptionalLimitOffsetPagination.max_limit
    assert page == ROWS


def test_a_default_limit_paginator_still_refuses_a_bad_limit():
    paginator = _DefaultLimitPagination()
    with pytest.raises(InvalidQueryParam) as exc_info:
        _paginate("?limit=abc", paginator)
    assert exc_info.value.field == "limit"


def test_a_default_limit_paginator_uses_its_default_when_none_is_sent():
    page, paginator = _paginate("", _DefaultLimitPagination())
    assert paginator.limit == 10
    assert page == ROWS[:10]


def test_schema_parameters_carry_the_validated_bounds():
    parameters = {
        parameter["name"]: parameter
        for parameter in OptionalLimitOffsetPagination().get_schema_operation_parameters(
            view=None
        )
    }
    # No ``maximum``: ``max_limit`` clamps the page size instead of refusing
    # it, so publishing it as a constraint would state a rule the server does
    # not apply. The cap is in the prose instead.
    assert parameters["limit"]["schema"] == {"type": "integer", "minimum": 1}
    assert parameters["offset"]["schema"] == {"type": "integer", "minimum": 0}
    # English, not the server locale's translation of DRF's own wording.
    assert "Page size" in parameters["limit"]["description"]
    assert str(OptionalLimitOffsetPagination.max_limit) in (
        parameters["limit"]["description"]
    )


def test_openapi_parameters_mirror_the_schema_parameters():
    """The hand-paginated views (gdpr's decided-deletions history) document the
    two parameters from the same source the paginator validates against."""
    by_name = {
        parameter.name: parameter
        for parameter in OptionalLimitOffsetPagination.openapi_parameters()
    }
    assert set(by_name) == {"limit", "offset"}
    assert by_name["limit"].type == {"type": "integer", "minimum": 1}
    assert by_name["offset"].type["minimum"] == 0
