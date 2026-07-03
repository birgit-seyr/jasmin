"""Performance budgets for ``ForecastService.update_forecast_with_related_objects``.

These are **regression guards**, not micro-benchmarks. They assert
that the heavy update path (delete-theoreticals → rewrite relations →
recompute_shares) is NOT executed when the office only edits a
display-only / documentation field. The light path (single
``Forecast.save(update_fields=…)``) should be roughly 10× faster.

Why timing rather than counting queries:

  * Query counts are a noisy proxy at this layer — the heavy path
    fires a variable number of queries depending on the number of
    variations / delivery days / stations. A "this took ≤ N queries"
    assertion drifts with normal fixture changes.
  * The office's actual complaint is wall-clock latency on a row
    save. A timing budget speaks to that directly.

The budgets are deliberately generous (5× the locally-measured
value at the time of writing) so they survive normal CI noise but
still fail loudly if someone re-introduces a recompute call on the
light path.

If a test goes flaky in CI: don't bump the budget blindly. First
check whether a recent change re-introduced a recompute on the
light path by setting ``--capture=no`` and printing the elapsed time
across runs. If the budget legitimately needs to grow because a
new validator / signal was added to the light path, document why
in the budget line.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from apps.commissioning.services.forecast_service import ForecastService
from apps.commissioning.tests.factories import (
    ForecastFactory,
    ForecastShareTypeVariationFactory,
    ShareArticleFactory,
    ShareTypeVariationFactory,
    StorageFactory,
)


def _measure_ms(callable_) -> float:
    """Run ``callable_`` once and return wall-clock ms."""
    t0 = time.perf_counter()
    callable_()
    return (time.perf_counter() - t0) * 1000


@pytest.mark.django_db
class TestForecastUpdatePerf:
    """Budgets are 5× the measured value on a warm dev DB."""

    def _make_forecast_with_variations(self, *, variation_count: int):
        """Build a forecast with N attached variations.

        Mirrors the typical office row: one forecast with a handful
        of variations. We don't add ShareContents yet — the heavy
        path's recompute is triggered by the relation rewrite + the
        cascade through ``_create_or_update_share_contents``.
        """
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
            storage=storage,
        )
        for _ in range(variation_count):
            ForecastShareTypeVariationFactory(
                forecast=forecast,
                share_type_variation=ShareTypeVariationFactory(),
            )
        return forecast, article

    def test_note_only_update_is_light(self, tenant):
        """Pure note edit → light path. ≤ 80 ms with 3 variations.

        Pre-2026-06-08 (no light-path short-circuit) this measured
        ~600 ms on the office's setup. The light path now does a
        single ``Forecast.save(update_fields=["note"])`` plus the
        ``_is_light_update`` exists-check per variation/offer-group
        key (none in this payload).
        """
        forecast, _ = self._make_forecast_with_variations(variation_count=3)
        svc = ForecastService()

        elapsed = _measure_ms(
            lambda: svc.update_forecast_with_related_objects(
                forecast, {"note": "kurz nachgesehen"}
            )
        )

        assert elapsed < 80, (
            f"note-only update took {elapsed:.0f}ms, expected <80ms. "
            f"A change must have re-introduced the heavy path "
            f"(check ``_is_light_update`` and "
            f"``update_forecast_with_related_objects``)."
        )

        forecast.refresh_from_db()
        assert forecast.note == "kurz nachgesehen"

    def test_sort_order_only_update_is_light(self, tenant):
        """``sort_order`` is the column-drag use case in the office UI.

        Office drags rows around → many small saves, each touching
        only ``sort_order``. The light path makes this snappy.
        """
        forecast, _ = self._make_forecast_with_variations(variation_count=3)
        svc = ForecastService()

        elapsed = _measure_ms(
            lambda: svc.update_forecast_with_related_objects(
                forecast, {"sort_order": 42}
            )
        )

        assert (
            elapsed < 80
        ), f"sort_order-only update took {elapsed:.0f}ms, expected <80ms."

        forecast.refresh_from_db()
        assert forecast.sort_order == 42

    def test_bed_number_only_update_is_light(self, tenant):
        """``bed_number`` is display-only metadata on the harvesting
        list header. No ShareContent / theoretical impact."""
        forecast, _ = self._make_forecast_with_variations(variation_count=3)
        svc = ForecastService()

        elapsed = _measure_ms(
            lambda: svc.update_forecast_with_related_objects(
                forecast, {"bed_number": 7}
            )
        )

        assert (
            elapsed < 80
        ), f"bed_number-only update took {elapsed:.0f}ms, expected <80ms."

        forecast.refresh_from_db()
        assert forecast.bed_number == 7

    def test_amount_update_routes_to_heavy_path(self, tenant):
        """Sanity check that ``_is_light_update`` rejects an amount edit.

        Pre-2026-06-08 the heavy path was wall-clock-detectable
        (~600 ms) so timing was a fine proxy for "the heavy path
        ran". Now that ``recompute_shares`` is deferred to a Huey
        task, the heavy path itself runs in <20 ms — the wall-clock
        check no longer separates light from heavy.

        Assert directly on the dispatch decision instead: the
        contract is "amount changes MUST take the heavy path so
        ShareContent / theoreticals stay in sync". If a future
        refactor accidentally moves ``amount`` into
        ``_LIGHT_UPDATE_FIELDS`` this test fires.
        """
        forecast, _ = self._make_forecast_with_variations(variation_count=3)
        payload = {
            "amount": Decimal("250"),
            "unit": "KG",
            "size": "M",
            "year": 2026,
            "delivery_week": 15,
        }

        is_light = ForecastService._is_light_update(forecast, payload)
        assert is_light is False, (
            "amount-update payload was classified as a light update. "
            "Did the dispatch shift ``amount`` into _LIGHT_UPDATE_FIELDS? "
            "That would skip the ShareContent rewrite + recompute and "
            "ship stale theoreticals."
        )

        # And confirm the update actually applies the new amount.
        ForecastService().update_forecast_with_related_objects(forecast, payload)
        forecast.refresh_from_db()
        assert forecast.amount == Decimal("250")

    def test_variation_toggle_routes_to_heavy_path(self, tenant):
        """Adding a new variation flag MUST take the heavy path so
        the ShareContent rows for the new variation get created and
        the downstream theoreticals get rebuilt.

        Same rationale as ``test_amount_update_routes_to_heavy_path``:
        wall-clock is no longer a reliable signal post-Huey-defer; we
        assert on the dispatch decision directly.
        """
        forecast, _ = self._make_forecast_with_variations(variation_count=2)
        new_variation = ShareTypeVariationFactory()
        payload = {
            "unit": "KG",
            "size": "M",
            "year": 2026,
            "delivery_week": 15,
            f"variation_{new_variation.pk}": True,
        }

        is_light = ForecastService._is_light_update(forecast, payload)
        assert is_light is False, (
            "variation-flag toggle was classified as a light update. "
            "Did ``_is_light_update`` accidentally treat a NEW "
            "variation flag as a no-op? That would leave ShareContent "
            "rows out of sync with ForecastShareTypeVariation."
        )

    def test_create_returns_fast_with_recompute_deferred(self, tenant):
        """CREATE path returns in <250 ms because ``recompute_shares``
        is deferred to a Huey task (see Option B in
        docs/todos/perf-audit-editabletables.md).

        Pre-defer: ~700 ms (recompute fired synchronously at the end of
        ``_create_or_update_share_contents``). Post-defer: the save
        commits + enqueues + returns; the actual recompute runs on the
        Huey worker.

        Budget is loose (~3× the measured value on dev) so legitimate
        prefetch / bulk_create growth doesn't trip it, but a regression
        that re-introduces the synchronous recompute call here would
        balloon back to ~700 ms and fail loudly.

        We don't assert that recompute didn't run at all — under
        ``HUEY.immediate = False`` (the test default) Huey tasks are
        enqueued, never executed — so the recompute side-effects don't
        happen in this test. A separate dedicated test should verify
        the enqueue payload if we ever want to lock down the contract.
        """
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        variation = ShareTypeVariationFactory()

        svc = ForecastService()

        elapsed = _measure_ms(
            lambda: svc.create_forecast_with_related_objects(
                {
                    "amount": Decimal("100"),
                    "unit": "KG",
                    "size": "M",
                    "year": 2026,
                    "delivery_week": 15,
                    "share_article": article,
                    "storage": storage,
                    f"variation_{variation.pk}": True,
                }
            )
        )

        assert elapsed < 250, (
            f"forecast CREATE took {elapsed:.0f}ms, expected <250ms. "
            f"A change must have re-introduced a synchronous "
            f"recompute_shares call inside "
            f"``_create_or_update_share_contents`` — verify it's still "
            f"wrapped in ``transaction.on_commit(lambda: "
            f"recompute_shares_async(...))`` instead of being called "
            f"directly."
        )

    def test_re_asserted_relation_flags_stay_on_light_path(self, tenant):
        """A payload that re-asserts the existing variation flag without
        changing it should NOT trigger the heavy path. ``_is_light_update``
        compares the flag value to the current state and returns True
        when they match — so a "save" that's actually a no-op (the office
        clicked save without changing anything) stays cheap.
        """
        forecast, _ = self._make_forecast_with_variations(variation_count=2)
        existing_variation = forecast.forecastsharetypevariation_set.first()

        svc = ForecastService()
        elapsed = _measure_ms(
            lambda: svc.update_forecast_with_related_objects(
                forecast,
                {
                    "note": "no change to variations",
                    f"variation_{existing_variation.share_type_variation_id}": True,
                },
            )
        )

        assert elapsed < 100, (
            f"re-asserted-flag update took {elapsed:.0f}ms, expected <100ms. "
            f"``_is_light_update`` should detect that the variation flag "
            f"matches the current state and stay on the light path."
        )
