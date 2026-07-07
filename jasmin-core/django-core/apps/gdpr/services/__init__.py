"""GDPR service layer, split by concern.

``GDPRService`` is assembled here from four mixins so every existing
``from apps.gdpr.services import GDPRService`` import keeps working:

* :mod:`.retention` — Art. 17(3)(b) retention pre-flight checks.
* :mod:`.subject_access` — the Art. 15 SAR bundle builder.
* :mod:`.anonymization` — the Art. 17 anonymization engine.
* :mod:`.deletion_workflow` — the two-step deletion state machine.
* :mod:`.preview` — persona detection + the pre-execute deletion dry-run.

The module-level deletion-email senders live in :mod:`.deletion_emails`
and are re-exported here unchanged.
"""

from __future__ import annotations

import logging

from . import anonymization, deletion_workflow, preview, retention, subject_access
from .anonymization import AnonymizationMixin
from .deletion_emails import (
    send_deletion_approved_email,
    send_deletion_confirmation_email,
    send_deletion_pending_admin_office_email,
    send_deletion_rejected_email,
)
from .deletion_workflow import DeletionWorkflowMixin
from .preview import Persona, PreviewMixin
from .retention import RetentionChecksMixin
from .subject_access import SubjectAccessMixin

logger = logging.getLogger("gdpr")


class GDPRService(
    RetentionChecksMixin,
    SubjectAccessMixin,
    AnonymizationMixin,
    DeletionWorkflowMixin,
    PreviewMixin,
):
    """Handles GDPR data operations: export and anonymization."""


# The mixin method bodies reference ``GDPRService.<attr>`` for their
# cross-concern calls (and tests monkeypatch attributes on the assembled
# class), so those lookups must resolve through THIS class at call time.
# Each mixin module declares the name under ``if TYPE_CHECKING`` for static
# analysis; this loop provides the runtime binding.
for _mixin_module in (
    retention,
    subject_access,
    anonymization,
    deletion_workflow,
    preview,
):
    _mixin_module.GDPRService = GDPRService

__all__ = [
    "GDPRService",
    "Persona",
    "send_deletion_approved_email",
    "send_deletion_confirmation_email",
    "send_deletion_pending_admin_office_email",
    "send_deletion_rejected_email",
]
