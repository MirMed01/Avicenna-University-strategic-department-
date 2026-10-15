from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ExamAnalysis(models.Model):
    """Итог анализа одного экзаменационного теста. Хранятся только показатели заданий, без данных о студентах."""

    class Kind(models.TextChoices):
        FINAL = "final", _("Итоговый (экзамен, аттестация)")
        INTERIM = "interim", _("Промежуточный (рубежный контроль)")
        CURRENT = "current", _("Текущий контроль")

    title = models.CharField(_("название (дисциплина, курс)"), max_length=255)
    org_unit = models.ForeignKey("org.OrgUnit", verbose_name=_("кафедра"), on_delete=models.PROTECT, related_name="exam_analyses")
    kind = models.CharField(_("вид контроля"), max_length=10, choices=Kind.choices, default=Kind.FINAL)
    exam_date = models.DateField(_("дата экзамена"))
    data = models.JSONField(default=dict, editable=False)
    note = models.TextField(_("примечание"), blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-exam_date", "-id"]
        verbose_name = _("анализ теста")
        verbose_name_plural = _("анализ тестов")

    def __str__(self):
        return f"{self.title} — {self.exam_date:%d.%m.%Y}"

    def alpha_min(self, s):
        return s["exam_alpha_final"] if self.kind == self.Kind.FINAL else s["exam_alpha_other"]
