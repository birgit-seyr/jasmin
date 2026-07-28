from django.db import models

from .base import JasminModel


class Plot(JasminModel):
    name = models.CharField(max_length=200, blank=True, null=True)
    is_greenhouse = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name or f"Plot {self.get_display_id()}"


class BedType(JasminModel):
    name = models.CharField(max_length=200, blank=True, null=True)
    length_in_m = models.IntegerField()
    width_in_m = models.DecimalField(max_digits=4, decimal_places=2)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(length_in_m__gt=0),
                name="bedtype_length_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(width_in_m__gt=0),
                name="bedtype_width_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name or f"BedType {self.get_display_id()}"


class PlotContent(JasminModel):
    plot = models.ForeignKey("Plot", related_name="contents", on_delete=models.CASCADE)
    bed_type = models.ForeignKey("BedType", on_delete=models.PROTECT)
    amount = models.PositiveIntegerField()

    class Meta:
        constraints = [
            # One row per (plot, bed_type): "how many beds of this type this
            # plot has".
            models.UniqueConstraint(
                fields=["plot", "bed_type"],
                name="uniq_plotcontent_plot_bedtype",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="plotcontent_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.amount}× {self.bed_type} in {self.plot}"
