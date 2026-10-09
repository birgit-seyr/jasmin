"""A crate line is one crate type at one price, rabatt and tax rate, and every
write addresses that line alone.

The crate summaries of delivery notes, invoices and orders show one line per
crate type, price, rabatt and tax rate, named ``{crate type id}_{row id}``.
These tests put two lines of one crate type on a document — a crate billed at
2.00 and, after a price change, at 2.50 — act on one line and check that the
other is untouched, and that a bare crate type id still names every line of
its type.
"""

from __future__ import annotations

import re
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from django.db.models import Q
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
)
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.services.order_service import OrderService
from apps.commissioning.tests.factories import (
    CrateFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
)

TAX = Decimal("19.00")


def _line_id(crate, *rows) -> str:
    return f"{crate.id}_{min(str(row.pk) for row in rows)}"


# ---------------------------------------------------------------------------
# Delivery notes and invoices
# ---------------------------------------------------------------------------


@pytest.fixture(params=["delivery_note", "invoice"])
def document(request, tenant):
    """A draft delivery note or invoice with a crate type, and what a test needs
    to read and write its crate lines through that document's endpoints."""
    crate = CrateFactory()
    if request.param == "delivery_note":
        parent = DeliveryNoteResellerFactory(
            order=OrderFactory(reseller=ResellerFactory())
        )
        return SimpleNamespace(
            url=reverse("crate_delivery_note_content-list"),
            detail="crate_delivery_note_content-detail",
            retrieve_url=reverse("delivery_notes-detail", args=[parent.id]),
            parent_key="delivery_note_id",
            parent_field="delivery_note",
            model=CrateDeliveryNoteContent,
            parent=parent,
            crate=crate,
            make_sibling=lambda: DeliveryNoteResellerFactory(
                order=OrderFactory(reseller=ResellerFactory())
            ),
        )
    parent = InvoiceResellerFactory()
    return SimpleNamespace(
        url=reverse("crate_invoice_content-list"),
        detail="crate_invoice_content-detail",
        retrieve_url=reverse("invoices-detail", args=[parent.id]),
        parent_key="invoice_id",
        parent_field="invoice",
        model=CrateContentInvoiceReseller,
        parent=parent,
        crate=crate,
        make_sibling=InvoiceResellerFactory,
    )


def _row(document, amount, price, rabatt=0, **fields):
    return document.model.objects.create(
        **{document.parent_field: document.parent},
        crate_type=document.crate,
        amount=amount,
        price_per_unit=Decimal(price),
        rabatt=rabatt,
        tax_rate=TAX,
        **fields,
    )


def _rows(document, price=None):
    rows = document.model.objects.filter(
        **{document.parent_field: document.parent}, crate_type=document.crate
    )
    return list(rows if price is None else rows.filter(price_per_unit=Decimal(price)))


def _body(document, **fields):
    return {
        document.parent_key: str(document.parent.id),
        "crate_type": str(document.crate.id),
        **fields,
    }


def _lines(api_client, document):
    resp = api_client.get(document.url, {document.parent_key: str(document.parent.id)})
    assert resp.status_code == status.HTTP_200_OK, resp.data
    return {line["price_per_unit"]: line for line in resp.data}


def _patch(api_client, document, line_id, **fields):
    return api_client.patch(
        reverse(document.detail, args=[line_id]),
        _body(document, **fields),
        format="json",
    )


def _delete(api_client, document, line_id):
    """DELETE a line with the document and crate type as query parameters, as
    the crate tables send them."""
    query = urlencode(
        {document.parent_key: document.parent.id, "crate_type": document.crate.id}
    )
    return api_client.delete(f"{reverse(document.detail, args=[line_id])}?{query}")


@pytest.mark.django_db
class TestDocumentCrateLineIds:
    def test_each_line_has_its_own_id_and_keeps_it_through_a_price_edit(
        self, api_client, document
    ):
        old = _row(document, 5, "2.00")
        new = _row(document, 3, "2.50")

        lines = _lines(api_client, document)

        assert lines["2.00"]["id"] == _line_id(document.crate, old)
        assert lines["2.50"]["id"] == _line_id(document.crate, new)
        assert {line["crate_type"] for line in lines.values()} == {document.crate.id}
        assert all(re.fullmatch(r"[^/.]+", line["id"]) for line in lines.values())
        # The document itself lists the same lines under the same ids.
        retrieved = api_client.get(document.retrieve_url).data["crate_items"]
        assert sorted(line["id"] for line in retrieved) == sorted(
            line["id"] for line in lines.values()
        )

        resp = _patch(
            api_client, document, lines["2.50"]["id"], amount=3, price_per_unit="2.60"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _lines(api_client, document)["2.60"]["id"] == lines["2.50"]["id"]

    def test_a_patch_changes_only_the_line_it_names(self, api_client, document):
        old = _row(document, 5, "2.00")
        new = _row(document, 3, "2.50")

        resp = _patch(
            api_client,
            document,
            _line_id(document.crate, new),
            amount=4,
            price_per_unit="2.50",
            rabatt=10,
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["id"] == _line_id(document.crate, new)
        assert resp.data["amount"] == 4
        assert resp.data["rabatt"] == 10.0
        old.refresh_from_db()
        assert (old.amount, old.price_per_unit, old.rabatt) == (5, Decimal("2.00"), 0)
        band = _rows(document, "2.50")
        assert sum(row.amount for row in band) == 4
        assert {row.rabatt for row in band} == {10}

    def test_a_price_edit_keeps_the_line_whole(self, api_client, document):
        """The line is scoped by its rows, not by its old price: after the new
        price is stamped the line still has its rows, so nothing is added."""
        old = _row(document, 5, "2.00")
        first = _row(document, 2, "2.50")
        second = _row(document, 1, "2.50")

        resp = _patch(
            api_client,
            document,
            _line_id(document.crate, first, second),
            amount=3,
            price_per_unit="2.70",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert sorted(row.pk for row in _rows(document, "2.70")) == sorted(
            (first.pk, second.pk)
        )
        assert sum(row.amount for row in _rows(document, "2.70")) == 3
        assert [row.pk for row in _rows(document, "2.00")] == [old.pk]
        assert resp.data["amount"] == 3

    def test_the_row_naming_a_line_survives_a_reduction(self, api_client, document):
        first = _row(document, 3, "2.50")
        second = _row(document, 3, "2.50")
        named, other = sorted((first, second), key=lambda row: str(row.pk))

        resp = _patch(
            api_client, document, _line_id(document.crate, named, other), amount=3
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["id"] == _line_id(document.crate, named)
        assert [row.pk for row in _rows(document)] == [named.pk]
        assert not document.model.objects.filter(pk=other.pk).exists()

    def test_zeroing_a_line_of_one_row_deletes_it_with_its_crate_only_document(
        self, api_client, document
    ):
        row = _row(document, 3, "2.50")
        line_id = _line_id(document.crate, row)

        resp = _patch(api_client, document, line_id, amount=0)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["id"] == line_id
        assert resp.data["amount"] == 0
        assert not document.model.objects.filter(pk=row.pk).exists()
        assert not type(document.parent).objects.filter(pk=document.parent.pk).exists()

    def test_setting_a_line_to_another_lines_price_merges_them(
        self, api_client, document
    ):
        old = _row(document, 5, "2.00")
        new = _row(document, 3, "2.50")

        resp = _patch(
            api_client,
            document,
            _line_id(document.crate, new),
            amount=3,
            price_per_unit="2.00",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        lines = _lines(api_client, document)
        assert list(lines) == ["2.00"]
        assert lines["2.00"]["amount"] == 8
        assert lines["2.00"]["id"] == _line_id(document.crate, old, new)
        assert resp.data["id"] == lines["2.00"]["id"]

    def test_a_delete_removes_only_the_line_it_names(self, api_client, document):
        old = _row(document, 5, "2.00")
        new = _row(document, 3, "2.50")

        resp = _delete(api_client, document, _line_id(document.crate, new))

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert [row.pk for row in _rows(document)] == [old.pk]

    def test_a_bare_crate_type_id_still_names_every_line_of_the_type(
        self, api_client, document
    ):
        """A page that still lists one line per crate type sends the crate
        type id; the write covers every line of that type."""
        _row(document, 5, "2.00")
        _row(document, 3, "2.50")

        resp = _patch(
            api_client, document, document.crate.id, amount=6, price_per_unit="2.20"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        rows = _rows(document)
        assert sum(row.amount for row in rows) == 6
        assert {row.price_per_unit for row in rows} == {Decimal("2.20")}
        # The answer is the line the write left, named as the list names it.
        assert resp.data["id"] == _line_id(document.crate, *rows)
        assert _lines(api_client, document)["2.20"]["id"] == resp.data["id"]

        resp = _delete(api_client, document, document.crate.id)

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert _rows(document) == []

    def test_a_line_whose_row_is_gone_is_refused_while_other_lines_remain(
        self, api_client, document
    ):
        old = _row(document, 5, "2.00")
        gone = _row(document, 3, "2.50")
        line_id = _line_id(document.crate, gone)
        document.model.objects.filter(pk=gone.pk).delete()

        patched = _patch(api_client, document, line_id, amount=4)
        deleted = _delete(api_client, document, line_id)

        assert patched.status_code == status.HTTP_409_CONFLICT
        assert patched.data["code"] == "crate_line.changed"
        assert deleted.status_code == status.HTTP_409_CONFLICT
        assert deleted.data["code"] == "crate_line.changed"
        old.refresh_from_db()
        assert (old.amount, old.price_per_unit) == (5, Decimal("2.00"))
        assert [row.pk for row in _rows(document)] == [old.pk]

    def test_a_line_whose_row_is_gone_is_written_anew_without_crates_of_the_type(
        self, api_client, document
    ):
        gone = _row(document, 3, "2.50")
        line_id = _line_id(document.crate, gone)
        document.model.objects.filter(pk=gone.pk).delete()

        resp = _patch(api_client, document, line_id, amount=4, price_per_unit="2.50")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        (written,) = _rows(document)
        assert (written.amount, written.price_per_unit) == (4, Decimal("2.50"))
        assert resp.data["id"] == _line_id(document.crate, written)

    def test_a_line_id_naming_another_documents_row_never_touches_it(
        self, api_client, document
    ):
        own = _row(document, 5, "2.00")
        foreign = document.model.objects.create(
            **{document.parent_field: document.make_sibling()},
            crate_type=document.crate,
            amount=7,
            price_per_unit=Decimal("2.00"),
            tax_rate=TAX,
        )

        patched = _patch(
            api_client, document, _line_id(document.crate, foreign), amount=1
        )
        deleted = _delete(api_client, document, _line_id(document.crate, foreign))

        assert patched.status_code == status.HTTP_409_CONFLICT
        assert deleted.status_code == status.HTTP_409_CONFLICT
        foreign.refresh_from_db()
        own.refresh_from_db()
        assert (foreign.amount, own.amount) == (7, 5)

    @pytest.mark.parametrize("line_id", ["abc_", "_abc", "abc_def_ghi"])
    def test_a_malformed_line_id_is_refused(self, api_client, document, line_id):
        row = _row(document, 5, "2.00")

        patched = _patch(api_client, document, line_id, amount=1)
        deleted = _delete(api_client, document, line_id)

        assert patched.status_code == status.HTTP_400_BAD_REQUEST
        assert patched.data["code"] == "crate_line.invalid_id"
        assert deleted.status_code == status.HTTP_400_BAD_REQUEST
        assert deleted.data["code"] == "crate_line.invalid_id"
        row.refresh_from_db()
        assert row.amount == 5

    def test_a_line_of_another_crate_type_is_refused(self, api_client, document):
        row = _row(document, 5, "2.00")
        other_line = f"{CrateFactory().id}_{row.pk}"

        patched = _patch(api_client, document, other_line, amount=1)
        deleted = _delete(api_client, document, other_line)

        assert patched.status_code == status.HTTP_400_BAD_REQUEST
        assert patched.data["code"] == "crate_line.invalid_id"
        assert deleted.status_code == status.HTTP_400_BAD_REQUEST
        row.refresh_from_db()
        assert row.amount == 5

    def test_create_answers_with_the_line_of_its_new_row(self, api_client, document):
        _row(document, 5, "2.00")

        resp = api_client.post(
            document.url,
            _body(document, amount=3, price_per_unit="2.50"),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        (created,) = _rows(document, "2.50")
        assert resp.data["id"] == _line_id(document.crate, created)
        assert resp.data["amount"] == 3
        assert resp.data["price_per_unit"] == "2.50"
        assert _lines(api_client, document)["2.50"]["id"] == resp.data["id"]


@pytest.mark.django_db
class TestDocumentCrateLineNotes:
    def test_an_update_writes_its_note_on_every_row_of_its_line(
        self, api_client, document
    ):
        other = _row(document, 5, "2.00", note="Other line")
        first = _row(document, 2, "2.50")
        second = _row(document, 1, "2.50")

        resp = _patch(
            api_client,
            document,
            _line_id(document.crate, first, second),
            amount=3,
            note="Pallet",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert {row.note for row in _rows(document, "2.50")} == {"Pallet"}
        other.refresh_from_db()
        assert other.note == "Other line"

    @pytest.mark.parametrize("amount", [2, 5])
    def test_an_amount_change_keeps_the_notes_of_the_line(
        self, api_client, document, amount
    ):
        """A write without a note leaves the notes of the line as they are,
        on the rows that take the change too."""
        named = _row(document, 2, "2.50", note="Pallet", id="A" * 12)
        other = _row(document, 1, "2.50", note="Bring back", id="B" * 12)

        resp = _patch(
            api_client, document, _line_id(document.crate, named), amount=amount
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        notes = {row.pk: row.note for row in _rows(document)}
        assert notes[named.pk] == "Pallet"
        assert notes.get(other.pk, "Bring back") == "Bring back"
        assert set(notes.values()) <= {"Pallet", "Bring back"}

    def test_a_line_of_one_row_keeps_its_note_through_an_amount_change(
        self, api_client, document
    ):
        row = _row(document, 2, "2.50", note="Pallet")

        resp = _patch(api_client, document, _line_id(document.crate, row), amount=4)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        row.refresh_from_db()
        assert (row.amount, row.note) == (4, "Pallet")

    def test_a_line_written_anew_takes_the_note_sent_with_it(
        self, api_client, document
    ):
        gone = _row(document, 3, "2.50")
        line_id = _line_id(document.crate, gone)
        document.model.objects.filter(pk=gone.pk).delete()

        resp = _patch(
            api_client,
            document,
            line_id,
            amount=4,
            price_per_unit="2.50",
            note="Pallet",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        (written,) = _rows(document)
        assert written.note == "Pallet"

    def test_a_line_written_anew_without_a_note_has_none(self, api_client, document):
        resp = _patch(api_client, document, document.crate.id, amount=4)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        (written,) = _rows(document)
        assert not written.note

    def test_the_crate_lines_and_the_document_show_each_lines_note(
        self, api_client, document
    ):
        """The note column reads the summary, so the note stays visible after
        the document is read again."""
        _row(document, 5, "2.00", note="Pallet")
        _row(document, 3, "2.50")

        lines = _lines(api_client, document)
        retrieved = api_client.get(document.retrieve_url)

        assert {price: line["note"] for price, line in lines.items()} == {
            "2.00": "Pallet",
            "2.50": None,
        }
        assert retrieved.status_code == status.HTTP_200_OK, retrieved.data
        assert {
            line["price_per_unit"]: line["note"]
            for line in retrieved.data["crate_items"]
        } == {"2.00": "Pallet", "2.50": None}

    def test_an_update_answers_with_its_lines_note(self, api_client, document):
        row = _row(document, 2, "2.50")

        resp = _patch(
            api_client, document, _line_id(document.crate, row), amount=2, note="Pallet"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["note"] == "Pallet"


@pytest.mark.django_db
class TestSummaryInvoiceAcrossACratePriceChange:
    def test_one_price_band_is_corrected_on_its_own(self, api_client, tenant):
        """A summary invoice over two delivery notes bills a crate at the old
        and at the new price as two lines; correcting the new band's amount and
        price leaves the old band as it was."""
        reseller = ResellerFactory()
        crate = CrateFactory()
        delivery_notes = []
        for week, amount, price in ((15, 5, "2.00"), (16, 3, "2.50")):
            order = OrderFactory(
                reseller=reseller, year=2026, delivery_week=week, day_number=2
            )
            CrateOrderContent.objects.create(
                order=order,
                crate_type=crate,
                amount=amount,
                price_per_unit=Decimal(price),
                tax_rate=TAX,
            )
            delivery_note = DeliveryNoteService.create_from_order(order=order)
            DeliveryNoteService.finalize_delivery_note(delivery_note)
            delivery_notes.append(delivery_note)
        invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes=delivery_notes
        )
        url = reverse("crate_invoice_content-list")
        lines = {
            line["price_per_unit"]: line
            for line in api_client.get(url, {"invoice_id": str(invoice.id)}).data
        }
        assert set(lines) == {"2.00", "2.50"}
        assert lines["2.00"]["id"] != lines["2.50"]["id"]

        resp = api_client.patch(
            reverse("crate_invoice_content-detail", args=[lines["2.50"]["id"]]),
            {
                "invoice_id": str(invoice.id),
                "crate_type": str(crate.id),
                "amount": 4,
                "price_per_unit": "2.60",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["id"] == lines["2.50"]["id"]
        rows = CrateContentInvoiceReseller.objects.filter(invoice=invoice)
        assert sorted((row.price_per_unit, row.amount) for row in rows) == [
            (Decimal("2.00"), 5),
            (Decimal("2.60"), 4),
        ]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
PERIOD = {"year": 2026, "delivery_week": 15, "day_number": 2}


@pytest.fixture
def order(tenant):
    return OrderFactory(reseller=ResellerFactory(), **PERIOD)


def _order_body(order, **fields):
    return {**PERIOD, "reseller": str(order.reseller_id), **fields}


def _offer_bound_row(order, crate, amount, price="2.50", **fields):
    """A deposit row derived from an offer line, as the order line save makes it."""
    return CrateOrderContent.objects.create(
        order_content=OrderContentFactory(order=order),
        crate_type=crate,
        amount=amount,
        price_per_unit=Decimal(price),
        tax_rate=TAX,
        **fields,
    )


def _direct_row(order, crate, amount, price="2.50", rabatt=None, **fields):
    """A row added on the order's crate tab."""
    return CrateOrderContent.objects.create(
        order=order,
        crate_type=crate,
        amount=amount,
        price_per_unit=Decimal(price),
        rabatt=rabatt,
        tax_rate=TAX,
        **fields,
    )


def _order_rows(order, crate):
    return list(
        CrateOrderContent.objects.filter(
            Q(order=order) | Q(order_content__order=order), crate_type=crate
        )
    )


def _order_patch(api_client, order, line_id, **fields):
    return api_client.patch(
        reverse("crate_contents-detail", args=[line_id]),
        _order_body(order, **fields),
        format="json",
    )


def _order_delete(api_client, order, line_id):
    query = urlencode({**PERIOD, "reseller": order.reseller_id, "order_id": order.id})
    return api_client.delete(
        f"{reverse('crate_contents-detail', args=[line_id])}?{query}"
    )


@pytest.mark.django_db
class TestOrderCrateLineIds:
    def test_setting_a_line_of_two_rows_gives_the_line_that_amount(
        self, api_client, order
    ):
        crate = CrateFactory()
        first = _offer_bound_row(order, crate, 2)
        second = _offer_bound_row(order, crate, 1)

        resp = _order_patch(api_client, order, _line_id(crate, first, second), amount=5)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["amount"] == 5
        assert sum(row.amount for row in _order_rows(order, crate)) == 5
        # The offer-bound rows stay as their order lines made them; the
        # difference sits on a row added to the order.
        first.refresh_from_db()
        second.refresh_from_db()
        assert (first.amount, second.amount) == (2, 1)
        (added,) = CrateOrderContent.objects.filter(order=order, crate_type=crate)
        assert added.amount == 2

    def test_a_direct_line_edit_leaves_the_offer_bound_line_alone(
        self, api_client, order
    ):
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)
        direct = _direct_row(order, crate, 2, rabatt=10)

        resp = _order_patch(
            api_client, order, _line_id(crate, direct), amount=3, rabatt=10
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["id"] == _line_id(crate, direct)
        deposit.refresh_from_db()
        assert (deposit.amount, deposit.rabatt, deposit.price_per_unit) == (
            4,
            None,
            Decimal("2.50"),
        )
        direct.refresh_from_db()
        assert (direct.amount, direct.rabatt) == (3, 10)

    def test_a_bare_crate_type_id_sets_the_type_total(self, api_client, order):
        crate = CrateFactory()
        _offer_bound_row(order, crate, 2)
        _offer_bound_row(order, crate, 1)

        resp = _order_patch(api_client, order, crate.id, amount=5)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert sum(row.amount for row in _order_rows(order, crate)) == 5
        lines = api_client.get(reverse("crate_contents-list"), _order_body(order)).data
        assert [line["id"] for line in lines] == [resp.data["id"]]

    def test_a_reduction_below_a_lines_deposit_crates_is_refused(
        self, api_client, order
    ):
        """Deposit crates come with their order line, which sets them anew
        whenever it is saved, so a reduction below them is refused: the
        office changes the order line instead."""
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)
        direct = _direct_row(order, crate, 2)

        resp = _order_patch(
            api_client, order, _line_id(crate, deposit, direct), amount=3
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "crate_line.offer_bound"
        assert resp.data["details"] == {"offer_bound_amount": 4}
        deposit.refresh_from_db()
        direct.refresh_from_db()
        assert (deposit.amount, direct.amount) == (4, 2)

    def test_a_bare_crate_type_id_cannot_lower_the_deposit_crates(
        self, api_client, order
    ):
        crate = CrateFactory()
        _offer_bound_row(order, crate, 2)
        _offer_bound_row(order, crate, 1)

        resp = _order_patch(api_client, order, crate.id, amount=2)

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "crate_line.offer_bound"
        assert sum(row.amount for row in _order_rows(order, crate)) == 3

    @pytest.mark.parametrize("named", ["deposit", "direct"])
    @pytest.mark.parametrize(("amount", "direct_left"), [(5, 1), (4, 0)])
    def test_a_reduction_comes_off_the_rows_added_to_the_order(
        self, api_client, order, named, amount, direct_left
    ):
        """The crates come off the rows added directly to the order; the
        deposit rows keep what their order line made. When the row that named
        the line goes, the answer names the line by a row it keeps."""
        crate = CrateFactory()
        named_id, other_id = "A" * 12, "B" * 12
        deposit = _offer_bound_row(
            order, crate, 4, id=named_id if named == "deposit" else other_id
        )
        direct = _direct_row(
            order, crate, 2, id=named_id if named == "direct" else other_id
        )

        resp = _order_patch(
            api_client, order, _line_id(crate, deposit, direct), amount=amount
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        rows = _order_rows(order, crate)
        assert resp.data["amount"] == amount
        assert resp.data["id"] == _line_id(crate, *rows)
        deposit.refresh_from_db()
        assert deposit.amount == 4
        assert sum(row.amount for row in rows if row.order_id) == direct_left
        assert all(row.amount > 0 for row in rows)

    def test_an_increase_on_a_deposit_line_carries_the_note_sent(
        self, api_client, order
    ):
        """The note goes on the crates added to the order; the deposit row
        takes none, as its order line would drop it on its next save."""
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)

        resp = _order_patch(
            api_client, order, _line_id(crate, deposit), amount=6, note="Pallet"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["note"] == "Pallet"
        deposit.refresh_from_db()
        assert deposit.note is None
        (added,) = CrateOrderContent.objects.filter(order=order, crate_type=crate)
        assert (added.amount, added.note) == (2, "Pallet")

    def test_an_increase_without_a_note_leaves_the_notes_alone(self, api_client, order):
        crate = CrateFactory()
        row = _direct_row(order, crate, 2, note="Pallet")

        resp = _order_patch(api_client, order, _line_id(crate, row), amount=5)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        row.refresh_from_db()
        assert (row.amount, row.note) == (5, "Pallet")

    def test_a_finalized_order_refuses_a_line_write(self, api_client, order):
        crate = CrateFactory()
        row = _direct_row(order, crate, 2)
        OrderService.finalize_order(order)

        resp = _order_patch(
            api_client, order, _line_id(crate, row), amount=5, price_per_unit="3.00"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "commissioning.already_finalized"
        row.refresh_from_db()
        assert (row.amount, row.price_per_unit) == (2, Decimal("2.50"))

    def test_a_delete_removes_only_the_direct_rows_of_its_line(self, api_client, order):
        crate = CrateFactory()
        kept = _direct_row(order, crate, 2, price="2.00")
        removed = _direct_row(order, crate, 3)

        resp = _order_delete(api_client, order, _line_id(crate, removed))

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert [row.pk for row in _order_rows(order, crate)] == [kept.pk]

    @pytest.mark.parametrize("by_type", [False, True])
    def test_a_line_of_deposit_crates_alone_cannot_be_deleted(
        self, api_client, order, by_type
    ):
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)

        resp = _order_delete(
            api_client, order, crate.id if by_type else _line_id(crate, deposit)
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "crate_line.offer_bound"
        assert resp.data["details"] == {"offer_bound_amount": 4}
        assert _order_rows(order, crate) == [deposit]

    def test_a_delete_takes_the_added_crates_off_a_deposit_line(
        self, api_client, order
    ):
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)
        _direct_row(order, crate, 2)

        resp = _order_delete(api_client, order, _line_id(crate, deposit))

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert _order_rows(order, crate) == [deposit]

    def test_a_line_whose_row_is_gone_is_refused(self, api_client, order):
        crate = CrateFactory()
        kept = _direct_row(order, crate, 2, price="2.00")
        gone = _direct_row(order, crate, 3)
        line_id = _line_id(crate, gone)
        CrateOrderContent.objects.filter(pk=gone.pk).delete()

        patched = _order_patch(api_client, order, line_id, amount=1)
        deleted = _order_delete(api_client, order, line_id)

        assert patched.status_code == status.HTTP_409_CONFLICT
        assert patched.data["code"] == "crate_line.changed"
        assert deleted.status_code == status.HTTP_409_CONFLICT
        kept.refresh_from_db()
        assert kept.amount == 2

    def test_a_malformed_line_id_is_refused(self, api_client, order):
        crate = CrateFactory()
        row = _direct_row(order, crate, 2)

        patched = _order_patch(api_client, order, f"{crate.id}_", amount=1)
        deleted = _order_delete(api_client, order, f"{crate.id}_")

        assert patched.status_code == status.HTTP_400_BAD_REQUEST
        assert patched.data["code"] == "crate_line.invalid_id"
        assert deleted.status_code == status.HTTP_400_BAD_REQUEST
        assert deleted.data["code"] == "crate_line.invalid_id"
        row.refresh_from_db()
        assert row.amount == 2

    def test_create_answers_with_the_line_of_its_new_row(self, api_client, order):
        crate = CrateFactory()
        _direct_row(order, crate, 2, price="2.00")

        resp = api_client.post(
            reverse("crate_contents-list"),
            _order_body(
                order, crate_type=str(crate.id), amount=3, price_per_unit="2.50"
            ),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        (created,) = CrateOrderContent.objects.filter(
            order=order, crate_type=crate, price_per_unit=Decimal("2.50")
        )
        assert resp.data["id"] == _line_id(crate, created)
        assert resp.data["amount"] == 3
        lines = api_client.get(reverse("crate_contents-list"), _order_body(order)).data
        assert resp.data["id"] in {line["id"] for line in lines}


@pytest.mark.django_db
class TestOrderCrateLineOfferBoundFields:
    """An order line rebuilds its deposit rows at the dated price with no rabatt
    and no note whenever it is saved, so a price, rabatt or note written onto
    them would not last: such a write is refused, and a note goes on the
    crates added directly to the order."""

    @pytest.mark.parametrize("mixed", [False, True])
    @pytest.mark.parametrize(
        "change", [{"price_per_unit": "3.00"}, {"rabatt": 10}], ids=["price", "rabatt"]
    )
    def test_a_price_or_rabatt_change_on_a_deposit_line_is_refused(
        self, api_client, order, mixed, change
    ):
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)
        rows = [deposit]
        if mixed:
            rows.append(_direct_row(order, crate, 2))

        resp = _order_patch(
            api_client,
            order,
            _line_id(crate, *rows),
            amount=6 if mixed else 4,
            **change,
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "crate_line.offer_bound_fields"
        assert resp.data["details"] == {"offer_bound_amount": 4}
        assert {
            (row.price_per_unit, row.rabatt) for row in _order_rows(order, crate)
        } == {(Decimal("2.50"), None)}

    def test_a_bare_crate_type_id_cannot_reprice_the_deposit_crates(
        self, api_client, order
    ):
        crate = CrateFactory()
        _offer_bound_row(order, crate, 4)

        resp = _order_patch(
            api_client, order, crate.id, amount=4, price_per_unit="3.00"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "crate_line.offer_bound_fields"

    def test_the_lines_own_values_sent_back_are_no_change(self, api_client, order):
        """The crate table sends the line's price and rabatt with every save; an
        amount change that sends them unchanged goes through."""
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)

        resp = _order_patch(
            api_client,
            order,
            _line_id(crate, deposit),
            amount=6,
            price_per_unit="2.50",
            rabatt=0,
            note="",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["amount"] == 6
        deposit.refresh_from_db()
        assert (deposit.amount, deposit.rabatt, deposit.note) == (4, None, None)

    def test_a_note_on_a_line_of_deposit_crates_alone_is_refused(
        self, api_client, order
    ):
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)

        resp = _order_patch(
            api_client, order, _line_id(crate, deposit), amount=4, note="Pallet"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "crate_line.offer_bound_fields"
        deposit.refresh_from_db()
        assert deposit.note is None

    def test_a_note_on_a_mixed_line_goes_on_its_added_crates(self, api_client, order):
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)
        direct = _direct_row(order, crate, 2)

        resp = _order_patch(
            api_client, order, _line_id(crate, deposit, direct), amount=6, note="Pallet"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["note"] == "Pallet"
        deposit.refresh_from_db()
        direct.refresh_from_db()
        assert (deposit.note, direct.note) == (None, "Pallet")

    def test_a_note_with_a_reduction_to_the_deposit_crates_is_refused(
        self, api_client, order
    ):
        """The reduction takes the added crates off, and the note with them."""
        crate = CrateFactory()
        deposit = _offer_bound_row(order, crate, 4)
        direct = _direct_row(order, crate, 2)

        resp = _order_patch(
            api_client, order, _line_id(crate, deposit, direct), amount=4, note="Pallet"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "crate_line.offer_bound_fields"
        direct.refresh_from_db()
        assert (direct.amount, direct.note) == (2, None)

    def test_a_line_of_added_crates_still_takes_a_new_price(self, api_client, order):
        crate = CrateFactory()
        direct = _direct_row(order, crate, 2)

        resp = _order_patch(
            api_client,
            order,
            _line_id(crate, direct),
            amount=2,
            price_per_unit="3.00",
            rabatt=5,
            note="Pallet",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        direct.refresh_from_db()
        assert (direct.price_per_unit, direct.rabatt, direct.note) == (
            Decimal("3.00"),
            5,
            "Pallet",
        )

    def test_the_crate_lines_say_how_many_crates_come_with_order_lines(
        self, api_client, order
    ):
        crate = CrateFactory()
        _offer_bound_row(order, crate, 4)
        _direct_row(order, crate, 2, note="Pallet")
        _direct_row(order, crate, 3, price="2.00")

        lines = api_client.get(reverse("crate_contents-list"), _order_body(order)).data

        assert {
            line["price_per_unit"]: (
                line["amount"],
                line["offer_bound_amount"],
                line["note"],
            )
            for line in lines
        } == {"2.50": (6, 4, "Pallet"), "2.00": (3, 0, None)}
