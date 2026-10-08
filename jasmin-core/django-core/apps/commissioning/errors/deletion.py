"""Errors refusing the deletion of a row that other rows still use."""

from __future__ import annotations

from core.errors import (
    ConflictError,
)

# --------------------------------------------------------------------------- #
# Deletion guards                                                             #
# --------------------------------------------------------------------------- #


class ShareTypeInUse(ConflictError):
    """A share type with variations, subscriptions or other rows still
    pointing at it cannot be deleted — the delete would cascade or fail on
    them (``can_be_deleted`` reports the same)."""

    code = "share_type.in_use"


class PlotInUse(ConflictError):
    """A plot still used by forecasts cannot be deleted: the delete would take
    them and their theoretical harvests with it."""

    code = "plot.in_use"


class StorageInUse(ConflictError):
    """A storage still used by forecasts or documentation rows cannot be
    deleted: the delete would take them with it."""

    code = "storage.in_use"


class ShareArticleInUse(ConflictError):
    """A share article still used by share contents, default-share entries or
    its price history cannot be deleted: the delete would take them with it."""

    code = "share_article.in_use"


class CrateInUse(ConflictError):
    """A crate still used by prices, offers or deliveries cannot be deleted:
    the delete would take its prices with it."""

    code = "crate.in_use"


class OrdersDeliveryDayInUse(ConflictError):
    """An order day still referenced elsewhere cannot be deleted."""

    code = "orders_delivery_day.in_use"


class DeliveryStationInUse(ConflictError):
    """A DeliveryStation cannot be deleted while any of its station-days still
    carry deliveries (the billing basis) — deleting would CASCADE-wipe those
    ShareDeliveries + Share history with no recompute / charge re-plan. Move or
    wind the deliveries down first."""

    code = "delivery_station.in_use"

    def __init__(self, *, station, delivery_count) -> None:
        super().__init__(
            f"Cannot delete station '{station}': {delivery_count} delivery/ies "
            "still reference its pickup days. Move or end them first.",
            details={"station": str(station), "delivery_count": delivery_count},
        )


class DeliveryStationDayInUse(ConflictError):
    """A DeliveryStationDay cannot be deleted while it still has deliveries —
    deleting would CASCADE-wipe those ShareDeliveries with no recompute."""

    code = "delivery_station_day.in_use"

    def __init__(self, *, station_day, delivery_count) -> None:
        super().__init__(
            f"Cannot delete pickup day '{station_day}': {delivery_count} "
            "delivery/ies still reference it. Move or end them first.",
            details={
                "station_day": str(station_day),
                "delivery_count": delivery_count,
            },
        )


class SharesDeliveryDayInUse(ConflictError):
    """A SharesDeliveryDay cannot be deleted while any Share references it —
    deleting would CASCADE-wipe whole historical weeks of Shares, their
    deliveries and ShareContents in one call."""

    code = "shares_delivery_day.in_use"

    def __init__(self, *, delivery_day, share_count) -> None:
        super().__init__(
            f"Cannot delete delivery day '{delivery_day}': {share_count} "
            "share(s) still reference it. It cannot be removed once used.",
            details={
                "delivery_day": str(delivery_day),
                "share_count": share_count,
            },
        )
