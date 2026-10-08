"""Cross-cutting commissioning errors: finalization, bulk ids, uploaded
documents and past weeks."""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
)

# --------------------------------------------------------------------------- #
# Generic / cross-cutting                                                     #
# --------------------------------------------------------------------------- #


class CommissioningError(BadRequestError):
    """Base for any commissioning-domain validation failure (400)."""

    code = "commissioning.invalid"


class CompositeIdInvalid(BadRequestError):
    """A composite URL id (e.g. ``year_week_share_article_unit_size``) was
    malformed — wrong number of parts, or a non-numeric year/week. Callers pass
    a per-resource ``code`` so the failure is still attributable."""

    code = "composite_id.invalid"


class FinalizedError(ConflictError):
    """Operation rejected because the target document is already finalized."""

    code = "commissioning.already_finalized"


class BulkFinalizeModelInvalid(BadRequestError):
    """The generic bulk (un)finalize ``model`` is not a finalizable commissioning
    model: an unknown name, a model without finalization, or not a string."""

    code = "finalize.model_invalid"


class BulkFinalizeAppLabelInvalid(BadRequestError):
    """The generic bulk (un)finalize ``app_label`` is anything other than
    ``"commissioning"``, the only app whose models carry finalization."""

    code = "finalize.app_label_invalid"


class BulkIdsInvalid(BadRequestError):
    """A bulk-by-ids ``ids`` entry is not a non-empty string id."""

    code = "bulk.ids_invalid"


class BulkIdsTooMany(BadRequestError):
    """A bulk-by-ids request carries more ids than one call may process.

    Every id costs a row lock and a cascade inside a single transaction, so an
    unbounded list holds those locks for the whole batch and stalls concurrent
    office work. ``details`` carries the ``limit`` and the ``received`` count."""

    code = "bulk.ids_too_many"


class BulkFinalizeIdsInvalid(BulkIdsInvalid):
    """A generic bulk (un)finalize ``ids`` entry is not a string id."""

    code = "finalize.ids_invalid"


class DocumentNotFinalized(BadRequestError):
    """A PDF upload was attempted before the document was finalized.

    The inverse of ``FinalizedError``: ``upload_pdf`` requires the invoice /
    delivery note to be finalized first, since the stored file is the legal
    artifact of a finalized document.
    """

    code = "document.not_finalized"


class InvalidUploadedDocument(BadRequestError):
    """An uploaded document failed validation: wrong extension, content that is
    not a PDF / XML, or larger than the upload size limit."""

    code = "uploaded_document.invalid"


class DocumentPdfMissing(BadRequestError):
    """A send action was attempted before the document's PDF was uploaded.

    The document is finalized but no PDF file is stored yet, so there is
    nothing to attach to the reseller email.
    """

    code = "document.pdf_missing"


class PastWeekError(ConflictError):
    """Operation rejected because the target week is in the past.

    ``Conflict`` (409) rather than 400: the request itself is well-formed —
    it's the state of the targeted week (already past/current) that forbids
    the change. Callers may override with ``force=True`` where the endpoint
    supports it.
    """

    code = "commissioning.past_week"
