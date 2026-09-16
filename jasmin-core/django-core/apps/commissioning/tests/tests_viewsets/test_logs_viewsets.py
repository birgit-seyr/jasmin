"""Tests for logs_viewsets.py — the theoretical-amount viewsets' default
recency window (harvest / purchase / wash / clean)."""

from __future__ import annotations

from datetime import datetime

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    ShareContentFactory,
    TheoreticalCleanAmountFactory,
    TheoreticalHarvestFactory,
    TheoreticalPurchaseFactory,
    TheoreticalWashAmountFactory,
)

# Monday of ISO week 1, 2027. The two-week cutoff lands on 2026-W52 — in the
# PREVIOUS ISO year — which is the case the window has to span.
EARLY_JANUARY = datetime(2027, 1, 4, 12, 0)

THEORETICAL_LISTS = [
    ("theoretical_harvests", TheoreticalHarvestFactory),
    ("theoretical_purchase_amounts", TheoreticalPurchaseFactory),
    ("theoretical_wash_amounts", TheoreticalWashAmountFactory),
    ("theoretical_clean_amounts", TheoreticalCleanAmountFactory),
]


@pytest.fixture(autouse=True)
def _frozen_early_january():
    """The window is now-relative, so every test here runs on a pinned clock —
    otherwise the hardcoded 2026/2027 weeks stop being before/after "now"."""
    with time_machine.travel(EARLY_JANUARY, tick=False):
        yield


def _row_ids(response) -> set[str]:
    rows = response.json()
    if isinstance(rows, dict):
        rows = rows.get("results", [])
    return {row["id"] for row in rows}


@pytest.mark.django_db
@pytest.mark.parametrize(("basename", "factory"), THEORETICAL_LISTS)
class TestTheoreticalListRecencyWindow:
    def test_current_year_rows_survive_in_early_january(
        self, api_client, tenant, basename, factory
    ):
        """In ISO weeks 1-2 the cutoff sits in the previous year, so a window
        pinned to the cutoff year alone hides the whole current year."""
        # All three rows hang off ONE ShareContent: a fresh one per row builds a
        # fresh SharesDeliveryDay too, and two open days on the same weekday
        # violate ``sharesdeliveryday_one_open_per_day_number``.
        share_content = ShareContentFactory()
        current = factory(year=2027, delivery_week=1, share_content=share_content)
        at_cutoff = factory(year=2026, delivery_week=52, share_content=share_content)
        before_cutoff = factory(
            year=2026, delivery_week=20, share_content=share_content
        )

        resp = api_client.get(reverse(f"{basename}-list"))

        assert resp.status_code == status.HTTP_200_OK
        ids = _row_ids(resp)
        assert current.id in ids
        assert at_cutoff.id in ids
        assert before_cutoff.id not in ids

    def test_a_future_year_stays_out_of_the_default_window(
        self, api_client, tenant, basename, factory
    ):
        """The window stops at today's year: planning rows are built per Share
        and roll into next year, and this list is unpaginated by default."""
        share_content = ShareContentFactory()
        current = factory(year=2027, delivery_week=1, share_content=share_content)
        next_year = factory(year=2028, delivery_week=10, share_content=share_content)

        resp = api_client.get(reverse(f"{basename}-list"))

        assert resp.status_code == status.HTTP_200_OK
        ids = _row_ids(resp)
        assert current.id in ids
        assert next_year.id not in ids

    def test_detail_route_reaches_a_row_outside_the_window(
        self, api_client, tenant, basename, factory
    ):
        """The window trims the list payload; it must not make an older row
        unreachable for read/edit/delete."""
        before_cutoff = factory(year=2026, delivery_week=20)

        resp = api_client.get(reverse(f"{basename}-detail", args=[before_cutoff.id]))

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == before_cutoff.id

    def test_an_explicit_past_year_is_not_narrowed(
        self, api_client, tenant, basename, factory
    ):
        before_cutoff = factory(year=2026, delivery_week=20)

        resp = api_client.get(reverse(f"{basename}-list"), {"year": 2026})

        assert resp.status_code == status.HTTP_200_OK
        assert before_cutoff.id in _row_ids(resp)
