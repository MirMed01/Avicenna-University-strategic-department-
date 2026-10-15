from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from inspections.models import Finding, Inspection, Task
from inspections.tests import Base

from .models import Action, Plan, Problem

TODAY = timezone.localdate()


class CapaBase(Base):
    def setUp(self):
        super().setUp()
        self.problem = Problem.objects.create(code="П-01", title="Остепенённость",
                                              typical_actions="Составить план диссертаций\nЗакрепить консультантов")
        self.problem.indicators.add(self.ind)
        self.other_problem = Problem.objects.create(code="П-99", title="Прочее")
        # Проверка с лёгким отклонением 45 % при пороге 50
        self.insp, t1, _ = self.make()
        self.fill(self.head, t1, {self.total: "40", self.part: "18"})
        self.client.force_login(self.expert)
        self.client.post(reverse("inspections:transition", args=[self.insp.pk, "review"]))
        self.finding = Finding.objects.get(inspection=self.insp, auto=True)

    def create_plan(self, user=None):
        self.client.force_login(user or self.expert)
        return self.client.post(reverse("capa:create", args=[self.finding.pk]), {
            "problem": self.problem.pk, "title": "Поднять остепенённость", "root_cause": "Нет соискателей",
            "owner": self.head.pk, "due_date": (TODAY + timedelta(days=90)).isoformat(), "effectiveness_criterion": "≥ 50 %"})

    def do(self, user, plan, action, comment=""):
        self.client.force_login(user)
        return self.client.post(reverse("capa:transition", args=[plan.pk, action]), {"comment": comment})

    def done_all(self, plan, user):
        self.client.force_login(user)
        for a in plan.actions.all():
            self.client.post(reverse("capa:action_report", args=[a.pk]), {"decision": "done", "note": "Сделано"})


class CreateTests(CapaBase):
    def test_suggestion_and_typical_actions(self):
        self.client.force_login(self.expert)
        r = self.client.get(reverse("capa:create", args=[self.finding.pk]))
        self.assertEqual(r.context["suggested"], [self.problem])
        self.assertContains(r, "★ П-01")
        self.create_plan()
        plan = Plan.objects.get()
        self.assertTrue(plan.ref.startswith(f"ПИ-{TODAY.year}-"))
        self.assertEqual(plan.actions.count(), 2)  # типовое лечение
        self.assertEqual(plan.state, Plan.State.DRAFT)

    def test_head_cannot_create_plan(self):
        r = self.create_plan(self.head)
        self.assertEqual(r.status_code, 403)

    def test_one_plan_per_finding(self):
        self.create_plan()
        self.create_plan()
        self.assertEqual(Plan.objects.count(), 1)


class FlowTests(CapaBase):
    def setUp(self):
        super().setUp()
        self.create_plan()
        self.plan = Plan.objects.get()

    def test_full_cycle_with_followup(self):
        self.do(self.head, self.plan, "submit")
        self.do(self.expert, self.plan, "approve")
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, Plan.State.IN_PROGRESS)
        self.done_all(self.plan, self.head)
        self.do(self.head, self.plan, "verify")
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, Plan.State.VERIFICATION)
        # Повторная проверка теми же инструментами
        self.client.force_login(self.expert)
        self.client.post(reverse("capa:followup", args=[self.plan.pk]))
        self.plan.refresh_from_db()
        fu = self.plan.followup
        self.assertEqual((fu.parent, fu.org_unit, fu.tasks.count()), (self.insp, self.dep, 2))
        fu.state = Inspection.State.COLLECTING
        fu.save()
        t = fu.tasks.get(version=self.v)
        self.fill(self.head, t, {self.total: "40", self.part: "22"})  # 55 %
        self.client.force_login(self.expert)
        self.client.post(reverse("inspections:transition", args=[fu.pk, "review"]))
        res = self.plan.followup_result()
        self.assertEqual((res.value, res.status), (Decimal("55.0"), "ok"))
        r = self.do(self.expert, self.plan, "effective", "Повторно 55 % при пороге 50")
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, Plan.State.CLOSED)
        self.assertIsNotNone(self.plan.closed_at)

    def test_submit_requires_root_cause(self):
        self.plan.root_cause = ""
        self.plan.save()
        self.do(self.head, self.plan, "submit")
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, Plan.State.DRAFT)

    def test_head_cannot_approve_own_plan(self):
        self.do(self.head, self.plan, "submit")
        self.assertEqual(self.do(self.head, self.plan, "approve").status_code, 403)

    def test_verify_blocked_while_actions_open(self):
        self.do(self.head, self.plan, "submit")
        self.do(self.expert, self.plan, "approve")
        self.do(self.head, self.plan, "verify")
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, Plan.State.IN_PROGRESS)

    def test_closing_requires_comment_and_not_effective_reopens(self):
        self.do(self.head, self.plan, "submit")
        self.do(self.expert, self.plan, "approve")
        self.done_all(self.plan, self.head)
        self.do(self.head, self.plan, "verify")
        self.do(self.expert, self.plan, "effective")  # без комментария
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, Plan.State.VERIFICATION)
        self.do(self.expert, self.plan, "not_effective", "Показатель не вырос")
        self.plan.refresh_from_db()
        self.assertEqual((self.plan.state, self.plan.effectiveness_comment), (Plan.State.IN_PROGRESS, "Показатель не вырос"))

    def test_action_report_requires_note(self):
        self.do(self.head, self.plan, "submit")
        self.do(self.expert, self.plan, "approve")
        a = self.plan.actions.first()
        self.client.force_login(self.head)
        self.client.post(reverse("capa:action_report", args=[a.pk]), {"decision": "done", "note": ""})
        a.refresh_from_db()
        self.assertEqual(a.state, Action.State.PLANNED)

    def test_other_department_cannot_see_plan(self):
        self.client.force_login(self.other_head)
        self.assertEqual(self.client.get(reverse("capa:detail", args=[self.plan.pk])).status_code, 403)
        self.assertNotIn(self.plan, list(self.client.get(reverse("capa:index")).context["plans"]))

    def test_overdue_shown_on_home(self):
        self.do(self.head, self.plan, "submit")
        self.do(self.expert, self.plan, "approve")
        Action.objects.filter(plan=self.plan).update(due_date=TODAY - timedelta(days=3))
        self.client.force_login(self.head)
        r = self.client.get(reverse("home"))
        self.assertEqual(len(r.context["my_overdue"]), 2)
        self.assertContains(r, "просроченные мероприятия")

    def test_finding_with_plan_cannot_be_deleted(self):
        manual = Finding.objects.create(inspection=self.insp, severity="note", text="Ручная")
        self.client.force_login(self.expert)
        self.client.post(reverse("capa:create", args=[manual.pk]), {
            "problem": self.other_problem.pk, "title": "П", "root_cause": "", "owner": self.head.pk,
            "due_date": TODAY.isoformat()})
        self.client.post(reverse("inspections:delete_finding", args=[manual.pk]))
        self.assertTrue(Finding.objects.filter(pk=manual.pk).exists())

    def test_history_logged(self):
        self.do(self.head, self.plan, "submit")
        r = self.client.get(reverse("capa:detail", args=[self.plan.pk]))
        self.assertContains(r, "подан на утверждение")


class SeedTests(TestCase):
    def test_problems_seed_links_indicators(self):
        from io import StringIO

        from django.core.management import call_command

        call_command("load_initial_data", stdout=StringIO())
        p = Problem.objects.get(code="П-05")
        self.assertEqual(sorted(i.code for i in p.indicators.all()), ["2.2", "ГО-5", "РП-1"])
        self.assertEqual(len(p.action_list()), 3)


class ClassifierTests(CapaBase):
    def test_director_adds_group_and_problem_with_causes(self):
        from .models import ProblemGroup

        self.client.force_login(self.director)
        self.client.post(reverse("capa:group_create"), {"code": "4", "title": "Оценка студентов", "order": "4", "is_active": "on"})
        g = ProblemGroup.objects.get(code="4")
        self.client.post(reverse("capa:problem_create"), {
            "group": g.pk, "code": "4.2", "title": "Тесты без статистической проверки", "description": "",
            "typical_actions": "Анализ тестов", "cause_set": ["measurement", "methods"], "is_active": "on"})
        p = Problem.objects.get(code="4.2")
        self.assertEqual((p.group, p.cause_list()), (g, ["measurement", "methods"]))
        r = self.client.get(reverse("capa:problems"))
        self.assertContains(r, "4. Оценка студентов")
        self.assertContains(r, "Измерения")

    def test_head_cannot_edit_classifier(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("capa:group_create")).status_code, 403)


class CombinationTests(CapaBase):
    def test_problem_with_more_matching_indicators_ranks_first(self):
        from inspections.models import Result

        from .models import Problem

        # Второй показатель этой проверки тоже ниже нормы и связан только с «синдромной» проблемой.
        other_ind = self.ind_nothr
        r2 = Result.objects.create(inspection=self.insp, indicator=other_ind, title="1.2", value=10,
                                   expected_level="medium", achieved="weak")
        Finding.objects.create(inspection=self.insp, result=r2, severity="mild", text="1.2 ниже", auto=False)
        combo = Problem.objects.create(code="К-1", title="Кадровая проблема по сочетанию")
        combo.indicators.add(self.ind, other_ind)
        self.client.force_login(self.expert)
        r = self.client.get(reverse("capa:create", args=[self.finding.pk]))
        self.assertEqual(r.context["suggested"][0], combo)
        self.assertEqual(r.context["suggested"][0].matches, 2)
        self.assertEqual(r.context["form"].initial["problem"], combo.pk)
        self.assertContains(r, "ниже нормы 2 связанных показателя")
