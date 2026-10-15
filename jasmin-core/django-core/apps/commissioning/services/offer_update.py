"""The office's edit of an offer.

An offer's available amount (``Offer.amount``) is the stock its order lines
leave, and every order-line write moves it under the offer's row lock
(``order_content_locks``). An edit of the offer takes the same lock and saves
only the fields it changes, so it never writes back an amount read before
orders moved it, and a published offer, which lets only its amount change,
takes an edit of the amount alone.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import models, transaction

from ..errors import OfferAmountChanged
from ..models import Offer


def _differs(offer: Offer, name: str, value: Any) -> bool:
    field = offer._meta.get_field(name)
    if isinstance(field, models.ForeignKey):
        # By id: reading the related row would cost a query per foreign key.
        return getattr(offer, field.attname) != (
            value.pk if value is not None else None
        )
    stored = getattr(offer, name)
    if isinstance(stored, str) and isinstance(value, str):
        # The serializer strips the text it takes, so a stored value with
        # spaces around it comes back without them although nobody changed it.
        return stored.strip() != value
    return stored != value


@transaction.atomic
def update_offer(
    offer: Offer, values: dict[str, Any], *, expected_amount: Decimal | None
) -> None:
    """Save the fields of ``values``, an edit of ``offer``, that differ from the
    stored offer, read under its row lock. ``offer`` then holds the row as
    saved.

    ``amount`` is compare-and-set against ``expected_amount``, the amount the
    client read. An amount equal to it is no change, whatever orders did to the
    stock since. A different one is saved only while the stored amount still
    equals ``expected_amount``. Without ``expected_amount`` a change can't be
    told from stock that moved since, so only the stored amount goes through.
    Either refusal raises ``OfferAmountChanged`` and saves nothing.
    """
    stored = Offer.objects.select_for_update().get(pk=offer.pk)
    changes = {
        name: value
        for name, value in values.items()
        if name != "amount" and _differs(stored, name, value)
    }
    if "amount" in values:
        amount = values["amount"]
        read_amount = stored.amount if expected_amount is None else expected_amount
        if amount != read_amount:
            details = {"offer_id": str(stored.pk), "amount": str(stored.amount)}
            if expected_amount is None:
                # Such as a tab still running an older page, which sends the
                # amount it read along with no edit.
                raise OfferAmountChanged(
                    "This page is out of date. Reload it and enter the amount "
                    "again.",
                    details=details,
                )
            if stored.amount != expected_amount:
                raise OfferAmountChanged(
                    "The available amount of this offer has changed since it "
                    "was loaded. Reload the page and enter the amount again.",
                    details=details,
                )
            changes["amount"] = amount

    if changes:
        for name, value in changes.items():
            setattr(stored, name, value)
        stored.save(update_fields=list(changes))
    # Onto ``offer``, which carries the list's annotations and its related
    # rows: a fresh read of it would drop both.
    for field in Offer._meta.concrete_fields:
        setattr(offer, field.attname, getattr(stored, field.attname))
