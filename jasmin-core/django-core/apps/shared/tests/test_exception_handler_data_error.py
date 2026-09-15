"""``core.exception_handler`` maps Django's ``DataError`` to a 400.

A value the database refuses for its column (too long, out of range, not
castable) is almost always client input the request validation let through.
The response carries a stable code and a generic message: the database text
can quote the rejected value, so it must never reach the client.
"""

from __future__ import annotations

import logging

from django.db import DataError

from core import exception_handler
from core.exception_handler import jasmin_exception_handler


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_data_error_maps_to_400_without_leaking_the_database_text():
    exc = DataError('invalid input syntax for type integer: "secret-value"')

    response = jasmin_exception_handler(exc, {})

    assert response is not None
    assert response.status_code == 400
    assert response.data["code"] == "data.value_invalid"
    assert "secret-value" not in str(response.data)
    assert "integer" not in str(response.data)


def test_data_error_is_logged_at_error_level_with_the_traceback():
    """Before the 400 mapping a DataError took the 500 path, which logs with
    ``logger.exception`` and so reaches Sentry as an event. Sentry turns only
    ERROR records into events, so the 400 path keeps that level: a DataError
    can also come from a server-side bug, not only from client input."""
    handler = _RecordingHandler()
    exception_handler.logger.addHandler(handler)
    try:
        jasmin_exception_handler(DataError("numeric field overflow"), {})
    finally:
        exception_handler.logger.removeHandler(handler)

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
