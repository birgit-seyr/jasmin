"""General contract for TimeBoundMixin models re: the standalone-close hazard.

A direct PATCH that closes/shortens a TimeBound row's ``valid_until`` can strand
its future children — the create/succession path migrates them (or refuses while
they're active), but a bare close does not. So EVERY TimeBound model must be
classified here; a newly-added one fails this test until its author decides
whether it needs a close-guard. See the SharesDeliveryDay / DeliveryStationDay
``perform_update`` guards and the ShareType / ShareTypeVariation ``clean()``
guards for the two patterns.
"""

from __future__ import annotations

from django.apps import apps as django_apps

from apps.commissioning.models.mixin import TimeBoundMixin

# Every concrete TimeBoundMixin model, mapped to HOW it is protected against the
# standalone-close-strands-children hazard. Adding a TimeBound model without an
# entry here fails the test below — forcing an explicit decision.
_CLOSE_HAZARD_CLASSIFICATION = {
    # Guarded in the model's clean() shortening guard (its handle_succession
    # also refuses succession while children are active, so clean() is safe).
    "ShareType": "guarded_clean",
    "ShareTypeVariation": "guarded_clean",
    # Guarded in the viewset's perform_update — NOT clean(), because the create
    # path closes the predecessor via handle_succession→save()→clean() before
    # the child-migration runs, so a clean() guard would break succession.
    "SharesDeliveryDay": "guarded_viewset",
    "DeliveryStationDay": "guarded_viewset",
    "ConsentDocument": "guarded_viewset",  # ConsentDocumentInUse on edit/close
    # Immutable after confirm (SubscriptionConfirmedImmutable); the only close is
    # the dedicated cancel flow, which ends deliveries properly.
    "Subscription": "immutable_or_cancel_flow",
    # Nothing references these via FK → a close strands nothing.
    "Season": "no_strandable_children",
    "DeliveryExceptionPeriod": "no_strandable_children",
    # Price windows: downstream order/invoice lines SNAPSHOT the resolved value,
    # so they are not children that strand on close; one-open is DB-backstopped
    # (sharearticlenetprice/cratenetprice/...grossprice one_open constraints).
    "ShareArticleNetPrice": "snapshot_no_stranding",
    "CrateNetPrice": "snapshot_no_stranding",
    "ShareTypeVariationGrossPrice": "snapshot_no_stranding",
}

_VALID_BUCKETS = {
    "guarded_clean",
    "guarded_viewset",
    "immutable_or_cancel_flow",
    "no_writable_endpoint",
    "no_strandable_children",
    "snapshot_no_stranding",
}


def _concrete_timebound_models():
    return [
        model
        for model in django_apps.get_models()
        if issubclass(model, TimeBoundMixin) and not model._meta.abstract
    ]


def test_every_timebound_model_is_classified_for_close_hazard():
    """Drift guard: a new TimeBound model must declare how it handles a
    standalone close (and add a guard if it can strand children)."""
    names = {model.__name__ for model in _concrete_timebound_models()}

    unclassified = names - set(_CLOSE_HAZARD_CLASSIFICATION)
    assert not unclassified, (
        f"New TimeBoundMixin model(s) {sorted(unclassified)} are not classified "
        "for the standalone-close-strands-children hazard. Decide whether a "
        "direct PATCH that closes/shortens valid_until can strand children; if "
        "so add a perform_update guard (see SharesDeliveryDay / "
        "DeliveryStationDay), then record the bucket in "
        "_CLOSE_HAZARD_CLASSIFICATION."
    )

    stale = set(_CLOSE_HAZARD_CLASSIFICATION) - names
    assert (
        not stale
    ), f"Stale TimeBound classification entries (no such model): {sorted(stale)}"

    bad_buckets = {
        name: bucket
        for name, bucket in _CLOSE_HAZARD_CLASSIFICATION.items()
        if bucket not in _VALID_BUCKETS
    }
    assert not bad_buckets, f"Unknown classification bucket(s): {bad_buckets}"
