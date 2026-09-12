"""Support-app domain errors — raised by views/services, rendered by
``core.exception_handler.jasmin_exception_handler``."""

from __future__ import annotations

from core.errors import BadRequestError, NotFoundError


class TicketNotFound(NotFoundError):
    code = "support.ticket_not_found"


class TicketReplyEmpty(BadRequestError):
    code = "support.reply_empty"


class InvalidTicketStatus(BadRequestError):
    code = "support.invalid_status"
