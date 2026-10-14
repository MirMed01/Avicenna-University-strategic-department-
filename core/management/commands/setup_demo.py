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
        self.demo_inspection(department)
        self.demo_campaign(department)
        self.stdout.write(text)

    # Демо-пороги: только для показа, только если порог ещё не задан, с явной пометкой.
    DEMO_THRESHOLDS = {"ГО-1": (40, 50, 60), "ГО-2": (90, 95, 100), "ГО-3": (85, 90, 95), "ГО-4": (40, 50, 60),
                       "ГО-5": (15, 20, 30), "ГО-6": (15, 20, 30), "ОСКЭ-1": (70, 85, 100), "ОСКЭ-2": (50, 65, 80),
                       "ПЗ-1": (50, 65, 80), "СТ-1": (50, 65, 80)}
    DEMO_ANSWERS = {
        "annual-report": [{"ppc_total": "40", "ppc_degree": "18", "ppc_dsc": "4", "ppc_young": "11", "ppc_trained": "9",
                           "hours_plan": "12000", "hours_fact": "11800", "st_total": "520", "st_passed": "497",
                           "st_good": "301", "um_published": "3", "um_tests": "yes", "um_interactive": "yes",
                           "um_diaries": "no", "sci_pubs": "14", "sci_scopus": "1"}],
        "osce-readiness": [{"o_stations": "yes", "o_examiners": "yes", "o_sheet": "yes", "o_tasks": "yes", "o_month": "no",
                            "o_instr": "yes", "o_sp": "no", "o_order": "yes", "o_equip": "yes", "o_signal": "yes",
                            "o_check": "yes", "o_collect": "yes", "o_sum": "yes", "o_debrief": "no"}],
        "class-visit": [{"v_goals": "4", "v_clinic": "5", "v_active": "2", "v_engage": "3", "v_feedback": "2",
                         "v_assess": "4", "v_time": "4", "v_equip": "3"},
                        {"v_goals": "5", "v_clinic": "4", "v_active": "3", "v_engage": "3", "v_feedback": "3",
                         "v_assess": "4", "v_time": "5", "v_equip": "4"}],
    }

    def demo_inspection(self, department):
        from inspections.models import Answer, Inspection, Task, calculate
        from instruments.models import Instrument
        from instruments.scoring import parse
        from norms.models import Indicator

        for code, (w, m, h) in self.DEMO_THRESHOLDS.items():
            Indicator.objects.filter(code=code, threshold_medium__isnull=True).update(
                threshold_weak=w, threshold_medium=m, threshold_high=h,
                note="Демо-порог для показа — не утверждён Центром.")
        if Inspection.objects.filter(title__endswith="(демо)").exists():
            return
        expert = User.objects.get(email="director@demo.local")
        insp = Inspection.objects.create(title="Плановая проверка кафедры (демо)", org_unit=department,
                                         lead_expert=expert, state=Inspection.State.COLLECTING, created_by=expert,
                                         note="Пример для показа: данные вымышлены.")
        for code, fillings in self.DEMO_ANSWERS.items():
            version = Instrument.objects.get(code=code).current_version()
            items = {i.code: i for i in version.items()}
            for n, answers in enumerate(fillings, 1):
                task = Task.objects.create(inspection=insp, version=version, label=f"посещение {n}" if len(fillings) > 1 else "",
                                           status=Task.Status.SUBMITTED, filled_by=expert)
                for c, raw in answers.items():
                    a = Answer(task=task, item=items[c])
                    a.set_value(parse(items[c], raw))
                    a.save()
        calculate(insp)
        insp.state = Inspection.State.REVIEW
        insp.save()

    DEMO_VOTES = [
        ("4", "5", "3", "3", "4", "5", "4", "yes", "Больше практики у постели больного"),
        ("5", "4", "2", "3", "5", "5", "5", "yes", ""),
        ("3", "4", "2", "2", "3", "4", "3", "no", "Не хватает разбора ошибок после занятия"),
        ("4", "4", "3", "4", "4", "5", "4", "yes", ""),
        ("5", "5", "4", "4", "5", "5", "5", "yes", "Всё понравилось"),
        ("4", "3", "2", "3", "4", "4", "4", "yes", "Больше симуляций"),
        ("3", "4", "3", "2", "3", "4", "2", "no", ""),
    ]

    def demo_campaign(self, department):
        from datetime import timedelta

        from django.utils import timezone

        from feedback.models import Campaign, TextAnswer
        from feedback.voting import submit, validate
        from instruments.models import Instrument

        if Campaign.objects.filter(title__endswith="(демо)").exists():
            return
        version = Instrument.objects.get(code="student-teaching").current_version()
        c = Campaign.objects.create(title="Опрос студентов 3 курса (демо)", version=version, org_unit=department,
                                    label="3 курс, лечебный факультет", closes_on=timezone.localdate() + timedelta(days=30),
                                    created_by=User.objects.get(email="director@demo.local"))
        c.add_codes(25)
        items = list(version.items())
        for vote, code in zip(self.DEMO_VOTES, c.codes.all()):
            answers, errors = validate(c, {f"i{it.pk}": v for it, v in zip(items, vote)})
            submit(code.code, answers)
        TextAnswer.objects.filter(campaign=c).exclude(text="Всё понравилось").update(decision=TextAnswer.Decision.PUBLIC)
