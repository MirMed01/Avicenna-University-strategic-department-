from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from dashboard.models import IndicatorValue
from norms.models import Framework, FrameworkVersion, Indicator, NormNode
from org.models import OrgUnit

from .models import Process, Risk, strategy_shares


class Base(TestCase):
    def setUp(self):
        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        self.director = self.user("d@x.tj", Role.DIRECTOR, uni)
        self.owner = self.user("o@x.tj", Role.TEACHER, uni)
        self.other = self.user("x@x.tj", Role.TEACHER, uni)
        fw = Framework.objects.create(code="tsmu-strategy-2030", title="Стратегия")
        node = NormNode.objects.create(version=FrameworkVersion.objects.create(framework=fw, version="1"), kind="area",
                                       code="4", title="Качество")
        self.i42 = Indicator.objects.create(node=node, code="4.2", title="Цифровые процессы")
        self.i43 = Indicator.objects.create(node=node, code="4.3", title="Процессы с владельцами", threshold_medium=60)
        self.full = Process.objects.create(code="У-2", title="Качество", group="management", owner_position="Директор Центра",
                                           owner=self.owner, improvement="Анализ раз в год", is_digital=True)
        self.full.indicators.add(self.i43)
        Risk.objects.create(process=self.full, title="Нет данных", likelihood=4, impact=4)
        self.empty = Process.objects.create(code="П-4", title="Финансы", group="support")

    def user(self, email, role, unit):
        u = User.objects.create_user(email, "pass12345!", full_name=email)
        RoleAssignment.objects.create(user=u, role=role, org_unit=unit)
        return u


class PassportTests(Base):
    def test_gaps_and_strategy_shares(self):
        self.assertEqual(self.full.gaps(), [])
        self.assertEqual(len(self.empty.gaps()), 4)
        self.assertEqual(strategy_shares(), (50, 50, 2))

    def test_indicator_without_threshold_is_not_monitoring(self):
        p = Process.objects.create(code="Т", title="Т", group="core", owner_position="X", improvement="Y")
        p.indicators.add(self.i42)
        Risk.objects.create(process=p, title="r", likelihood=1, impact=1)
        self.assertEqual([str(g) for g in p.gaps()], ["пороги показателей (мониторинг)"])

    def test_save_strategy_values(self):
        self.client.force_login(self.director)
        self.client.post(reverse("processes:save_strategy"))
        year = timezone.localdate().year
        self.assertEqual(IndicatorValue.objects.get(indicator=self.i43, year=year).value, 50)
        self.assertEqual(IndicatorValue.objects.get(indicator=self.i42, year=year).value, 50)

    def test_owner_edits_own_process_other_cannot(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("processes:risk_create", args=[self.full.pk]),
                             {"title": "Сбой сервера", "likelihood": "2", "impact": "5"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.full.risks.count(), 2)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("processes:edit", args=[self.full.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("processes:create")).status_code, 403)

    def test_pages_and_risk_levels_follow_settings(self):
        from core.models import Setting

        self.client.force_login(self.other)
        r = self.client.get(reverse("processes:index"))
        self.assertContains(r, "Качество")
        self.assertContains(r, "не хватает:")
        r = self.client.get(reverse("processes:risks"))
        self.assertContains(r, 'class="pill high">16')
        Setting.objects.create(key="risk_high", value="20")
        r = self.client.get(reverse("processes:risks"))
        self.assertContains(r, 'class="pill medium">16')
        self.assertEqual(self.client.get(reverse("processes:detail", args=[self.full.pk])).status_code, 200)
