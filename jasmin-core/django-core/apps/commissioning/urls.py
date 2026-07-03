from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BulkCopyOffersToNextWeekView,
    BulkCopyOffersToOfferGroupView,
    BulkCreateDocumentsFromOrdersView,
    BulkCreateSummaryInvoiceFromOrdersView,
    BulkDeleteDocumentsView,
    BulkFinalizeDocumentsView,
    BulkFinalizeShareContentView,
    BulkFinalizeView,
    BulkSendInvoiceRemindersViaEmailView,
    BulkSendOffersViaEmailView,
    BulkSetToPaidDocumentsView,
    BulkUnfinalizeShareContentView,
    BulkUnfinalizeView,
    CombinedOrderOverviewView,
    CreateOffersView,
    CurrentStockComparisonView,
    DataImportView,
    DaysWithOrdersView,
    DeliveryStationFeesView,
    DeliveryStationsToursOverviewView,
    DocumentationOverviewView,
    MyCoopShareSubscribeView,
    MyCustomerDataView,
    MyMemberDataView,
    MyMembershipCancelView,
    MySubscriptionSubscribeView,
    SetInvoiceNoteView,
    SetOrderNoteView,
    ShareContentGranularityView,
    ShareTypeVariationsTotalsView,
    ShareVariationAmountsForPlanningView,
    StorageLoggingView,
    active_share_options_list,
    bulk_finalize_current_stock,
    bulk_set_as_expected_current_stock,
    bulk_set_to_zero_current_stock,
    historical_share_variation_averages,
    member_growth_statistics,
    offer_sending_status,
    share_options_list,
)
from .viewsets import (
    CommissioningListViewSet,
    ConsentDocumentViewSet,
    ConsentRecordViewSet,
    CoopShareViewSet,
    CrateContentInvoiceResellerViewSet,
    CrateDeliveryNoteContentViewSet,
    CrateNetPriceViewSet,
    CrateOrderContentViewSet,
    CrateViewSet,
    DefaultShareArticleInShareViewSet,
    DefaultShareContentViewSet,
    DeliveryExceptionPeriodViewSet,
    DeliveryNoteResellerContentViewSet,
    DeliveryNoteResellerViewSet,
    DeliveryStationDayViewSet,
    DeliveryStationViewSet,
    DeliveryToursViewSet,
    DocumentationSummaryViewSet,
    ExternalCodeMappingViewSet,
    ExternalShareDemandViewSet,
    ForecastViewSet,
    HarvestSharePlanningViewSet,
    HarvestViewSet,
    InvoiceResellerContentViewSet,
    InvoiceResellerViewSet,
    MemberLoanViewSet,
    MemberViewSet,
    OfferGroupViewSet,
    OfferViewSet,
    OrderContentViewSet,
    OrdersDeliveryDayViewSet,
    PackingListBulkViewSet,
    PackingListViewSet,
    PaymentCycleViewSet,
    PlotViewSet,
    PurchaseViewSet,
    ResellerViewSet,
    SeasonViewSet,
    ShareArticleNetPriceViewSet,
    ShareArticleViewSet,
    ShareContentViewSet,
    ShareDeliveryDetailsViewSet,
    ShareDeliveryOverviewViewSet,
    ShareDeliveryViewSet,
    ShareImportBatchViewSet,
    SharesDeliveryDayViewSet,
    ShareTypeVariationGrossPriceViewSet,
    ShareTypeVariationViewSet,
    ShareTypeViewSet,
    ShareViewSet,
    StorageViewSet,
    SubscriptionViewSet,
    TheoreticalCleanAmountViewSet,
    TheoreticalHarvestViewSet,
    TheoreticalPurchaseViewSet,
    TheoreticalWashAmountViewSet,
    UnconfirmedCoopSharesViewSet,
    UnconfirmedMembersViewSet,
    UnconfirmedSubscriptionsViewSet,
    UnconfirmedTrialSubscriptionsViewSet,
    VirtualComponentsViewSet,
    WasteViewSet,
)

router = DefaultRouter()
router.register(
    r"delivery_stations_days",
    DeliveryStationDayViewSet,
    basename="delivery_station_day",
)
router.register(r"packing_list", PackingListViewSet, basename="packing_list")
router.register(
    r"packing_list_bulk", PackingListBulkViewSet, basename="packing_list_bulk"
)
router.register(r"payment_cycles", PaymentCycleViewSet, basename="payment_cycle")
router.register(r"delivery_tours", DeliveryToursViewSet, basename="delivery_tours")
router.register(
    r"harvest_share_planning",
    HarvestSharePlanningViewSet,
    basename="harvest_share_planning",
)
router.register(
    r"virtual_variation_components",
    VirtualComponentsViewSet,
    basename="virtual_variation_components",
)
router.register(
    r"theoretical_harvests", TheoreticalHarvestViewSet, basename="theoretical_harvests"
)
router.register(
    r"theoretical_clean_amounts",
    TheoreticalCleanAmountViewSet,
    basename="theoretical_clean_amounts",
)
router.register(
    r"theoretical_purchase_amounts",
    TheoreticalPurchaseViewSet,
    basename="theoretical_purchase_amounts",
)
router.register(
    r"theoretical_wash_amounts",
    TheoreticalWashAmountViewSet,
    basename="theoretical_wash_amounts",
)
router.register(
    r"default_share_contents",
    DefaultShareContentViewSet,
    basename="default_share_contents",
)
router.register(
    r"delivery_exception_periods",
    DeliveryExceptionPeriodViewSet,
    basename="delivery_exception_periods",
)
router.register("invoices", InvoiceResellerViewSet, basename="invoices")
router.register(
    "invoice_contents", InvoiceResellerContentViewSet, basename="invoice_contents"
)
router.register(
    "delivery_notes", DeliveryNoteResellerViewSet, basename="delivery_notes"
)
router.register("crate_net_prices", CrateNetPriceViewSet, basename="crate_net_prices")
router.register(
    "share_type_variation_price",
    ShareTypeVariationGrossPriceViewSet,
    basename="share_type_variation_price",
)
router.register(
    "delivery_note_contents",
    DeliveryNoteResellerContentViewSet,
    basename="delivery_note_contents",
)
router.register(r"plots", PlotViewSet, basename="plots")
router.register(r"crates", CrateViewSet, basename="crates")
router.register(r"crate_contents", CrateOrderContentViewSet, basename="crate_contents")
router.register(
    r"crate_contents_delivery_note",
    CrateDeliveryNoteContentViewSet,
    basename="crate_delivery_note_content",
)
router.register(
    r"crate_contents_invoice",
    CrateContentInvoiceResellerViewSet,
    basename="crate_invoice_content",
)
router.register(r"storages", StorageViewSet, basename="storages")
router.register(r"share_articles", ShareArticleViewSet, basename="share_article")
router.register(
    r"default_share_articles_in_share",
    DefaultShareArticleInShareViewSet,
    basename="default_share_articles_in_share",
)

router.register(
    r"share_article_net_prices",
    ShareArticleNetPriceViewSet,
    basename="share_article_net_price",
)
router.register(r"share_contents", ShareContentViewSet, basename="share_contents")
router.register(r"order_contents", OrderContentViewSet, basename="order_contents")
router.register(
    r"unconfirmed_subscriptions",
    UnconfirmedSubscriptionsViewSet,
    basename="unconfirmed_subscriptions",
)
router.register(
    r"unconfirmed_trial_subscriptions",
    UnconfirmedTrialSubscriptionsViewSet,
    basename="unconfirmed_trial_subscriptions",
)
router.register(r"offer_groups", OfferGroupViewSet, basename="offer_group")
router.register(
    r"unconfirmed_members", UnconfirmedMembersViewSet, basename="unconfirmed_members"
)
router.register(
    r"unconfirmed_coop_shares",
    UnconfirmedCoopSharesViewSet,
    basename="unconfirmed_coop_shares",
)
router.register(
    r"commissioning_lists", CommissioningListViewSet, basename="commissioning_list"
)
router.register(r"forecast", ForecastViewSet, basename="forecast")
router.register(r"share_types", ShareTypeViewSet, basename="share_type")
router.register(
    r"share_type_variations", ShareTypeVariationViewSet, basename="share_type_variation"
)
router.register(r"members", MemberViewSet, basename="member")
router.register(
    r"consent_documents", ConsentDocumentViewSet, basename="consent_document"
)
router.register(r"consents", ConsentRecordViewSet, basename="consent_record")
router.register(r"abos", SubscriptionViewSet, basename="abos")
router.register(r"resellers", ResellerViewSet, basename="reseller")
router.register(
    r"delivery_stations", DeliveryStationViewSet, basename="delivery_station"
)
router.register(
    r"shares_delivery_days", SharesDeliveryDayViewSet, basename="share_delivery_day"
)
router.register(
    r"orders_delivery_days", OrdersDeliveryDayViewSet, basename="orders_delivery_day"
)
router.register(r"waste", WasteViewSet, basename="waste")
router.register(r"coop_shares", CoopShareViewSet, basename="coop_shares")
router.register(r"member_loans", MemberLoanViewSet, basename="member_loans")
router.register(r"purchase", PurchaseViewSet, basename="purchase")
router.register(r"harvest", HarvestViewSet, basename="harvest")
router.register(
    r"documentation_summary",
    DocumentationSummaryViewSet,
    basename="documentation_summary",
)
router.register(r"share_delivery", ShareDeliveryViewSet, basename="share_delivery")
router.register(r"season", SeasonViewSet, basename="season")
router.register(r"offers", OfferViewSet, basename="offer")
router.register(r"shares", ShareViewSet, basename="share")
router.register(
    r"share_delivery_overview",
    ShareDeliveryOverviewViewSet,
    basename="share_delivery_overview",
)
router.register(
    r"share_delivery_details",
    ShareDeliveryDetailsViewSet,
    basename="share_delivery_details",
)
router.register(
    r"external_code_mappings",
    ExternalCodeMappingViewSet,
    basename="external_code_mapping",
)
router.register(
    r"share_import_batches",
    ShareImportBatchViewSet,
    basename="share_import_batch",
)
router.register(
    r"external_share_demand",
    ExternalShareDemandViewSet,
    basename="external_share_demand",
)


urlpatterns = [
    path("", include(router.urls)),
    path(
        "days_with_orders/",
        DaysWithOrdersView.as_view(),
        name="days_with_orders",
    ),
    path(
        "granularity/",
        ShareContentGranularityView.as_view(),
        name="granularity",
    ),
    path(
        "share_type_variations_totals/",
        ShareTypeVariationsTotalsView.as_view(),
        name="share_type_variations_totals",
    ),
    # Scope methods per URL: the list URL has only GET (the bulk-read
    # entry point), the detail URL has PATCH + DELETE (single-row
    # mutations keyed by composite_id). `as_view(http_method_names=…)`
    # narrows the routes — also eliminates spectacular operationId
    # collisions where the same auto-name would otherwise be emitted
    # for two URLs serving the same HTTP method.
    path(
        "current_stock_comparison/",
        CurrentStockComparisonView.as_view(http_method_names=["get"]),
        name="current_stock_comparison",
    ),
    path(
        "current_stock_comparison/<str:composite_id>/",
        CurrentStockComparisonView.as_view(http_method_names=["patch", "delete"]),
        name="current_stock_comparison_detail",
    ),
    path(
        "current_stock_bulk_finalize/",
        bulk_finalize_current_stock,
        name="bulk_finalize_current_stock",
    ),
    path(
        "current_stock_bulk_set_as_expected/",
        bulk_set_as_expected_current_stock,
        name="bulk_set_as_expected_current_stock",
    ),
    path(
        "current_stock_bulk_set_to_zero/",
        bulk_set_to_zero_current_stock,
        name="bulk_set_to_zero_current_stock",
    ),
    path(
        "documentation_overview/",
        DocumentationOverviewView.as_view(),
        name="documentation_overview",
    ),
    path(
        "share_variation_amounts_for_planning/",
        ShareVariationAmountsForPlanningView.as_view(),
        name="share_variation_amounts_for_planning",
    ),
    path(
        "member_growth_statistics/",
        member_growth_statistics,
        name="member_growth_statistics",
    ),
    path(
        "historical_share_variation_averages/",
        historical_share_variation_averages,
        name="historical_share_variation_averages",
    ),
    path(
        "orders_overview/",
        CombinedOrderOverviewView.as_view(),
        name="orders_overview",
    ),
    path(
        "bulk_create_documents_from_orders/",
        BulkCreateDocumentsFromOrdersView.as_view(),
        name="bulk_create_documents_from_orders",
    ),
    path(
        "bulk_delete_documents/",
        BulkDeleteDocumentsView.as_view(),
        name="bulk_delete_documents",
    ),
    path(
        "offer_sending_status/",
        offer_sending_status,
        name="offer_sending_status",
    ),
    path(
        "share_options/",
        share_options_list,
        name="share_options_list",
    ),
    path(
        "share_options/active/",
        active_share_options_list,
        name="active_share_options_list",
    ),
    path(
        "bulk_finalize_documents/",
        BulkFinalizeDocumentsView.as_view(),
        name="bulk_finalize_documents",
    ),
    path(
        "bulk_set_to_paid_documents/",
        BulkSetToPaidDocumentsView.as_view(),
        name="bulk_set_to_paid_documents",
    ),
    path(
        "bulk_copy_offers_to_next_week/",
        BulkCopyOffersToNextWeekView.as_view(),
        name="bulk_copy_offers_to_next_week",
    ),
    path(
        "bulk_copy_offers_to_offer_group/",
        BulkCopyOffersToOfferGroupView.as_view(),
        name="bulk_copy_offers_to_offer_group",
    ),
    path(
        "bulk_create_summary_invoice_from_orders/",
        BulkCreateSummaryInvoiceFromOrdersView.as_view(),
        name="bulk_create_summary_invoice_from_orders",
    ),
    path(
        "delivery_station_tours_overview/",
        DeliveryStationsToursOverviewView.as_view(),
        name="delivery_station_tours_overview",
    ),
    path(
        "delivery_station_fees/",
        DeliveryStationFeesView.as_view(),
        name="delivery_station_fees",
    ),
    path(
        "create_offers/",
        CreateOffersView.as_view(),
        name="create_offers",
    ),
    path("storage_logging/", StorageLoggingView.as_view(), name="storage_logging"),
    path("data_import/", DataImportView.as_view(), name="data_import"),
    path("bulk_finalize/", BulkFinalizeView.as_view(), name="bulk_finalize"),
    path("bulk_unfinalize/", BulkUnfinalizeView.as_view(), name="bulk_unfinalize"),
    path(
        "bulk_finalize_share_content/",
        BulkFinalizeShareContentView.as_view(),
        name="bulk_finalize_share_content",
    ),
    path(
        "bulk_unfinalize_share_content/",
        BulkUnfinalizeShareContentView.as_view(),
        name="bulk_unfinalize_share_content",
    ),
    path(
        "set_invoice_note/<str:pk>/",
        SetInvoiceNoteView.as_view(),
        name="set_invoice_note",
    ),
    path(
        "set_order_note/<str:pk>/",
        SetOrderNoteView.as_view(),
        name="set_order_note",
    ),
    path(
        "bulk_send_invoice_reminders_via_email/",
        BulkSendInvoiceRemindersViaEmailView.as_view(),
        name="bulk_send_invoice_reminders_via_email",
    ),
    path(
        "bulk_send_offers_via_email/",
        BulkSendOffersViaEmailView.as_view(),
        name="bulk_send_offers_via_email",
    ),
    path(
        "my_member_data/",
        MyMemberDataView.as_view(),
        name="my_member_data",
    ),
    path(
        "my_coop_shares/subscribe/",
        MyCoopShareSubscribeView.as_view(),
        name="my_coop_shares_subscribe",
    ),
    path(
        "my_subscriptions/subscribe/",
        MySubscriptionSubscribeView.as_view(),
        name="my_subscriptions_subscribe",
    ),
    path(
        "my_membership/cancel/",
        MyMembershipCancelView.as_view(),
        name="my_membership_cancel",
    ),
    path(
        "my_customer_data/",
        MyCustomerDataView.as_view(),
        name="my_customer_data",
    ),
]
