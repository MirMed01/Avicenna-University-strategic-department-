"""Демо-учётные записи для показа (только в режиме разработки).

Пароль не хранится в репозитории: берётся из KANON_DEMO_PASSWORD или создаётся случайно,
печатается в терминал и записывается в .demo-logins.txt (файл не попадает в git).
"""

import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, RoleAssignment, User
from org.models import OrgUnit

DEMO = [
    ("director@demo.local", "Директор Центра (демо)", Role.DIRECTOR, "university"),
    ("rector@demo.local", "Ректор (демо)", Role.RECTOR, "university"),
    ("dean@demo.local", "Декан медицинского факультета (демо)", Role.DEAN, "faculty"),
    ("head@demo.local", "Заведующий кафедрой (демо)", Role.HEAD, "department"),
    ("teacher@demo.local", "Преподаватель (демо)", Role.TEACHER, "department"),
]


class Command(BaseCommand):
    help = "Создать демо-учётные записи для показа (только при KANON_DEBUG=1)"

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Демо-записи создаются только в режиме разработки (KANON_DEBUG=1).")
        import os

        password = os.environ.get("KANON_DEMO_PASSWORD") or secrets.token_urlsafe(9)
        uni = OrgUnit.objects.filter(kind=OrgUnit.Kind.UNIVERSITY).first()
        if not uni:
            raise CommandError("Сначала выполните load_initial_data.")
        faculty = uni.children.filter(kind=OrgUnit.Kind.FACULTY).order_by("order", "name").first()
        department = faculty.children.filter(kind=OrgUnit.Kind.DEPARTMENT).order_by("order", "name").first()
        units = {"university": uni, "faculty": faculty, "department": department}
        lines = []
        for email, name, role, unit_key in DEMO:
            u, _ = User.objects.get_or_create(email=email, defaults={"full_name": name})
            u.is_active = True
            u.is_staff = u.is_superuser = role == Role.DIRECTOR  # директору демо — доступ и к /admin/
            u.set_password(password)
            u.save()
            RoleAssignment.objects.get_or_create(user=u, role=role, org_unit=units[unit_key])
            lines.append(f"{Role(role).label:<22} {email}")
        text = "Демо-входы «Канона» (пароль у всех один):\n" + "\n".join(lines) + f"\nПароль: {password}\n"
        (settings.BASE_DIR / ".demo-logins.txt").write_text(text, encoding="utf-8")
        self.stdout.write(text)
