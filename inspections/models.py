"""Проверки кафедр — «обследование»: инструменты заполняются, показатели считаются, отклонения становятся находками."""

from decimal import Decimal

from django.conf import settings
from django.db import models

from instruments.models import InstrumentVersion, Item
from norms.models import LEVEL_ORDER, Indicator, Level, effective_level


class Inspection(models.Model):
    class State(models.TextChoices):
        PLANNED = "planned", "Назначена"
        COLLECTING = "collecting", "Сбор данных"
        REVIEW = "review", "Разбор экспертом"
        CLOSED = "closed", "Закрыта"
        CANCELLED = "cancelled", "Отменена"

    title = models.CharField("название", max_length=255)
    org_unit = models.ForeignKey("org.OrgUnit", verbose_name="подразделение", on_delete=models.PROTECT, related_name="inspections")
    lead_expert = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="ведущий эксперт", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="led_inspections")
    state = models.CharField("статус", max_length=12, choices=State.choices, default=State.PLANNED)
    due_date = models.DateField("срок сбора данных", null=True, blank=True)
    parent = models.ForeignKey("self", verbose_name="повторная к проверке", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="followups")
    note = models.TextField("цель и примечание", blank=True)
    conclusion = models.TextField("заключение эксперта", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "проверка"
        verbose_name_plural = "проверки"

    def __str__(self):
        return f"{self.title} — {self.org_unit}"


class Task(models.Model):
    """Одно заполнение одного инструмента в рамках проверки."""

    class Status(models.TextChoices):
        OPEN = "open", "Не заполнено"
        DRAFT = "draft", "Черновик"
        SUBMITTED = "submitted", "Сдано"

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="tasks")
    version = models.ForeignKey(InstrumentVersion, verbose_name="инструмент", on_delete=models.PROTECT)
    label = models.CharField("уточнение", max_length=255, blank=True, help_text="Например: «занятие доц. N, 3 курс».")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    filled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.version.instrument.title}{' — ' + self.label if self.label else ''}"

    def answers_dict(self):
        """{item_id: значение} в том виде, в котором его понимает instruments.scoring."""
        out = {}
        for a in self.answers.select_related("item"):
            out[a.item_id] = a.value()
        return out


class Answer(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="answers")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    number = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    flag = models.BooleanField(null=True, blank=True)
    text = models.TextField(blank=True)

    class Meta:
        unique_together = ("task", "item")

    def value(self):
        t = self.item.type
        if t == Item.Type.YES_NO:
            return self.flag
        if t == Item.Type.SCALE:
            return int(self.number) if self.number is not None else None
        if t == Item.Type.NUMBER:
            return self.number
        return self.text or None

    def set_value(self, v):
        self.number, self.flag, self.text = None, None, ""
        if v is None:
            return
        if self.item.type == Item.Type.YES_NO:
            self.flag = v
        elif self.item.type in (Item.Type.SCALE, Item.Type.NUMBER):
            self.number = Decimal(v)
        else:
            self.text = v

    def display(self):
        v = self.value()
        if v is None:
            return "—"
        if v is True:
            return "да"
        if v is False:
            return "нет"
        if isinstance(v, Decimal):
            return f"{v.normalize():f}"
        return str(v)


class Result(models.Model):
    """Значение показателя по итогам проверки (снимок на момент расчёта)."""

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="results")
    indicator = models.ForeignKey(Indicator, null=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=255)
    value = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    n = models.PositiveIntegerField("сколько заполнений учтено", default=0)
    note = models.CharField(max_length=255, blank=True)
    expected_level = models.CharField(max_length=10, choices=Level.choices, blank=True)
    achieved = models.CharField(max_length=10, blank=True)  # weak/medium/high/below или пусто — порогов нет

    class Meta:
        ordering = ["id"]

    @property
    def status(self):
        """ok / mild / severe / unknown — для цвета и «паутинки»."""
        if self.value is None or not self.achieved:
            return "unknown"
        if self.achieved == "below":
            return "severe"
        exp = LEVEL_ORDER.index(self.expected_level)
        got = LEVEL_ORDER.index(self.achieved)
        return "ok" if got >= exp else "mild"

    @property
    def expected_threshold(self):
        return self.indicator.threshold(self.expected_level) if (self.indicator and self.expected_level) else None


class Finding(models.Model):
    class Severity(models.TextChoices):
        MILD = "mild", "Лёгкое отклонение"
        SEVERE = "severe", "Выраженное отклонение"
        NOTE = "note", "Замечание"
        STRENGTH = "strength", "Сильная сторона"

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="findings")
    result = models.ForeignKey(Result, null=True, blank=True, on_delete=models.CASCADE, related_name="findings")
    severity = models.CharField("вид", max_length=10, choices=Severity.choices)
    text = models.TextField("описание")
    auto = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-auto", "id"]


def calculate(inspection):
    """Пересчитать показатели и автоматические находки по сданным заполнениям."""
    from collections import defaultdict

    from instruments.scoring import compute

    inspection.findings.filter(auto=True).delete()
    inspection.results.all().delete()
    unit = inspection.org_unit
    groups = defaultdict(list)  # (instrument_id, derived code) → [(derived, value, note)]
    for task in inspection.tasks.filter(status=Task.Status.SUBMITTED).select_related("version"):
        items = list(task.version.items())
        answers = task.answers_dict()
        for d in task.version.derived.select_related("indicator__node__version__framework"):
            value, note = compute(d, items, answers)
            groups[(task.version.instrument_id, d.code)].append((d, value, note))
    for (_, _), rows in groups.items():
        d = rows[0][0]
        values = [v for _, v, _ in rows if v is not None]
        if values:
            value = (sum(values) / len(values)).quantize(Decimal("0.1"))
            note = rows[0][2] if len(rows) == 1 else f"среднее по {len(values)} заполнениям из {len(rows)}"
        else:
            value, note = None, rows[0][2]
        ind = d.indicator
        expected = effective_level(unit, ind.node.version.framework) if ind else ""
        achieved = (ind.achieved_level(value) or "") if (ind and value is not None) else ""
        r = Result.objects.create(inspection=inspection, indicator=ind, title=f"{d.code} {d.title}", value=value,
                                  n=len(values), note=note[:255], expected_level=expected, achieved=achieved)
        if r.status in ("mild", "severe"):
            thr = r.expected_threshold
            Finding.objects.create(
                inspection=inspection, result=r, auto=True, severity=r.status,
                text=f"{r.title}: {value:f} при норме {'≥' if ind.direction == 'higher_better' else '≤'} "
                     f"{thr.normalize():f} (уровень «{Level(expected).label.lower()}»)"
                     + (" — ниже всех порогов" if r.status == "severe" else ""))
    return inspection.results.all()
