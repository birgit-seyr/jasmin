"""Errors of the market price lists and their scale export."""

from __future__ import annotations

from decimal import Decimal

from core.errors import BadRequestError, ConflictError


class ScaleUnitUnsupported(ConflictError):
    """The scale export has a PLU sold by the gram or the litre: the scale
    weighs by the kg or counts, so it couldn't charge that price.
    ``details.plu_numbers`` names the PLUs."""

    code = "scale_unit.unsupported"

    def __init__(self, *, plu_numbers: list[int]) -> None:
        listed = ", ".join(str(number) for number in plu_numbers)
        super().__init__(
            f"The scale can't sell PLU {listed} in its unit.",
            details={"plu_numbers": listed},
        )


class ScaleTaxCodeMissing(BadRequestError):
    """A new PLU saved without a scale VAT code takes the code of its share
    article's VAT rate, or of the farm's default rate; ``details.tax_rate``
    names the rate the scale has no code for yet."""

    code = "scale_tax_code.missing"

    def __init__(self, *, tax_rate: Decimal) -> None:
        rate = f"{tax_rate.normalize():f}"
        super().__init__(
            f"The scale has no VAT code for {rate} %.",
            field="scale_tax_code",
            details={"tax_rate": rate},
        )
