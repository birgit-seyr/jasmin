"""``parse_capacity_window`` — the shared ``year`` / ``delivery_week`` /
``num_weeks`` window behind both ``capacity_by_week`` serializer fields.

The field is a per-row ``SerializerMethodField``, so the window is resolved once
per request and reused; a request that carries only one half of the pair reads
as "no window" and the field renders ``None``.
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.commissioning.utils import capacity_window
from apps.commissioning.utils.capacity_window import parse_capacity_window


def _request(**params) -> Request:
    return Request(APIRequestFactory().get("/", params))


class TestParseCapacityWindow:
    def test_no_request_reads_as_no_window(self):
        assert parse_capacity_window(None) == (None, None, 52)

    def test_full_window_is_parsed(self):
        request = _request(year=2026, delivery_week=15, num_weeks=4)
        assert parse_capacity_window(request) == (2026, 15, 4)

    def test_num_weeks_falls_back_to_the_catalogue_default(self):
        assert parse_capacity_window(_request(year=2026, delivery_week=15)) == (
            2026,
            15,
            52,
        )

    def test_year_without_week_reads_as_no_window(self):
        assert parse_capacity_window(_request(year=2026)) == (None, None, 52)

    def test_week_without_year_reads_as_no_window(self):
        assert parse_capacity_window(_request(delivery_week=15)) == (None, None, 52)


class TestWindowIsMemoizedPerRequest:
    def _counting_validator(self, monkeypatch) -> list:
        """Swap in a wrapper that records every catalogue validation call."""
        calls: list = []
        validate = capacity_window.validate_query_params

        def counting(request, **kwargs):
            calls.append(request)
            return validate(request, **kwargs)

        monkeypatch.setattr(capacity_window, "validate_query_params", counting)
        return calls

    def test_repeated_calls_validate_the_params_once(self, monkeypatch):
        calls = self._counting_validator(monkeypatch)
        request = _request(year=2026, delivery_week=15, num_weeks=4)

        windows = [parse_capacity_window(request) for _ in range(5)]

        assert windows == [(2026, 15, 4)] * 5
        assert len(calls) == 1

    def test_the_empty_window_is_memoized_too(self, monkeypatch):
        calls = self._counting_validator(monkeypatch)
        request = _request()

        assert parse_capacity_window(request) == (None, None, 52)
        assert parse_capacity_window(request) == (None, None, 52)
        assert len(calls) == 1

    def test_each_request_resolves_its_own_window(self, monkeypatch):
        calls = self._counting_validator(monkeypatch)

        first = parse_capacity_window(_request(year=2026, delivery_week=15))
        second = parse_capacity_window(_request(year=2027, delivery_week=2))

        assert first == (2026, 15, 52)
        assert second == (2027, 2, 52)
        assert len(calls) == 2
