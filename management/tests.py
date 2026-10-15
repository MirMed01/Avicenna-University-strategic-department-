from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from org.models import OrgUnit

from .models import Decision, Review

TODAY = timezone.localdate()


class ReviewTests(TestCase):
    def setUp(self):
        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        self.director = self.user("d@x.tj", Role.DIRECTOR, uni)
        self.rector = self.user("r@x.tj", Role.RECTOR, uni)
        self.teacher = self.user("t@x.tj", Role.TEACHER, uni)
        self.other = self.user("o@x.tj", Role.TEACHER, uni)

    def user(self, email, role, unit):
        u = User.objects.create_user(email, "pass12345!", full_name=email)
        RoleAssignment.objects.create(user=u, role=role, org_unit=unit)
        return u

    def create(self):
        self.client.force_login(self.director)
        self.client.post(reverse("management:create"), {
            "title": "Анализ 2026", "date": TODAY.isoformat(), "period_from": TODAY.replace(month=1, day=1).isoformat(),
            "period_to": TODAY.isoformat()})
        return Review.objects.get()

    def test_inputs_collected_and_decision_tracked(self):
        r = self.create()
        self.assertIn("plans", r.inputs)
        self.assertEqual(r.inputs["inspections"]["count"], 0)
        self.client.post(reverse("management:decision_add", args=[r.pk]), {
            "text": "Ввести анализ тестов на всех кафедрах", "responsible": self.teacher.pk,
            "due_date": (TODAY - timedelta(days=1)).isoformat()})
        d = Decision.objects.get()
        self.assertTrue(d.overdue)
        # Ответственный видит поручение на главной и отмечает выполнение
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse("home")), "Ввести анализ тестов")
        self.client.post(reverse("management:decision_report", args=[d.pk]), {"state": "done", "result": "Сделано на 12 кафедрах"})
        d.refresh_from_db()
        self.assertEqual((d.state, d.done_at), ("done", TODAY))
        # Следующий анализ видит выполнение прошлых решений
        r2 = Review.objects.create(title="Следующий", date=TODAY, period_from=TODAY, period_to=TODAY)
        from .inputs import collect

        self.assertEqual(collect(TODAY, TODAY, exclude_review=r2)["prev_decisions"]["done"], 1)

    def test_access(self):
        r = self.create()
        self.client.force_login(self.rector)
        self.assertEqual(self.client.get(reverse("management:detail", args=[r.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("management:create")).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("management:detail", args=[r.pk])).status_code, 403)
        d = Decision.objects.create(review=r, text="x", responsible=self.teacher, due_date=TODAY)
        self.assertEqual(self.client.post(reverse("management:decision_report", args=[d.pk]), {"state": "done"}).status_code, 403)

    def test_held_review_is_frozen(self):
        r = self.create()
        self.client.post(reverse("management:held", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.state, "held")
        self.assertEqual(self.client.post(reverse("management:refresh", args=[r.pk])).status_code, 403)
