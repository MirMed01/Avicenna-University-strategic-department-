from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Нужен email")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, is_active=True)
        return self.create_user(email, password, **extra)


class Role(models.TextChoices):
    ADMIN = "admin", _("Администратор системы")
    RECTOR = "rector", _("Ректор / проректор")
    DIRECTOR = "director", _("Директор Центра")
    EXPERT = "expert", _("Эксперт Центра")
    DEAN = "dean", _("Декан")
    HEAD = "head", _("Заведующий кафедрой")
    TEACHER = "teacher", _("Преподаватель")
    EXTERNAL = "external", _("Внешний эксперт")


# Роли, которые человек может запросить сам при регистрации.
SELF_REQUEST_ROLES = (Role.TEACHER, Role.HEAD, Role.DEAN, Role.EXPERT)


class User(AbstractUser):
    """Сотрудник. Вход по email. После саморегистрации неактивен, пока администратор не откроет доступ."""

    username = None
    email = models.EmailField(_("email"), unique=True)
    full_name = models.CharField(_("ФИО"), max_length=255)
    position = models.CharField(_("должность"), max_length=255, blank=True)
    academic_degree = models.CharField(_("учёная степень"), max_length=100, blank=True)
    academic_title = models.CharField(_("учёное звание"), max_length=100, blank=True)
    requested_unit = models.ForeignKey(
        "org.OrgUnit", verbose_name=_("подразделение (заявка)"), null=True, blank=True, on_delete=models.SET_NULL
    )
    requested_role = models.CharField(_("роль (заявка)"), max_length=20, choices=Role.choices, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    class Meta:
        ordering = ["full_name"]
        verbose_name = _("пользователь")
        verbose_name_plural = _("пользователи")

    def __str__(self):
        return self.full_name or self.email


class RoleAssignment(models.Model):
    """Роль действует на своём подразделении и на всём, что в него входит."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(_("роль"), max_length=20, choices=Role.choices)
    org_unit = models.ForeignKey(
        "org.OrgUnit", verbose_name=_("подразделение"), on_delete=models.PROTECT, related_name="role_assignments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "role", "org_unit")
        verbose_name = _("роль")
        verbose_name_plural = _("роли")

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} ({self.org_unit})"
