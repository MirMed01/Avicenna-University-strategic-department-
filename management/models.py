"""Анализ со стороны руководства (ISO 9001 и ISO 21001, п. 9.3): сводка за период, решения, контроль их выполнения."""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Review(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", _("Подготовка")
        HELD = "held", _("Проведён")

    title = models.CharField(_("название"), max_length=255)
    date = models.DateField(_("дата заседания"))
    period_from = models.DateField(_("период: с"))
    period_to = models.DateField(_("период: по"))
    participants = models.TextField(_("участники"), blank=True)
    changes = models.TextField(_("изменения внешних и внутренних условий"), blank=True,
                               help_text=_("Новые требования государства, аккредитации, стратегии; изменения в университете."))
    resources = models.TextField(_("достаточность ресурсов"), blank=True)
    conclusions = models.TextField(_("выводы руководства"), blank=True)
    inputs = models.JSONField(default=dict, editable=False)
    state = models.CharField(_("статус"), max_length=10, choices=State.choices, default=State.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = _("анализ со стороны руководства")
        verbose_name_plural = _("анализ со стороны руководства")

    def __str__(self):
        return f"{self.title} ({self.date:%d.%m.%Y})"


class Decision(models.Model):
    class State(models.TextChoices):
        OPEN = "open", _("Выполняется")
        DONE = "done", _("Выполнено")
        CANCELLED = "cancelled", _("Отменено")

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="decisions")
    text = models.TextField(_("решение"))
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("ответственный"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="management_decisions")
    due_date = models.DateField(_("срок"))
    state = models.CharField(_("статус"), max_length=10, choices=State.choices, default=State.OPEN)
    result = models.TextField(_("что сделано"), blank=True)
    done_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["state", "due_date", "id"]
        verbose_name = _("решение руководства")
        verbose_name_plural = _("решения руководства")

    def __str__(self):
        return self.text[:80]

    @property
    def overdue(self):
        return self.state == self.State.OPEN and self.due_date < timezone.localdate()
