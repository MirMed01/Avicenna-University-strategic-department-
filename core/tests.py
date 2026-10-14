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
