"""Unit tests for the shared PII display-masking helpers."""

from __future__ import annotations

import pytest

from apps.shared.pii_masking import mask_account_holder, mask_iban


@pytest.mark.parametrize(
    "value,expected",
    [
        ("DE89370400440532013000", "DE •••• 3000"),
        ("DE89 3704 0044 0532 0130 00", "DE •••• 3000"),  # spaces ignored
        ("AT611904300234573201", "AT •••• 3201"),
        ("", ""),
        (None, ""),
        ("AB12", "••••"),  # too short to reveal a tail
    ],
)
def test_mask_iban(value, expected):
    assert mask_iban(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Ada Lovelace", "A•• L•••••••"),
        ("Maria Muster", "M•••• M•••••"),
        ("X", "X"),  # single char keeps nothing to hide
        ("Acme GmbH & Co", "A••• G••• & C•"),
        ("", ""),
        (None, ""),
    ],
)
def test_mask_account_holder(value, expected):
    assert mask_account_holder(value) == expected
