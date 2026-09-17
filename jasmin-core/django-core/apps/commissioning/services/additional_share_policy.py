"""Guard: an additional share ("Zusatz") requires a co-timed base share.

An additional ``share_type_variation`` (its ``ShareType.is_additional_share_type``
is True) is physically packed INTO a base box, so a member may only subscribe to
one while they already hold a non-additional (base) share that is active over the
additional share's whole period. Enforced at subscription create + draft update.
"""

from __future__ import annotations

import datetime
from typing import Any

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


def _as_id(value: Any) -> Any:
    """Normalise an FK input to its pk.

    The serializer sends ``member`` / ``share_type_variation`` as id strings,
    but the update path also accepts model instances (the setattr loop in
    ``update_draft_subscription`` assigns those straight to the FK). Both shapes
    have to compare like-for-like against the stored ``*_id``, and the pk is
    what may reach the rule's queryset: ``TapirModel.id`` is a ``CharField``, so
    filtering it by an instance stringifies the instance and silently matches
    nothing.
    """
    return getattr(value, "pk", value)


def assert_additional_share_has_base_on_update(
    subscription: Subscription,
    validated_data: dict[str, Any],
) -> None:
    """Apply the rule to a draft edit — but only when the edit MOVES one of the
    inputs the rule reads (member, variation, ``valid_from``, ``valid_until``).

    Clients PATCH whole rows back, so a field's presence in ``validated_data``
    carries no intent; only a value that differs from the stored one counts as a
    move. An edit that leaves all four where they are (a station change, a
    quantity fix) is therefore never held to account for the row's pre-existing
    state, which keeps an add-on whose base has gone missing repairable instead
    of delete-and-recreate. An edit that does move one of them is judged on the
    resulting values, so no write can introduce or re-assert a violation.
    """
    current: dict[str, Any] = {
        "member": subscription.member_id,
        "share_type_variation": subscription.share_type_variation_id,
        "valid_from": subscription.valid_from,
        "valid_until": subscription.valid_until,
    }
    resulting = {
        field: _as_id(validated_data[field]) if field in validated_data else stored
        for field, stored in current.items()
    }
    if resulting == current:
        return

    assert_additional_share_has_base(
        member_id=resulting["member"],
        share_type_variation_id=resulting["share_type_variation"],
        valid_from=resulting["valid_from"],
        valid_until=resulting["valid_until"],
    )
