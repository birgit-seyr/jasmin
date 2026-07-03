from django.db import models

from .base import JasminModel
from .mixin import CreatedMixin


class OfferSending(JasminModel, CreatedMixin):
    """One row per bulk-send of an OfferGroup × (year, delivery_week)
    to a reseller.

    The unit of work for a "send offers" action is the WHOLE OfferGroup
    for a specific (year, delivery_week) — not a single Offer. Within
    that group there are many Offer rows (one per share article); the
    outgoing email packs them all into one table. So the composite key
    ``(offer_group, year, delivery_week, reseller)`` is the right
    identity for "we sent THIS particular thing to this reseller".

    Previously this model held a single ``offer`` FK populated via
    ``offers.first()`` in offer_service.py — see P1-2 in
    docs/code/email-overview.md for the migration rationale.

    The unique constraint enforces idempotency at the DB layer: a
    second send to the same composite key will raise IntegrityError
    instead of silently creating a duplicate audit row. The service
    pre-checks with ``.exists()`` to give a clean per-reseller skip
    in the bulk-send response; the DB constraint catches everything
    else (raw SQL, future contributors, races).
    """

    offer_group = models.ForeignKey(
        "OfferGroup",
        on_delete=models.CASCADE,
        related_name="+",
    )
    year = models.PositiveSmallIntegerField()
    delivery_week = models.PositiveSmallIntegerField()
    reseller = models.ForeignKey(
        "Reseller",
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["offer_group", "year", "delivery_week", "reseller"],
                name="offersending_unique_composite_key",
            ),
        ]


class ReminderSending(JasminModel, CreatedMixin):
    """Idempotency + audit record: one row per ``(reseller, day)`` that received
    a bulk invoice-payment reminder.

    EML-3: the bulk reminder send is consolidated per reseller (one email listing
    all their overdue invoices). Without a dedup record, a retry after a 'failed'
    job — or a re-click — re-sends dunning to every reseller already served. The
    composite-unique ``(reseller, sent_on)`` makes a same-day re-run SKIP those
    resellers (the service pre-checks for a clean skip; the DB constraint catches
    races / raw SQL). A genuinely new reminder on a later day has a different
    ``sent_on`` and is allowed — mirrors :class:`OfferSending`'s idempotency.

    ``sent_on`` is a DATE (not ``created_at``): a unique on the full timestamp
    would never collide and so provide no dedup at all.
    """

    reseller = models.ForeignKey(
        "Reseller",
        on_delete=models.CASCADE,
        related_name="+",
    )
    sent_on = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reseller", "sent_on"],
                name="remindersending_unique_reseller_day",
            ),
        ]
