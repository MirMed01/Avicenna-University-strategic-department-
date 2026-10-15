"""Реестр процессов СМК (ISO 9001, п. 4.4): паспорт процесса, показатели, риски, связь с пунктами стандартов.

Из реестра считаются показатели Стратегии 2030 № 4.2 и 4.3 — доля ключевых процессов, переведённых в цифровую
систему, и доля ключевых процессов с владельцем, показателями, рисками, мониторингом и механизмом улучшения.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class Process(models.Model):
    class Group(models.TextChoices):
        MANAGEMENT = "management", _("Процессы управления")
        CORE = "core", _("Основные процессы")
        SUPPORT = "support", _("Поддерживающие процессы")

    class Level(models.TextChoices):
        UNIVERSITY = "university", _("Университет")
        FACULTY = "faculty", _("Факультет (деканат)")
        DEPARTMENT = "department", _("Кафедра")

    code = models.CharField(_("код"), max_length=20, unique=True)
    title = models.CharField(_("название"), max_length=255)
    level = models.CharField(_("уровень"), max_length=12, choices=Level.choices, default=Level.UNIVERSITY,
                             help_text=_("Процессы факультета и кафедры — типовая карта: одинакова для всех факультетов или кафедр."))
    parent = models.ForeignKey("self", verbose_name=_("входит в процесс"), null=True, blank=True, on_delete=models.CASCADE,
                               related_name="children")
    group = models.CharField(_("группа"), max_length=12, choices=Group.choices)
    is_key = models.BooleanField(_("ключевой процесс"), default=True,
                                 help_text=_("Ключевые процессы учитываются в показателях Стратегии 4.2 и 4.3."))
    purpose = models.TextField(_("цель процесса"), blank=True)
    owner_position = models.CharField(_("владелец (должность)"), max_length=255, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("владелец (пользователь)"), null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="owned_processes")
    suppliers = models.TextField(_("поставщики (кто даёт входы)"), blank=True)
    inputs = models.TextField(_("входы"), blank=True)
    outputs = models.TextField(_("выходы (результаты)"), blank=True)
    customers = models.TextField(_("потребители (кому нужен результат)"), blank=True)
    resources = models.TextField(_("ресурсы"), blank=True)
    documents = models.TextField(_("документы (положения, регламенты)"), blank=True)
    improvement = models.TextField(_("механизм улучшения"), blank=True,
                                   help_text=_("Как процесс анализируется и улучшается: кто, как часто, по каким данным."))
    is_digital = models.BooleanField(_("ведётся в цифровой системе"), default=False,
                                     help_text=_("Данные процесса ведутся в «Каноне» или другой единой цифровой системе (Стратегия 4.2)."))
    norm_nodes = models.ManyToManyField("norms.NormNode", verbose_name=_("пункты стандартов"), blank=True, related_name="processes")
    indicators = models.ManyToManyField("norms.Indicator", verbose_name=_("показатели"), blank=True, related_name="processes")
    instruments = models.ManyToManyField("instruments.Instrument", verbose_name=_("инструменты оценки"), blank=True,
                                         related_name="processes")
    order = models.PositiveIntegerField(_("порядок"), default=0)
    is_active = models.BooleanField(_("действует"), default=True)

    class Meta:
        ordering = ["order", "code"]
        verbose_name = _("процесс")
        verbose_name_plural = _("процессы")

    def __str__(self):
        return f"{self.code} {self.title}"

    def gaps(self):
        """Чего не хватает до «полного» паспорта (Стратегия 4.3). Пустой список — паспорт полный."""
        out = []
        if not (self.owner_position or self.owner_id):
            out.append(_("владелец"))
        inds = list(self.indicators.all())
        if not inds:
            out.append(_("показатели"))
        elif not any(i.threshold_weak is not None or i.threshold_medium is not None or i.threshold_high is not None for i in inds):
            out.append(_("пороги показателей (мониторинг)"))
        if not self.risks.filter(is_closed=False).exists():
            out.append(_("риски"))
        if not self.improvement.strip():
            out.append(_("механизм улучшения"))
        return out


class Risk(models.Model):
    """Риск процесса: вероятность × последствия (1–5 каждое). Пороги уровня — в «Настройках»."""

    process = models.ForeignKey(Process, on_delete=models.CASCADE, related_name="risks")
    title = models.CharField(_("риск"), max_length=255)
    likelihood = models.PositiveSmallIntegerField(_("вероятность (1–5)"), validators=[MinValueValidator(1), MaxValueValidator(5)])
    impact = models.PositiveSmallIntegerField(_("последствия (1–5)"), validators=[MinValueValidator(1), MaxValueValidator(5)])
    measures = models.TextField(_("меры"), blank=True)
    responsible = models.CharField(_("ответственный"), max_length=255, blank=True)
    review_date = models.DateField(_("пересмотреть до"), null=True, blank=True)
    is_closed = models.BooleanField(_("риск снят"), default=False)

    class Meta:
        ordering = ["is_closed", "-id"]
        verbose_name = _("риск")
        verbose_name_plural = _("риски")

    def __str__(self):
        return self.title

    @property
    def score(self):
        return self.likelihood * self.impact

    def level(self, high, medium):
        return "high" if self.score >= high else "medium" if self.score >= medium else "low"


def strategy_shares(processes=None):
    """Показатели Стратегии 4.2 и 4.3 по реестру: (доля цифровых, доля полных паспортов, число ключевых)."""
    # Считаются ключевые процессы университета верхнего уровня; типовые карты факультета и кафедры — отдельно.
    key = [p for p in (processes if processes is not None else Process.objects.filter(is_active=True, is_key=True))
           if p.is_active and p.is_key and p.level == Process.Level.UNIVERSITY and p.parent_id is None]
    if not key:
        return None, None, 0
    digital = round(100 * sum(1 for p in key if p.is_digital) / len(key))
    full = round(100 * sum(1 for p in key if not p.gaps()) / len(key))
    return digital, full, len(key)
