"""Tests for the factur-x PDF/A-3 conversion service.

The happy-path test needs the Ghostscript system binary (`gs`) and the
`factur-x` library; it skips cleanly when `gs` is absent so a CI runner without
it doesn't fail. The fallback tests are pure Python and always run.
"""

from __future__ import annotations

import shutil

import pytest

from apps.commissioning.services.facturx_pdfa3 import (
    FacturxConversionError,
    to_facturx_pdfa3,
)

_HAS_GS = shutil.which("gs") is not None
_needs_gs = pytest.mark.skipif(
    _HAS_GS is False, reason="Ghostscript ('gs') not installed"
)


# A minimal but structurally-complete EN 16931 CII invoice — enough fields for
# the factur-x library to build the XMP (document id / type / date, seller +
# buyer name, currency). Not XSD-strict (the service embeds with check_xsd
# off), which mirrors production where the KoSIT validator is authoritative.
_MINIMAL_FACTURX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>INV-TEST-1</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20260101</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>Test Seller GmbH</ram:Name>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>Test Buyer AG</ram:Name>
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""


def _sample_invoice_pdf() -> bytes:
    """A real, plain (non-PDF/A) invoice PDF, standing in for the @react-pdf
    upload: DeviceRGB colours, text, no OutputIntent."""
    from weasyprint import HTML

    return HTML(
        string="<h1 style='color:#2a6'>Invoice INV-TEST-1</h1><p>Total: 100.00 EUR</p>"
    ).write_pdf()


@_needs_gs
class TestToFacturxPdfa3:
    def test_produces_pdfa3_and_facturx_markers(self):
        from io import BytesIO

        import facturx
        from pypdf import PdfReader

        hybrid = to_facturx_pdfa3(_sample_invoice_pdf(), _MINIMAL_FACTURX_XML)
        assert isinstance(hybrid, bytes) and hybrid.startswith(b"%PDF")

        reader = PdfReader(BytesIO(hybrid))
        root = reader.trailer["/Root"]

        # PDF/A-3: an sRGB OutputIntent in the catalog (fixes the DeviceRGB and
        # transparency conformance failures at once).
        assert "/OutputIntents" in root

        # factur-x: the XML is attached as an associated file...
        assert "/AF" in root
        # ...and the pdfaid + factur-x XMP is present (decompress the stream).
        xmp = reader.xmp_metadata.stream.get_data().decode("utf-8", "replace")
        assert "pdfaid" in xmp
        assert "3" in xmp  # pdfaid:part = 3
        assert "factur-x" in xmp.lower() or "urn:factur-x" in xmp.lower()

        # The embedded XML round-trips out under its canonical filename.
        filename, extracted = facturx.get_facturx_xml_from_pdf(hybrid, check_xsd=False)
        assert filename == "factur-x.xml"
        assert b"CrossIndustryInvoice" in extracted

    def test_raises_on_unparseable_pdf(self):
        # Ghostscript can't make a PDF/A out of junk → the service surfaces a
        # typed error the caller can fall back on, never a raw subprocess error.
        with pytest.raises(FacturxConversionError):
            to_facturx_pdfa3(b"this is not a pdf", _MINIMAL_FACTURX_XML)


class TestServiceContractErrorWrapping:
    """The service must honour its docstring: EVERY failure surfaces as
    FacturxConversionError, never a raw OSError — otherwise the caller's
    ``except FacturxConversionError`` fallback would leak a 500. No gs needed."""

    def test_unexpected_oserror_from_gs_stage_is_wrapped(self, monkeypatch):
        # A disk-full temp dir / unreadable output surfaces from _to_pdfa3 as a
        # bare OSError; to_facturx_pdfa3 must convert it, not let it escape.
        def _raise_oserror(_pdf):
            raise OSError("No space left on device")

        monkeypatch.setattr(
            "apps.commissioning.services.facturx_pdfa3._to_pdfa3", _raise_oserror
        )

        with pytest.raises(FacturxConversionError):
            to_facturx_pdfa3(b"%PDF-1.4", _MINIMAL_FACTURX_XML)


class TestUploadFallback:
    """The upload path must never break because the post-process failed —
    regardless of WHICH failure it is (typed conversion error, unexpected
    exception, or an I/O error while reading the upload)."""

    @staticmethod
    def _patch_converter(monkeypatch, exc):
        # The helper imports to_facturx_pdfa3 lazily from source, so patch there.
        def _boom(*_a, **_k):
            raise exc

        monkeypatch.setattr(
            "apps.commissioning.services.facturx_pdfa3.to_facturx_pdfa3", _boom
        )

    def _run(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.commissioning.viewsets import resellers_viewsets

        pdf = SimpleUploadedFile(
            "inv.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        xml = SimpleUploadedFile("inv.xml", b"<x/>", content_type="application/xml")
        result = resellers_viewsets._embed_facturx_or_fallback(
            pdf, xml, invoice_pk="INV1"
        )
        return result, pdf, xml

    def test_falls_back_on_typed_conversion_error(self, monkeypatch):
        self._patch_converter(monkeypatch, FacturxConversionError("gs blew up"))
        result, pdf, xml = self._run()
        # Falls back to the SAME untouched upload, both handles rewound.
        assert result is pdf
        assert result.read() == b"%PDF-1.4 fake"
        assert xml.read() == b"<x/>"

    def test_falls_back_on_unexpected_exception(self, monkeypatch):
        # A non-FacturxConversionError (a bug, an OSError that slipped the
        # service) must STILL fall back, not 500 the upload.
        self._patch_converter(monkeypatch, RuntimeError("unexpected boom"))
        result, pdf, xml = self._run()
        assert result is pdf
        assert result.read() == b"%PDF-1.4 fake"
        assert xml.read() == b"<x/>"

    def test_falls_back_on_read_error(self):
        # An I/O error reading a disk-backed TemporaryUploadedFile must not
        # escape the helper — it falls back to the (same) raw upload.
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.commissioning.viewsets import resellers_viewsets

        class _ExplodingFile:
            name = "inv.pdf"

            def __init__(self):
                self.seeks = 0

            def read(self, *_a):
                raise OSError("read failed")

            def seek(self, *_a):
                self.seeks += 1

        pdf = _ExplodingFile()
        xml = SimpleUploadedFile("inv.xml", b"<x/>", content_type="application/xml")

        # Must not raise, and returns the raw (exploding) upload for storage.
        result = resellers_viewsets._embed_facturx_or_fallback(
            pdf, xml, invoice_pk="INV1"
        )
        assert result is pdf
        assert pdf.seeks >= 1  # rewound in the finally despite the read error
        assert xml.read() == b"<x/>"  # xml handle rewound too
