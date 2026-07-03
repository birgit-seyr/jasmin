"""Render a ConsentDocument to an immutable PDF (WeasyPrint).

First actual use of WeasyPrint in the backend — its native deps (pango / cairo
/ gdk-pixbuf) already ship in the runtime image (see jasmin-core/django-core/
Dockerfile). Called once per document version via ``ConsentDocument.ensure_pdf``
(the body is append-only, so the render is a stable legal artifact).
"""

from __future__ import annotations

import html
import re

from django.core.files.base import ContentFile

# A leading ``<tag>`` anywhere means the body is HTML (tenant convention:
# "store it as-shown"); otherwise treat it as plain text and preserve its line
# breaks with ``white-space: pre-wrap`` instead of collapsing them.
_LOOKS_LIKE_HTML = re.compile(r"<[a-zA-Z!/][^>]*>")

_PAGE_CSS = """
  @page { size: A4; margin: 2.5cm; }
  body { font-family: sans-serif; font-size: 11pt; line-height: 1.5; color: #111; }
  h1 { font-size: 18pt; margin: 0 0 6px; }
  .meta { font-size: 9pt; color: #666; margin-bottom: 20px; }
  .footer { margin-top: 28px; padding-top: 8px; border-top: 1px solid #ccc;
            font-size: 8pt; color: #888; word-break: break-all; }
"""

# Minimal per-locale labels for the header (backend render has no i18n; only
# de/en ship). Falls back to en.
_LABELS = {
    "de": {"version": "Version", "valid_from": "gültig ab"},
    "en": {"version": "Version", "valid_from": "valid from"},
}


def render_consent_pdf(document) -> ContentFile:
    """Return a ``ContentFile`` of the document's ``body`` rendered to PDF.

    Header is the document's **title**, then its **version**, then its
    **valid_from** date; the body follows. The SHA-256 stays in the footer as
    the integrity anchor.
    """
    from weasyprint import HTML  # heavy import — keep local to the call

    body = document.body or ""
    if _LOOKS_LIKE_HTML.search(body):
        body_block = body
    else:
        body_block = f'<div style="white-space: pre-wrap">{html.escape(body)}</div>'

    labels = _LABELS.get(document.locale, _LABELS["en"])
    # Fall back to kind only if a document genuinely has no title.
    title = html.escape(document.title or document.kind)
    version_line = html.escape(f"{labels['version']} {document.version}")
    valid_from_line = html.escape(f"{labels['valid_from']}: {document.valid_from}")
    footer = html.escape(f"SHA-256: {document.body_sha256}")

    full_html = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_PAGE_CSS}</style></head><body>"
        f"<h1>{title}</h1>"
        f"<div class='meta'>{version_line}<br/>{valid_from_line}</div>"
        f"<div class='doc-body'>{body_block}</div>"
        f"<div class='footer'>{footer}</div>"
        f"</body></html>"
    )

    pdf_bytes = HTML(string=full_html).write_pdf()
    return ContentFile(pdf_bytes)
