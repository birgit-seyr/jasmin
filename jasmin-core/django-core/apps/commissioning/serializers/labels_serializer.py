from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers
from rest_framework.fields import empty

from ..errors import LabelElementInvalid, LabelElementOutside, LabelSheetTooLarge
from ..models import LabelTemplate

# The information a label element shows. The image ones are drawn into their
# box; the others are a line of text. The frontend's label layout mirrors them.
LABEL_TEXT_FIELDS = (
    "reseller_name",
    "reseller_address",
    "reseller_city",
    "article",
    "sort",
    "size",
    "amount_per_pu",
    "delivery_date",
    "order_number",
    "farm_name",
    "control_number",
    "static_text",
)
LABEL_IMAGE_FIELDS = ("farm_logo", "organic_logo", "qr_code")
LABEL_FIELDS = LABEL_TEXT_FIELDS + LABEL_IMAGE_FIELDS
# The elements that print what they were given rather than an order line's data.
LABEL_FIELDS_WITH_TEXT = ("static_text", "qr_code")
LABEL_ALIGNMENTS = ("left", "center", "right")

A4_WIDTH_MM = Decimal("210")
A4_HEIGHT_MM = Decimal("297")
# Room for rounding at a tenth of a millimetre.
TOLERANCE_MM = Decimal("0.05")


class LabelElementSerializer(serializers.Serializer):
    """One piece of information on the label: a box in mm from the label's top
    left corner. ``font_size_pt``, ``bold`` and ``align`` style a text;
    ``text`` is what a ``static_text`` prints and what a ``qr_code`` encodes;
    ``organic_prefix`` puts the organic word before an organic article."""

    id = serializers.CharField(max_length=40)
    field = serializers.CharField(help_text=f"One of: {', '.join(LABEL_FIELDS)}.")
    x_mm = serializers.FloatField(min_value=0, max_value=300)
    y_mm = serializers.FloatField(min_value=0, max_value=300)
    width_mm = serializers.FloatField(min_value=1, max_value=300)
    height_mm = serializers.FloatField(min_value=1, max_value=300)
    font_size_pt = serializers.FloatField(min_value=4, max_value=72, default=10)
    bold = serializers.BooleanField(default=False)
    align = serializers.CharField(
        default="left", help_text=f"One of: {', '.join(LABEL_ALIGNMENTS)}."
    )
    text = serializers.CharField(max_length=500, allow_blank=True, default="")
    organic_prefix = serializers.BooleanField(default=True)


# A partial update skips a nested element's defaults, and a stored element
# checked against a changed size never passed through them; both get them here.
LABEL_ELEMENT_DEFAULTS = {
    name: field.default
    for name, field in LabelElementSerializer().fields.items()
    if field.default is not empty
}
LABEL_ELEMENT_REQUIRED_KEYS = tuple(
    name for name, field in LabelElementSerializer().fields.items() if field.required
)


class LabelTemplateSerializer(serializers.ModelSerializer):
    """The label's layout. Sizes are in mm; the ``sheet_*`` fields lay the
    labels out on an A4 page when ``print_mode`` is ``sheet``."""

    elements = serializers.ListField(child=LabelElementSerializer(), max_length=40)

    class Meta:
        model = LabelTemplate
        fields = (
            "id",
            "name",
            "width_mm",
            "height_mm",
            "elements",
            "print_mode",
            "sheet_columns",
            "sheet_rows",
            "sheet_margin_top_mm",
            "sheet_margin_left_mm",
            "sheet_gap_x_mm",
            "sheet_gap_y_mm",
        )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if "elements" in attrs:
            attrs["elements"] = [
                {**LABEL_ELEMENT_DEFAULTS, **element} for element in attrs["elements"]
            ]
        width = Decimal(str(self._value(attrs, "width_mm")))
        height = Decimal(str(self._value(attrs, "height_mm")))
        self._validate_elements(self._value(attrs, "elements") or [], width, height)
        if self._value(attrs, "print_mode") == LabelTemplate.PrintMode.SHEET:
            self._validate_sheet(attrs, width, height)
        return attrs

    def _value(self, attrs: dict[str, Any], name: str) -> Any:
        """The submitted value, else the stored one, else the model default."""
        if name in attrs:
            return attrs[name]
        stored = self.instance if self.instance is not None else LabelTemplate()
        return getattr(stored, name)

    @staticmethod
    def _validate_elements(
        elements: list[dict[str, Any]], width: Decimal, height: Decimal
    ) -> None:
        seen_ids: set[str] = set()
        for index, given in enumerate(elements):
            element = {**LABEL_ELEMENT_DEFAULTS, **given}
            for key in LABEL_ELEMENT_REQUIRED_KEYS:
                if key not in element:
                    raise LabelElementInvalid(
                        f"Label element {index} lacks its {key}.",
                        details={"index": index, "key": key},
                    )
            for key, allowed in (
                ("field", LABEL_FIELDS),
                ("align", LABEL_ALIGNMENTS),
            ):
                if element[key] not in allowed:
                    raise LabelElementInvalid(
                        f"Label element {index} has an unknown {key}.",
                        details={"index": index, "key": key},
                    )
            if element["id"] in seen_ids:
                raise LabelElementInvalid(
                    f"Label element {index} repeats another one's id.",
                    details={"index": index, "key": "id"},
                )
            seen_ids.add(element["id"])
            if (
                element["field"] in LABEL_FIELDS_WITH_TEXT
                and not element["text"].strip()
            ):
                raise LabelElementInvalid(
                    f"Label element {index} needs a text.",
                    details={"index": index, "key": "text"},
                )
            right = Decimal(str(element["x_mm"])) + Decimal(str(element["width_mm"]))
            bottom = Decimal(str(element["y_mm"])) + Decimal(str(element["height_mm"]))
            if right > width + TOLERANCE_MM or bottom > height + TOLERANCE_MM:
                raise LabelElementOutside(
                    f"Label element {index} reaches beyond the label.",
                    details={"index": index},
                )

    def _validate_sheet(
        self, attrs: dict[str, Any], width: Decimal, height: Decimal
    ) -> None:
        columns = self._value(attrs, "sheet_columns")
        rows = self._value(attrs, "sheet_rows")
        needed_width = (
            self._value(attrs, "sheet_margin_left_mm")
            + columns * width
            + (columns - 1) * self._value(attrs, "sheet_gap_x_mm")
        )
        needed_height = (
            self._value(attrs, "sheet_margin_top_mm")
            + rows * height
            + (rows - 1) * self._value(attrs, "sheet_gap_y_mm")
        )
        if (
            needed_width > A4_WIDTH_MM + TOLERANCE_MM
            or needed_height > A4_HEIGHT_MM + TOLERANCE_MM
        ):
            raise LabelSheetTooLarge(
                "The labels with their margins and gaps don't fit on an A4 page.",
                details={
                    "width_mm": str(needed_width),
                    "height_mm": str(needed_height),
                },
            )
