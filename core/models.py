from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Журнал изменений: кто, когда и что поменял (структура, нормы, роли)."""

    at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20)  # create / update / delete / archive / ...
    object_type = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50, blank=True)
    description = models.TextField()

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "запись журнала"
        verbose_name_plural = "журнал изменений"

    def __str__(self):
        return f"{self.at:%d.%m.%Y %H:%M} {self.action} {self.object_type}: {self.description[:60]}"


def log(user, action, obj, description):
    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        object_type=obj._meta.model_name,
        object_id=str(obj.pk or ""),
        description=description,
    )


class Setting(models.Model):
    """Настройка, которую Центр меняет сам (страница «Настройки»). Список и значения по умолчанию — core/config.py."""

    key = models.CharField(max_length=50, unique=True)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.key} = {self.value}"
