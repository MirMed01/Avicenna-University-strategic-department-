from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


class Level(models.TextChoices):
    WEAK = "weak", _("Слабый")
    MEDIUM = "medium", _("Средний")
    HIGH = "high", _("Высокий")


LEVEL_ORDER = [Level.WEAK, Level.MEDIUM, Level.HIGH]


class Framework(models.Model):
    """Документ-источник норм: WFME, ESG, ISO, IAAR, Стратегия ТГМУ…"""

    code = models.SlugField(_("код"), max_length=40, unique=True)
    title = models.CharField(_("название"), max_length=255)
    description = models.TextField(_("описание"), blank=True)

    class Meta:
        ordering = ["title"]
        verbose_name = _("документ-источник")
        verbose_name_plural = _("документы-источники")

    def __str__(self):
        return self.title

    def active_version(self):
        return self.versions.filter(status=FrameworkVersion.Status.ACTIVE).order_by("-effective_from").first()


class FrameworkVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Черновик")
        ACTIVE = "active", _("Действует")
        RETIRED = "retired", _("Утратила силу")

    framework = models.ForeignKey(Framework, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(_("редакция"), max_length=50)
    effective_from = models.DateField(_("действует с"), null=True, blank=True)
    status = models.CharField(_("статус"), max_length=10, choices=Status.choices, default=Status.ACTIVE)
    source_url = models.URLField(_("ссылка на документ"), blank=True)

    class Meta:
        unique_together = ("framework", "version")
        ordering = ["framework", "-effective_from"]
        verbose_name = _("редакция")
        verbose_name_plural = _("редакции")

    def __str__(self):
        return f"{self.framework.title}, ред. {self.version}"


class NormNode(models.Model):
    """Узел дерева норм: область → стандарт → критерий. Глубина у разных документов разная."""

    class Kind(models.TextChoices):
        AREA = "area", _("Область")
        STANDARD = "standard", _("Стандарт")
        CRITERION = "criterion", _("Критерий")

    version = models.ForeignKey(FrameworkVersion, on_delete=models.CASCADE, related_name="nodes")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    kind = models.CharField(_("вид"), max_length=10, choices=Kind.choices)
    code = models.CharField(_("код"), max_length=30)
    title = models.CharField(_("название"), max_length=500)
    text = models.TextField(_("краткое изложение"), blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "code"]
        verbose_name = _("раздел норм")
        verbose_name_plural = _("разделы норм")

    def __str__(self):
        return f"{self.code} {self.title}"


class Indicator(models.Model):
    """Показатель с тремя порогами («референсными значениями»)."""

    class Direction(models.TextChoices):
        HIGHER = "higher_better", _("Чем больше, тем лучше")
        LOWER = "lower_better", _("Чем меньше, тем лучше")

    node = models.ForeignKey(NormNode, verbose_name=_("раздел"), on_delete=models.CASCADE, related_name="indicators")
    code = models.CharField(_("код"), max_length=30)
    title = models.CharField(_("показатель"), max_length=500)
    unit = models.CharField(_("единица"), max_length=30, blank=True)
    direction = models.CharField(_("направление"), max_length=15, choices=Direction.choices, default=Direction.HIGHER)
    threshold_weak = models.DecimalField(_("порог: слабый"), max_digits=12, decimal_places=2, null=True, blank=True)
    threshold_medium = models.DecimalField(_("порог: средний"), max_digits=12, decimal_places=2, null=True, blank=True)
    threshold_high = models.DecimalField(_("порог: высокий"), max_digits=12, decimal_places=2, null=True, blank=True)
    measurement = models.TextField(_("как измеряется"), blank=True)
    note = models.TextField(_("примечание"), blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "code"]
        verbose_name = _("показатель")
        verbose_name_plural = _("показатели")

    def __str__(self):
        return f"{self.code} {self.title}"

    def threshold(self, level):
        return getattr(self, f"threshold_{level}")

    def thresholds_text(self):
        def f(v):
            return "—" if v is None else f"{v.normalize():f}"
        return " / ".join(f(self.threshold(lv)) for lv in LEVEL_ORDER)

    def meets(self, value, level):
        """Достигнут ли порог уровня. None — порог не задан: проверить нельзя, это не «норма»."""
        t = self.threshold(level)
        if t is None or value is None:
            return None
        value = Decimal(str(value))
        return value >= t if self.direction == self.Direction.HIGHER else value <= t

    def achieved_level(self, value):
        """Наивысший достигнутый уровень, «below» — ниже всех заданных порогов, None — порогов нет."""
        best, any_set = None, False
        for lv in LEVEL_ORDER:
            ok = self.meets(value, lv)
            if ok is None:
                continue
            any_set = True
            if ok:
                best = lv
        if not any_set:
            return None
        return best or "below"


class LevelAssignment(models.Model):
    """Какой уровень строгости действует для подразделения по документу. Наследуется вниз по структуре."""

    org_unit = models.ForeignKey("org.OrgUnit", on_delete=models.CASCADE, related_name="level_assignments")
    framework = models.ForeignKey(Framework, on_delete=models.CASCADE)
    level = models.CharField(_("уровень"), max_length=10, choices=Level.choices)

    class Meta:
        unique_together = ("org_unit", "framework")
        verbose_name = _("уровень строгости")
        verbose_name_plural = _("уровни строгости")


def effective_level(org_unit, framework, default=Level.MEDIUM):
    """Ближайшая настройка вверх по структуре; если нигде не задано — средний уровень."""
    ids = [int(x) for x in org_unit.path.strip("/").split("/") if x]
    by_unit = dict(LevelAssignment.objects.filter(org_unit_id__in=ids, framework=framework).values_list("org_unit_id", "level"))
    for uid in reversed(ids):
        if uid in by_unit:
            return by_unit[uid]
    return default
