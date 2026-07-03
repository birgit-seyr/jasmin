from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)


def _expand_to_dependent_physical_shares(share_ids: set) -> set:
    """Expand a recompute set to include the PHYSICAL Shares fed by any VIRTUAL
    Share in it.

    A Share on a virtual variation has no ShareContent of its own; the demand a
    virtual delivery contributes is distributed onto its physical component
    variations (``VirtualVariationComponent.quantity``), so the ShareContent
    whose theoreticals/SHARECONTENT movements actually change lives on the
    PHYSICAL-variation Shares for the same (year, week, delivery_day). Recompute
    callers only pass the directly-edited share id (the virtual one), so without
    this expansion those dependent physical shares stay computed off the old
    virtual demand. No-op for tenants without virtual variations (one cheap
    indexed query that returns empty).
    """
    from django.db.models import Q

    from ..models import Share, VirtualVariationComponent

    virtual_shares = list(
        Share.objects.filter(
            id__in=share_ids, share_type_variation__variation_type="virtual"
        ).values("share_type_variation_id", "year", "delivery_week", "delivery_day_id")
    )
    if not virtual_shares:
        return share_ids

    virtual_variation_ids = {s["share_type_variation_id"] for s in virtual_shares}
    physical_by_virtual: dict = defaultdict(set)
    for component in VirtualVariationComponent.objects.filter(
        virtual_variation_id__in=virtual_variation_ids
    ).values("virtual_variation_id", "physical_variation_id"):
        physical_by_virtual[component["virtual_variation_id"]].add(
            component["physical_variation_id"]
        )
    if not physical_by_virtual:
        return share_ids

    # Match the dependent physical Shares at the SAME (year, week, day) as each
    # virtual share, for that virtual variation's component physical variations.
    match = Q()
    for s in virtual_shares:
        physical_ids = physical_by_virtual.get(s["share_type_variation_id"])
        if not physical_ids:
            continue
        match |= Q(
            year=s["year"],
            delivery_week=s["delivery_week"],
            delivery_day_id=s["delivery_day_id"],
            share_type_variation_id__in=physical_ids,
        )
    if not match:
        return share_ids

    physical_share_ids = set(Share.objects.filter(match).values_list("id", flat=True))
    return share_ids | physical_share_ids


def recompute_shares(
    share_ids: Iterable[Any],
    *,
    collect_movements: list | None = None,
) -> list[Any]:
    """Rebuild theoreticals + SHARECONTENT movements for the given Shares.

    Call this at the end of any service operation that:

    * created / updated / deleted a ``ShareContent``,
    * created / updated / deleted a ``ShareDelivery``,
    * updated a ``Forecast`` that any ``ShareContent`` is linked to.

    When a passed Share is on a VIRTUAL variation, the physical-variation Shares
    it feeds are recomputed too (see ``_expand_to_dependent_physical_shares``).

    Idempotent — calling it twice with the same ids just wastes a query.

    ``collect_movements``: for callers that run this INSIDE a transaction that
    also cascades other movements (e.g. a slot delete capturing old movements) —
    the recompute's own single union cascade is deferred into this list so the
    caller keeps the whole transaction at ONE sorted advisory-lock pass. See
    ``ShareContentService.recompute_for_shares``.

    Returns the touched ``ShareContent`` ids (from ``recompute_for_shares``) so
    callers can report what changed or invalidate caches.
    """
    ids = {share_id for share_id in share_ids if share_id is not None}
    if not ids:
        return []

    # Local imports to avoid an import cycle at app-load time.
    from .share_content_service import ShareContentService

    ids = _expand_to_dependent_physical_shares(ids)

    try:
        return ShareContentService().recompute_for_shares(
            ids, collect_movements=collect_movements
        )
    except Exception:
        logger.exception(
            "Recompute of theoreticals/movements failed for shares=%s",
            sorted(str(s) for s in ids),
        )
        raise


def recompute_order_contents(order_content_ids: Iterable[Any]) -> None:
    """Rebuild theoreticals + ORDERCONTENT movements for the given OrderContents.

    Call this at the end of any service operation that created / updated /
    deleted an ``OrderContent``. Mirrors ``recompute_shares`` but for the
    reseller (Order) chain.

    Wired into ``OrderContentService.create_order_with_content_and_crates``
    and ``update_order_content``; the delete path cascades inventories via
    ``SnapshotService`` instead. Covered by
    ``tests_services/test_order_content_signal_recompute.py``.
    """
    ids = {
        order_content_id
        for order_content_id in order_content_ids
        if order_content_id is not None
    }
    if not ids:
        return

    from ..models import OrderContent
    from .order_content_service import OrderContentService

    order_contents = list(OrderContent.objects.filter(id__in=ids))
    if not order_contents:
        return

    try:
        OrderContentService().recompute_for_order_contents(order_contents)
    except Exception:
        logger.exception(
            "Recompute of theoreticals/movements failed for order_contents=%s",
            sorted(str(o) for o in ids),
        )
        raise
