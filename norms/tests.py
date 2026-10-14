from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, RoleAssignment, User
from core.models import AuditLog
from org.models import OrgUnit

from .models import Framework, FrameworkVersion, Indicator, Level, LevelAssignment, NormNode, effective_level


def make_indicator(direction=Indicator.Direction.HIGHER, weak=40, medium=50, high=65):
    fw = Framework.objects.create(code=f"t{Framework.objects.count()}", title="Тест")
    v = FrameworkVersion.objects.create(framework=fw, version="1")
    node = NormNode.objects.create(version=v, kind=NormNode.Kind.AREA, code="1", title="Область")
    return Indicator.objects.create(node=node, code="1.1", title="Доля", direction=direction,
                                    threshold_weak=weak, threshold_medium=medium, threshold_high=high)


class LevelLogicTests(TestCase):
    def test_achieved_level_higher_better(self):
        i = make_indicator()
        self.assertEqual(i.achieved_level(38), "below")
        self.assertEqual(i.achieved_level(40), Level.WEAK)
        self.assertEqual(i.achieved_level(52), Level.MEDIUM)
        self.assertEqual(i.achieved_level(Decimal("65")), Level.HIGH)

    def test_lower_better(self):
        i = make_indicator(Indicator.Direction.LOWER, weak=20, medium=10, high=5)  # например, отсев, %
        self.assertEqual(i.achieved_level(25), "below")
        self.assertEqual(i.achieved_level(8), Level.MEDIUM)
        self.assertEqual(i.achieved_level(3), Level.HIGH)

    def test_missing_threshold_is_not_treated_as_norm(self):
        i = make_indicator(weak=None)
        self.assertIsNone(i.meets(100, Level.WEAK))
        self.assertEqual(i.achieved_level(45), "below")  # средний и высокий заданы, оба не достигнуты
        none = make_indicator(weak=None, medium=None, high=None)
        self.assertIsNone(none.achieved_level(45))


class EffectiveLevelTests(TestCase):
    def test_inherited_down_the_structure(self):
        fw = Framework.objects.create(code="w", title="WFME")
        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        fac = OrgUnit.objects.create(kind="faculty", name="Мед", parent=uni)
        dep = OrgUnit.objects.create(kind="department", name="Хир", parent=fac)
        self.assertEqual(effective_level(dep, fw), Level.MEDIUM)
        LevelAssignment.objects.create(org_unit=uni, framework=fw, level=Level.WEAK)
        self.assertEqual(effective_level(dep, fw), Level.WEAK)
        LevelAssignment.objects.create(org_unit=dep, framework=fw, level=Level.HIGH)
        self.assertEqual(effective_level(dep, fw), Level.HIGH)
        self.assertEqual(effective_level(fac, fw), Level.WEAK)


class InitialDataTests(TestCase):
    def test_load_initial_data(self):
        call_command("load_initial_data", stdout=open("/dev/null", "w"))
        self.assertEqual(OrgUnit.objects.filter(kind="faculty").count(), 5)
        self.assertEqual(OrgUnit.objects.filter(kind="department").count(), 59)
        strat = Framework.objects.get(code="tsmu-strategy-2030")
        inds = Indicator.objects.filter(node__version__framework=strat)
        self.assertEqual(inds.count(), 16)
        i43 = inds.get(code="4.3")
        self.assertEqual((i43.threshold_medium, i43.threshold_high, i43.threshold_weak), (Decimal(40), Decimal(100), None))
        self.assertIsNone(inds.get(code="1.4").threshold_medium)  # университетская клиника — без чисел
        self.assertEqual(NormNode.objects.filter(version__framework__code="wfme-bme").count(), 8)
        # Повторный запуск ничего не дублирует.
        call_command("load_initial_data", stdout=open("/dev/null", "w"))
        self.assertEqual(OrgUnit.objects.filter(kind="department").count(), 59)
        self.assertEqual(Indicator.objects.count(), 16)


class NormViewsTests(TestCase):
    def setUp(self):
        self.ind = make_indicator()
        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        self.director = User.objects.create_user("d@x.tj", "pass12345!", full_name="Директор")
        RoleAssignment.objects.create(user=self.director, role=Role.DIRECTOR, org_unit=uni)
        self.expert = User.objects.create_user("e@x.tj", "pass12345!", full_name="Эксперт")
        RoleAssignment.objects.create(user=self.expert, role=Role.EXPERT, org_unit=uni)

    def test_director_changes_threshold_and_it_is_logged(self):
        self.client.force_login(self.director)
        r = self.client.post(reverse("norms:indicator_edit", args=[self.ind.pk]), {
            "code": "1.1", "title": "Доля", "unit": "%", "direction": "higher_better",
            "threshold_weak": "40", "threshold_medium": "55", "threshold_high": "65", "measurement": "", "note": "", "order": 0})
        self.assertEqual(r.status_code, 302)
        self.ind.refresh_from_db()
        self.assertEqual(self.ind.threshold_medium, Decimal(55))
        self.assertTrue(AuditLog.objects.filter(description__contains="40 / 50 / 65 → 40 / 55 / 65").exists())

    def test_director_adds_standard_and_indicator(self):
        self.client.force_login(self.director)
        v = self.ind.node.version
        self.client.post(reverse("norms:node_create", args=[v.pk]) + f"?parent={self.ind.node.pk}",
                         {"kind": "standard", "code": "1.2", "title": "Новый стандарт", "text": "", "order": 0})
        node = NormNode.objects.get(code="1.2")
        self.assertEqual(node.parent, self.ind.node)
        self.client.post(reverse("norms:indicator_create", args=[node.pk]), {
            "code": "1.2.1", "title": "Новый показатель", "unit": "%", "direction": "higher_better",
            "threshold_weak": "", "threshold_medium": "70", "threshold_high": "", "measurement": "", "note": "", "order": 0})
        self.assertTrue(Indicator.objects.filter(code="1.2.1", node=node).exists())

    def test_expert_reads_but_cannot_edit(self):
        self.client.force_login(self.expert)
        self.assertEqual(self.client.get(reverse("norms:version", args=[self.ind.node.version_id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("norms:indicator_edit", args=[self.ind.pk])).status_code, 403)
