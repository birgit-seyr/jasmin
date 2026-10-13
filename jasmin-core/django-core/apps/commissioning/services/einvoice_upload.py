"""Checks on the files the office uploads for a finalized delivery note or
invoice: the PDF, and the invoice's e-invoice XML.

Both are stored on the document, emailed to the reseller and to accounting, and
served back from the media store, where a browser opens an ``.xml`` file as an
XML document and runs any XHTML or SVG script in it. So the e-invoice XML is
parsed in full and held to what the frontend generates (``zugferd.ts``) and the
factur-x embedding takes: a UN/CEFACT CII invoice, without a DTD, without an
``xml-stylesheet`` processing instruction, and with nothing in a namespace a
browser runs script from.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from xml.etree.ElementTree import Element, ParseError, TreeBuilder

from defusedxml.ElementTree import DefusedXMLParser

from ..errors import DocumentNotFinalized, InvalidUploadedDocument, RequiredFieldMissing

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.core.files.uploadedfile import UploadedFile

    from ..models import DeliveryNoteReseller, InvoiceReseller

# Legit ``upload_pdf`` traffic is the frontend's own @react-pdf output
# (a real invoice is well under 2 MB), but the endpoint accepts arbitrary
# bytes from any authenticated client — so check the content, not just
# the filename, and cap the size. The stored file is emailed to resellers
# and accounting, which makes "malware named invoice.pdf" a real concern.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# The root of every e-invoice the frontend generates: CII D16B, the syntax of
# ZUGFeRD 2 / Factur-X, which the factur-x embedding requires. A credit note is
# the same root with TypeCode 381.
_CII_ROOT = (
    "{urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100}"
    "CrossIndustryInvoice"
)

# Namespaces a browser runs script from in an XML document: XHTML and SVG
# elements execute scripts and event handlers, and MathML and XLink carry links
# that may be ``javascript:`` URLs. None of them occurs in a CII invoice.
_ACTIVE_CONTENT_NAMESPACES = frozenset(
    {
        "http://www.w3.org/1999/xhtml",
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1998/Math/MathML",
        "http://www.w3.org/1999/xlink",
    }
)


class _ProcessingInstructionRecorder(TreeBuilder):
    """The default tree builder that also keeps the target of every processing
    instruction — the tree it builds drops them, the prolog's included."""

    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    def pi(self, target: str, text: str | None = None) -> Element[Any]:
        self.targets.append(target)
        return super().pi(target, text)


def validate_finalized_pdf_upload(
    document: DeliveryNoteReseller | InvoiceReseller,
    files: Mapping[str, UploadedFile[bytes]],
    *,
    doc_label: str,
    allow_xml: bool = False,
) -> tuple[UploadedFile[bytes], UploadedFile[bytes] | None]:
    """Shared pre-checks for the reseller ``upload_pdf`` actions.

    The document must be finalized and ``files`` must hold a ``file`` (``.pdf``,
    passing the size and magic-byte checks). With ``allow_xml``, an optional
    ``xml_file`` is checked as the document's e-invoice. Raises the matching
    typed error on failure; on success returns ``(uploaded_file, uploaded_xml)``
    where ``uploaded_xml`` is ``None`` unless ``allow_xml`` and one was sent.
    """
    if not document.is_finalized:
        raise DocumentNotFinalized(
            f"{doc_label} must be finalized before uploading PDF."
        )
    uploaded_file = files.get("file")
    if not uploaded_file:
        raise RequiredFieldMissing("No file provided.", field="file")
    pdf_error = _pdf_error(uploaded_file)
    if pdf_error:
        raise InvalidUploadedDocument(pdf_error, field="file")
    uploaded_xml = files.get("xml_file") if allow_xml else None
    if uploaded_xml:
        xml_error = _einvoice_xml_error(document, uploaded_xml)
        if xml_error:
            raise InvalidUploadedDocument(xml_error, field="xml_file")
    return uploaded_file, uploaded_xml


def _size_error(upload: UploadedFile[bytes]) -> str | None:
    if (upload.size or 0) > _MAX_UPLOAD_BYTES:
        return (
            f"{upload.name} exceeds the "
            f"{_MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit"
        )
    return None


def _pdf_error(upload: UploadedFile[bytes]) -> str | None:
    """Why the upload is not a PDF to store, or ``None`` when it passes."""
    if not (upload.name or "").lower().endswith(".pdf"):
        return "file must be a .pdf"
    size_error = _size_error(upload)
    if size_error:
        return size_error
    head = upload.read(5)
    upload.seek(0)
    if not head.startswith(b"%PDF-"):
        return "file content is not a PDF"
    return None


def _einvoice_xml_error(
    document: DeliveryNoteReseller | InvoiceReseller, upload: UploadedFile[bytes]
) -> str | None:
    """Why the upload can't be stored as the document's e-invoice XML, or
    ``None`` when it passes.

    The XML must parse, with every DTD refused: an e-invoice never carries
    one, and a DTD can declare entities or move an element into the XHTML
    namespace through an attribute default. Its root must be the CII invoice,
    no processing instruction may name a stylesheet, and no element or
    attribute may sit in a namespace a browser runs script from. It must then
    not contradict the document (see ``_einvoice_mismatch``).
    """
    if not (upload.name or "").lower().endswith(".xml"):
        return "xml_file must be a .xml"
    size_error = _size_error(upload)
    if size_error:
        return size_error
    raw = upload.read()
    upload.seek(0)

    recorder = _ProcessingInstructionRecorder()
    parser = DefusedXMLParser(target=recorder, forbid_dtd=True)
    try:
        parser.feed(raw)
        root: Element = parser.close()
    except (ParseError, ValueError, LookupError):
        # ValueError covers defusedxml's refusals and an encoding expat can't
        # read, LookupError an encoding Python doesn't know.
        return "uploaded e-invoice XML is not well-formed, or carries a DTD"

    if root.tag != _CII_ROOT:
        return "uploaded e-invoice XML is not a CII invoice"
    if any(target.lower() == "xml-stylesheet" for target in recorder.targets):
        return "uploaded e-invoice XML references a stylesheet"
    for element in root.iter():
        names = (element.tag, *element.attrib)
        if any(_namespace(name) in _ACTIVE_CONTENT_NAMESPACES for name in names):
            return "uploaded e-invoice XML carries XHTML, SVG, MathML or XLink"
    return _einvoice_mismatch(document, root)


def _namespace(name: str) -> str:
    return name[1:].partition("}")[0] if name.startswith("{") else ""


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _einvoice_mismatch(
    document: DeliveryNoteReseller | InvoiceReseller, root: Element
) -> str | None:
    """Cross-check that the e-invoice describes THIS finalized document, so a
    wrong or hand-edited e-invoice can't be stored and emailed in its place.

    Fails only on an unambiguous mismatch of the document number or the grand
    total. A missing element, or a credit note's positive total, is tolerated
    so a legitimate upload is never blocked by a format quirk.
    """
    doc_id, grand_total = _einvoice_number_and_total(root)

    # Number: compare the trailing segment after the last "-" (the XML id is
    # ``<prefix>-<number>``; the prefix itself may carry dashes / a year).
    number = document.number
    if number is not None and doc_id:
        xml_number = doc_id.rsplit("-", 1)[-1].strip()
        if xml_number and xml_number != str(number):
            return "uploaded e-invoice number does not match this document"

    # Total: compare magnitudes (a storno credit note is positive in the XML
    # but negative on the record), 1-cent tolerance.
    sum_brutto: Decimal | None
    try:
        sum_brutto = document.sum_brutto
    except (AttributeError, TypeError):
        sum_brutto = None
    if sum_brutto is not None and grand_total:
        try:
            if abs(abs(Decimal(grand_total)) - abs(Decimal(sum_brutto))) > Decimal(
                "0.01"
            ):
                return "uploaded e-invoice total does not match this document"
        except (InvalidOperation, ValueError, TypeError):
            pass

    return None


def _einvoice_number_and_total(root: Element) -> tuple[str | None, str | None]:
    """The invoice number (the first ``ID`` under ``ExchangedDocument``) and
    the grand total the e-invoice states, each ``None`` when it states none."""
    doc_id: str | None = None
    grand_total: str | None = None
    for element in root.iter():
        name = _local_name(element.tag)
        text = (element.text or "").strip()
        if name == "ExchangedDocument" and doc_id is None:
            for child in element.iter():
                child_text = (child.text or "").strip()
                if _local_name(child.tag) == "ID" and child_text:
                    doc_id = child_text
                    break
        elif name == "GrandTotalAmount" and text:
            grand_total = text
    return doc_id, grand_total
