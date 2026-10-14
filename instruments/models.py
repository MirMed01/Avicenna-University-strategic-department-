"""Инструменты — «методы обследования»: анкеты, чек-листы, протоколы, станции ОСКЭ, формы отчётов.

Версия инструмента после публикации не меняется: правки — только в новой версии.
Так старые проверки всегда видно по той форме, по которой их проводили.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class Instrument(models.Model):
    class Kind(models.TextChoices):
        DATA_FORM = "data_form", "Форма сбора данных (отчёт)"
        CHECKLIST = "checklist", "Чек-лист проверки"
        VISIT = "visit", "Протокол посещения занятия"
        OSCE = "osce", "Оценочный лист станции ОСКЭ"
        SURVEY = "survey", "Анкета"

    class Respondent(models.TextChoices):
        EXPERT = "expert", "Эксперт Центра"
        HEAD = "head", "Заведующий кафедрой"
        TEACHER = "teacher", "Преподаватель"
        EXAMINER = "examiner", "Экзаменатор"
        STUDENT = "student", "Студент (анонимно)"
        EXTERNAL = "external", "Внешний эксперт, работодатель"

    code = models.SlugField("код", max_length=50, unique=True)
    title = models.CharField("название", max_length=255)
    kind = models.CharField("вид", max_length=20, choices=Kind.choices)
    respondent = models.CharField("кто заполняет", max_length=20, choices=Respondent.choices)
    description = models.TextField("описание", blank=True)
    source_title = models.CharField("основание (документ)", max_length=255, blank=True)
    source_url = models.URLField("ссылка на документ", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "инструмент"
        verbose_name_plural = "инструменты"

    def __str__(self):
        return self.title

    def current_version(self):
        return self.versions.filter(status=InstrumentVersion.Status.PUBLISHED).order_by("-number").first()

    def latest_version(self):
        return self.versions.order_by("-number").first()


class InstrumentVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликована"
        ARCHIVED = "archived", "В архиве"

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField("версия", default=1)
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.DRAFT)
    note = models.CharField("что изменено", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("instrument", "number")
        ordering = ["instrument", "-number"]
        verbose_name = "версия инструмента"
        verbose_name_plural = "версии инструментов"

    def __str__(self):
        return f"{self.instrument.title}, версия {self.number}"

    @property
    def editable(self):
        return self.status == self.Status.DRAFT

    def items(self):
        return Item.objects.filter(section__version=self).select_related("section", "indicator").order_by("section__order", "order", "id")

    @transaction.atomic
    def publish(self):
        if not self.editable:
            raise ValidationError("Опубликовать можно только черновик.")
        if not self.items().exists():
            raise ValidationError("В инструменте нет ни одного пункта.")
        # Предыдущая опубликованная версия уходит в архив.
        self.instrument.versions.filter(status=self.Status.PUBLISHED).update(status=self.Status.ARCHIVED)
        self.status, self.published_at = self.Status.PUBLISHED, timezone.now()
        self.save(update_fields=["status", "published_at"])

    @transaction.atomic
    def new_draft(self, note=""):
        """Новая версия-черновик: копия разделов, пунктов и расчётов этой версии."""
        if self.instrument.versions.filter(status=self.Status.DRAFT).exists():
            raise ValidationError("Черновик уже есть — правьте его.")
        number = self.instrument.versions.aggregate(models.Max("number"))["number__max"] + 1
        draft = InstrumentVersion.objects.create(instrument=self.instrument, number=number, note=note)
        item_map = {}
        section_map = {}
        for s in self.sections.all():
            old_id = s.pk
            items = list(s.items.all())
            s.pk, s.version = None, draft
            s.save()
            section_map[old_id] = s
            for it in items:
                old_item = it.pk
                it.pk, it.section = None, s
                it.save()
                item_map[old_item] = it
        for d in self.derived.all():
            d.pk, d.version = None, draft
            d.numerator = item_map.get(d.numerator_id)
            d.denominator = item_map.get(d.denominator_id)
            d.section = section_map.get(d.section_id)
            d.save()
        return draft


class Section(models.Model):
    version = models.ForeignKey(InstrumentVersion, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField("раздел", max_length=255)
    text = models.TextField("пояснение", blank=True)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "раздел"
        verbose_name_plural = "разделы"

    def __str__(self):
        return self.title


class Item(models.Model):
    class Type(models.TextChoices):
        YES_NO = "yes_no", "Да / нет"
        SCALE = "scale", "Шкала 1–5"
        NUMBER = "number", "Число"
        CHOICE = "choice", "Выбор одного варианта"
        TEXT = "text", "Текст"

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="items")
    code = models.CharField("код", max_length=30)
    text = models.CharField("пункт (вопрос)", max_length=500)
    help = models.CharField("подсказка", max_length=500, blank=True)
    type = models.CharField("тип ответа", max_length=10, choices=Type.choices)
    options = models.TextField("варианты (по одному в строке)", blank=True)
    required = models.BooleanField("обязательный", default=True)
    weight = models.DecimalField("вес (баллы)", max_digits=6, decimal_places=2, default=Decimal(1))
    indicator = models.ForeignKey(
        "norms.Indicator", verbose_name="показатель, который измеряет пункт", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="instrument_items")
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "пункт"
        verbose_name_plural = "пункты"

    def __str__(self):
        return f"{self.code} {self.text}"

    def option_list(self):
        return [o.strip() for o in self.options.splitlines() if o.strip()]

    def clean(self):
        if self.type == self.Type.CHOICE and len(self.option_list()) < 2:
            raise ValidationError({"options": "Для выбора нужно хотя бы два варианта."})
        if self.section_id and Item.objects.filter(section__version=self.section.version, code=self.code).exclude(pk=self.pk).exists():
            raise ValidationError({"code": "Такой код уже есть в этой версии."})


class Derived(models.Model):
    """Расчётный показатель: как из ответов получить число, которое сравнивается с нормой."""

    class Method(models.TextChoices):
        RATIO = "ratio", "Доля, %: пункт ÷ пункт × 100"
        PERCENT_YES = "percent_yes", "Доля пунктов «да», %"
        SCORE = "score", "Набранные баллы, % от максимума"

    version = models.ForeignKey(InstrumentVersion, on_delete=models.CASCADE, related_name="derived")
    code = models.CharField("код", max_length=30)
    title = models.CharField("название", max_length=255)
    method = models.CharField("как считать", max_length=15, choices=Method.choices)
    numerator = models.ForeignKey(Item, verbose_name="числитель", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    denominator = models.ForeignKey(Item, verbose_name="знаменатель", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    section = models.ForeignKey(Section, verbose_name="только раздел", null=True, blank=True, on_delete=models.CASCADE,
                                help_text="Пусто — по всему инструменту.")
    indicator = models.ForeignKey("norms.Indicator", verbose_name="показатель нормы", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="instrument_derived")
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "расчётный показатель"
        verbose_name_plural = "расчётные показатели"

    def __str__(self):
        return f"{self.code} {self.title}"

    def clean(self):
        if self.method == self.Method.RATIO:
            for f in ("numerator", "denominator"):
                it = getattr(self, f)
                if it is None:
                    raise ValidationError({f: "Для доли нужны числитель и знаменатель."})
                if it.type != Item.Type.NUMBER:
                    raise ValidationError({f: "Выберите пункт с числовым ответом."})
