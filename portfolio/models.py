from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}
MAX_FILE_MB = 10


def validate_file(f):
    if Path(f.name).suffix.lower() not in ALLOWED_EXT:
        raise ValidationError(_("Допустимы файлы: PDF, JPG, PNG, DOC, DOCX."))
    if f.size > MAX_FILE_MB * 1024 * 1024:
        raise ValidationError(_("Файл больше %(mb)s МБ.") % {"mb": MAX_FILE_MB})


class EntryKind(models.TextChoices):
    # В скобках — показатель Стратегии ТГМУ 2030, который считается по этому виду записей.
    EDUCATION = "education", _("Образование")
    DEGREE = "degree", _("Учёная степень, звание")
    TRAINING = "training", _("Повышение квалификации")
    CERTIFICATION = "certification", _("Сертифицированное обучение (медпедагогика, оценка компетенций и др.)")  # KPI 2.2
    MOBILITY = "mobility", _("Стажировка, академическая мобильность")  # KPI 2.3
    PUBLICATION = "publication", _("Публикация")  # KPI 3.1
    GRANT = "grant", _("Грант, международный проект")  # KPI 3.3
    MENTORING = "mentoring", _("Наставничество, менторинг")  # KPI 1.3, 2.4
    METHODICAL = "methodical", _("Учебно-методическая работа")
    AWARD = "award", _("Награда")
    OTHER = "other", _("Другое")


class Indexing(models.TextChoices):
    NONE = "", "—"
    SCOPUS = "scopus", "Scopus"
    WOS = "wos", "Web of Science"
    SCOPUS_WOS = "scopus_wos", _("Scopus и Web of Science")
    RINC = "rinc", _("РИНЦ")
    VAK = "vak", _("Перечень ВАК / журналы РТ")


class PortfolioEntry(models.Model):
    """Запись портфолио преподавателя. Подтверждает заведующий кафедрой, декан или Центр."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Черновик")
        SUBMITTED = "submitted", _("На проверке")
        VERIFIED = "verified", _("Подтверждено")
        REJECTED = "rejected", _("Возвращено")

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portfolio")
    kind = models.CharField(_("вид"), max_length=20, choices=EntryKind.choices)
    title = models.CharField(_("название"), max_length=500)
    organization = models.CharField(_("где / кем выдано"), max_length=255, blank=True)
    date_start = models.DateField(_("дата (начало)"))
    date_end = models.DateField(_("дата окончания"), null=True, blank=True)
    hours = models.PositiveIntegerField(_("часы"), null=True, blank=True)
    indexing = models.CharField(_("индексация"), max_length=12, choices=Indexing.choices, blank=True)
    doi_or_url = models.CharField(_("DOI или ссылка"), max_length=500, blank=True)
    details = models.TextField(_("подробности"), blank=True)
    file = models.FileField(_("подтверждающий файл"), upload_to="portfolio/%Y/", blank=True, validators=[validate_file])

    status = models.CharField(_("статус"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(_("комментарий проверяющего"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_start", "-id"]
        verbose_name = _("запись портфолио")
        verbose_name_plural = _("портфолио")

    def __str__(self):
        return f"{self.owner}: {self.title}"

    def clean(self):
        if self.date_end and self.date_end < self.date_start:
            raise ValidationError({"date_end": _("Окончание раньше начала.")})
        if self.kind != EntryKind.PUBLICATION and self.indexing:
            raise ValidationError({"indexing": _("Индексация указывается только для публикаций.")})
