"""Shared helpers for the per-order bulk operations (delivery-note / invoice
creation + finalize, invoice reminders).

These were module-private helpers in
``apps.commissioning.views.reseller_views``, but the ``invoice_reminder``
service (run from a Huey task) reuses them — importing them from the view
inverted the service→view dependency direction and pulled the whole DRF
view module into a worker dispatch. Homing them in this neutral service-layer
module lets both the view and the service import them without the service
depending on the view layer.
"""

from __future__ import annotations

from typing import Any

from ..models import Order


def format_order_error(order: Order, error_msg: str) -> dict[str, Any]:
    """Standard per-order error row for a bulk response."""
    return {
        "order_id": str(order.id),
        "order_number": order.full_number,
        "error": error_msg,
        "success": False,
    }


def get_delivery_note_or_error(
    order: Order,
) -> tuple[Any, dict[str, Any] | None]:
    """Return ``(delivery_note, None)``, or ``(None, error_dict)`` when the
    order has no delivery note yet."""
    delivery_note = getattr(order, "delivery_note", None)
    if not delivery_note:
        return None, format_order_error(order, "No delivery note found for this order")
    return delivery_note, None
