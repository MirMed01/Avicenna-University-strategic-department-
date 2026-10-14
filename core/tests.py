from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import User


class DemoSetupTests(TestCase):
    @override_settings(DEBUG=True)
    def test_demo_users_created_and_can_log_in(self):
        call_command("load_initial_data", stdout=StringIO())
        out = StringIO()
        with self.settings(BASE_DIR=self._tmp()):
            call_command("setup_demo", stdout=out)
        password = out.getvalue().strip().rsplit("Пароль: ", 1)[1]
        self.assertEqual(User.objects.filter(email__endswith="@demo.local").count(), 5)
        self.assertTrue(self.client.login(email="teacher@demo.local", password=password))
        teacher = User.objects.get(email="teacher@demo.local")
        self.assertEqual(teacher.roles.get().org_unit.kind, "department")

    @override_settings(DEBUG=False)
    def test_demo_refused_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("setup_demo", stdout=StringIO())

    def _tmp(self):
        import tempfile
        from pathlib import Path

        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d


class CodespacesLoginTests(TestCase):
    """Codespaces пересылает запрос с Host и Origin = localhost:8000 (https). Вход не должен падать с 403."""

    def test_login_through_codespaces_proxy(self):
        import json

        from django.conf import settings

        env = json.loads((settings.BASE_DIR / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))["containerEnv"]
        origins = env["KANON_CSRF_ORIGINS"].split(",")
        User.objects.create_user("d@demo.local", "Demo-pass-2026", full_name="Д", is_active=True)
        with self.settings(CSRF_TRUSTED_ORIGINS=origins, ALLOWED_HOSTS=["localhost", ".app.github.dev"]):
            c = self.client_class(enforce_csrf_checks=True)
            page = c.get("/login/", HTTP_HOST="localhost:8000")
            token = page.cookies["csrftoken"].value
            r = c.post("/login/", {"username": "d@demo.local", "password": "Demo-pass-2026", "csrfmiddlewaretoken": token},
                       HTTP_HOST="localhost:8000", HTTP_ORIGIN="https://localhost:8000")
        self.assertEqual(r.status_code, 302)


class CodespacesForwardedTests(TestCase):
    """За прокси Codespaces: вход не ломается, а ссылки для студентов ведут на внешний адрес https."""

    def setUp(self):
        import json

        from django.conf import settings

        env = json.loads((settings.BASE_DIR / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))["containerEnv"]
        self.assertEqual(env["KANON_USE_X_FORWARDED_HOST"], "1")
        self.over = self.settings(CSRF_TRUSTED_ORIGINS=env["KANON_CSRF_ORIGINS"].split(","), ALLOWED_HOSTS=["localhost", ".app.github.dev"],
                                  USE_X_FORWARDED_HOST=True, SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
        self.over.enable()
        self.addCleanup(self.over.disable)
        self.h = {"HTTP_HOST": "localhost:8000", "HTTP_X_FORWARDED_HOST": "demo-8000.app.github.dev", "HTTP_X_FORWARDED_PROTO": "https"}

    def test_login_and_student_links(self):
        from datetime import date

        from accounts.models import Role, RoleAssignment
        from feedback.models import Campaign
        from instruments.models import Instrument, InstrumentVersion, Item, Section
        from org.models import OrgUnit

        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        dep = OrgUnit.objects.create(kind="department", name="К", parent=uni)
        u = User.objects.create_user("d@demo.local", "Demo-pass-2026", full_name="Д", is_active=True)
        RoleAssignment.objects.create(user=u, role=Role.DIRECTOR, org_unit=uni)
        c = self.client_class(enforce_csrf_checks=True)
        token = c.get("/login/", **self.h).cookies["csrftoken"].value
        r = c.post("/login/", {"username": "d@demo.local", "password": "Demo-pass-2026", "csrfmiddlewaretoken": token},
                   HTTP_ORIGIN="https://localhost:8000", **self.h)
        self.assertEqual(r.status_code, 302)
        inst = Instrument.objects.create(code="s", title="А", kind="survey", respondent="student")
        v = InstrumentVersion.objects.create(instrument=inst)
        Item.objects.create(section=Section.objects.create(version=v, title="Р"), code="a", text="?", type="scale")
        v.publish()
        camp = Campaign.objects.create(title="О", version=v, org_unit=dep, closes_on=date(2099, 1, 1))
        camp.add_codes(1)
        page = c.get(f"/feedback/{camp.pk}/codes/", **self.h)
        self.assertContains(page, "https://demo-8000.app.github.dev/s/")
