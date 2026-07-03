"""Project-wide DRF exception handler.

Wired in ``settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]``. Translates every
exception that escapes a view into the canonical Jasmin error response::

    {
        "code":       "<stable machine-readable code>",
        "message":    "<human-readable, possibly translated>",
        "field":      "<optional, form-field name>",
        "details":    {...},      # optional, structured context
        "request_id": "<uuid>",   # added when request-id middleware is in place
    }

Translation table
-----------------
``core.errors.JasminError``           → ``exc.http_status`` + ``exc.to_dict()``
``django ValidationError``           → 400 (field map preserved in ``details``)
``django ObjectDoesNotExist``        → 404
``django IntegrityError``            → 409 (logged as warning — likely race)
DRF ``APIException`` & subclasses    → original status, payload normalised
Anything else                        → 500 with traceback logged, no ``str(exc)`` leak

The handler NEVER puts ``str(exc)`` into a 500 response — that's the main
reason it exists. If you want a specific message to reach the client, raise
a ``JasminError`` subclass.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .errors import (
    BadRequestError,
    ConflictError,
    JasminError,
    NotFoundError,
)

logger = logging.getLogger("jasmin.errors")


def jasmin_exception_handler(
    exc: Exception, context: dict[str, Any]
) -> Response | None:
    request = context.get("request")
    request_id = getattr(request, "id", None) if request is not None else None
    view = context.get("view")
    view_name = view.__class__.__name__ if view is not None else "<unknown>"

    if isinstance(exc, JasminError):
        return _respond(exc.to_dict(), exc.http_status, request_id, exc, view_name)

    if isinstance(exc, DjangoValidationError):
        return _respond(
            _django_validation_payload(exc),
            400,
            request_id,
            exc,
            view_name,
            log_level=logging.INFO,
        )

    if isinstance(exc, ObjectDoesNotExist):
        payload = NotFoundError(str(exc) or "Resource not found").to_dict()
        return _respond(
            payload, 404, request_id, exc, view_name, log_level=logging.INFO
        )

    if isinstance(exc, IntegrityError):
        # Almost always a unique/FK violation. Log it because they often
        # indicate a race condition or missing validation upstream.
        logger.warning(
            "IntegrityError in %s: %s",
            view_name,
            exc,
            extra={"request_id": request_id},
        )
        return _respond(
            ConflictError("Database integrity error").to_dict(),
            409,
            request_id,
            exc,
            view_name,
            log_level=None,  # already logged above
        )

    # Fall through to DRF's default handler (APIException, NotAuthenticated,
    # PermissionDenied, Throttled, serializers.ValidationError, ...)
    response = drf_exception_handler(exc, context)
    if response is not None:
        response.data = _normalise_drf_payload(exc, response.data, request_id)
        return response

    # Unhandled — bug. Log full traceback, return generic 500.
    logger.exception(
        "Unhandled exception in %s: %s",
        view_name,
        exc,
        extra={"request_id": request_id},
    )
    payload: dict[str, Any] = {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
    }
    if request_id:
        payload["request_id"] = request_id
    return Response(payload, status=500)


def _respond(
    payload: dict[str, Any],
    status: int,
    request_id: str | None,
    exc: Exception,
    view_name: str,
    *,
    log_level: int | None = logging.INFO,
) -> Response:
    if request_id:
        payload["request_id"] = request_id
    if log_level is not None:
        if status >= 500:
            logger.exception(
                "%s in %s: %s",
                type(exc).__name__,
                view_name,
                payload.get("message", ""),
                extra={"request_id": request_id, "code": payload.get("code")},
            )
        else:
            logger.log(
                log_level,
                "%s in %s: %s",
                type(exc).__name__,
                view_name,
                payload.get("message", ""),
                extra={"request_id": request_id, "code": payload.get("code")},
            )
    return Response(payload, status=status)


def _django_validation_payload(exc: DjangoValidationError) -> dict[str, Any]:
    if hasattr(exc, "message_dict"):
        details = dict(exc.message_dict)
        message = "Validation failed"
    else:
        messages = list(exc.messages)
        details = {"_errors": messages}
        message = messages[0] if messages else "Validation failed"
    return BadRequestError(message, code="validation_error", details=details).to_dict()


def _normalise_drf_payload(
    exc: Exception, data: Any, request_id: str | None
) -> dict[str, Any]:
    """Convert DRF's default error payload into our canonical shape.

    DRF emits several shapes:
        - ``{"detail": "..."}``                                  (most APIExceptions)
        - ``{"field_a": ["err1", "err2"], "field_b": [...]}``    (serializer errors)
        - ``["err1", "err2"]``                                   (non-field errors list)
        - ``"some string"``                                      (rare)
    We collapse all of them into ``{code, message, [field], [details]}``.
    """
    code = getattr(exc, "default_code", None) or "error"

    payload: dict[str, Any]
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        payload = {"code": code, "message": str(data["detail"])}
    elif isinstance(data, dict):
        # Serializer-style field errors. If exactly one field has errors,
        # surface that as `field` for the client; always keep the full map
        # in `details` so multi-field forms work too.
        single_field = next(iter(data)) if len(data) == 1 else None
        first_msg = _first_message(data)
        payload = {
            "code": "validation_error" if code == "invalid" else code,
            "message": first_msg or "Validation failed",
            "details": data,
        }
        if single_field and single_field != "non_field_errors":
            payload["field"] = single_field
    elif isinstance(data, list):
        payload = {
            "code": code,
            "message": str(data[0]) if data else "Request failed",
            "details": {"_errors": data},
        }
    else:
        payload = {"code": code, "message": str(data)}

    if request_id:
        payload["request_id"] = request_id
    return payload


def _first_message(data: dict[str, Any]) -> str | None:
    for value in data.values():
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            nested = _first_message(value)
            if nested:
                return nested
    return None
