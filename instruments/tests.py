from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, RoleAssignment, User
from norms.models import Framework, FrameworkVersion, Indicator, NormNode
from org.models import OrgUnit

from .models import Derived, Instrument, InstrumentVersion, Item, Section
from .scoring import compute, parse

D = Decimal


def build(published=False):
    inst = Instrument.objects.create(code="t", title="Тест", kind="checklist", respondent="expert")
    v = InstrumentVersion.objects.create(instrument=inst, number=1)
    s = Section.objects.create(version=v, title="Раздел")
    a = Item.objects.create(section=s, code="a", text="Всего", type="number")
    b = Item.objects.create(section=s, code="b", text="Из них", type="number")
    y1 = Item.objects.create(section=s, code="y1", text="Пункт 1", type="yes_no", weight=2)
    y2 = Item.objects.create(section=s, code="y2", text="Пункт 2", type="yes_no")
    sc = Item.objects.create(section=s, code="sc", text="Шкала", type="scale")
    ratio = Derived.objects.create(version=v, code="R", title="Доля", method="ratio", numerator=b, denominator=a)
    if published:
        v.publish()
    return v, dict(a=a, b=b, y1=y1, y2=y2, sc=sc, ratio=ratio)


class ScoringTests(TestCase):
    def setUp(self):
        self.v, self.i = build()
        self.items = list(self.v.items())

    def test_ratio(self):
        ans = {self.i["a"].pk: D(40), self.i["b"].pk: D(18)}
        self.assertEqual(compute(self.i["ratio"], self.items, ans)[0], D("45.0"))

    def test_ratio_missing_or_zero_is_not_zero(self):
        self.assertIsNone(compute(self.i["ratio"], self.items, {self.i["a"].pk: D(40)})[0])
        val, note = compute(self.i["ratio"], self.items, {self.i["a"].pk: D(0), self.i["b"].pk: D(0)})
        self.assertIsNone(val)
        self.assertIn("нулю", note)

    def test_ratio_above_100_is_flagged(self):
        val, note = compute(self.i["ratio"], self.items, {self.i["a"].pk: D(100), self.i["b"].pk: D(104)})
        self.assertEqual(val, D("104.0"))
        self.assertIn("проверьте", note)

    def test_percent_yes_requires_all_answers(self):
        d = Derived(version=self.v, code="P", title="Да", method="percent_yes")
        self.assertIsNone(compute(d, self.items, {self.i["y1"].pk: True})[0])
        self.assertEqual(compute(d, self.items, {self.i["y1"].pk: True, self.i["y2"].pk: False})[0], D("50.0"))

    def test_score_uses_weights_and_scale(self):
        d = Derived(version=self.v, code="S", title="Баллы", method="score")
        # y1 да (вес 2) + y2 нет (вес 1) + шкала 3 из 5 (=0.5 веса 1) → 2.5 из 4
        ans = {self.i["y1"].pk: True, self.i["y2"].pk: False, self.i["sc"].pk: 3}
        self.assertEqual(compute(d, self.items, ans)[0], D("62.5"))

    def test_parse_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            parse(self.i["a"], "абв")
        with self.assertRaises(ValueError):
            parse(self.i["a"], "-3")
        with self.assertRaises(ValueError):
            parse(self.i["sc"], "7")
        self.assertEqual(parse(self.i["a"], "12,5"), D("12.5"))
        self.assertIsNone(parse(self.i["y1"], ""))


class VersioningTests(TestCase):
    def test_publish_archives_previous_and_copy_keeps_links(self):
        v1, i = build(published=True)
        v2 = v1.new_draft(note="уточнены пункты")
        self.assertEqual(v2.number, 2)
        self.assertEqual(v2.items().count(), v1.items().count())
        d2 = v2.derived.get()
        self.assertEqual(d2.numerator.section.version, v2)  # ссылки указывают на копии, а не на старую версию
        v2.publish()
        v1.refresh_from_db()
        self.assertEqual(v1.status, InstrumentVersion.Status.ARCHIVED)
        self.assertEqual(v1.instrument.current_version(), v2)

    def test_only_one_draft(self):
        v1, _ = build(published=True)
        v1.new_draft()
        with self.assertRaises(ValidationError):
            v1.new_draft()

    def test_empty_instrument_cannot_be_published(self):
        inst = Instrument.objects.create(code="e", title="Пустой", kind="survey", respondent="student")
        with self.assertRaises(ValidationError):
            InstrumentVersion.objects.create(instrument=inst).publish()


class ViewTests(TestCase):
    def setUp(self):
        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        self.director = User.objects.create_user("d@x.tj", "pass12345!", full_name="Д")
        RoleAssignment.objects.create(user=self.director, role=Role.DIRECTOR, org_unit=uni)
        self.teacher = User.objects.create_user("t@x.tj", "pass12345!", full_name="Т")
        dep = OrgUnit.objects.create(kind="department", name="К", parent=uni)
        RoleAssignment.objects.create(user=self.teacher, role=Role.TEACHER, org_unit=dep)

    def test_published_version_is_locked(self):
        v, i = build(published=True)
        self.client.force_login(self.director)
        r = self.client.post(reverse("instruments:item_edit", args=[i["a"].section_id, i["a"].pk]),
                             {"code": "a", "text": "Изменено", "type": "number", "weight": "1", "order": 0, "required": "on"})
        self.assertEqual(r.status_code, 302)
        i["a"].refresh_from_db()
        self.assertEqual(i["a"].text, "Всего")

    def test_director_adds_item_to_draft(self):
        v, i = build()
        self.client.force_login(self.director)
        self.client.post(reverse("instruments:item_create", args=[i["a"].section_id]),
                         {"code": "new", "text": "Новый пункт", "type": "yes_no", "weight": "1", "order": 9, "required": "on"})
        self.assertTrue(Item.objects.filter(code="new", section__version=v).exists())
        from core.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(description__contains="Новый пункт").exists())

    def test_duplicate_code_rejected(self):
        v, i = build()
        self.client.force_login(self.director)
        self.client.post(reverse("instruments:item_create", args=[i["a"].section_id]),
                         {"code": "a", "text": "Дубль", "type": "number", "weight": "1", "order": 9})
        self.assertEqual(Item.objects.filter(code="a").count(), 1)

    def test_teacher_can_try_but_not_edit(self):
        v, i = build(published=True)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("instruments:try", args=[v.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("instruments:item_create", args=[i["a"].section_id])).status_code, 403)

    def test_try_fill_compares_with_norm(self):
        v, i = build(published=True)
        fw = Framework.objects.create(code="f", title="Ф")
        node = NormNode.objects.create(version=FrameworkVersion.objects.create(framework=fw, version="1"), kind="area", code="1", title="О")
        ind = Indicator.objects.create(node=node, code="1.1", title="Доля", threshold_weak=30, threshold_medium=50, threshold_high=70)
        i["ratio"].indicator = ind
        i["ratio"].save()
        self.client.force_login(self.teacher)
        r = self.client.post(reverse("instruments:try", args=[v.pk]), {f"i{i['a'].pk}": "40", f"i{i['b'].pk}": "18"})
        res = r.context["results"][0]
        self.assertEqual((res["value"], res["level"]), (D("45.0"), "weak"))
        self.assertContains(r, "слабый уровень")


class SeedTests(TestCase):
    def test_seed_instruments(self):
        call_command("load_initial_data", stdout=StringIO())
        self.assertEqual(Instrument.objects.count(), 5)  # + анкета студентов (этап 5)
        annual = Instrument.objects.get(code="annual-report").current_version()
        self.assertEqual(annual.derived.count(), 6)
        self.assertTrue(all(d.indicator for d in annual.derived.all()))
        osce = Instrument.objects.get(code="osce-readiness").current_version()
        self.assertEqual(osce.items().filter(type="yes_no").count(), 14)
        # Пороги внутренних показателей не выдуманы: их нет, пока Центр не задаст.
        self.assertFalse(Indicator.objects.filter(node__version__framework__code="tsmu-internal", threshold_medium__isnull=False).exists())
