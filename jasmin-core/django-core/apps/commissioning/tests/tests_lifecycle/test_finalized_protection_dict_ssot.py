"""SSOT pin for the FinalizedProtected one-way state at the MIGRATION-DICT layer.

Migration ``0002_finalized_protection_and_reference_data`` installs the Postgres
protection triggers from its ``PROTECTED_TABLES`` dict, which records the six
reseller-document *content* tables as ``one_way: False`` — the body it
originally installed. Migration ``0015_content_finalized_one_way`` LATER rebuilds
exactly those six trigger functions with ``one_way=True``, the effective state,
matching ``IS_FINALIZED_ONE_WAY = True`` on the models (GoBD / HGB §257 / UStG
§14: a finalized content line is legally immutable).

The live DB is therefore consistent, but 0002's dict on its own is a STALE
template: CLAUDE.md points future authors at it "as the shape to mirror", and
copying a content row's ``one_way: False`` verbatim into a NEW trigger migration
would silently un-protect legally-immutable lines.

This test complements ``test_finalized_allowlist_sync`` (model ↔ LIVE trigger,
which needs the trigger installed) by pinning the relationship at the
migration-dict layer with NO DB required: it reconstructs the EFFECTIVE spec
(0002's base with 0015's override layered on) and asserts it equals what the
models declare. A bad edit to 0002 / 0015, or a flipped model flag, fails here
at import time — before it can reach a schema.
"""

from __future__ import annotations

import importlib

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
    DeliveryNoteContent,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
    Offer,
    Order,
    OrderContent,
)

_M0002 = importlib.import_module(
    "apps.commissioning.migrations.0002_finalized_protection_and_reference_data"
)
_M0015 = importlib.import_module(
    "apps.commissioning.migrations.0015_content_finalized_one_way"
)

# The six line-item content tables that 0015 flips to one-way.
_CONTENT_MODELS = {
    "commissioning_ordercontent": OrderContent,
    "commissioning_crateordercontent": CrateOrderContent,
    "commissioning_cratedeliverynotecontent": CrateDeliveryNoteContent,
    "commissioning_cratecontentinvoicereseller": CrateContentInvoiceReseller,
    "commissioning_deliverynotecontent": DeliveryNoteContent,
    "commissioning_invoiceresellercontent": InvoiceResellerContent,
}

# The non-content protected models: 0002's dict is already the effective state
# for these (no 0015 override), so its value must equal the model directly.
_NON_CONTENT_MODELS = {
    "commissioning_offer": Offer,
    "commissioning_order": Order,
    "commissioning_deliverynotereseller": DeliveryNoteReseller,
    "commissioning_invoicereseller": InvoiceReseller,
}


def _effective_one_way(table: str) -> bool:
    """0002's base ``one_way`` with 0015's content-table override layered on."""
    base = _M0002.PROTECTED_TABLES[table]["one_way"]
    if table in _M0015.CONTENT_TABLES:
        return True  # 0015 rebuilds these functions with one_way=True
    return base


class TestContentDictStaleButEffectiveOneWay:
    def test_0002_records_content_tables_as_not_one_way(self):
        """Pin the documented staleness: 0002's dict alone under-protects the
        content tables — the exact reason the annotation + 0015 exist."""
        for table in _CONTENT_MODELS:
            assert _M0002.PROTECTED_TABLES[table]["one_way"] is False, table

    def test_0015_overrides_exactly_the_content_tables(self):
        assert set(_M0015.CONTENT_TABLES) == set(_CONTENT_MODELS)

    def test_effective_one_way_matches_models(self):
        for table, model in _CONTENT_MODELS.items():
            assert _effective_one_way(table) is True, table
            assert model.IS_FINALIZED_ONE_WAY is True, model.__name__

    def test_content_tables_allow_nothing_but_is_finalized(self):
        for table, model in _CONTENT_MODELS.items():
            assert _M0002.PROTECTED_TABLES[table]["allowed"] == [], table
            assert list(model.ALLOWED_FINALIZED_UPDATES) == [], model.__name__


class TestNonContentDictIsEffective:
    def test_non_content_one_way_matches_models(self):
        for table, model in _NON_CONTENT_MODELS.items():
            assert (
                _effective_one_way(table)
                == _M0002.PROTECTED_TABLES[table]["one_way"]
                == bool(model.IS_FINALIZED_ONE_WAY)
            ), table

    def test_table_keys_match_model_db_tables(self):
        # Guard the string keys against a model table rename.
        for table, model in {**_CONTENT_MODELS, **_NON_CONTENT_MODELS}.items():
            assert model._meta.db_table == table, model.__name__
