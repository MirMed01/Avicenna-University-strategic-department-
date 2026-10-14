"""Подготовка к аккредитации: самооценка по каждому критерию стандарта, доказательства, готовность."""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from portfolio.models import validate_file


class Rating(models.TextChoices):
    # Шкала IAAR («параметры профиля»).
    STRONG = "strong", _("Сильная")
    SATISFACTORY = "satisfactory", _("Удовлетворительная")
    IMPROVE = "improve", _("Предполагает улучшение")
    UNSATISFACTORY = "unsatisfactory", _("Неудовлетворительная")


class Cycle(models.Model):
    title = models.CharField(_("название"), max_length=255)
    version = models.ForeignKey("norms.FrameworkVersion", verbose_name=_("стандарт"), on_delete=models.PROTECT)
    programme = models.CharField(_("образовательная программа"), max_length=255, help_text=_("Например: 1-790101 Лечебное дело"))
    org_unit = models.ForeignKey("org.OrgUnit", verbose_name=_("факультет"), null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="accreditation_cycles")
    deadline = models.DateField(_("визит экспертов / окончание действующей аккредитации"))
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("ответственный за подготовку"), null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["deadline"]
        verbose_name = _("подготовка к аккредитации")
        verbose_name_plural = _("подготовка к аккредитации")

    def __str__(self):
        return self.title

    @property
    def report_due(self):
        """Самоотчёт сдаётся не позднее чем за 8 недель до визита (руководство IAAR)."""
        return self.deadline - timedelta(weeks=8)

    @property
    def days_left(self):
        return (self.report_due - timezone.localdate()).days

    def ensure_assessments(self):
        from norms.models import NormNode

        have = set(self.assessments.values_list("criterion_id", flat=True))
        Assessment.objects.bulk_create([Assessment(cycle=self, criterion=n) for n in NormNode.objects.filter(
            version=self.version, kind=NormNode.Kind.CRITERION).exclude(pk__in=have)])


class Assessment(models.Model):
    cycle = models.ForeignKey(Cycle, on_delete=models.CASCADE, related_name="assessments")
    criterion = models.ForeignKey("norms.NormNode", on_delete=models.PROTECT)
    rating = models.CharField(_("самооценка"), max_length=15, choices=Rating.choices, blank=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("кто готовит"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="accreditation_tasks")
    evidence = models.TextField(_("доказательства"), blank=True,
                                help_text=_("Документы, приказы, протоколы, ссылки — что подтверждает соответствие."))
    justification = models.TextField(_("обоснование оценки"), blank=True)
    measures = models.TextField(_("меры по улучшению"), blank=True,
                                help_text=_("Обязательно для оценок «предполагает улучшение» и «неудовлетворительная»."))
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("cycle", "criterion")
        ordering = ["criterion__order", "criterion__id"]

    def __str__(self):
        return self.criterion.code


class EvidenceFile(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="files")
    title = models.CharField(_("название документа"), max_length=255)
    file = models.FileField(_("файл"), upload_to="accreditation/%Y/", validators=[validate_file])
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
