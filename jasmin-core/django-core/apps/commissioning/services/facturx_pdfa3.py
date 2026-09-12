"""Turn an uploaded invoice PDF + its EN 16931 CII XML into a conformant
factur-x (ZUGFeRD) PDF/A-3.

The frontend (`@react-pdf`) produces a plain, visually-correct invoice PDF plus
the matching CII XML, but that PDF is *not* a PDF/A-3 container: it has no
OutputIntent (so its DeviceRGB colours and transparency fail the profile), no
pdfaid metadata, and the XML is only loosely attached. veraPDF / KoSIT reject
it on all of those.

Two stages fix it:

1. **Ghostscript → PDF/A-3.** Normalises the PDF into PDF/A-3: embeds an sRGB
   OutputIntent (which satisfies both the DeviceRGB rule 6.2.4.3 and the
   transparency-blending rule 6.2.10), subsets/embeds the fonts, and writes the
   pdfaid XMP. The sRGB profile is shipped next to this module so the result
   doesn't depend on the Ghostscript install path.
2. **factur-x → hybrid.** The `facturx` library embeds the XML as the
   `factur-x.xml` associated file (AFRelationship=Data) and writes the factur-x
   XMP extension schema, so validators can extract and match it.

Every failure raises `FacturxConversionError` so the caller can fall back to
storing the un-converted upload — an invoice upload must never be dropped just
because the conformance post-process failed.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent / "facturx_assets"
_SRGB_ICC = _ASSETS / "srgb.icc"

# Ghostscript prologue: registers the shipped sRGB profile as the document's
# OutputIntent. Written to a temp file per run with the absolute ICC path baked
# in (pdfmark can't read a relative path reliably). Braces are doubled for
# str.format; ``{icc}`` is the only substitution.
_PDFA_DEF_PS_TEMPLATE = """%!
% Register the shipped sRGB profile as the PDF/A-3 OutputIntent.
/ICCProfile ({icc}) def

[/_objdef {{icc_stream}} /type /stream /OBJ pdfmark
[{{icc_stream}} << /N 3 >> /PUT pdfmark
[{{icc_stream}} ICCProfile (r) file /PUT pdfmark

[/_objdef {{OutputIntent}} /type /dict /OBJ pdfmark
[{{OutputIntent}} <<
  /Type /OutputIntent
  /S /GTS_PDFA1
  /DestOutputProfile {{icc_stream}}
  /OutputConditionIdentifier (sRGB)
  /Info (sRGB IEC61966-2.1)
>> /PUT pdfmark

[{{Catalog}} << /OutputIntents [ {{OutputIntent}} ] >> /PUT pdfmark
"""

# Conversion is CPU-bound and self-contained; a generous ceiling guards against
# a pathological input hanging the request thread.
_GS_TIMEOUT_SECONDS = 60


class FacturxConversionError(Exception):
    """The upload could not be turned into a conformant factur-x PDF/A-3."""


def _to_pdfa3(pdf_bytes: bytes) -> bytes:
    """Run Ghostscript to normalise ``pdf_bytes`` into a PDF/A-3 with an sRGB
    OutputIntent and embedded fonts."""
    if not _SRGB_ICC.exists():  # pragma: no cover - packaging guard
        raise FacturxConversionError(f"sRGB profile missing at {_SRGB_ICC}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        def_ps = tmp_path / "PDFA_def.ps"
        src.write_bytes(pdf_bytes)
        def_ps.write_text(_PDFA_DEF_PS_TEMPLATE.format(icc=_SRGB_ICC))

        try:
            subprocess.run(
                [
                    "gs",
                    # SAFER is on by default (GS 10.x). The ICC is read from
                    # inside the prologue via ``(path) file``, which SAFER blocks
                    # unless the path is explicitly permitted — grant just this
                    # one file rather than disabling SAFER wholesale.
                    f"--permit-file-read={_SRGB_ICC}",
                    "-dPDFA=3",
                    "-dBATCH",
                    "-dNOPAUSE",
                    "-dQUIET",
                    "-sColorConversionStrategy=RGB",
                    "-sDEVICE=pdfwrite",
                    "-dPDFACompatibilityPolicy=1",
                    f"-sOutputFile={out}",
                    str(def_ps),
                    str(src),
                ],
                check=True,
                capture_output=True,
                timeout=_GS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise FacturxConversionError("Ghostscript ('gs') is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise FacturxConversionError(
                "Ghostscript PDF/A-3 conversion timed out"
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", "replace")[:500]
            raise FacturxConversionError(
                f"Ghostscript PDF/A-3 conversion failed: {stderr}"
            ) from exc

        if not out.exists() or out.stat().st_size == 0:
            raise FacturxConversionError("Ghostscript produced no output")
        return out.read_bytes()


def to_facturx_pdfa3(
    pdf_bytes: bytes,
    xml_bytes: bytes,
    *,
    level: str = "en16931",
) -> bytes:
    """Build a conformant factur-x PDF/A-3 from a visual invoice PDF and its CII
    XML.

    Args:
        pdf_bytes: the uploaded, visually-correct invoice PDF.
        xml_bytes: the EN 16931 CII XML that matches it.
        level: factur-x conformance level (default ``"en16931"``).

    Returns:
        The hybrid PDF/A-3 bytes (visual PDF + embedded ``factur-x.xml``).

    Raises:
        FacturxConversionError: on any conversion/embedding failure, so the
            caller can fall back to storing the un-converted upload.
    """
    # Lazy import: keeps facturx/pypdf/lxml off unrelated import paths and lets
    # environments without the dep still import this module.
    try:
        import facturx
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise FacturxConversionError("factur-x library is not installed") from exc

    # Honour the documented contract: EVERY failure surfaces as
    # FacturxConversionError, never a raw OSError/subprocess error. This covers
    # not just the embedding step but also any filesystem error from _to_pdfa3
    # (temp-dir creation, write, read) that its own targeted handlers miss —
    # so the caller's `except FacturxConversionError` fallback is airtight.
    try:
        pdfa_bytes = _to_pdfa3(pdf_bytes)
        return facturx.generate_from_binary(
            pdfa_bytes,
            xml_bytes,
            flavor="factur-x",
            level=level,
            check_xsd=False,
            afrelationship="data",
        )
    except FacturxConversionError:
        raise
    except Exception as exc:
        raise FacturxConversionError(f"factur-x conversion failed: {exc}") from exc
