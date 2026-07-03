from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Account(models.Model):
    account_type = models.CharField(max_length=50)
    account_number = models.CharField(max_length=20, unique=True)
    account_name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.account_number} - {self.account_name}"


class AccountValue(models.Model):
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    account = models.ForeignKey("Account", on_delete=models.PROTECT)

    # Add debit and credit fields
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # S
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # H

    # Or if you're only storing the net value, for example for planning
    value = models.DecimalField(max_digits=12, decimal_places=2)

    real_value = models.BooleanField(
        default=True
    )  # is it from real accounting data or just a plan

    class Meta:
        unique_together = ["year", "month", "account"]
        ordering = ["year", "month"]

    def __str__(self):
        return f"{self.account.account_number} - {self.year}/{self.month:02d}"

    @property
    def balance(self):
        """Calculate balance based on account class (account_number / 1,000,000)"""
        try:
            account_class = int(int(self.account.account_number) / 1000000)
        except (ValueError, TypeError):
            return self.value

        if account_class in [0, 1, 4, 5, 6, 9]:
            # Assets, expenses - Debit increases balance
            return self.debit - self.credit
        elif account_class in [2, 3, 7, 8]:
            # Liabilities, equity, revenue - Credit increases balance
            return self.credit - self.debit
        else:
            return self.value
