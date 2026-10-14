"""Диагнозы и лечение: справочник проблем качества и планы исправления (CAPA).

Ход плана — по образцу модулей ISO (OCA management-system, взята только идея):
без анализа и мероприятий план не подать; закрыть можно только после оценки результативности;
«не помогло» — план снова в работе.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Problem(models.Model):
    """«Нозология» образования: типовая проблема качества с типовым лечением."""

    code = models.CharField(_("код"), max_length=20, unique=True)
    title = models.CharField(_("название"), max_length=255)
    description = models.TextField(_("описание и признаки"), blank=True)
    typical_actions = models.TextField(_("типовые мероприятия (по одному в строке)"), blank=True)
    indicators = models.ManyToManyField("norms.Indicator", verbose_name=_("при отклонении каких показателей подсказывать"),
                                        blank=True, related_name="problems")
    is_active = models.BooleanField(_("используется"), default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = _("проблема качества")
        verbose_name_plural = _("проблемы качества")

    def __str__(self):
        return f"{self.code} {self.title}"

    def action_list(self):
        return [a.strip() for a in self.typical_actions.splitlines() if a.strip()]


class Plan(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", _("Черновик")
        SUBMITTED = "submitted", _("На утверждении")
        IN_PROGRESS = "in_progress", _("Выполняется")
        VERIFICATION = "verification", _("Проверка результативности")
        CLOSED = "closed", _("Закрыт: помогло")
        CANCELLED = "cancelled", _("Отменён")

    ref = models.CharField(_("номер"), max_length=20, unique=True, editable=False)
    finding = models.OneToOneField("inspections.Finding", verbose_name=_("находка"), on_delete=models.PROTECT, related_name="plan")
    problem = models.ForeignKey(Problem, verbose_name=_("диагноз (проблема качества)"), on_delete=models.PROTECT, related_name="plans")
    title = models.CharField(_("план"), max_length=255)
    root_cause = models.TextField(_("анализ причины"), blank=True,
                                  help_text=_("Почему это произошло? Без анализа причины план не подать на утверждение."))
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("ответственный за план"), null=True,
                              on_delete=models.SET_NULL, related_name="owned_plans")
    due_date = models.DateField(_("срок выполнения"))
    state = models.CharField(_("статус"), max_length=15, choices=State.choices, default=State.DRAFT)
    effectiveness_criterion = models.TextField(
        _("как поймём, что помогло"), blank=True,
        help_text=_("Например: доля ППС со степенью на повторной проверке не ниже порога уровня кафедры."))
    effectiveness_comment = models.TextField(_("оценка результативности"), blank=True)
    followup = models.ForeignKey("inspections.Inspection", verbose_name=_("повторная проверка"), null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="verifies_plans")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("план исправления")
        verbose_name_plural = _("планы исправления")

    def __str__(self):
        return f"{self.ref} {self.title}"

    @property
    def inspection(self):
        return self.finding.inspection

    @property
    def org_unit(self):
        return self.finding.inspection.org_unit

    @property
    def is_open(self):
        return self.state not in (self.State.CLOSED, self.State.CANCELLED)

    @property
    def overdue(self):
        return self.is_open and self.due_date < timezone.localdate()

    def save(self, *args, **kwargs):
        if not self.ref:
            year = timezone.localdate().year
            n = Plan.objects.filter(ref__startswith=f"ПИ-{year}-").count() + 1
            self.ref = f"ПИ-{year}-{n:03d}"
        super().save(*args, **kwargs)

    def followup_result(self):
        """Значение того же показателя на повторной проверке (если она уже посчитана)."""
        ind = self.finding.result.indicator if self.finding.result_id else None
        if not (self.followup_id and ind):
            return None
        return self.followup.results.filter(indicator=ind).first()


class Action(models.Model):
    class Type(models.TextChoices):
        IMMEDIATE = "immediate", _("Срочная мера")
        CORRECTIVE = "corrective", _("Устранение причины")
        PREVENTIVE = "preventive", _("Предупреждение повторения")
        IMPROVEMENT = "improvement", _("Улучшение")

    class State(models.TextChoices):
        PLANNED = "planned", _("Запланировано")
        DONE = "done", _("Выполнено")
        CANCELLED = "cancelled", _("Отменено")

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="actions")
    type = models.CharField(_("вид"), max_length=12, choices=Type.choices, default=Type.CORRECTIVE)
    title = models.CharField(_("мероприятие"), max_length=500)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("исполнитель"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="capa_actions")
    due_date = models.DateField(_("срок"))
    state = models.CharField(_("статус"), max_length=10, choices=State.choices, default=State.PLANNED)
    result_note = models.TextField(_("что сделано"), blank=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due_date", "id"]
        verbose_name = _("мероприятие")
        verbose_name_plural = _("мероприятия")

    def __str__(self):
        return self.title

    @property
    def overdue(self):
        return self.state == self.State.PLANNED and self.due_date < timezone.localdate()
