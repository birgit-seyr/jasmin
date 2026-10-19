"""Writes of one order line move its offer's stock exactly once.

``update_order_content`` and ``delete_order_content`` read the line's amount
under the line's row lock, taken after its offer's
(``services/order_content_locks.lock_order_content``). Two writes of one line
that both read it before either commits, a double save on the orders grid say,
then see each other's result instead of both moving the offer's stock by the
full difference.

The race tests run the second write in a thread of its own, so it commits in
its own transaction, and ``transaction=True`` lets the threads see each other's
committed rows. A hook on the offer lock runs that second write to its commit
after the first write has read the line and before it holds any lock: the
interleaving a double save produces, made deterministic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.db import DatabaseError, connection, connections, transaction
from django.db.transaction import TransactionManagementError
from django.test.utils import CaptureQueriesContext

from apps.commissioning.errors import OrderContentChanged, OrderContentNotFound
from apps.commissioning.models import (
    Offer,
    OfferGroup,
    Order,
    OrderContent,
    ShareArticle,
)
from apps.commissioning.services import order_content_locks
from apps.commissioning.services.order_content_locks import lock_order_content
from apps.commissioning.services.order_content_service import OrderContentService
from apps.commissioning.tests.factories import (
    OfferFactory,
    OrderContentFactory,
    OrderFactory,
)

# The rebuild of a line's harvest and storage movements has nothing to do with
# its offer's stock, and needs storages these tests don't set up.
_RECOMPUTE = "apps.commissioning.services.recompute.recompute_order_contents"
_STORED_OFFER_ID = "apps.commissioning.services.order_content_locks._stored_offer_id"


def _locked_tables(captured: CaptureQueriesContext) -> list[str]:
    """The offer and order-line tables, in the order their rows were locked."""
    tables = []
    for query in captured.captured_queries:
        if "FOR UPDATE" not in query["sql"]:
            continue
        for table in ("commissioning_offer", "commissioning_ordercontent"):
            if f'FROM "{table}"' in query["sql"]:
                tables.append(table)
    return tables


@pytest.mark.django_db
class TestLockOrder:
    """The offer is locked before the line, the order creating a line takes."""

    def test_a_save_locks_the_offer_before_the_line(self, tenant):
        offer = OfferFactory(amount=Decimal("90"))
        line = OrderContentFactory(
            offer=offer, share_article=None, amount=Decimal("10")
        )

        with patch(_RECOMPUTE), CaptureQueriesContext(connection) as captured:
            OrderContentService.update_order_content(
                order_content_id=line.pk, amount=Decimal("15")
            )

        assert _locked_tables(captured)[:2] == [
            "commissioning_offer",
            "commissioning_ordercontent",
        ]

    def test_a_delete_locks_the_offer_before_the_line(self, tenant):
        offer = OfferFactory(amount=Decimal("90"))
        line = OrderContentFactory(
            offer=offer, share_article=None, amount=Decimal("10")
        )

        with CaptureQueriesContext(connection) as captured:
            OrderContentService.delete_order_content(line.pk)

        assert _locked_tables(captured)[:2] == [
            "commissioning_offer",
            "commissioning_ordercontent",
        ]


@pytest.mark.django_db
class TestLockOrderContent:
    def test_returns_the_line_with_its_locked_offer(self, tenant):
        offer = OfferFactory(amount=Decimal("90"))
        line = OrderContentFactory(
            offer=offer, share_article=None, amount=Decimal("10")
        )
        # Another write takes stock after the line was loaded here.
        Offer.objects.filter(pk=offer.pk).update(amount=Decimal("70"))

        locked = lock_order_content(line.pk)

        assert locked.pk == line.pk
        assert locked.offer is not None
        assert locked.offer.pk == offer.pk
        assert locked.offer.amount == Decimal("70")

    def test_a_line_without_an_offer_locks_the_line_alone(self, tenant):
        line = OrderContentFactory(amount=Decimal("10"))

        with CaptureQueriesContext(connection) as captured:
            locked = lock_order_content(line.pk)

        assert locked.pk == line.pk
        assert locked.offer is None
        assert _locked_tables(captured) == ["commissioning_ordercontent"]

    def test_a_line_moved_to_another_offer_is_locked_with_that_offer(self, tenant):
        offer = OfferFactory(amount=Decimal("90"))
        other_offer = OfferFactory(amount=Decimal("50"))
        line = OrderContentFactory(
            offer=other_offer, share_article=None, amount=Decimal("10")
        )

        # The first read still finds the line on ``offer``, as when another
        # write moved it after that read.
        with patch(
            _STORED_OFFER_ID, side_effect=[offer.pk, other_offer.pk]
        ) as stored_offer_id:
            locked = lock_order_content(line.pk)

        assert locked.offer is not None
        assert locked.offer.pk == other_offer.pk
        assert stored_offer_id.call_count == 2

    def test_gives_up_when_the_line_moves_on_every_attempt(self, tenant):
        offer = OfferFactory(amount=Decimal("90"))
        other_offer = OfferFactory(amount=Decimal("50"))
        line = OrderContentFactory(
            offer=other_offer, share_article=None, amount=Decimal("10")
        )

        with (
            patch(_STORED_OFFER_ID, return_value=offer.pk) as stored_offer_id,
            pytest.raises(OrderContentChanged),
        ):
            lock_order_content(line.pk)

        assert stored_offer_id.call_count == order_content_locks._LOCK_ATTEMPTS

    def test_a_missing_line_raises_does_not_exist(self, tenant):
        with pytest.raises(OrderContent.DoesNotExist):
            lock_order_content("no-such-line")

    def test_refuses_to_run_outside_a_transaction(self, tenant):
        line = OrderContentFactory(amount=Decimal("10"))

        with (
            patch.object(
                order_content_locks.transaction, "get_autocommit", return_value=True
            ),
            pytest.raises(TransactionManagementError),
        ):
            lock_order_content(line.pk)


# --------------------------------------------------------------------------- #
# Races between real transactions                                              #
# --------------------------------------------------------------------------- #


@dataclass
class _CommittedLine:
    line: OrderContent
    offer: Offer
    other_offer: Offer


def _in_own_connection(schema_name: str, write: Callable[[], Any]) -> Any:
    """Run ``write`` on this thread's own connection in the tenant schema.

    Closes the thread's connections afterwards, so none outlives the test.
    """
    from django_tenants.utils import schema_context

    try:
        with schema_context(schema_name):
            return write()
    finally:
        for thread_connection in connections.all():
            thread_connection.close()


def _in_other_thread(schema_name: str, write: Callable[[], Any]) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_in_own_connection, schema_name, write).result(timeout=30)


@contextmanager
def _runs_before_the_first_offer_lock(
    schema_name: str, second_write: Callable[[], Any]
) -> Iterator[None]:
    """Run ``second_write`` to its commit in another thread when a write is
    about to lock an offer for the first time. That write has read the line by
    then and holds no lock yet, so the second write can finish first."""
    select_for_update = Offer.objects.select_for_update
    fired = threading.Event()

    def second_write_first(*args: Any, **kwargs: Any) -> Any:
        if not fired.is_set():
            fired.set()
            _in_other_thread(schema_name, second_write)
        return select_for_update(*args, **kwargs)

    with patch.object(
        Offer.objects, "select_for_update", side_effect=second_write_first
    ):
        yield
    assert fired.is_set(), "no write locked an offer"


def _offer_lock_is_free(offer_pk: str) -> bool:
    """Whether this connection can lock the offer without waiting."""
    try:
        with transaction.atomic():
            Offer.objects.select_for_update(nowait=True).filter(pk=offer_pk).first()
    except DatabaseError:
        return False
    return True


def _save(line_pk: str, amount: str, **fields: Any) -> Callable[[], Any]:
    return lambda: OrderContentService.update_order_content(
        order_content_id=line_pk, amount=Decimal(amount), **fields
    )


def _delete(line_pk: str) -> Callable[[], Any]:
    return lambda: OrderContentService.delete_order_content(line_pk)


@pytest.mark.django_db(transaction=True)
class TestConcurrentWritesOfOneLine:
    """Each test starts from a committed line of 10 PU whose offer has 90 PU
    left, so offer and line together hold 100 PU."""

    @pytest.fixture(autouse=True)
    def _without_goods_flow_rebuild(self) -> Iterator[None]:
        with patch(_RECOMPUTE):
            yield

    @pytest.fixture()
    def committed(self, tenant) -> Iterator[_CommittedLine]:
        offer = OfferFactory(amount=Decimal("90"))
        other_offer = OfferFactory(amount=Decimal("50"))
        order = OrderFactory()
        line = OrderContentFactory(
            order=order, offer=offer, share_article=None, amount=Decimal("10")
        )
        # A second line keeps the order when the first one goes.
        second_line = OrderContentFactory(order=order, amount=Decimal("1"))
        yield _CommittedLine(line=line, offer=offer, other_offer=other_offer)

        # ``transaction=True`` leaves committed rows in the shared schema.
        reseller = order.reseller
        offers = [offer, other_offer]
        OrderContent.objects.filter(order__reseller=reseller).delete()
        Order.objects.filter(reseller=reseller).delete()
        Offer.objects.filter(pk__in=[o.pk for o in offers]).delete()
        OfferGroup.objects.filter(pk__in=[o.offer_group_id for o in offers]).delete()
        ShareArticle.objects.filter(
            pk__in=[o.share_article_id for o in offers] + [second_line.share_article_id]
        ).delete()
        contact = reseller.contact
        reseller.delete()
        contact.delete()

    def _stock(self, committed: _CommittedLine) -> tuple[Decimal, Decimal | None]:
        """The offer's stock and the line's amount, or ``None`` once it's gone."""
        committed.offer.refresh_from_db()
        line = OrderContent.objects.filter(pk=committed.line.pk).first()
        return committed.offer.amount, (line.amount if line else None)

    def test_two_saves_of_one_line_take_its_stock_once(self, committed, tenant):
        line_pk = committed.line.pk

        with _runs_before_the_first_offer_lock(
            tenant.schema_name, _save(line_pk, "15")
        ):
            _save(line_pk, "15")()

        assert self._stock(committed) == (Decimal("85"), Decimal("15"))

    def test_two_deletes_of_one_line_give_its_stock_back_once(self, committed, tenant):
        line_pk = committed.line.pk

        with (
            _runs_before_the_first_offer_lock(tenant.schema_name, _delete(line_pk)),
            pytest.raises(OrderContentNotFound),
        ):
            _delete(line_pk)()

        assert self._stock(committed) == (Decimal("100"), None)

    def test_a_save_after_a_concurrent_delete_does_not_bring_the_line_back(
        self, committed, tenant
    ):
        line_pk = committed.line.pk

        with (
            _runs_before_the_first_offer_lock(tenant.schema_name, _delete(line_pk)),
            pytest.raises(OrderContentNotFound),
        ):
            _save(line_pk, "15")()

        assert self._stock(committed) == (Decimal("100"), None)

    def test_a_delete_after_a_concurrent_save_gives_back_the_saved_amount(
        self, committed, tenant
    ):
        line_pk = committed.line.pk

        with _runs_before_the_first_offer_lock(
            tenant.schema_name, _save(line_pk, "15")
        ):
            _delete(line_pk)()

        assert self._stock(committed) == (Decimal("100"), None)

    def test_a_save_after_the_line_moved_takes_its_new_offers_stock(
        self, committed, tenant
    ):
        line_pk = committed.line.pk
        other_offer = committed.other_offer
        move_to_other_offer = _save(line_pk, "10", offer=other_offer)

        with _runs_before_the_first_offer_lock(tenant.schema_name, move_to_other_offer):
            _save(line_pk, "15")()

        line = OrderContent.objects.get(pk=line_pk)
        other_offer.refresh_from_db()
        assert line.offer_id == other_offer.pk
        assert line.amount == Decimal("15")
        assert other_offer.amount == Decimal("45")
        assert self._stock(committed) == (Decimal("90"), Decimal("15"))

    def test_an_attempt_on_a_stale_offer_gives_that_offers_lock_back(
        self, committed, tenant
    ):
        offer, other_offer = committed.offer, committed.other_offer
        OrderContent.objects.filter(pk=committed.line.pk).update(offer=other_offer)

        with transaction.atomic():
            with patch(_STORED_OFFER_ID, side_effect=[offer.pk, other_offer.pk]):
                locked = lock_order_content(committed.line.pk)
            stale_offer_free = _in_other_thread(
                tenant.schema_name, lambda: _offer_lock_is_free(offer.pk)
            )
            line_offer_free = _in_other_thread(
                tenant.schema_name, lambda: _offer_lock_is_free(other_offer.pk)
            )

        assert locked.offer_id == other_offer.pk
        assert stale_offer_free is True
        assert line_offer_free is False

    def test_concurrent_saves_and_a_delete_keep_the_stock_whole(
        self, committed, tenant
    ):
        line_pk = committed.line.pk
        writes = [_save(line_pk, amount) for amount in ("11", "12", "13", "14")]
        writes.append(_delete(line_pk))
        start = threading.Barrier(len(writes))

        def run(write: Callable[[], Any]) -> str:
            def at_once() -> str:
                start.wait(timeout=30)
                try:
                    write()
                except OrderContentNotFound:
                    return "line gone"
                return "written"

            return _in_own_connection(tenant.schema_name, at_once)

        # A rebuild that takes a moment keeps each write's transaction open
        # while the others have read the line and wait for its offer.
        with (
            patch(_RECOMPUTE, side_effect=lambda ids: time.sleep(0.05)),
            ThreadPoolExecutor(max_workers=len(writes)) as pool,
        ):
            outcomes = list(pool.map(run, writes, timeout=60))

        # Whichever order the writes took, the one delete removed the line and
        # gave back what it held then; the saves after it found no line.
        assert outcomes[-1] == "written"
        assert self._stock(committed) == (Decimal("100"), None)
