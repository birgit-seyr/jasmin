"""Which uploaded e-invoice XML bodies the invoice upload stores, and which it
refuses.

The stored XML is emailed to the reseller and to accounting and served back
from the media store, where a browser renders it as an XML document. Only the
CII invoice the frontend generates passes: no DTD, no stylesheet, and nothing in
a namespace a browser runs script from.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.commissioning.services.einvoice_upload import _einvoice_xml_error

_CII_NAMESPACES = (
    'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
    'xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100" '
    'xmlns:ram="urn:un:unece:uncefact:data:standard:'
    'ReusableAggregateBusinessInformationEntity:100" '
    'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"'
)


def cii_invoice(
    *,
    document_id: str = "RE-2026-7",
    grand_total: str = "10.00",
    type_code: str = "380",
    prolog: str = "",
    inside: str = "",
) -> bytes:
    """A CII invoice shaped like the one ``zugferd.ts`` generates — its
    namespaces, an XML comment, a ``currencyID`` attribute. ``prolog`` goes
    between the XML declaration and the root, ``inside`` into the trade
    transaction."""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
{prolog}<rsm:CrossIndustryInvoice {_CII_NAMESPACES}>
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{document_id}</ram:ID>
    <ram:TypeCode>{type_code}</ram:TypeCode>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20260105</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>{inside}
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradePaymentTerms>
        <!-- BT-9: the due date receivers schedule their payment by -->
        <ram:Description>Payable within 14 days</ram:Description>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxTotalAmount currencyID="EUR">0.91</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{grand_total}</ram:GrandTotalAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
    return xml.encode()


def _in_utf16(raw: bytes) -> bytes:
    """``raw`` re-encoded as UTF-16, the encoding its declaration then names."""
    xml = raw.decode().replace('encoding="UTF-8"', 'encoding="UTF-16"', 1)
    return xml.encode("utf-16")


def _error(raw: bytes, *, name="invoice.xml", number=7, sum_brutto="10.00"):
    document = SimpleNamespace(number=number, sum_brutto=Decimal(sum_brutto))
    upload = SimpleUploadedFile(name, raw, content_type="application/xml")
    return _einvoice_xml_error(document, upload)


_STYLESHEET = '<?xml-stylesheet type="text/xsl" href="#transform"?>\n'


class TestAcceptedEinvoiceXml:
    def test_the_cii_invoice_the_frontend_generates_passes(self):
        assert _error(cii_invoice()) is None

    def test_a_credit_note_with_its_total_positive_passes(self):
        raw = cii_invoice(type_code="381")

        assert _error(raw, sum_brutto="-10.00") is None

    def test_a_utf8_byte_order_mark_passes(self):
        assert _error(b"\xef\xbb\xbf" + cii_invoice()) is None

    def test_elements_and_attributes_of_other_namespaces_pass(self):
        raw = cii_invoice(
            inside=(
                '<ext:Extension xmlns:ext="urn:example:extension" '
                'xmlns:ds="http://www.w3.org/2000/09/xmldsig#" ds:Id="sig-1">'
                "<ds:Signature/></ext:Extension>"
            )
        )

        assert _error(raw) is None

    def test_the_upload_is_rewound_for_storing(self):
        upload = SimpleUploadedFile("invoice.xml", cii_invoice())
        document = SimpleNamespace(number=7, sum_brutto=Decimal("10.00"))

        assert _einvoice_xml_error(document, upload) is None
        assert upload.read() == cii_invoice()


class TestEinvoiceXmlContradictingTheDocument:
    def test_a_wrong_number_is_reported(self):
        assert "number" in _error(cii_invoice(document_id="RE-2026-8"))

    def test_a_wrong_total_is_reported(self):
        assert "total" in _error(cii_invoice(grand_total="12.00"))


class TestRefusedEinvoiceXml:
    def test_a_file_not_named_xml_is_refused(self):
        assert ".xml" in _error(cii_invoice(), name="invoice.txt")

    @pytest.mark.parametrize(
        "raw",
        [
            b"<invoice",
            cii_invoice()[:400],
            b"",
            b"<h:script>alert(1)</h:script>",
        ],
        ids=["unclosed", "truncated", "empty", "unbound-prefix"],
    )
    def test_a_body_that_does_not_parse_is_refused(self, raw):
        assert "not well-formed" in _error(raw)

    @pytest.mark.parametrize(
        "prolog",
        [
            "<!DOCTYPE rsm:CrossIndustryInvoice>\n",
            '<!DOCTYPE x [<!ENTITY payload SYSTEM "file:///etc/passwd">]>\n',
            # An attribute default moves the unprefixed script into XHTML.
            "<!DOCTYPE rsm:CrossIndustryInvoice "
            '[<!ATTLIST script xmlns CDATA #FIXED "http://www.w3.org/1999/xhtml">]>\n',
        ],
        ids=["doctype", "external-entity", "namespace-attribute-default"],
    )
    def test_a_dtd_is_refused(self, prolog):
        raw = cii_invoice(prolog=prolog, inside="<script>alert(1)</script>")

        assert "DTD" in _error(raw)

    @pytest.mark.parametrize(
        "raw",
        [
            b'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
            b"<script>alert(1)</script></body></html>",
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">'
            b"<ID>RE-2026-7</ID></Invoice>",
            b'<rsm:Invoice xmlns:rsm="urn:example">'
            b"<rsm:ExchangedDocument><rsm:ID>RE-2026-7</rsm:ID></rsm:ExchangedDocument>"
            b"</rsm:Invoice>",
        ],
        ids=["xhtml", "svg", "ubl", "lookalike"],
    )
    def test_a_root_other_than_the_cii_invoice_is_refused(self, raw):
        assert "not a CII invoice" in _error(raw)

    @pytest.mark.parametrize(
        "inside",
        [
            '<h:script xmlns:h="http://www.w3.org/1999/xhtml">alert(1)</h:script>',
            '<div xmlns="http://www.w3.org/1999/xhtml">'
            '<img src="x" onerror="alert(1)"/></div>',
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            '<math xmlns="http://www.w3.org/1998/Math/MathML" '
            'href="javascript:alert(1)">x</math>',
            '<ram:Note xmlns:xlink="http://www.w3.org/1999/xlink" '
            'xlink:type="simple" xlink:href="javascript:alert(1)">x</ram:Note>',
        ],
        ids=["xhtml-prefixed", "xhtml-default", "svg", "mathml", "xlink-attribute"],
    )
    def test_active_content_inside_the_invoice_is_refused(self, inside):
        error = _error(cii_invoice(inside=inside))

        assert "XHTML, SVG, MathML or XLink" in error

    @pytest.mark.parametrize(
        "raw",
        [
            cii_invoice(prolog=_STYLESHEET),
            _in_utf16(cii_invoice(prolog=_STYLESHEET)),
            cii_invoice(inside=_STYLESHEET),
        ],
        ids=["prolog", "prolog-utf16", "inside"],
    )
    def test_a_stylesheet_processing_instruction_is_refused(self, raw):
        assert "stylesheet" in _error(raw)
