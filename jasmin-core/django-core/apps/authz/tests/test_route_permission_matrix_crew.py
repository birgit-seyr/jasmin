"""HTTP role matrix for the crew tier on viewsets whose read and write gates differ.

``staff`` and ``gardener`` are the roles that separate ``IsStaff`` from
``IsOffice``: the first gate admits them, the second refuses them. A viewset that
declares one gate for reads and another for writes therefore needs both roles on
both sides to show its wiring — a crew role reading what it may read and refused
on a write — plus ``office`` on the write, so a read/write swap fails a row
instead of passing unseen. Cultivation splits the crew: its write gate
(``CanEditCultivation``) admits the gardener but not staff.

Rows have the shape and categories of ``MATRIX`` in
``test_route_permission_matrix.py`` and run through its ``check_route``.

A read that needs query parameters carries them in its path and names a week of
2025: an empty past week answers 200 whatever the clock says, a stronger row than
the ``"4xx"`` a bare path would earn. Write rows send an empty body: a denied role
is refused by the permission layer before the body or the pk is looked at, and an
admitted one lands in ``"4xx"`` when the body is refused or the pk names no row.

A view that routes only reads has read rows only, since its write gate guards no
route. ``test_every_view_with_split_gates_has_crew_rows`` holds every routed view
with differing gates to crew rows in one of the two matrices.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, resolve

from apps.authz.tests.test_route_permission_matrix import MATRIX, check_route

pytestmark = pytest.mark.django_db

YEAR = "year=2025"
WEEK = f"{YEAR}&delivery_week=15"
DAY = f"{WEEK}&day_number=1"
HARVEST = "share_option=HARVEST_SHARE"

# (path, method, role, expected_category)
CREW_MATRIX: list[tuple[str, str, str, str]] = [
    # ======= commissioning: master data =======
    # ------- Seasons (Staff read, Office write) -------
    ("/api/commissioning/season/", "get", "staff", "ok"),
    ("/api/commissioning/season/", "get", "gardener", "ok"),
    ("/api/commissioning/season/", "post", "staff", "deny"),
    ("/api/commissioning/season/", "post", "gardener", "deny"),
    ("/api/commissioning/season/", "post", "office", "4xx"),
    # ------- Share article net prices (Staff read, Office write) -------
    ("/api/commissioning/share_article_net_prices/", "get", "staff", "ok"),
    ("/api/commissioning/share_article_net_prices/", "get", "gardener", "ok"),
    ("/api/commissioning/share_article_net_prices/", "post", "staff", "deny"),
    ("/api/commissioning/share_article_net_prices/", "post", "gardener", "deny"),
    ("/api/commissioning/share_article_net_prices/", "post", "office", "4xx"),
    # ------- Default share articles in a share (Staff read, Office write) -------
    ("/api/commissioning/default_share_articles_in_share/", "get", "staff", "ok"),
    ("/api/commissioning/default_share_articles_in_share/", "get", "gardener", "ok"),
    ("/api/commissioning/default_share_articles_in_share/", "post", "staff", "deny"),
    (
        "/api/commissioning/default_share_articles_in_share/",
        "post",
        "gardener",
        "deny",
    ),
    ("/api/commissioning/default_share_articles_in_share/", "post", "office", "4xx"),
    # ------- Crate net prices (Staff read, Office write) -------
    ("/api/commissioning/crate_net_prices/", "get", "staff", "ok"),
    ("/api/commissioning/crate_net_prices/", "get", "gardener", "ok"),
    ("/api/commissioning/crate_net_prices/", "post", "staff", "deny"),
    ("/api/commissioning/crate_net_prices/", "post", "gardener", "deny"),
    ("/api/commissioning/crate_net_prices/", "post", "office", "4xx"),
    # ------- Plots, commissioning documentation (Staff read, Office write) -------
    ("/api/commissioning/plots/", "get", "staff", "ok"),
    ("/api/commissioning/plots/", "get", "gardener", "ok"),
    ("/api/commissioning/plots/", "post", "staff", "deny"),
    ("/api/commissioning/plots/", "post", "gardener", "deny"),
    ("/api/commissioning/plots/", "post", "office", "4xx"),
    # ------- Orders delivery days (StaffOrMemberOrCustomer read, Office write) -------
    ("/api/commissioning/orders_delivery_days/", "get", "staff", "ok"),
    ("/api/commissioning/orders_delivery_days/", "get", "gardener", "ok"),
    ("/api/commissioning/orders_delivery_days/", "post", "staff", "deny"),
    ("/api/commissioning/orders_delivery_days/", "post", "gardener", "deny"),
    ("/api/commissioning/orders_delivery_days/", "post", "office", "4xx"),
    # ------- Shares delivery days (StaffOrMember read, Office write) -------
    ("/api/commissioning/shares_delivery_days/", "get", "staff", "ok"),
    ("/api/commissioning/shares_delivery_days/", "get", "gardener", "ok"),
    ("/api/commissioning/shares_delivery_days/", "post", "staff", "deny"),
    ("/api/commissioning/shares_delivery_days/", "post", "gardener", "deny"),
    ("/api/commissioning/shares_delivery_days/", "post", "office", "4xx"),
    # ------- Payment cycles (public list, StaffOrMember read, Office write) -------
    ("/api/commissioning/payment_cycles/", "get", "staff", "ok"),
    ("/api/commissioning/payment_cycles/", "get", "gardener", "ok"),
    ("/api/commissioning/payment_cycles/", "post", "staff", "deny"),
    ("/api/commissioning/payment_cycles/", "post", "gardener", "deny"),
    ("/api/commissioning/payment_cycles/", "post", "office", "4xx"),
    # ------- Consent documents (public read, Office write) -------
    ("/api/commissioning/consent_documents/", "get", "staff", "ok"),
    ("/api/commissioning/consent_documents/", "get", "gardener", "ok"),
    ("/api/commissioning/consent_documents/", "post", "staff", "deny"),
    ("/api/commissioning/consent_documents/", "post", "gardener", "deny"),
    ("/api/commissioning/consent_documents/", "post", "office", "4xx"),
    # ======= commissioning: delivery =======
    # ------- Delivery stations (StaffOrMember read, Office write) -------
    # The write rows name an unknown pk: an empty POST creates a station.
    ("/api/commissioning/delivery_stations/", "get", "staff", "ok"),
    ("/api/commissioning/delivery_stations/", "get", "gardener", "ok"),
    ("/api/commissioning/delivery_stations/unknown/", "delete", "staff", "deny"),
    ("/api/commissioning/delivery_stations/unknown/", "delete", "gardener", "deny"),
    ("/api/commissioning/delivery_stations/unknown/", "delete", "office", "4xx"),
    # ------- Delivery station days (public list, StaffOrMember read, Office write) -------
    ("/api/commissioning/delivery_stations_days/", "get", "staff", "ok"),
    ("/api/commissioning/delivery_stations_days/", "get", "gardener", "ok"),
    ("/api/commissioning/delivery_stations_days/", "post", "staff", "deny"),
    ("/api/commissioning/delivery_stations_days/", "post", "gardener", "deny"),
    ("/api/commissioning/delivery_stations_days/", "post", "office", "4xx"),
    # ------- Delivery exceptions (public list, StaffOrMember read, Office write) -------
    ("/api/commissioning/delivery_exception_periods/", "get", "staff", "ok"),
    ("/api/commissioning/delivery_exception_periods/", "get", "gardener", "ok"),
    ("/api/commissioning/delivery_exception_periods/", "post", "staff", "deny"),
    ("/api/commissioning/delivery_exception_periods/", "post", "gardener", "deny"),
    ("/api/commissioning/delivery_exception_periods/", "post", "office", "4xx"),
    # ------- Delivery tours (Staff read, Office write) -------
    ("/api/commissioning/delivery_tours/?delivery_day=1", "get", "staff", "ok"),
    ("/api/commissioning/delivery_tours/?delivery_day=1", "get", "gardener", "ok"),
    ("/api/commissioning/delivery_tours/update_tours/", "post", "staff", "deny"),
    ("/api/commissioning/delivery_tours/update_tours/", "post", "gardener", "deny"),
    ("/api/commissioning/delivery_tours/update_tours/", "post", "office", "4xx"),
    # ======= commissioning: members =======
    # ------- Cooperative shares (Staff read, Office write) -------
    ("/api/commissioning/coop_shares/", "get", "staff", "ok"),
    ("/api/commissioning/coop_shares/", "get", "gardener", "ok"),
    ("/api/commissioning/coop_shares/", "post", "staff", "deny"),
    ("/api/commissioning/coop_shares/", "post", "gardener", "deny"),
    ("/api/commissioning/coop_shares/", "post", "office", "4xx"),
    # ------- Member loans (Staff read, Office write) -------
    ("/api/commissioning/member_loans/", "get", "staff", "ok"),
    ("/api/commissioning/member_loans/", "get", "gardener", "ok"),
    ("/api/commissioning/member_loans/", "post", "staff", "deny"),
    ("/api/commissioning/member_loans/", "post", "gardener", "deny"),
    ("/api/commissioning/member_loans/", "post", "office", "4xx"),
    # ======= commissioning: markets =======
    # ------- Market product groups (Staff read, Office write) -------
    ("/api/commissioning/market_product_groups/", "get", "staff", "ok"),
    ("/api/commissioning/market_product_groups/", "get", "gardener", "ok"),
    ("/api/commissioning/market_product_groups/", "post", "staff", "deny"),
    ("/api/commissioning/market_product_groups/", "post", "gardener", "deny"),
    ("/api/commissioning/market_product_groups/", "post", "office", "4xx"),
    # ------- PLUs (Staff read, Office write) -------
    ("/api/commissioning/market_articles/", "get", "staff", "ok"),
    ("/api/commissioning/market_articles/", "get", "gardener", "ok"),
    ("/api/commissioning/market_articles/", "post", "staff", "deny"),
    ("/api/commissioning/market_articles/", "post", "gardener", "deny"),
    ("/api/commissioning/market_articles/", "post", "office", "4xx"),
    # ------- Scale VAT codes (Staff read, Office write) -------
    ("/api/commissioning/scale_tax_codes/", "get", "staff", "ok"),
    ("/api/commissioning/scale_tax_codes/", "get", "gardener", "ok"),
    ("/api/commissioning/scale_tax_codes/", "post", "staff", "deny"),
    ("/api/commissioning/scale_tax_codes/", "post", "gardener", "deny"),
    ("/api/commissioning/scale_tax_codes/", "post", "office", "4xx"),
    # ------- Market prices (Staff read, Office write) -------
    (f"/api/commissioning/market_prices/?{WEEK}", "get", "staff", "ok"),
    (f"/api/commissioning/market_prices/?{WEEK}", "get", "gardener", "ok"),
    ("/api/commissioning/market_prices/", "post", "staff", "deny"),
    ("/api/commissioning/market_prices/", "post", "gardener", "deny"),
    ("/api/commissioning/market_prices/", "post", "office", "4xx"),
    (
        "/api/commissioning/market_prices/bulk_copy_to_next_week/",
        "post",
        "staff",
        "deny",
    ),
    (
        "/api/commissioning/market_prices/bulk_copy_to_next_week/",
        "post",
        "gardener",
        "deny",
    ),
    (
        "/api/commissioning/market_prices/bulk_copy_to_next_week/",
        "post",
        "office",
        "4xx",
    ),
    ("/api/commissioning/market_prices/bulk_set_active/", "post", "staff", "deny"),
    ("/api/commissioning/market_prices/bulk_set_active/", "post", "gardener", "deny"),
    ("/api/commissioning/market_prices/bulk_set_active/", "post", "office", "4xx"),
    # The scale export is a GET custom action, so it takes the write gate.
    (f"/api/commissioning/market_prices/scale_export/?{WEEK}", "get", "staff", "deny"),
    (
        f"/api/commissioning/market_prices/scale_export/?{WEEK}",
        "get",
        "gardener",
        "deny",
    ),
    (f"/api/commissioning/market_prices/scale_export/?{WEEK}", "get", "office", "ok"),
    # ======= commissioning: resellers =======
    # ------- Offers (StaffOrCustomer read, Office write) -------
    (f"/api/commissioning/offers/?{WEEK}", "get", "staff", "ok"),
    (f"/api/commissioning/offers/?{WEEK}", "get", "gardener", "ok"),
    ("/api/commissioning/offers/", "post", "staff", "deny"),
    ("/api/commissioning/offers/", "post", "gardener", "deny"),
    ("/api/commissioning/offers/", "post", "office", "4xx"),
    # ------- Offer groups (Staff read, Office write) -------
    ("/api/commissioning/offer_groups/", "get", "staff", "ok"),
    ("/api/commissioning/offer_groups/", "get", "gardener", "ok"),
    ("/api/commissioning/offer_groups/", "post", "staff", "deny"),
    ("/api/commissioning/offer_groups/", "post", "gardener", "deny"),
    ("/api/commissioning/offer_groups/", "post", "office", "4xx"),
    # ------- Organic certificates (Staff read, Office write) -------
    ("/api/commissioning/organic_certificates/", "get", "staff", "ok"),
    ("/api/commissioning/organic_certificates/", "get", "gardener", "ok"),
    ("/api/commissioning/organic_certificates/", "post", "staff", "deny"),
    ("/api/commissioning/organic_certificates/", "post", "gardener", "deny"),
    ("/api/commissioning/organic_certificates/", "post", "office", "4xx"),
    # ------- Resellers (StaffOrCustomer read, OfficeOrCustomer write) -------
    ("/api/commissioning/resellers/", "get", "staff", "ok"),
    ("/api/commissioning/resellers/", "get", "gardener", "ok"),
    ("/api/commissioning/resellers/", "post", "staff", "deny"),
    ("/api/commissioning/resellers/", "post", "gardener", "deny"),
    ("/api/commissioning/resellers/", "post", "office", "4xx"),
    # ------- Order contents (StaffOrCustomer read, OfficeOrCustomer write) -------
    ("/api/commissioning/order_contents/", "get", "staff", "ok"),
    ("/api/commissioning/order_contents/", "get", "gardener", "ok"),
    ("/api/commissioning/order_contents/", "post", "staff", "deny"),
    ("/api/commissioning/order_contents/", "post", "gardener", "deny"),
    ("/api/commissioning/order_contents/", "post", "office", "4xx"),
    # ------- Commissioning lists per reseller (Staff read; reads only) -------
    (f"/api/commissioning/commissioning_lists_resellers/?{DAY}", "get", "staff", "ok"),
    (
        f"/api/commissioning/commissioning_lists_resellers/?{DAY}",
        "get",
        "gardener",
        "ok",
    ),
    # ------- Delivery notes (OfficeOrCustomer read, Office write) -------
    # The crew tier is in neither gate of the four reseller document viewsets.
    ("/api/commissioning/delivery_notes/", "get", "staff", "deny"),
    ("/api/commissioning/delivery_notes/", "get", "gardener", "deny"),
    ("/api/commissioning/delivery_notes/", "post", "staff", "deny"),
    ("/api/commissioning/delivery_notes/", "post", "gardener", "deny"),
    ("/api/commissioning/delivery_notes/", "post", "office", "4xx"),
    # ------- Delivery note contents (OfficeOrCustomer read, Office write) -------
    ("/api/commissioning/delivery_note_contents/", "get", "staff", "deny"),
    ("/api/commissioning/delivery_note_contents/", "get", "gardener", "deny"),
    ("/api/commissioning/delivery_note_contents/", "post", "staff", "deny"),
    ("/api/commissioning/delivery_note_contents/", "post", "gardener", "deny"),
    ("/api/commissioning/delivery_note_contents/", "post", "office", "4xx"),
    # ------- Invoices (OfficeOrCustomer read, Office write) -------
    ("/api/commissioning/invoices/", "get", "staff", "deny"),
    ("/api/commissioning/invoices/", "get", "gardener", "deny"),
    ("/api/commissioning/invoices/", "post", "staff", "deny"),
    ("/api/commissioning/invoices/", "post", "gardener", "deny"),
    ("/api/commissioning/invoices/", "post", "office", "4xx"),
    # ------- Invoice contents (OfficeOrCustomer read, Office write) -------
    ("/api/commissioning/invoice_contents/", "get", "staff", "deny"),
    ("/api/commissioning/invoice_contents/", "get", "gardener", "deny"),
    ("/api/commissioning/invoice_contents/", "post", "staff", "deny"),
    ("/api/commissioning/invoice_contents/", "post", "gardener", "deny"),
    ("/api/commissioning/invoice_contents/", "post", "office", "4xx"),
    # ------- Crate contents of delivery notes (Staff read, Office write) -------
    # "4xx" on the reads: the unknown delivery note is a 404, past the gate.
    (
        "/api/commissioning/crate_contents_delivery_note/?delivery_note_id=unknown",
        "get",
        "staff",
        "4xx",
    ),
    (
        "/api/commissioning/crate_contents_delivery_note/?delivery_note_id=unknown",
        "get",
        "gardener",
        "4xx",
    ),
    ("/api/commissioning/crate_contents_delivery_note/", "post", "staff", "deny"),
    ("/api/commissioning/crate_contents_delivery_note/", "post", "gardener", "deny"),
    ("/api/commissioning/crate_contents_delivery_note/", "post", "office", "4xx"),
    # ------- Crate contents of invoices (Staff read, Office write) -------
    # "4xx" on the reads: the unknown invoice is a 404, past the gate.
    (
        "/api/commissioning/crate_contents_invoice/?invoice_id=unknown",
        "get",
        "staff",
        "4xx",
    ),
    (
        "/api/commissioning/crate_contents_invoice/?invoice_id=unknown",
        "get",
        "gardener",
        "4xx",
    ),
    ("/api/commissioning/crate_contents_invoice/", "post", "staff", "deny"),
    ("/api/commissioning/crate_contents_invoice/", "post", "gardener", "deny"),
    ("/api/commissioning/crate_contents_invoice/", "post", "office", "4xx"),
    # ======= commissioning: shares =======
    # ------- Share types (public list, StaffOrMember read, Office write) -------
    ("/api/commissioning/share_types/", "get", "staff", "ok"),
    ("/api/commissioning/share_types/", "get", "gardener", "ok"),
    ("/api/commissioning/share_types/", "post", "staff", "deny"),
    ("/api/commissioning/share_types/", "post", "gardener", "deny"),
    ("/api/commissioning/share_types/", "post", "office", "4xx"),
    # ------- Share sizes (public list, StaffOrMember read, Office write) -------
    ("/api/commissioning/share_type_variations/", "get", "staff", "ok"),
    ("/api/commissioning/share_type_variations/", "get", "gardener", "ok"),
    ("/api/commissioning/share_type_variations/", "post", "staff", "deny"),
    ("/api/commissioning/share_type_variations/", "post", "gardener", "deny"),
    ("/api/commissioning/share_type_variations/", "post", "office", "4xx"),
    # ------- Share size prices (Staff read, Office write) -------
    ("/api/commissioning/share_type_variation_price/", "get", "staff", "ok"),
    ("/api/commissioning/share_type_variation_price/", "get", "gardener", "ok"),
    ("/api/commissioning/share_type_variation_price/", "post", "staff", "deny"),
    ("/api/commissioning/share_type_variation_price/", "post", "gardener", "deny"),
    ("/api/commissioning/share_type_variation_price/", "post", "office", "4xx"),
    # ------- Virtual size components (Staff read, Office write) -------
    ("/api/commissioning/virtual_variation_components/", "get", "staff", "ok"),
    ("/api/commissioning/virtual_variation_components/", "get", "gardener", "ok"),
    ("/api/commissioning/virtual_variation_components/", "post", "staff", "deny"),
    ("/api/commissioning/virtual_variation_components/", "post", "gardener", "deny"),
    ("/api/commissioning/virtual_variation_components/", "post", "office", "4xx"),
    # ------- Shares (Staff read, Office write) -------
    # No create route: the write rows PATCH an unknown pk.
    ("/api/commissioning/shares/", "get", "staff", "ok"),
    ("/api/commissioning/shares/", "get", "gardener", "ok"),
    ("/api/commissioning/shares/unknown/", "patch", "staff", "deny"),
    ("/api/commissioning/shares/unknown/", "patch", "gardener", "deny"),
    ("/api/commissioning/shares/unknown/", "patch", "office", "4xx"),
    # ------- Share deliveries (StaffOrMember read, Office write) -------
    # The crew tier's 200 lists no member's deliveries: it is outside the owner
    # bypass of ``apps.authz.scoping``.
    (f"/api/commissioning/share_delivery/?{YEAR}", "get", "staff", "ok"),
    (f"/api/commissioning/share_delivery/?{YEAR}", "get", "gardener", "ok"),
    ("/api/commissioning/share_delivery/", "post", "staff", "deny"),
    ("/api/commissioning/share_delivery/", "post", "gardener", "deny"),
    ("/api/commissioning/share_delivery/", "post", "office", "4xx"),
    # ------- Share delivery overview (Staff read, Office write) -------
    ("/api/commissioning/share_delivery_overview/", "get", "staff", "ok"),
    ("/api/commissioning/share_delivery_overview/", "get", "gardener", "ok"),
    ("/api/commissioning/share_delivery_overview/", "post", "staff", "deny"),
    ("/api/commissioning/share_delivery_overview/", "post", "gardener", "deny"),
    ("/api/commissioning/share_delivery_overview/", "post", "office", "4xx"),
    # ------- Share delivery details (Staff read; reads only) -------
    (f"/api/commissioning/share_delivery_details/?{DAY}", "get", "staff", "ok"),
    (f"/api/commissioning/share_delivery_details/?{DAY}", "get", "gardener", "ok"),
    # ------- Default share contents (Staff read, Office write) -------
    (
        f"/api/commissioning/default_share_contents/bulk_list/?{YEAR}&{HARVEST}",
        "get",
        "gardener",
        "ok",
    ),
    ("/api/commissioning/default_share_contents/bulk_create/", "post", "staff", "deny"),
    (
        "/api/commissioning/default_share_contents/bulk_create/",
        "post",
        "gardener",
        "deny",
    ),
    ("/api/commissioning/default_share_contents/bulk_create/", "post", "office", "4xx"),
    # ------- Harvest share planning (Staff read, Office write) -------
    (
        f"/api/commissioning/harvest_share_planning/?{WEEK}&{HARVEST}",
        "get",
        "staff",
        "ok",
    ),
    (
        f"/api/commissioning/harvest_share_planning/?{WEEK}&{HARVEST}",
        "get",
        "gardener",
        "ok",
    ),
    ("/api/commissioning/harvest_share_planning/", "post", "staff", "deny"),
    ("/api/commissioning/harvest_share_planning/", "post", "gardener", "deny"),
    ("/api/commissioning/harvest_share_planning/", "post", "office", "4xx"),
    # ------- Packing lists (Staff read; reads only) -------
    (
        f"/api/commissioning/packing_list/?{DAY}&share_type=unknown",
        "get",
        "staff",
        "ok",
    ),
    (
        f"/api/commissioning/packing_list/?{DAY}&share_type=unknown",
        "get",
        "gardener",
        "ok",
    ),
    (f"/api/commissioning/packing_list_bulk/?{DAY}", "get", "staff", "ok"),
    (f"/api/commissioning/packing_list_bulk/?{DAY}", "get", "gardener", "ok"),
    # ------- Share content granularity (Staff read; GET only) -------
    (f"/api/commissioning/granularity/?{WEEK}", "get", "staff", "ok"),
    (f"/api/commissioning/granularity/?{WEEK}", "get", "gardener", "ok"),
    # ------- Size amounts for planning (Staff read; GET only) -------
    (
        "/api/commissioning/share_type_variation_amounts_for_planning/"
        f"?{WEEK}&{HARVEST}",
        "get",
        "staff",
        "ok",
    ),
    (
        "/api/commissioning/share_type_variation_amounts_for_planning/"
        f"?{WEEK}&{HARVEST}",
        "get",
        "gardener",
        "ok",
    ),
    # ======= commissioning: documentation =======
    # ------- Washing amounts (Staff read, Office write) -------
    ("/api/commissioning/theoretical_wash_amounts/", "get", "staff", "ok"),
    ("/api/commissioning/theoretical_wash_amounts/", "get", "gardener", "ok"),
    ("/api/commissioning/theoretical_wash_amounts/", "post", "staff", "deny"),
    ("/api/commissioning/theoretical_wash_amounts/", "post", "gardener", "deny"),
    ("/api/commissioning/theoretical_wash_amounts/", "post", "office", "4xx"),
    # ------- Cleaning amounts (Staff read, Office write) -------
    ("/api/commissioning/theoretical_clean_amounts/", "get", "staff", "ok"),
    ("/api/commissioning/theoretical_clean_amounts/", "get", "gardener", "ok"),
    ("/api/commissioning/theoretical_clean_amounts/", "post", "staff", "deny"),
    ("/api/commissioning/theoretical_clean_amounts/", "post", "gardener", "deny"),
    ("/api/commissioning/theoretical_clean_amounts/", "post", "office", "4xx"),
    # ======= cultivation (Staff read, CanEditCultivation write) =======
    # The write gate admits the gardener and the office but not staff.
    # ------- Bed types -------
    ("/api/cultivation/bed_types/", "get", "staff", "ok"),
    ("/api/cultivation/bed_types/", "get", "gardener", "ok"),
    ("/api/cultivation/bed_types/", "post", "staff", "deny"),
    ("/api/cultivation/bed_types/", "post", "gardener", "4xx"),
    ("/api/cultivation/bed_types/", "post", "office", "4xx"),
    # ------- Plots -------
    # The write rows name an unknown pk: an empty POST creates a plot.
    ("/api/cultivation/plots/", "get", "staff", "ok"),
    ("/api/cultivation/plots/", "get", "gardener", "ok"),
    ("/api/cultivation/plots/unknown/", "delete", "staff", "deny"),
    ("/api/cultivation/plots/unknown/", "delete", "gardener", "4xx"),
    ("/api/cultivation/plots/unknown/", "delete", "office", "4xx"),
    # ------- Plot contents -------
    ("/api/cultivation/plot_contents/", "get", "staff", "ok"),
    ("/api/cultivation/plot_contents/", "get", "gardener", "ok"),
    ("/api/cultivation/plot_contents/", "post", "staff", "deny"),
    ("/api/cultivation/plot_contents/", "post", "gardener", "4xx"),
    ("/api/cultivation/plot_contents/", "post", "office", "4xx"),
    # ------- Vegetables -------
    ("/api/cultivation/vegetables/", "get", "staff", "ok"),
    ("/api/cultivation/vegetables/", "get", "gardener", "ok"),
    ("/api/cultivation/vegetables/", "post", "staff", "deny"),
    ("/api/cultivation/vegetables/", "post", "gardener", "4xx"),
    ("/api/cultivation/vegetables/", "post", "office", "4xx"),
    # ------- Vegetable aggregations -------
    ("/api/cultivation/vegetable_aggregations/", "get", "staff", "ok"),
    ("/api/cultivation/vegetable_aggregations/", "get", "gardener", "ok"),
    ("/api/cultivation/vegetable_aggregations/", "post", "staff", "deny"),
    ("/api/cultivation/vegetable_aggregations/", "post", "gardener", "4xx"),
    ("/api/cultivation/vegetable_aggregations/", "post", "office", "4xx"),
    # ------- Cultivation break families -------
    ("/api/cultivation/cultivation_break_families/", "get", "staff", "ok"),
    ("/api/cultivation/cultivation_break_families/", "get", "gardener", "ok"),
    ("/api/cultivation/cultivation_break_families/", "post", "staff", "deny"),
    ("/api/cultivation/cultivation_break_families/", "post", "gardener", "4xx"),
    ("/api/cultivation/cultivation_break_families/", "post", "office", "4xx"),
    # ------- Cultivation batches -------
    ("/api/cultivation/cultivation_batches/", "get", "staff", "ok"),
    ("/api/cultivation/cultivation_batches/", "get", "gardener", "ok"),
    ("/api/cultivation/cultivation_batches/", "post", "staff", "deny"),
    ("/api/cultivation/cultivation_batches/", "post", "gardener", "4xx"),
    ("/api/cultivation/cultivation_batches/", "post", "office", "4xx"),
    # ------- Historical plantings -------
    ("/api/cultivation/historical_plantings/", "get", "staff", "ok"),
    ("/api/cultivation/historical_plantings/", "get", "gardener", "ok"),
    ("/api/cultivation/historical_plantings/", "post", "staff", "deny"),
    ("/api/cultivation/historical_plantings/", "post", "gardener", "4xx"),
    ("/api/cultivation/historical_plantings/", "post", "office", "4xx"),
    # ------- Seed vendors -------
    ("/api/cultivation/seeds_vendors/", "get", "staff", "ok"),
    ("/api/cultivation/seeds_vendors/", "get", "gardener", "ok"),
    ("/api/cultivation/seeds_vendors/", "post", "staff", "deny"),
    ("/api/cultivation/seeds_vendors/", "post", "gardener", "4xx"),
    ("/api/cultivation/seeds_vendors/", "post", "office", "4xx"),
    # ------- Seedling vendors -------
    ("/api/cultivation/seedlings_vendors/", "get", "staff", "ok"),
    ("/api/cultivation/seedlings_vendors/", "get", "gardener", "ok"),
    ("/api/cultivation/seedlings_vendors/", "post", "staff", "deny"),
    ("/api/cultivation/seedlings_vendors/", "post", "gardener", "4xx"),
    ("/api/cultivation/seedlings_vendors/", "post", "office", "4xx"),
    # ------- Solver settings -------
    # An empty PATCH keeps every setting and answers 200.
    ("/api/cultivation/solver_settings/", "get", "staff", "ok"),
    ("/api/cultivation/solver_settings/", "get", "gardener", "ok"),
    ("/api/cultivation/solver_settings/save/", "patch", "staff", "deny"),
    ("/api/cultivation/solver_settings/save/", "patch", "gardener", "ok"),
    ("/api/cultivation/solver_settings/save/", "patch", "office", "ok"),
    # ------- Plan solutions -------
    ("/api/cultivation/plan_solutions/", "get", "staff", "ok"),
    ("/api/cultivation/plan_solutions/", "get", "gardener", "ok"),
    ("/api/cultivation/plan_solutions/run/", "post", "staff", "deny"),
    ("/api/cultivation/plan_solutions/run/", "post", "gardener", "4xx"),
    ("/api/cultivation/plan_solutions/run/", "post", "office", "4xx"),
    # ======= staff (Staff read, Office write) =======
    # ------- Employees -------
    ("/api/staff/employees/", "get", "staff", "ok"),
    ("/api/staff/employees/", "get", "gardener", "ok"),
    ("/api/staff/employees/", "post", "staff", "deny"),
    ("/api/staff/employees/", "post", "gardener", "deny"),
    ("/api/staff/employees/", "post", "office", "4xx"),
    # ------- Absence categories -------
    ("/api/staff/absence_categories/", "get", "staff", "ok"),
    ("/api/staff/absence_categories/", "get", "gardener", "ok"),
    ("/api/staff/absence_categories/", "post", "staff", "deny"),
    ("/api/staff/absence_categories/", "post", "gardener", "deny"),
    ("/api/staff/absence_categories/", "post", "office", "4xx"),
    # ------- Weekly plan categories -------
    ("/api/staff/weekly_plan_categories/", "get", "staff", "ok"),
    ("/api/staff/weekly_plan_categories/", "get", "gardener", "ok"),
    ("/api/staff/weekly_plan_categories/", "post", "staff", "deny"),
    ("/api/staff/weekly_plan_categories/", "post", "gardener", "deny"),
    ("/api/staff/weekly_plan_categories/", "post", "office", "4xx"),
    # ------- Weekly plan -------
    # The grid read is in ``MATRIX``.
    ("/api/staff/weekly_plan/", "post", "staff", "deny"),
    ("/api/staff/weekly_plan/", "post", "gardener", "deny"),
    ("/api/staff/weekly_plan/", "post", "office", "4xx"),
    # ======= tenants =======
    # ------- Tenant email config (Office read, Admin write) -------
    # The office reads the config but may not repoint the SMTP host; the crew
    # tier is in neither gate.
    ("/api/tenants/email_config/", "get", "staff", "deny"),
    ("/api/tenants/email_config/", "get", "gardener", "deny"),
    ("/api/tenants/email_config/", "get", "office", "ok"),
    ("/api/tenants/email_config/save/", "patch", "staff", "deny"),
    ("/api/tenants/email_config/save/", "patch", "gardener", "deny"),
    ("/api/tenants/email_config/save/", "patch", "office", "deny"),
    ("/api/tenants/email_config/save/", "patch", "admin", "ok"),
    # ------- Tenant (any logged-in read, Admin write) -------
    # Every logged-in user reads their own tenant row. The write rows name an
    # unknown pk.
    ("/api/tenants/tenants/", "get", "staff", "ok"),
    ("/api/tenants/tenants/", "get", "gardener", "ok"),
    ("/api/tenants/tenants/unknown/", "patch", "staff", "deny"),
    ("/api/tenants/tenants/unknown/", "patch", "gardener", "deny"),
    ("/api/tenants/tenants/unknown/", "patch", "office", "deny"),
    ("/api/tenants/tenants/unknown/", "patch", "admin", "4xx"),
]


@pytest.mark.parametrize("path,method,role,expected", CREW_MATRIX)
def test_crew_route_permission_matrix(tenant, path, method, role, expected):
    check_route(path, method, role, expected)


CREW_ROLES = frozenset({"staff", "gardener"})
READ_METHODS = frozenset({"get", "head", "options"})


def _routed_views():
    """Yield ``(view class, HTTP methods it serves)`` for every tenant route."""

    def walk(patterns):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns)
            elif isinstance(pattern, URLPattern):
                yield pattern

    for pattern in walk(get_resolver().url_patterns):
        view_class = getattr(pattern.callback, "cls", None)
        if view_class is None:
            continue
        # A router route maps methods to actions; an APIView serves the
        # handlers it defines. ``http_method_names`` narrows both.
        allowed = set(view_class.http_method_names)
        actions = getattr(pattern.callback, "actions", None)
        if actions:
            yield view_class, set(actions) & allowed
        else:
            yield view_class, {name for name in allowed if hasattr(view_class, name)}


def test_every_view_with_split_gates_has_crew_rows():
    """A routed view whose read and write gates differ has a crew-role read row,
    and a crew-role write row when it routes a write, in ``MATRIX`` or
    ``CREW_MATRIX``."""
    crew_rows: dict[type, set[str]] = {}
    for path, method, role, _expected in [*MATRIX, *CREW_MATRIX]:
        if role in CREW_ROLES:
            view_class = resolve(urlsplit(path).path).func.cls
            side = "read" if method in READ_METHODS else "write"
            crew_rows.setdefault(view_class, set()).add(side)

    routed_writes: dict[type, bool] = {}
    for view_class, methods in _routed_views():
        read_gate = getattr(view_class, "read_permission", None)
        write_gate = getattr(view_class, "write_permission", None)
        if read_gate is write_gate:
            continue
        routes_write = bool(methods - READ_METHODS)
        routed_writes[view_class] = routed_writes.get(view_class, False) or routes_write

    missing = []
    for view_class, routes_write in sorted(
        routed_writes.items(), key=lambda item: item[0].__qualname__
    ):
        sides = crew_rows.get(view_class, set())
        needed = {"read", "write"} if routes_write else {"read"}
        if needed - sides:
            missing.append(f"{view_class.__qualname__}: {sorted(needed - sides)}")
    assert not missing, (
        "Views with differing read and write gates lack staff/gardener rows:\n"
        + "\n".join(missing)
    )
