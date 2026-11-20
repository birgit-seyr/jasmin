"""The farm's label template: read by the staff who print the labels, kept by
an admin. Its elements must name a known field, fit on the label and, for a
free text or a QR code, carry content; on A4 sheets the labels with their
margins and gaps must fit on the page."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.authz.roles import Role
from apps.commissioning.models import LabelTemplate
from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("tenant")]

LIST = reverse("label_template-list")


def _client(role):
    client = APIClient()
    client.force_authenticate(user=JasminUserFactory(roles=[role]))
    return client


def _element(**values):
    return {
        "id": "el-1",
        "field": "article",
        "x_mm": 2,
        "y_mm": 3,
        "width_mm": 40,
        "height_mm": 8,
        **values,
    }


def _template(**values):
    return {
        "name": "Etikett",
        "width_mm": "70.0",
        "height_mm": "37.0",
        "elements": [_element()],
        **values,
    }


class TestWhoKeepsTheTemplate:
    def test_an_admin_creates_it_with_the_element_defaults(self):
        resp = _client(Role.ADMIN).post(LIST, _template(), format="json")

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        template = LabelTemplate.objects.get(pk=resp.data["id"])
        assert template.width_mm == Decimal("70.0")
        assert template.print_mode == LabelTemplate.PrintMode.LABEL_PRINTER
        assert template.elements == [
            {
                **_element(),
                "font_size_pt": 10,
                "bold": False,
                "align": "left",
                "text": "",
                "organic_prefix": True,
            }
        ]

    def test_the_office_reads_it_but_cannot_change_it(self):
        LabelTemplate.objects.create(name="Etikett", width_mm=70, height_mm=37)
        office = _client(Role.OFFICE)

        assert office.get(LIST).status_code == status.HTTP_200_OK
        refused = office.post(LIST, _template(), format="json")
        assert refused.status_code == status.HTTP_403_FORBIDDEN

    def test_it_cannot_be_deleted(self):
        template = LabelTemplate.objects.create(
            name="Etikett", width_mm=70, height_mm=37
        )

        resp = _client(Role.ADMIN).delete(
            reverse("label_template-detail", args=[template.pk])
        )

        assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


class TestTheElements:
    @pytest.mark.parametrize(
        "element, key",
        [
            (_element(field="price"), "field"),
            (_element(align="justify"), "align"),
            (_element(field="static_text", text="  "), "text"),
            (_element(field="qr_code"), "text"),
        ],
        ids=["unknown field", "unknown alignment", "blank text", "empty qr code"],
    )
    def test_an_invalid_element_is_refused(self, element, key):
        resp = _client(Role.ADMIN).post(
            LIST, _template(elements=[element]), format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "label_template.element_invalid"
        assert resp.data["details"] == {"index": 0, "key": key}

    def test_two_elements_cannot_share_an_id(self):
        resp = _client(Role.ADMIN).post(
            LIST, _template(elements=[_element(), _element(y_mm=20)]), format="json"
        )

        assert resp.data["code"] == "label_template.element_invalid"
        assert resp.data["details"] == {"index": 1, "key": "id"}

    def test_an_element_beyond_the_edge_is_refused(self):
        resp = _client(Role.ADMIN).post(
            LIST, _template(elements=[_element(x_mm=40, width_mm=31)]), format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "label_template.element_outside"

    def test_a_smaller_label_is_checked_against_the_stored_elements(self):
        template = LabelTemplate.objects.create(
            name="Etikett", width_mm=70, height_mm=37, elements=[_element()]
        )

        resp = _client(Role.ADMIN).patch(
            reverse("label_template-detail", args=[template.pk]),
            {"width_mm": "30.0"},
            format="json",
        )

        assert resp.data["code"] == "label_template.element_outside"

    def test_a_partial_update_names_an_element_s_missing_key(self):
        template = LabelTemplate.objects.create(
            name="Etikett", width_mm=70, height_mm=37, elements=[_element()]
        )
        element = _element()
        del element["width_mm"]

        resp = _client(Role.ADMIN).patch(
            reverse("label_template-detail", args=[template.pk]),
            {"elements": [element]},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "label_template.element_invalid"
        assert resp.data["details"] == {"index": 0, "key": "width_mm"}

    def test_a_partial_update_stores_the_element_defaults(self):
        template = LabelTemplate.objects.create(
            name="Etikett", width_mm=70, height_mm=37, elements=[]
        )

        resp = _client(Role.ADMIN).patch(
            reverse("label_template-detail", args=[template.pk]),
            {"elements": [_element()]},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        template.refresh_from_db()
        assert template.elements[0]["font_size_pt"] == 10
        assert template.elements[0]["organic_prefix"] is True


class TestTheSheet:
    def test_labels_that_fill_the_page_fit(self):
        resp = _client(Role.ADMIN).post(
            LIST,
            _template(
                print_mode="sheet",
                sheet_columns=3,
                sheet_rows=8,
                sheet_margin_top_mm="0.5",
            ),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_labels_beyond_the_page_are_refused(self):
        resp = _client(Role.ADMIN).post(
            LIST,
            _template(print_mode="sheet", sheet_columns=3, sheet_gap_x_mm="1.0"),
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "label_template.sheet_too_large"
        assert resp.data["details"]["width_mm"] == "212.0"

    def test_a_label_printer_has_no_sheet_to_fit(self):
        resp = _client(Role.ADMIN).post(
            LIST,
            _template(sheet_columns=10, sheet_rows=30),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
