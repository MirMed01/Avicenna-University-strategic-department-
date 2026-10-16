"""Аудит безопасности 16.10.2026 (OWASP ASVS 4.0.3): тесты на подтверждённые находки."""

from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from org.models import OrgUnit


class Base(TestCase):
    def setUp(self):
        self.uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        fac = OrgUnit.objects.create(kind="faculty", name="Мед", parent=self.uni)
        self.dep = OrgUnit.objects.create(kind="department", name="Хирургия", parent=fac)
        self.other = OrgUnit.objects.create(kind="department", name="Терапия", parent=fac)
        self.director = self.user("d@x.tj", Role.DIRECTOR, self.uni)
        self.head = self.user("h@x.tj", Role.HEAD, self.dep)
        self.other_teacher = self.user("t@x.tj", Role.TEACHER, self.other)

    def user(self, email, role, unit):
        u = User.objects.create_user(email, "Strong-pass-2026!", full_name=email)
        RoleAssignment.objects.create(user=u, role=role, org_unit=unit)
        return u


class LoginThrottleTests(Base):
    """M1 (ASVS 2.2.1): подбор пароля не ограничивался."""

    def attempt(self, password):
        return self.client.post("/login/", {"username": "d@x.tj", "password": password})

    def test_lock_after_failures_then_unlock(self):
        for _ in range(5):
            self.assertEqual(self.attempt("wrong").status_code, 200)
        r = self.attempt("Strong-pass-2026!")  # даже верный пароль — после 5 неудач блокировка
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Слишком много неудачных попыток")
        from accounts.models import LoginFailure

        LoginFailure.objects.update(at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.attempt("Strong-pass-2026!").status_code, 302)

    def test_admin_login_goes_through_same_door(self):
        r = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(r, "/login/?next=/admin/", fetch_redirect_response=False)


class SurveyResultsAfterCloseTests(Base):
    """M2 (ASVS 8.3): итоги менялись после каждого ответа — по разнице видно ответ конкретного студента."""

    def test_results_hidden_while_open(self):
        from feedback.models import Campaign
        from instruments.models import Instrument, InstrumentVersion, Item, Section

        inst = Instrument.objects.create(code="st", title="Анкета", kind="survey", respondent="student")
        v = InstrumentVersion.objects.create(instrument=inst)
        Item.objects.create(section=Section.objects.create(version=v, title="Р"), code="a", text="?", type="scale")
        v.publish()
        c = Campaign.objects.create(title="О", version=v, org_unit=self.dep, closes_on=timezone.localdate() + timedelta(days=3),
                                    min_respondents=3)
        Campaign.objects.filter(pk=c.pk).update(response_count=10)
        c.refresh_from_db()
        self.assertFalse(c.results_visible)
        c.is_open = False
        self.assertTrue(c.results_visible)


class XlsxBombTests(Base):
    """M3 (ASVS 12.1): огромная таблица читалась целиком в память до проверки размера."""

    def test_too_many_rows_rejected_without_reading_all(self):
        from openpyxl import Workbook

        from exams.analysis import MAX_ROWS

        wb = Workbook(write_only=True)
        ws = wb.create_sheet()
        ws.append(["№", "1", "2"])
        for i in range(MAX_ROWS + 50):
            ws.append([i, 1, 0])
        buf = BytesIO()
        wb.save(buf)
        self.client.force_login(self.head)
        r = self.client.post(reverse("exams:upload"), {"title": "Т", "org_unit": self.dep.pk, "kind": "final",
                                                       "exam_date": "2026-06-10", "file": SimpleUploadedFile("t.xlsx", buf.getvalue())})
        self.assertContains(r, "Слишком большой файл")


class ExpertRoleTests(Base):
    """M4 (ASVS 4.1.3): роль «Эксперт Центра» с правом на весь университет нельзя просить при регистрации."""

    def test_expert_not_self_requestable(self):
        from accounts.forms import RegisterForm

        values = [v for v, _ in RegisterForm().fields["requested_role"].choices]
        self.assertNotIn(Role.EXPERT, values)


class SmallFindingsTests(Base):
    def test_open_redirect_blocked(self):
        """L1 (ASVS 5.1.5): переадресация на чужой сайт после проверки портфолио."""
        from portfolio.models import PortfolioEntry

        teacher = self.user("tt@x.tj", Role.TEACHER, self.dep)
        e = PortfolioEntry.objects.create(owner=teacher, kind=PortfolioEntry._meta.get_field("kind").choices[0][0], title="Курс", date_start=timezone.localdate(),
                                          status=PortfolioEntry.Status.SUBMITTED)
        self.client.force_login(self.head)
        r = self.client.post(reverse("portfolio:review", args=[e.pk]), {"decision": "verify", "comment": "", "next": "https://evil.example/"})
        self.assertNotIn("evil.example", r.get("Location", ""))

    def test_unit_page_hides_other_units_inspections(self):
        """L5 (ASVS 4.2.1): преподаватель чужой кафедры видел список проверок кафедры."""
        from inspections.models import Inspection

        Inspection.objects.create(title="Секретная проверка", org_unit=self.dep)
        self.client.force_login(self.other_teacher)
        self.assertNotContains(self.client.get(reverse("org:detail", args=[self.dep.pk])), "Секретная проверка")
        self.client.force_login(self.head)
        self.assertContains(self.client.get(reverse("org:detail", args=[self.dep.pk])), "Секретная проверка")

    def test_bad_inputs_do_not_crash(self):
        """L6: «abc» в числе кодов и «/» в коде студента давали ошибку 500."""
        self.assertEqual(self.client.get("/s/?code=a/b", follow=True).status_code, 200)
        self.client.force_login(self.director)
        from feedback.models import Campaign
        from instruments.models import Instrument, InstrumentVersion

        v = InstrumentVersion.objects.create(instrument=Instrument.objects.create(code="s", title="А", kind="survey", respondent="student"))
        c = Campaign.objects.create(title="О", version=v, org_unit=self.dep, closes_on=timezone.localdate())
        self.assertEqual(self.client.post(reverse("feedback:add_codes", args=[c.pk]), {"n": "abc"}).status_code, 302)
        self.assertEqual(c.codes.count(), 10)


class HardeningTests(Base):
    def test_csp_header_and_no_inline_scripts(self):
        """L8 (ASVS 14.4.3): политика содержимого; в шаблонах нет встроенных скриптов, которые она бы заблокировала."""
        from pathlib import Path

        from django.conf import settings

        r = self.client.get("/login/")
        self.assertIn("script-src 'self'", r["Content-Security-Policy"])
        for path in Path(settings.BASE_DIR, "templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("<script", text)
                self.assertNotRegex(text, r"\son(click|submit|change|load)=")

    def test_password_policy_and_session_age(self):
        """L3, L4 (ASVS 2.1.1, 3.3.2): пароль не короче 12 и не похож на email; сессия — 8 часов."""
        from django.conf import settings
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validate_password("Dushanbe1")
        validate_password("Avicenna-Qanun-2026")
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 3600)

    def test_survey_codes_not_logged_by_server(self):
        """M5 (ASVS 8.3.5): nginx не пишет адреса /s/… в журнал, gunicorn журнал запросов не ведёт."""
        from pathlib import Path

        from django.conf import settings

        nginx = Path(settings.BASE_DIR, "deploy", "nginx-kanon.conf").read_text(encoding="utf-8")
        block = nginx[nginx.index("location /s/"):]
        self.assertIn("access_log off", block[:block.index("}")])
        self.assertNotIn("--access-logfile", Path(settings.BASE_DIR, "deploy", "kanon.service").read_text(encoding="utf-8"))
