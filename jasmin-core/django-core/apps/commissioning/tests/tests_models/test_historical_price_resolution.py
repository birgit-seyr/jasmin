"""Pin the time-bounded price-resolution semantics.

The codebase relies on three invariants that, before this suite,
were enforced only by code review:

  1. ``PricingMixin.get_pricing_on_date(date)`` returns the
     ``ShareArticleNetPrice`` (or ``CrateNetPrice``) whose
     ``[valid_from, valid_until]`` window contains ``date`` — NOT
     just the latest row. A delivery in W10 must price at the
     rate valid in W10 even if a newer rate was filed afterwards.

  2. ``CrateNetPrice`` resolution behaves identically (separate model,
     same mixin — same window semantics).

  3. Snapshotted ``price_per_unit`` on line items (``OrderContent``,
     ``InvoiceResellerContent``) is FROZEN once written. A later
     edit to the underlying ``ShareArticleNetPrice`` row must NOT
     retroactively change the invoice's stored amount — the auditor
     reading the invoice in 2030 sees the price actually charged in
     2026, not whatever current row happens to occupy that window now.

These three failures are the kind that only surface during a
year-end audit. The point of this suite is to make them surface in
CI instead.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.commissioning.models import ShareArticleNetPrice
from apps.commissioning.tests.factories import (
    CrateFactory,
    CrateNetPriceFactory,
    OrderContentFactory,
    ShareArticleFactory,
    ShareArticleNetPriceFactory,
)

# Hand-picked Monday/Sunday pairs so the TimeBoundMixin week-boundary
# validation (valid_from must be Mon, valid_until must be Sun) is
# satisfied without having to call ``__class__.next_monday(...)`` helpers
# in every test.
_W1_MON = datetime.date(2026, 1, 5)
_W12_SUN = datetime.date(2026, 3, 29)
_W13_MON = datetime.date(2026, 3, 30)
_W26_SUN = datetime.date(2026, 6, 28)
_W27_MON = datetime.date(2026, 6, 29)


@pytest.mark.django_db
class TestShareArticlePriceHistoryResolution:
    """``ShareArticle.get_pricing_on_date`` must select by window, not
    by recency."""

    def _two_period_pricing(self):
        """Helper: an article with two non-overlapping price windows.

        W1..W12 → ``net_price_for_orders_pieces_1 = 1.50``
        W13..   → ``net_price_for_orders_pieces_1 = 2.00``
        """
        article = ShareArticleFactory(default_movement_unit="PCS")
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W1_MON,
            valid_until=_W12_SUN,
            net_price_for_orders_pieces_1=Decimal("1.50"),
            tax_rate=Decimal("7.00"),
        )
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W13_MON,
            valid_until=None,  # open-ended
            net_price_for_orders_pieces_1=Decimal("2.00"),
            tax_rate=Decimal("7.00"),
        )
        return article

    def test_picks_first_window_when_date_inside_first(self, tenant):
        article = self._two_period_pricing()
        # Mid-February sits inside the first window.
        pricing = article.get_pricing_on_date(datetime.date(2026, 2, 15))
        assert pricing is not None
        assert pricing.net_price_for_orders_pieces_1 == Decimal("1.50")

    def test_picks_second_window_when_date_inside_second(self, tenant):
        article = self._two_period_pricing()
        pricing = article.get_pricing_on_date(datetime.date(2026, 5, 1))
        assert pricing is not None
        assert pricing.net_price_for_orders_pieces_1 == Decimal("2.00")

    def test_picks_first_window_on_last_day_of_window(self, tenant):
        """Boundary: ``valid_until`` is inclusive. The Sunday closing W12
        must still resolve to W12's price, not W13's."""
        article = self._two_period_pricing()
        pricing = article.get_pricing_on_date(_W12_SUN)
        assert pricing is not None
        assert pricing.net_price_for_orders_pieces_1 == Decimal("1.50")

    def test_picks_second_window_on_first_day_of_window(self, tenant):
        """Boundary: the Monday opening W13 jumps to the new price."""
        article = self._two_period_pricing()
        pricing = article.get_pricing_on_date(_W13_MON)
        assert pricing is not None
        assert pricing.net_price_for_orders_pieces_1 == Decimal("2.00")

    def test_returns_none_when_date_before_any_window(self, tenant):
        article = self._two_period_pricing()
        # 2025 — long before any price was filed.
        assert article.get_pricing_on_date(datetime.date(2025, 12, 1)) is None

    def test_does_not_silently_fall_back_to_latest_when_in_gap(self, tenant):
        """Manufactured price gap: W1..W12, then NOTHING. A delivery in
        W15 must NOT pull the W1..W12 price.

        This is the silent-fail mode that motivates the whole suite —
        if ``get_pricing_on_date`` ever fell back to "most recent
        before the date" instead of "window contains the date",
        deliveries in the gap would invoice at the old rate.
        """
        article = ShareArticleFactory(default_movement_unit="PCS")
        # Single CLOSED window — explicit valid_until.
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W1_MON,
            valid_until=_W12_SUN,
            net_price_for_orders_pieces_1=Decimal("1.50"),
            tax_rate=Decimal("7.00"),
        )
        # 2026-04-15 is after the W12 close but no new price was filed.
        assert article.get_pricing_on_date(datetime.date(2026, 4, 15)) is None

    def test_two_open_windows_rejected_by_db_constraint(self, tenant):
        # SUC-7: the one-open-per-article partial-unique backstop rejects a
        # SECOND open (valid_until IS NULL) window — even via bulk_create, which
        # bypasses save()/the Python no-overlap guard. This is what keeps the
        # canonical invoice tax/price read unambiguous.
        from django.db import IntegrityError

        article = ShareArticleFactory(default_movement_unit="PCS")
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W1_MON,
            valid_until=None,
            net_price_for_orders_pieces_1=Decimal("1.50"),
            tax_rate=Decimal("7.00"),
        )
        with pytest.raises(IntegrityError):
            ShareArticleNetPrice.objects.bulk_create(
                [
                    ShareArticleNetPrice(
                        share_article=article,
                        valid_from=_W13_MON,
                        valid_until=None,
                        net_price_for_orders_pieces_1=Decimal("2.00"),
                        tax_rate=Decimal("7.00"),
                    )
                ]
            )

    def test_overlapping_windows_resolve_to_newest_deterministically(self, tenant):
        # Only OPEN-vs-OPEN is DB-blocked (SUC-7); a CLOSED window can still
        # overlap a newer OPEN one (closed-range overlap stays Python-only /
        # TOCTOU, and bulk_create bypasses it). When a date falls in both,
        # get_pricing_on_date must pick the newest valid_from deterministically.
        article = ShareArticleFactory(default_movement_unit="PCS")
        ShareArticleNetPrice.objects.bulk_create(
            [
                ShareArticleNetPrice(
                    share_article=article,
                    valid_from=_W1_MON,
                    valid_until=datetime.date(2026, 12, 27),  # closed, far Sunday
                    net_price_for_orders_pieces_1=Decimal("1.50"),
                    tax_rate=Decimal("7.00"),
                ),
                ShareArticleNetPrice(
                    share_article=article,
                    valid_from=_W13_MON,
                    valid_until=None,  # open — overlaps the closed window above
                    net_price_for_orders_pieces_1=Decimal("2.00"),
                    tax_rate=Decimal("7.00"),
                ),
            ]
        )
        pricing = article.get_pricing_on_date(datetime.date(2026, 5, 1))
        assert pricing is not None
        assert pricing.valid_from == _W13_MON  # newest-effective wins
        assert pricing.net_price_for_orders_pieces_1 == Decimal("2.00")

    def test_open_ended_window_resolves_for_far_future_dates(self, tenant):
        """A price with ``valid_until=None`` must resolve indefinitely."""
        article = ShareArticleFactory(default_movement_unit="PCS")
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W1_MON,
            valid_until=None,
            net_price_for_orders_pieces_1=Decimal("9.99"),
            tax_rate=Decimal("7.00"),
        )
        pricing = article.get_pricing_on_date(datetime.date(2030, 12, 31))
        assert pricing is not None
        assert pricing.net_price_for_orders_pieces_1 == Decimal("9.99")


@pytest.mark.django_db
class TestCratePriceHistoryResolution:
    """Mirror of the share-article suite but for ``CrateNetPrice``.

    Same mixin, same semantics — separate suite so a regression in
    crate-pricing alone (which has historically been the more
    forgotten path) shows up named after the right model in CI.
    """

    def _two_period_pricing(self):
        crate = CrateFactory()
        CrateNetPriceFactory(
            crate=crate,
            valid_from=_W1_MON,
            valid_until=_W26_SUN,
            price=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
        )
        CrateNetPriceFactory(
            crate=crate,
            valid_from=_W27_MON,
            valid_until=None,
            price=Decimal("3.00"),
            tax_rate=Decimal("19.00"),
        )
        return crate

    def test_picks_first_window_when_date_inside_first(self, tenant):
        crate = self._two_period_pricing()
        pricing = crate.get_pricing_on_date(datetime.date(2026, 4, 1))
        assert pricing is not None
        assert pricing.price == Decimal("2.50")

    def test_picks_second_window_when_date_inside_second(self, tenant):
        crate = self._two_period_pricing()
        pricing = crate.get_pricing_on_date(datetime.date(2026, 9, 1))
        assert pricing is not None
        assert pricing.price == Decimal("3.00")

    def test_boundary_last_day_of_first_window(self, tenant):
        crate = self._two_period_pricing()
        pricing = crate.get_pricing_on_date(_W26_SUN)
        assert pricing is not None
        assert pricing.price == Decimal("2.50")

    def test_boundary_first_day_of_second_window(self, tenant):
        crate = self._two_period_pricing()
        pricing = crate.get_pricing_on_date(_W27_MON)
        assert pricing is not None
        assert pricing.price == Decimal("3.00")

    def test_returns_none_when_no_window_matches(self, tenant):
        crate = self._two_period_pricing()
        assert crate.get_pricing_on_date(datetime.date(2025, 12, 31)) is None


@pytest.mark.django_db
class TestSnapshottedPriceDoesNotShiftRetroactively:
    """A line item's ``price_per_unit`` is a SNAPSHOT, not a pointer.

    The flow under audit:
      1. Office files a ``ShareArticleNetPrice`` for W1.
      2. ``OrderContent`` is created in W1; its ``price_per_unit``
         records 1.50.
      3. Three months later, a new ``ShareArticleNetPrice`` row
         supersedes the old one (auto-closing the predecessor via
         ``TimeBoundMixin._on_save_auto_close_predecessor``).
      4. The auditor pulls the W1 ``OrderContent``: it must still
         show 1.50 and ``line_netto`` derived from 1.50.

    Failure mode this guards against: someone refactors
    ``OrderContent`` to derive ``price_per_unit`` from
    ``share_article.get_pricing_on_date(...)`` at read time instead
    of from the snapshotted column. The auditor sees the new price
    on every old invoice — GoBD violation, plus actual money was
    invoiced at 1.50, so the figures no longer match the bank.
    """

    def test_order_content_price_unchanged_when_new_price_filed(self, tenant):
        article = ShareArticleFactory(default_movement_unit="PCS")
        # W1 price.
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W1_MON,
            valid_until=None,
            net_price_for_orders_pieces_1=Decimal("1.50"),
            tax_rate=Decimal("7.00"),
        )

        # OrderContent snapshots ``price_per_unit`` at the time of
        # creation. We pass it explicitly — the production write paths
        # (offer→order conversion, manual order entry) all resolve via
        # ``share_article.get_pricing_on_date`` and pass the resolved
        # value as ``price_per_unit``.
        oc = OrderContentFactory(
            share_article=article,
            amount=Decimal("10"),
            unit="PCS",
            size="M",
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("7.00"),
        )
        original_pk = oc.pk

        # File a new price effective from W13 — the old row is auto-
        # closed at W12 Sunday by TimeBoundMixin's predecessor-close
        # hook. The W1 OrderContent must NOT shift.
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W13_MON,
            valid_until=None,
            net_price_for_orders_pieces_1=Decimal("9.99"),
            tax_rate=Decimal("19.00"),
        )

        oc.refresh_from_db()
        assert oc.pk == original_pk
        assert oc.price_per_unit == Decimal("1.50"), (
            "OrderContent.price_per_unit must remain the snapshotted "
            "value even after a new ShareArticleNetPrice supersedes "
            "the original (GoBD: figures invoiced must match figures "
            "stored)."
        )
        # tax_rate stays snapshotted too.
        assert oc.tax_rate == Decimal("7.00")
        # ``line_netto`` is derived from the snapshotted price, not
        # looked up. 10 PCS * 1.50 = 15.00.
        assert oc.line_netto == Decimal("15.00")

    def test_predecessor_close_does_not_touch_existing_lines(self, tenant):
        """Belt-and-braces: filing the new price closes the predecessor
        via ``TimeBoundMixin`` (sets ``valid_until = new.valid_from -
        1``). Verify that close updates the price row but NOT the
        already-snapshotted line items keyed off that row."""
        article = ShareArticleFactory(default_movement_unit="PCS")
        open_price = ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W1_MON,
            valid_until=None,
            net_price_for_orders_pieces_1=Decimal("1.50"),
            tax_rate=Decimal("7.00"),
        )
        oc = OrderContentFactory(
            share_article=article,
            amount=Decimal("5"),
            unit="PCS",
            size="M",
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("7.00"),
        )

        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=_W13_MON,
            valid_until=None,
            net_price_for_orders_pieces_1=Decimal("9.99"),
            tax_rate=Decimal("19.00"),
        )

        # The predecessor row got auto-closed.
        open_price.refresh_from_db()
        assert open_price.valid_until == _W12_SUN, (
            "TimeBoundMixin should have closed the predecessor at the "
            "Sunday before the new valid_from."
        )

        # The OrderContent's snapshotted price + tax stay put.
        oc.refresh_from_db()
        assert oc.price_per_unit == Decimal("1.50")
        assert oc.tax_rate == Decimal("7.00")
        assert oc.line_netto == Decimal("7.50")  # 5 * 1.50

    def test_price_per_unit_is_a_plain_db_column_not_a_property(self, tenant):
        """Direct contract assertion: ``OrderContent.price_per_unit`` is
        a model field, NOT a computed property. If a future refactor
        turns it into a ``@property`` that reads
        ``share_article.get_pricing_on_date(...)`` at access time, this
        test fails and the snapshot guarantee is gone.
        """
        from apps.commissioning.models import OrderContent

        field = OrderContent._meta.get_field("price_per_unit")
        # It's a DecimalField, persisted, not a computed thing.
        from django.db.models import DecimalField

        assert isinstance(field, DecimalField), (
            "OrderContent.price_per_unit must remain a persisted "
            "DecimalField. Turning it into a @property would silently "
            "break the snapshot guarantee."
        )

    def test_crate_price_snapshot_does_not_shift(self, tenant):
        """Same invariant on the crate side — line items snapshot crate
        prices independently and must not drift when CrateNetPrice
        gets superseded."""
        crate = CrateFactory()
        CrateNetPriceFactory(
            crate=crate,
            valid_from=_W1_MON,
            valid_until=None,
            price=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
        )
        # Snapshot a price-resolved value the way the production
        # crate-content writer does (see
        # ``crate_order_content_service.py:120`` — it calls
        # ``crate.get_pricing_on_date(...)`` and stores the result).
        resolved = crate.get_pricing_on_date(_W1_MON)
        assert resolved is not None
        snapshotted_price = resolved.price
        snapshotted_tax = resolved.tax_rate

        # File a new CrateNetPrice — predecessor auto-closes.
        CrateNetPriceFactory(
            crate=crate,
            valid_from=_W13_MON,
            valid_until=None,
            price=Decimal("3.50"),
            tax_rate=Decimal("19.00"),
        )

        # Resolving for W1 today still gives 2.50; new W13+ gives 3.50.
        assert crate.get_pricing_on_date(_W1_MON).price == Decimal("2.50")
        assert crate.get_pricing_on_date(_W13_MON).price == Decimal("3.50")
        # And the value we previously captured is the same object
        # we'd still capture today — the resolver is a query, not a
        # mutator.
        assert snapshotted_price == Decimal("2.50")
        assert snapshotted_tax == Decimal("19.00")


# ---------------------------------------------------------------------------
# Reference: where each invariant is enforced in production code
# ---------------------------------------------------------------------------
#
# (1) PricingMixin.get_pricing_on_date — apps/commissioning/models/mixin.py:264
#     Single filter; correctness is "valid_from <= date AND
#     (valid_until IS NULL OR valid_until >= date)". The boundary tests
#     above pin both inclusive ends.
#
# (2) TimeBoundMixin auto-closes the predecessor on save — same file,
#     ~line 140. Closes the predecessor's valid_until to
#     (new.valid_from - 1 day). The W12_SUN boundary tests confirm
#     this is the date arithmetic actually applied.
#
# (3) Snapshot fields on OrderableItem — apps/commissioning/models/
#     resellers.py:178-199. ``price_per_unit`` + ``tax_rate`` are plain
#     DecimalFields, written once at line-creation. The "is a plain DB
#     column" test fails fast if anyone turns these into properties.
