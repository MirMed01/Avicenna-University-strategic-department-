from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class IndicatorValue(models.Model):
    """Значение показателя по университету за год (например, показатели Стратегии 2030), которое вносит Центр."""

    indicator = models.ForeignKey("norms.Indicator", verbose_name=_("показатель"), on_delete=models.CASCADE, related_name="yearly_values")
    year = models.PositiveIntegerField(_("год"))
    value = models.DecimalField(_("значение"), max_digits=12, decimal_places=2)
    note = models.CharField(_("источник / примечание"), max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    entered_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("indicator", "year")
        verbose_name = _("значение показателя за год")
        verbose_name_plural = _("значения показателей за год")
