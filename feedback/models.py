"""Окно студентов: анонимные анкеты по одноразовым кодам.

Схема анонимности — по образцу EvaP (e-valuation/EvaP, лицензия MIT):
- код отмечается «использован», но НИКАК не связан с ответами (нет внешних ключей, нет времени ответа);
- оценки хранятся счётчиками («оценку 4 поставили 12 раз»), а не строками с ответом каждого;
- свободные ответы — с случайным UUID вместо порядкового номера, показываются только после модерации;
- итоги видны, только если ответили не меньше порога (по умолчанию 5).
"""

import secrets
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

# Без похожих символов (0/O, 1/I/L), чтобы код можно было ввести с листка.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(10))


class Campaign(models.Model):
    title = models.CharField("название опроса", max_length=255)
    version = models.ForeignKey("instruments.InstrumentVersion", verbose_name="анкета", on_delete=models.PROTECT)
    org_unit = models.ForeignKey("org.OrgUnit", verbose_name="кафедра", on_delete=models.PROTECT, related_name="campaigns")
    label = models.CharField("группа, курс, дисциплина", max_length=255, blank=True)
    closes_on = models.DateField("принимать ответы до (включительно)")
    min_respondents = models.PositiveIntegerField("показывать итоги не меньше чем при", default=5,
                                                  validators=[MinValueValidator(3)])
    is_open = models.BooleanField("приём ответов открыт", default=True)
    response_count = models.PositiveIntegerField(default=0, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "опрос студентов"
        verbose_name_plural = "опросы студентов"

    def __str__(self):
        return f"{self.title} — {self.org_unit}"

    @property
    def accepting(self):
        return self.is_open and self.closes_on >= timezone.localdate()

    @property
    def results_visible(self):
        return self.response_count >= self.min_respondents

    def add_codes(self, n):
        made = 0
        while made < n:
            code = new_code()
            if not AccessCode.objects.filter(code=code).exists():
                AccessCode.objects.create(campaign=self, code=code)
                made += 1


class AccessCode(models.Model):
    """Одноразовый код. Знает только «использован или нет» — без времени и без связи с ответом."""

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="codes")
    code = models.CharField(max_length=12, unique=True)
    used = models.BooleanField(default=False)


class Counter(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="counters")
    item = models.ForeignKey("instruments.Item", on_delete=models.PROTECT)
    value = models.CharField(max_length=255)  # "yes"/"no", "1".."5" или текст варианта
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("campaign", "item", "value")


class TextAnswer(models.Model):
    class Decision(models.TextChoices):
        UNDECIDED = "undecided", "Не просмотрен"
        PUBLIC = "public", "Показан кафедре"
        HIDDEN = "hidden", "Скрыт"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="texts")
    item = models.ForeignKey("instruments.Item", on_delete=models.PROTECT)
    text = models.TextField()
    decision = models.CharField(max_length=10, choices=Decision.choices, default=Decision.UNDECIDED)

    class Meta:
        ordering = ["id"]  # случайный порядок, не по времени
