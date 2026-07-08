"""Guard: an additional share ("Zusatz") requires a co-timed base share.

An additional ``share_type_variation`` (its ``ShareType.is_additional_share_type``
is True) is physically packed INTO a base box, so a member may only subscribe to
one while they already hold a non-additional (base) share that is active over the
additional share's whole period. Enforced at subscription create + draft update.
"""

from __future__ import annotations

import datetime

from ..errors import AdditionalShareExceedsBase, AdditionalShareRequiresBase
from ..models import ShareTypeVariation, Subscription


def _effective_end(subscription: Subscription) -> datetime.date | None:
    """The base's real coverage end: its ``valid_until``, pulled back to
    ``cancelled_effective_at`` when the base has been cancelled — cancellation
    leaves ``valid_until`` untouched, so the effective end is the earlier of the
    two. ``None`` means open-ended (covers everything)."""
    ends = [
        end
        for end in (subscription.valid_until, subscription.cancelled_effective_at)
        if end is not None
    ]
    return min(ends) if ends else None


def assert_additional_share_has_base(
    *,
    member_id,
    share_type_variation_id,
    valid_from: datetime.date | None,
    valid_until: datetime.date | None,
) -> None:
    """Raise if this (would-be) subscription is an additional share without a
    base share covering its period.

    - No base active at ``valid_from`` → :class:`AdditionalShareRequiresBase`.
    - A base covers the start but ends before ``valid_until`` →
      :class:`AdditionalShareExceedsBase`, carrying the base's effective end as
      the suggested ``valid_until``.

    No-op for base (non-additional) shares, or when the variation / ``valid_from``
    can't be resolved (other validation rejects those first).
    """
    if not share_type_variation_id or valid_from is None:
        return
    variation = (
        ShareTypeVariation.objects.select_related("share_type")
        .filter(id=share_type_variation_id)
        .first()
    )
    if variation is None or not variation.share_type.is_additional_share_type:
        return

    # The member's base (non-additional) subscriptions that might cover this
    # add-on: not rejected, starting on/before the add-on's start. A member has
    # only a handful, so the effective-end refinement runs in Python.
    candidate_bases = Subscription.objects.filter(
        member_id=member_id,
        share_type_variation__share_type__is_additional_share_type=False,
        admin_rejected_at__isnull=True,
        valid_from__lte=valid_from,
    )

    covering_ends: list[datetime.date] = []
    for base in candidate_bases:
        end = _effective_end(base)
        if end is None:
            # An open-ended base covers the whole add-on period.
            return
        if end >= valid_from:
            covering_ends.append(end)

    if not covering_ends:
        raise AdditionalShareRequiresBase(share_type_variation_id=variation.id)

    if valid_until is not None and max(covering_ends) < valid_until:
        raise AdditionalShareExceedsBase(suggested_valid_until=max(covering_ends))
