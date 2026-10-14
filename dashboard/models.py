from django.conf import settings
from django.db import models


class IndicatorValue(models.Model):
    """Значение показателя по университету за год (например, показатели Стратегии 2030), которое вносит Центр."""

    indicator = models.ForeignKey("norms.Indicator", verbose_name="показатель", on_delete=models.CASCADE, related_name="yearly_values")
    year = models.PositiveIntegerField("год")
    value = models.DecimalField("значение", max_digits=12, decimal_places=2)
    note = models.CharField("источник / примечание", max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    entered_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("indicator", "year")
        verbose_name = "значение показателя за год"
        verbose_name_plural = "значения показателей за год"
