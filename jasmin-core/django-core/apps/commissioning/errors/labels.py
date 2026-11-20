"""Errors refusing a label template the labels couldn't be printed from."""

from __future__ import annotations

from core.errors import BadRequestError


class LabelElementInvalid(BadRequestError):
    """A label element lacks a value, names an unknown field or carries a value
    of the wrong kind or out of range. ``details`` names the element's index and
    the offending key."""

    code = "label_template.element_invalid"


class LabelElementOutside(BadRequestError):
    """A label element reaches beyond the label's edges. ``details`` names the
    element's index."""

    code = "label_template.element_outside"


class LabelSheetTooLarge(BadRequestError):
    """The sheet's columns and rows of labels, with their margins and gaps, are
    larger than an A4 page. ``details`` carries the size they need, in mm."""

    code = "label_template.sheet_too_large"
