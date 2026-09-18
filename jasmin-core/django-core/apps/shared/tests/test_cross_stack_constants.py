"""Guard: the numbers the frontend restates must match the backend's.

A few constants are declared on BOTH sides of the wire on purpose, because the
client needs them before it can ask the server — a picker that greys out what
the API would refuse, a fallback applied before a tenant has configured its
own. That duplication is deliberate, but neither language notices when one side
moves, so a VAT change or a raised cap can land on one side alone and stay
silently wrong. These assertions are what notices.

The frontend values are read out of the TypeScript source rather than imported,
for the same reason ``test_error_code_i18n_coverage`` reads the locale JSON:
it is the only way a Python test can see them.

Not every repeated number belongs here. ``ID_LENGTH`` is duplicated across the
apps deliberately and is already pinned by ``test_jasmin_model_consistency``;
two page sizes that happen to both be 5 are coincidence, not one rule.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.commissioning.constants import DEFAULT_CRATE_TAX_RATE, DEFAULT_TAX_RATE
from apps.commissioning.views.statistic_views import _MAX_PURCHASE_COST_SPAN_YEARS

# This file lives at apps/shared/tests/<file>, so django-core is three up.
DJANGO_CORE = Path(__file__).resolve().parents[3]
REACT_SRC = DJANGO_CORE.parent / "react-core" / "src"

TAX_RATES_MODULE = (
    REACT_SRC / "shared" / "hooks" / "configuration" / "useDefaultTaxRates.ts"
)
PURCHASE_RANGE_MODULE = (
    REACT_SRC / "features" / "commissioning" / "utils" / "purchaseCostRange.ts"
)


def _numeric_const(path: Path, name: str) -> float:
    """The value of a module-level ``const NAME = <number>`` in a TS module.

    Fails loudly when the file or the constant is gone: a guard that silently
    finds nothing is worse than no guard, because it reads as green.
    """
    if not path.exists():
        pytest.fail(
            f"{path} no longer exists. This guard pins a constant declared "
            "there — point it at whatever replaced the module."
        )
    match = re.search(
        rf"^(?:export )?const {re.escape(name)}\s*(?::\s*number\s*)?=\s*(-?[\d.]+)\s*;",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        pytest.fail(
            f"{name} was renamed or removed from {path.name}. Update this guard "
            "alongside whatever replaced it, so the two sides stay pinned."
        )
    return float(match[1])


class TestDefaultTaxRatesMatchAcrossTheWire:
    """``useDefaultTaxRates`` resolves the tenant's configured rate and falls
    back to these literals; the backend falls back to the same numbers through
    ``get_default_tax_rate_articles`` / ``get_default_tax_rate_crates``. A VAT
    change has to move both, and only office staff on a tenant with no
    configured rate would ever see them disagree.
    """

    def test_the_article_fallback_matches(self):
        assert (
            _numeric_const(TAX_RATES_MODULE, "DEFAULT_TAX_RATE_ARTICLES")
            == DEFAULT_TAX_RATE
        )

    def test_the_crate_fallback_matches(self):
        assert (
            _numeric_const(TAX_RATES_MODULE, "DEFAULT_TAX_RATE_CRATES")
            == DEFAULT_CRATE_TAX_RATE
        )

    def test_the_share_fallback_matches_the_article_rate(self):
        """The backend declares no shares-specific default: ``DEFAULT_TAX_RATE``
        serves articles and shares alike, while the frontend splits them so a
        tenant can configure the two apart."""
        assert (
            _numeric_const(TAX_RATES_MODULE, "DEFAULT_TAX_RATE_SHARES")
            == DEFAULT_TAX_RATE
        )


class TestPurchaseCostRangeMatchesTheServerCap:
    def test_the_picker_bound_matches_the_server_cap(self):
        """``purchase_cost_by_week`` walks one iteration per ISO week, so the
        server caps the span and 400s past it; the picker greys out the same
        range so the bound is never met as an error. Raising the server cap
        without the client would hide range the report can now serve.
        """
        assert (
            _numeric_const(PURCHASE_RANGE_MODULE, "MAX_PURCHASE_COST_RANGE_YEARS")
            == _MAX_PURCHASE_COST_SPAN_YEARS
        )
