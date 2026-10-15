from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, RoleAssignment, User
from instruments.models import Derived, Instrument, InstrumentVersion, Item, Section
from norms.models import Framework, FrameworkVersion, Indicator, Level, LevelAssignment, NormNode
from org.models import OrgUnit

from .models import Finding, Inspection, Task
from .radar import radar

D = Decimal


class Base(TestCase):
    def setUp(self):
        self.uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        self.fac = OrgUnit.objects.create(kind="faculty", name="Мед", parent=self.uni)
        self.dep = OrgUnit.objects.create(kind="department", name="Хирургия", parent=self.fac)
        self.other = OrgUnit.objects.create(kind="department", name="Терапия", parent=self.fac)
        self.director = self.user("d@x.tj", Role.DIRECTOR, self.uni)
        self.expert = self.user("e@x.tj", Role.EXPERT, self.uni)
        self.head = self.user("h@x.tj", Role.HEAD, self.dep)
        self.other_head = self.user("o@x.tj", Role.HEAD, self.other)
        self.teacher = self.user("t@x.tj", Role.TEACHER, self.dep)
        # Норма: доля со степенью, пороги 40 / 50 / 65
        self.fw = Framework.objects.create(code="f", title="Ф")
        node = NormNode.objects.create(version=FrameworkVersion.objects.create(framework=self.fw, version="1"), kind="area", code="1", title="О")
        self.ind = Indicator.objects.create(node=node, code="1.1", title="Доля", threshold_weak=40, threshold_medium=50, threshold_high=65)
        self.ind_nothr = Indicator.objects.create(node=node, code="1.2", title="Без порога")
        # Инструмент для заведующего: два числа и доля
        inst = Instrument.objects.create(code="rep", title="Отчёт", kind="data_form", respondent="head")
        self.v = InstrumentVersion.objects.create(instrument=inst)
        s = Section.objects.create(version=self.v, title="Р")
        self.total = Item.objects.create(section=s, code="n", text="Всего", type="number")
        self.part = Item.objects.create(section=s, code="k", text="Из них", type="number")
        self.comment = Item.objects.create(section=s, code="c", text="Комментарий", type="text", required=False)
        Derived.objects.create(version=self.v, code="R", title="Доля со степенью", method="ratio",
                               numerator=self.part, denominator=self.total, indicator=self.ind)
        self.v.publish()
        # Инструмент для эксперта: да/нет → доля «да», показатель без порога
        inst2 = Instrument.objects.create(code="chk", title="Чек-лист", kind="checklist", respondent="expert")
        self.v2 = InstrumentVersion.objects.create(instrument=inst2)
        s2 = Section.objects.create(version=self.v2, title="Р")
        self.y = Item.objects.create(section=s2, code="y", text="Есть ли", type="yes_no")
        Derived.objects.create(version=self.v2, code="P", title="Соответствие", method="percent_yes", indicator=self.ind_nothr)
        self.v2.publish()

    def user(self, email, role, unit):
        u = User.objects.create_user(email, "pass12345!", full_name=email)
        RoleAssignment.objects.create(user=u, role=role, org_unit=unit)
        return u

    def make(self, collecting=True):
        insp = Inspection.objects.create(title="Плановая", org_unit=self.dep, lead_expert=self.expert,
                                         state="collecting" if collecting else "planned")
        t1 = Task.objects.create(inspection=insp, version=self.v)
        t2 = Task.objects.create(inspection=insp, version=self.v2)
        return insp, t1, t2

    def fill(self, user, task, data, submit=True):
        self.client.force_login(user)
        post = {f"i{k.pk}": v for k, v in data.items()}
        post["submit" if submit else "draft"] = "1"
        return self.client.post(reverse("inspections:fill", args=[task.pk]), post)


class CreateTests(Base):
    def test_director_assigns_inspection_with_instruments(self):
        self.client.force_login(self.director)
        r = self.client.post(reverse("inspections:create"), {"title": "Плановая 2026", "org_unit": self.dep.pk,
                             "lead_expert": self.expert.pk, "instruments": [self.v.pk, self.v2.pk]})
        insp = Inspection.objects.get()
        self.assertRedirects(r, reverse("inspections:detail", args=[insp.pk]))
        self.assertEqual(insp.tasks.count(), 2)

    def test_head_cannot_assign(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("inspections:create")).status_code, 403)


class FillTests(Base):
    def test_head_fills_own_report(self):
        insp, t1, _ = self.make()
        r = self.fill(self.head, t1, {self.total: "40", self.part: "18"})
        self.assertEqual(r.status_code, 302)
        t1.refresh_from_db()
        self.assertEqual(t1.status, Task.Status.SUBMITTED)
        self.assertEqual(t1.answers_dict()[self.part.pk], D(18))

    def test_required_items_block_submit_but_draft_saves(self):
        insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "40"})
        t1.refresh_from_db()
        self.assertNotEqual(t1.status, Task.Status.SUBMITTED)
        self.fill(self.head, t1, {self.total: "40"}, submit=False)
        t1.refresh_from_db()
        self.assertEqual((t1.status, t1.answers_dict()[self.total.pk]), (Task.Status.DRAFT, D(40)))

    def test_head_cannot_fill_expert_checklist(self):
        insp, _, t2 = self.make()
        self.assertEqual(self.fill(self.head, t2, {self.y: "yes"}).status_code, 403)

    def test_other_department_cannot_see(self):
        insp, t1, _ = self.make()
        self.client.force_login(self.other_head)
        self.assertEqual(self.client.get(reverse("inspections:detail", args=[insp.pk])).status_code, 403)
        self.assertEqual(self.fill(self.other_head, t1, {self.total: "1", self.part: "1"}).status_code, 403)

    def test_no_filling_before_start(self):
        insp, t1, _ = self.make(collecting=False)
        self.assertEqual(self.fill(self.head, t1, {self.total: "40", self.part: "18"}).status_code, 403)


class CalculateTests(Base):
    def run_review(self, insp):
        self.client.force_login(self.expert)
        return self.client.post(reverse("inspections:transition", args=[insp.pk, "review"]))

    def test_mild_deviation_against_medium_level(self):
        insp, t1, t2 = self.make()
        self.fill(self.head, t1, {self.total: "40", self.part: "18"})   # 45 % при среднем пороге 50
        self.fill(self.expert, t2, {self.y: "yes"})
        self.run_review(insp)
        insp.refresh_from_db()
        self.assertEqual(insp.state, "review")
        r = insp.results.get(indicator=self.ind)
        self.assertEqual((r.value, r.achieved, r.expected_level, r.status), (D("45.0"), "weak", "medium", "mild"))
        f = Finding.objects.get(inspection=insp, auto=True)
        self.assertEqual(f.severity, "mild")
        self.assertIn("45", f.text)
        # Показатель без порога — не находка, а «проверить нельзя».
        self.assertEqual(insp.results.get(indicator=self.ind_nothr).status, "unknown")

    def test_department_level_changes_diagnosis(self):
        LevelAssignment.objects.create(org_unit=self.fac, framework=self.fw, level=Level.WEAK)
        insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "40", self.part: "18"})
        self.run_review(insp)
        self.assertEqual(insp.results.get(indicator=self.ind).status, "ok")
        self.assertFalse(Finding.objects.filter(inspection=insp).exists())

    def test_below_all_thresholds_is_severe(self):
        insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "40", self.part: "10"})   # 25 %
        self.run_review(insp)
        self.assertEqual(Finding.objects.get(inspection=insp).severity, "severe")

    def test_several_fillings_are_averaged(self):
        insp, t1, _ = self.make()
        t3 = Task.objects.create(inspection=insp, version=self.v, label="второе")
        self.fill(self.head, t1, {self.total: "10", self.part: "4"})    # 40 %
        self.fill(self.head, t3, {self.total: "10", self.part: "6"})    # 60 %
        self.run_review(insp)
        self.assertEqual(insp.results.get(indicator=self.ind).value, D("50.0"))

    def test_review_needs_submitted_task(self):
        insp, _, _ = self.make()
        self.run_review(insp)
        insp.refresh_from_db()
        self.assertEqual(insp.state, "collecting")

    def test_head_cannot_change_state(self):
        insp, t1, _ = self.make()
        self.client.force_login(self.head)
        self.assertEqual(self.client.post(reverse("inspections:transition", args=[insp.pk, "review"])).status_code, 403)

    def test_close_with_conclusion_and_manual_finding(self):
        insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "40", self.part: "30"})
        self.run_review(insp)
        self.client.post(reverse("inspections:add_finding", args=[insp.pk]), {"severity": "strength", "text": "Сильный состав"})
        self.client.post(reverse("inspections:transition", args=[insp.pk, "close"]), {"conclusion": "Кафедра в норме"})
        insp.refresh_from_db()
        self.assertEqual((insp.state, insp.conclusion), ("closed", "Кафедра в норме"))
        self.assertTrue(Finding.objects.filter(inspection=insp, severity="strength").exists())

    def test_unit_with_inspection_cannot_be_deleted(self):
        self.make()
        self.assertTrue(any("проверки" in b for b in self.dep.delete_blockers()))


class RadarTests(Base):
    def test_radar_needs_three_values(self):
        insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "40", self.part: "18"})
        self.client.force_login(self.expert)
        self.client.post(reverse("inspections:transition", args=[insp.pk, "review"]))
        self.assertIsNone(radar(list(insp.results.all())))
        r = self.client.get(reverse("inspections:detail", args=[insp.pk]))
        self.assertContains(r, "ниже требуемого уровня")


class RenderTests(Base):
    """Дефект, замеченный на демо-проверке: координаты «паутинки» с запятой ломали рисунок, а в пояснениях было «18.00 из 40.00»."""

    def test_radar_coordinates_use_dot_and_notes_are_clean(self):
        import re

        from .models import Result

        insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "40", self.part: "18"})
        self.client.force_login(self.expert)
        self.client.post(reverse("inspections:transition", args=[insp.pk, "review"]))
        for k in range(2):  # ещё два показателя, чтобы «паутинка» строилась
            Result.objects.create(inspection=insp, title=f"Х-{k} Доп", value=D("70.5"), indicator=self.ind, expected_level="medium", achieved="high")
        html = self.client.get(reverse("inspections:detail", args=[insp.pk])).content.decode()
        coords = re.findall(r'(?:cx|cy|x1|y1|x2|y2|x|y)="([^"]*)"', html.split("<svg", 1)[1].split("</svg>", 1)[0])
        self.assertTrue(coords)
        self.assertFalse([c for c in coords if "," in c], "координаты с запятой")
        self.assertIn("18 из 40", html)
        self.assertNotIn("18.00", html)
        self.assertIn(">R</text>", html)  # подпись оси — код расчёта целиком, а не одна буква


class HintsTests(Base):
    def review(self, value):
        insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "100", self.part: str(value)})
        self.client.force_login(self.expert)
        self.client.post(reverse("inspections:transition", args=[insp.pk, "review"]))
        return insp

    def test_repeated_nonconformity_is_flagged(self):
        first = self.review(45)
        r = self.client.get(reverse("inspections:detail", args=[first.pk]))
        self.assertNotContains(r, "повторяется")
        second = self.review(42)
        r = self.client.get(reverse("inspections:detail", args=[second.pk]))
        self.assertContains(r, "повторяется")
        self.assertEqual(len(r.context["repeated"]), 1)

    def test_several_minor_in_one_section_warn(self):
        from core.models import Setting

        from .models import Result

        insp = self.review(45)
        r2 = Result.objects.create(inspection=insp, indicator=self.ind, title="1.1 ещё", value=D(44),
                                   expected_level="medium", achieved="weak")
        Finding.objects.create(inspection=insp, result=r2, severity="mild", text="ещё одно", auto=False)
        Setting.objects.create(key="minor_to_major", value="2")
        r = self.client.get(reverse("inspections:detail", args=[insp.pk]))
        self.assertEqual(len(r.context["clusters"]), 1)
        self.assertContains(r, "повод рассмотреть их как значительное")
        Setting.objects.filter(key="minor_to_major").update(value="3")
        self.assertEqual(self.client.get(reverse("inspections:detail", args=[insp.pk])).context["clusters"], [])
