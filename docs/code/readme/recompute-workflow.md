================================================================================
COMMISSIONING — RECOMPUTE PIPELINE (post-signal refactor)
================================================================================

Overview
--------
Theoretical objects (TheoreticalHarvest / TheoreticalPurchase /
TheoreticalWashAmount / TheoreticalCleanAmount) and theoretical/real
MovementShareArticle rows are DERIVED state. They are produced from
"source" rows: ShareContent + ShareDelivery + Forecast (for the shares
side) and OrderContent (for the resellers side).

Whenever a source row changes we WIPE and REBUILD the derived rows for
the affected aggregate (Share or OrderContent). No incremental updates,
no signals, no on_commit hooks. Every mutation path either:

  (a) calls a fat service method that recomputes internally, or
  (b) calls one of two top-level helpers:
        recompute_shares(share_ids)
        recompute_order_contents(order_content_ids)

Both helpers live in apps/commissioning/services/recompute.py, dedupe
their input via set(), no-op on empty input, and run synchronously
inside the caller's transaction.


================================================================================
A. SHARE PIPELINE
   Forecast / ShareContent / ShareDelivery  →  Theoreticals + Movements
================================================================================

Source rows (the inputs)
------------------------
* Forecast        — planned harvest volume for (year, week, share_article, size).
* ShareContent    — one row per (Share, share_article, station, unit, size).
                    Carries the per-share default amount + an optional FK
                    to a Forecast.
* ShareDelivery   — one row per (Share, Subscription) opt-in/opt-out, plus
                    "manual entries" without a Subscription. Joker, swap,
                    cancellation flags also live here.

Aggregation
-----------
A Share is the unit of recompute. Its derived rows are:

    TheoreticalHarvest  / TheoreticalPurchase  /
    TheoreticalWashAmount / TheoreticalCleanAmount   (FK: share_content)
    MovementShareArticle  movement_type=SHARECONTENT (FK: share_content)

Recompute = delete-and-rebuild for ALL of those, scoped by the
ShareContents of the affected Shares.

Entry point
-----------
    apps.commissioning.services.recompute.recompute_shares(share_ids)
        → ShareContentService().recompute_for_shares(shares)
              1. SELECT FOR UPDATE on the Shares (locks the aggregate).
              2. Delete Theoretical{Harvest, Purchase, Wash, Clean}
                 where share_content.share_id IN share_ids.
              3. Delete MovementShareArticle of type SHARECONTENT for
                 those ShareContents.
              4. Aggregate net demand from ShareContent.amount and
                 ShareDelivery (taking joker/cancel/swap into account).
              5. Re-create theoreticals + SHARECONTENT movements.

Trigger points (where recompute_shares is called explicitly)
------------------------------------------------------------
Service layer:
  * ForecastService._create_or_update_share_contents
        after bulk_create + bulk_update of ShareContent.
  * DefaultShareContentService.apply_defaults_to_week
        after bulk_create of new ShareContents.
  * SubscriptionService.materialize_confirmed_subscription
        both bulk_create paths for ShareDelivery.
  * SubscriptionService.cancel_subscription
        after deleting future ShareDeliveries.
  * SharesDeliveryDayService.update_share_deliveries_for_delivery_day
        after bulk_update of delivery_station_day on future deliveries.
  * SharesDayChangeService.apply
        when one of {harvesting_day, packing_day, washing_day,
        cleaning_day} actually changes on a Share. (Calls
        ShareContentService().recompute_for_shares directly via a thin
        helper — same pipeline.) Note: changed_delivery_day and
        get_current_stock_day are informational and do NOT trigger.

DRF viewset layer (paths that don't go through a service):
  * ShareDeliveryViewSet.perform_create
  * ShareDeliveryViewSet.perform_update      (also handles apply_to_future:
        recomputes the union of {edited share, all future shares whose
        delivery_station_day was propagated})
  * ShareDeliveryViewSet.perform_destroy
  * ShareDeliveryViewSet.create_manual_entry (custom @action)
  * ShareContentViewSet.perform_create / perform_update / perform_destroy

Forecast mutations:
  * ForecastViewSet.create / update route through ForecastService, which
    recomputes inside the service.

Day-field mutations on Share:
  * ShareViewSet.bulk_update routes through SharesDayChangeService, which
    only triggers recompute when a recompute-relevant day field changed.


================================================================================
B. ORDERCONTENT PIPELINE
   OrderContent  →  Theoreticals + ORDERCONTENT Movements
================================================================================

Source rows
-----------
* OrderContent — one row per ordered article line, owned by an Order
                 placed by a Reseller. There is NO aggregation step:
                 each OrderContent owns its own theoreticals and
                 movements directly via FK.

Derived rows
------------
    TheoreticalHarvest / TheoreticalPurchase / TheoreticalWashAmount /
    TheoreticalCleanAmount                                (FK: order_content)
    MovementShareArticle  movement_type=ORDERCONTENT      (FK: order_content)

Important: TheoreticalHarvest is only produced when a matching Forecast
exists for (year, week, share_article, size). No Forecast → no
TheoreticalHarvest (this is intentional; harvest theoreticals model
contracted demand against a planned harvest).

Entry point
-----------
    apps.commissioning.services.recompute.recompute_order_contents(oc_ids)
        → OrderContentService().recompute_for_order_contents(ocs)
              1. SELECT FOR UPDATE on the OrderContents.
              2. Delete Theoretical{Harvest, Purchase, Wash, Clean} for
                 the affected OrderContents.
              3. Delete MovementShareArticle of type ORDERCONTENT for
                 the affected OrderContents.
              4. create_all_theoretical_objects(ocs).
              5. create_movements(ocs) — including storage routing and
                 wash/clean step decisions.

Trigger points
--------------
Most OrderContent mutations are already inside fat service methods that
maintain derived state directly (no separate recompute call needed):

  * OrderContentService.create_order_with_content_and_crates
        calls create_all_theoretical_objects + create_movements.
  * OrderContentService.update_order_content
        rebuilds via _recreate_movements + create_all_theoretical_objects.
  * OrderContentService.delete_order_content
        cascade FK deletes wipe theoreticals and movements.

For any future direct mutation path that does NOT go through these
service methods (e.g. an admin script, a new viewset, a management
command), call:

    recompute_order_contents([oc.id, ...])

right after the mutation.


================================================================================
C. SIGNALS — WHAT REMAINS
================================================================================

The only application-defined signals still wired up live in
apps/commissioning/signals.py and concern Member ↔ JasminUser.roles:

  * post_save  on commissioning.Member  — _sync_member_role_on_save
  * pre_delete on commissioning.Member  — _sync_member_role_on_delete

These are intentionally signal-based: pre_delete is the only safe place
to scrub roles when the Member row is removed by a cascade higher up
the tree.

External-library signals we still consume (NOT ours to remove):
  * django-axes user_locked_out
  * anymail tracking signals

EVERYTHING ELSE IS NOW EXPLICIT. In particular, the following are gone:
  * recompute_scheduler.py (deleted)
  * The 8 receivers that used to call schedule_share_recompute /
    schedule_order_content_recompute on post_save / post_delete /
    m2m_changed of ShareContent, ShareDelivery, Forecast, OrderContent.
  * The custom admin_confirmed Signal — replaced by the
    AdminConfirmableMixin._post_confirm(admin_user=...) hook, overridden
    by Member (member_number + activate user) and Subscription
    (materialize_confirmed_subscription).


================================================================================
D. INVARIANTS / EDGE CASES
================================================================================

1. Idempotency
   recompute_shares([s.id, s.id, s.id]) and a single
   recompute_shares([s.id]) produce identical end state. Same for
   recompute_order_contents.

2. Empty input is a no-op
   recompute_shares([]) / recompute_shares([None]) / recompute_shares(())
   return immediately without touching the DB. Same for OC.

3. Atomicity
   Both helpers run inside the caller's transaction.atomic. The inner
   service methods take SELECT FOR UPDATE locks on the Shares /
   OrderContents being rebuilt, so two concurrent recomputes for the
   same aggregate serialize at the row-lock level.

4. Cascade deletes
   * Deleting a Share cascade-deletes its ShareContents → cascade-deletes
     their theoreticals and SHARECONTENT movements. No recompute needed.
   * Deleting an OrderContent cascade-deletes its theoreticals and
     ORDERCONTENT movements. The standard
     OrderContentService.delete_order_content already does this.
   * Deleting a Subscription cascades to its ShareDeliveries; if any
     code path deletes a Subscription DIRECTLY (instead of going through
     SubscriptionService.cancel_subscription), it MUST collect the
     affected share_ids first and call recompute_shares afterwards.

5. Day-field changes on Share
   harvesting_day / packing_day / washing_day / cleaning_day are
   recompute-relevant. changed_delivery_day and get_current_stock_day
   are not. SharesDayChangeService is the canonical entry point and
   already encodes this distinction.

6. Forecast required for harvest theoreticals
   On the OrderContent side, no Forecast for the (year, week, article,
   size) means no TheoreticalHarvest is created. Tests creating
   OrderContent without an associated Forecast will see only
   ORDERCONTENT movements, no theoreticals.

7. Bulk operations bypass model save() / signals by design
   This is no longer a problem because we DO NOT rely on signals.
   Any caller doing bulk_create / bulk_update / queryset.update /
   queryset.delete on ShareContent, ShareDelivery, Forecast or
   OrderContent MUST follow up with the appropriate recompute helper.
   Current callers that do this correctly:
     - ForecastService._create_or_update_share_contents
     - DefaultShareContentService.apply_defaults_to_week
     - SubscriptionService.materialize_confirmed_subscription
     - SubscriptionService.cancel_subscription
     - SharesDeliveryDayService.update_share_deliveries_for_delivery_day

8. ShareDelivery edits with apply_to_future=True
   ShareDeliveryViewSet.perform_update walks all future ShareDeliveries
   for the same (subscription, delivery_day) and updates their DSD if a
   matching one exists. The recompute call covers BOTH the edited
   delivery's share AND every future share whose delivery was retargeted.

9. Tests
   * No more captureOnCommitCallbacks anywhere in the recompute test
     suite.
   * Tests that need theoreticals for OrderContent must create a
     matching Forecast (year/week/share_article/size). See
     tests_services/test_order_content_signal_recompute.py.
   * Tests can mutate raw models and then call recompute_shares /
     recompute_order_contents directly — same code path the production
     callers use.


================================================================================
E. WHEN ADDING NEW CODE
================================================================================

If your new code mutates Forecast, ShareContent, ShareDelivery or
OrderContent in a way that does not go through one of the existing
fat service methods listed in section A/B trigger points:

  1. Identify which Shares (or OrderContents) the mutation affects.
  2. Call recompute_shares([...]) / recompute_order_contents([...])
     inside the same transaction, after the mutation.

If your new code adds a new derived field that depends on these
sources, extend ShareContentService.recompute_for_shares (or
OrderContentService.recompute_for_order_contents) so the rebuild step
emits it. Do NOT add a new signal.
