"""Инструменты: анкеты, чек-листы, протоколы, станции ОСКЭ, формы отчётов.

Версия инструмента после публикации не меняется: правки — только в новой версии.
Так старые проверки всегда видно по той форме, по которой их проводили.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _


class Instrument(models.Model):
    class Kind(models.TextChoices):
        DATA_FORM = "data_form", _("Форма сбора данных (отчёт)")
        CHECKLIST = "checklist", _("Чек-лист проверки")
        VISIT = "visit", _("Протокол посещения занятия")
        OSCE = "osce", _("Оценочный лист станции ОСКЭ")
        SURVEY = "survey", _("Анкета")

    class Respondent(models.TextChoices):
        EXPERT = "expert", _("Эксперт Центра")
        HEAD = "head", _("Заведующий кафедрой")
        DEAN = "dean", _("Декан")
        TEACHER = "teacher", _("Преподаватель")
        EXAMINER = "examiner", _("Экзаменатор")
        STUDENT = "student", _("Студент (анонимно)")
        GRADUATE = "graduate", _("Выпускник (анонимно)")
        EXTERNAL = "external", _("Внешний эксперт, работодатель")

    code = models.SlugField(_("код"), max_length=50, unique=True)
    title = models.CharField(_("название"), max_length=255)
    kind = models.CharField(_("вид"), max_length=20, choices=Kind.choices)
    respondent = models.CharField(_("кто заполняет"), max_length=20, choices=Respondent.choices)
    description = models.TextField(_("описание"), blank=True)
    source_title = models.CharField(_("основание (документ)"), max_length=255, blank=True)
    source_url = models.URLField(_("ссылка на документ"), max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]
        verbose_name = _("инструмент")
        verbose_name_plural = _("инструменты")

    def __str__(self):
        return self.title

    def current_version(self):
        return self.versions.filter(status=InstrumentVersion.Status.PUBLISHED).order_by("-number").first()

    def latest_version(self):
        return self.versions.order_by("-number").first()


class InstrumentVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Черновик")
        PUBLISHED = "published", _("Опубликована")
        ARCHIVED = "archived", _("В архиве")

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField(_("версия"), default=1)
    status = models.CharField(_("статус"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    note = models.CharField(_("что изменено"), max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("instrument", "number")
        ordering = ["instrument", "-number"]
        verbose_name = _("версия инструмента")
        verbose_name_plural = _("версии инструментов")

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
            raise ValidationError(gettext("Опубликовать можно только черновик."))
        if not self.items().exists():
            raise ValidationError(gettext("В инструменте нет ни одного пункта."))
        # Предыдущая опубликованная версия уходит в архив.
        self.instrument.versions.filter(status=self.Status.PUBLISHED).update(status=self.Status.ARCHIVED)
        self.status, self.published_at = self.Status.PUBLISHED, timezone.now()
        self.save(update_fields=["status", "published_at"])

    @transaction.atomic
    def new_draft(self, note=""):
        """Новая версия-черновик: копия разделов, пунктов и расчётов этой версии."""
        if self.instrument.versions.filter(status=self.Status.DRAFT).exists():
            raise ValidationError(gettext("Черновик уже есть — правьте его."))
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
    title = models.CharField(_("раздел"), max_length=255)
    title_tg = models.CharField(_("раздел по-таджикски"), max_length=255, blank=True)
    text = models.TextField(_("пояснение"), blank=True)
    order = models.PositiveIntegerField(_("порядок"), default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("раздел")
        verbose_name_plural = _("разделы")

    def localized_title(self):
        from django.utils.translation import get_language

        return self.title_tg if (get_language() or "").startswith("tg") and self.title_tg else self.title

    def __str__(self):
        return self.title


class Item(models.Model):
    class Type(models.TextChoices):
        YES_NO = "yes_no", _("Да / нет")
        SCALE = "scale", _("Шкала 1–5")
        NUMBER = "number", _("Число")
        CHOICE = "choice", _("Выбор одного варианта")
        TEXT = "text", _("Текст")

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="items")
    code = models.CharField(_("код"), max_length=30)
    text = models.CharField(_("пункт (вопрос)"), max_length=500)
    help = models.CharField(_("подсказка"), max_length=500, blank=True)
    # Таджикский вариант для анкет студентов: показывается, если выбран таджикский язык.
    text_tg = models.CharField(_("пункт по-таджикски"), max_length=500, blank=True)
    help_tg = models.CharField(_("подсказка по-таджикски"), max_length=500, blank=True)
    type = models.CharField(_("тип ответа"), max_length=10, choices=Type.choices)
    options = models.TextField(_("варианты (по одному в строке)"), blank=True)
    required = models.BooleanField(_("обязательный"), default=True)
    weight = models.DecimalField(_("вес (баллы)"), max_digits=6, decimal_places=2, default=Decimal(1))
    indicator = models.ForeignKey(
        "norms.Indicator", verbose_name=_("показатель, который измеряет пункт"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="instrument_items")
    order = models.PositiveIntegerField(_("порядок"), default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("пункт")
        verbose_name_plural = _("пункты")

    def __str__(self):
        return f"{self.code} {self.text}"

    def localized_text(self):
        from django.utils.translation import get_language

        return self.text_tg if (get_language() or "").startswith("tg") and self.text_tg else self.text

    def localized_help(self):
        from django.utils.translation import get_language

        return self.help_tg if (get_language() or "").startswith("tg") and self.help_tg else self.help

    def option_list(self):
        return [o.strip() for o in self.options.splitlines() if o.strip()]

    def clean(self):
        if self.type == self.Type.CHOICE and len(self.option_list()) < 2:
            raise ValidationError({"options": gettext("Для выбора нужно хотя бы два варианта.")})
        if self.section_id and Item.objects.filter(section__version=self.section.version, code=self.code).exclude(pk=self.pk).exists():
            raise ValidationError({"code": gettext("Такой код уже есть в этой версии.")})


class Derived(models.Model):
    """Расчётный показатель: как из ответов получить число, которое сравнивается с нормой."""

    class Method(models.TextChoices):
        RATIO = "ratio", _("Доля, %: пункт ÷ пункт × 100")
        PERCENT_YES = "percent_yes", _("Доля пунктов «да», %")
        SCORE = "score", _("Набранные баллы, % от максимума")

    version = models.ForeignKey(InstrumentVersion, on_delete=models.CASCADE, related_name="derived")
    code = models.CharField(_("код"), max_length=30)
    title = models.CharField(_("название"), max_length=255)
    method = models.CharField(_("как считать"), max_length=15, choices=Method.choices)
    numerator = models.ForeignKey(Item, verbose_name=_("числитель"), null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    denominator = models.ForeignKey(Item, verbose_name=_("знаменатель"), null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    section = models.ForeignKey(Section, verbose_name=_("только раздел"), null=True, blank=True, on_delete=models.CASCADE,
                                help_text=_("Пусто — по всему инструменту."))
    indicator = models.ForeignKey("norms.Indicator", verbose_name=_("показатель нормы"), null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="instrument_derived")
    order = models.PositiveIntegerField(_("порядок"), default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("расчётный показатель")
        verbose_name_plural = _("расчётные показатели")

    def __str__(self):
        return f"{self.code} {self.title}"

    def clean(self):
        if self.method == self.Method.RATIO:
            for f in ("numerator", "denominator"):
                it = getattr(self, f)
                if it is None:
                    raise ValidationError({f: gettext("Для доли нужны числитель и знаменатель.")})
                if it.type != Item.Type.NUMBER:
                    raise ValidationError({f: gettext("Выберите пункт с числовым ответом.")})
