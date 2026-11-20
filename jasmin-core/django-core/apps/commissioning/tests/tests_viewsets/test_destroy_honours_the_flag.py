"""Every routed DELETE whose serializer reports ``can_be_deleted`` refuses what
the flag refuses.

The frontend hides a row's delete button by the flag, so a viewset whose
DELETE ignores it lets a direct request delete — and cascade over — what the
page never offers. ``CanBeDeletedDestroyMixin`` closes that by calling the flag
itself; a viewset whose own ``destroy`` stands in is listed in ``OWN_DESTROY``
with the reason. The register fails in both directions: a flagged DELETE that
neither takes the mixin nor is listed, and an entry that has since taken the
mixin or no longer routes a flagged DELETE.
"""

from __future__ import annotations

from django.urls import get_resolver

from apps.commissioning.viewsets.base_viewsets import CanBeDeletedDestroyMixin

URLCONFS = ("config.tenant_urls", "config.public_urls")

OWN_DESTROY = {
    "SubscriptionViewSet": "refuses a confirmed subscription, the one case "
    "its flag reports",
    "OfferViewSet": "the delete and the flag both ask offer_deletion_blocker",
    "ConsentDocumentViewSet": "only PROTECT relations point at it, and destroy "
    "turns their ProtectedError into ConsentDocumentInUse",
    "ResellerViewSet": "a delete drops one of two roles; the service applies "
    "the flag's rule before it deletes the row",
    "DeliveryStationViewSet": "the service applies the flag's rule, then "
    "removes the contact the station leaves orphaned",
}


def _routed_patterns():
    def walk(resolver):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern)
            else:
                yield pattern

    for urlconf in URLCONFS:
        yield from walk(get_resolver(urlconf))


def _reports_the_flag(view_class: type) -> bool:
    serializer_class = getattr(view_class, "serializer_class", None)
    return isinstance(serializer_class, type) and hasattr(
        serializer_class, "get_can_be_deleted"
    )


def _routed_deletes() -> dict[str, type]:
    """The viewsets that route a DELETE, by class name."""
    found: dict[str, type] = {}
    for pattern in _routed_patterns():
        view_class = getattr(pattern.callback, "cls", None)
        actions = getattr(pattern.callback, "actions", None) or {}
        if view_class is None or "delete" not in actions:
            continue
        if "delete" in view_class.http_method_names:
            found[view_class.__name__] = view_class
    return found


def _flagged_deletes() -> dict[str, type]:
    """The routed DELETEs whose serializer reports ``can_be_deleted``."""
    return {
        name: view_class
        for name, view_class in _routed_deletes().items()
        if _reports_the_flag(view_class)
    }


def test_every_flagged_delete_honours_the_flag():
    unguarded = sorted(
        name
        for name, view_class in _flagged_deletes().items()
        if not issubclass(view_class, CanBeDeletedDestroyMixin)
        and name not in OWN_DESTROY
    )

    assert unguarded == [], (
        "These DELETEs ignore the can_be_deleted flag their list reports. Add "
        "CanBeDeletedDestroyMixin with a not_deletable_error, or list the "
        f"viewset in OWN_DESTROY with the reason its destroy stands in: "
        f"{unguarded}"
    )


def test_every_own_destroy_entry_is_still_needed():
    flagged = _flagged_deletes()
    stale = sorted(
        name
        for name in OWN_DESTROY
        if name not in flagged or issubclass(flagged[name], CanBeDeletedDestroyMixin)
    )

    assert stale == [], (
        "These OWN_DESTROY entries no longer route a flagged DELETE without the "
        f"mixin; remove them: {stale}"
    )


def test_every_mixin_user_has_a_flag_and_an_error():
    incomplete = sorted(
        name
        for name, view_class in _routed_deletes().items()
        if issubclass(view_class, CanBeDeletedDestroyMixin)
        and not (
            _reports_the_flag(view_class) and hasattr(view_class, "not_deletable_error")
        )
    )

    assert incomplete == [], (
        "These viewsets take CanBeDeletedDestroyMixin without a serializer that "
        f"reports can_be_deleted or without a not_deletable_error: {incomplete}"
    )
