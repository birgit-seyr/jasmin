"""Row locks for a write to an existing order line.

A write that changes an order line's amount moves its offer's stock
(``Offer.amount``) by the difference to the stored amount, so it reads that
amount under the line's row lock. Two writes of one line that both read it
before either commits, a double save on the orders grid say, would otherwise
both move the stock by the full difference, and a write that read a line
deleted in the meantime would save it back.

Every path that locks an offer and one of its lines takes the offer first, so
two writes never wait on each other the other way round: creating a line locks
its offer before the line exists, and the locks here follow the same order.
"""

from __future__ import annotations

from django.db import transaction
from django.db.transaction import TransactionManagementError

from ..errors import OrderContentChanged
from ..models import Offer, OrderContent

# How many times a write looks up its line's offer before it gives up. A retry
# follows only when another write moved the line to another offer between the
# lookup and the lock, so a few attempts cover any real interleaving.
_LOCK_ATTEMPTS = 3


def _stored_offer_id(order_content_id: str) -> str | None:
    """The offer of the stored line, read without a lock. Raises
    ``OrderContent.DoesNotExist`` when there is no such line."""
    return (
        OrderContent.objects.filter(id=order_content_id)
        .values_list("offer_id", flat=True)
        .get()
    )


def lock_order_content(order_content_id: str) -> OrderContent:
    """Lock the order line ``order_content_id`` and its offer, the offer first,
    and return the line as read under the lock, its ``offer`` the locked row.

    The offer comes from a read of the line without a lock, so another write
    can move the line to another offer before the line is locked. That attempt
    then rolls back to its savepoint, which releases both locks, and starts
    over with the line's new offer: waiting for that offer while holding the
    line would take the two locks the other way round.

    Raises ``OrderContent.DoesNotExist`` when there is no such line, also when
    another write deleted it before it was locked, and ``OrderContentChanged``
    when the line moved on every attempt. The locks last until the caller's
    transaction ends, so the caller must run in one.
    """
    if transaction.get_autocommit():
        raise TransactionManagementError(
            "lock_order_content() must run inside a transaction."
        )
    for _attempt in range(_LOCK_ATTEMPTS):
        offer_id = _stored_offer_id(order_content_id)
        with transaction.atomic():
            offer = (
                Offer.objects.select_for_update().filter(pk=offer_id).first()
                if offer_id is not None
                else None
            )
            order_content = OrderContent.objects.select_for_update().get(
                id=order_content_id
            )
            if order_content.offer_id == (offer.pk if offer is not None else None):
                order_content.offer = offer
                return order_content
            transaction.set_rollback(True)
    raise OrderContentChanged(
        "The order line moved to another offer while it was being saved.",
        details={"order_content_id": order_content_id},
    )
