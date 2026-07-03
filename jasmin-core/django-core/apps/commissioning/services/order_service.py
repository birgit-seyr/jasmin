from __future__ import annotations

from django.db import transaction

from ..models import CrateOrderContent, Order
from .finalize_utils import finalize_children


class OrderService:
    """Service for managing orders."""

    @staticmethod
    @transaction.atomic
    def finalize_order(order: Order, user=None) -> bool:
        """
        Finalize an order and cascade to all order contents and crate order contents.
        """
        order.assert_not_finalized(label="Order", code="order.already_finalized")

        order.assign_final_number()
        order.save(update_fields=["number", "prefix"])

        success = order.finalize(user=user)
        if not success:
            return False

        finalize_children(
            order.ordercontent_set,
            order.crateordercontent_set,
            # Crates attached to an order_content (offer-bound lines) carry
            # order=NULL per the XOR constraint, so they are NOT in
            # order.crateordercontent_set — finalize them explicitly too, or a
            # finalized order's crate lines stay mutable/deletable.
            CrateOrderContent.objects.filter(order_content__order=order),
            user=user,
        )

        return True
