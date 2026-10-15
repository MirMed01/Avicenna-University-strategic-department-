from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from instruments.models import Derived, Instrument, InstrumentVersion, Item, Section
from org.models import OrgUnit

from .models import AccessCode, Campaign, Counter, TextAnswer
from .voting import VoteError, submit, summary, validate


class Base(TestCase):
    def setUp(self):
        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        fac = OrgUnit.objects.create(kind="faculty", name="Мед", parent=uni)
        self.dep = OrgUnit.objects.create(kind="department", name="Хирургия", parent=fac)
        other = OrgUnit.objects.create(kind="department", name="Терапия", parent=fac)

        def user(email, role, unit):
            u = User.objects.create_user(email, "pass12345!", full_name=email)
            RoleAssignment.objects.create(user=u, role=role, org_unit=unit)
            return u

        self.director = user("d@x.tj", Role.DIRECTOR, uni)
        self.head = user("h@x.tj", Role.HEAD, self.dep)
        self.other_head = user("o@x.tj", Role.HEAD, other)
        self.teacher = user("t@x.tj", Role.TEACHER, self.dep)
        inst = Instrument.objects.create(code="st", title="Анкета", kind="survey", respondent="student")
        self.v = InstrumentVersion.objects.create(instrument=inst)
        s = Section.objects.create(version=self.v, title="Р")
        self.sc = Item.objects.create(section=s, code="a", text="Понятно?", type="scale")
        self.yn = Item.objects.create(section=s, code="b", text="Рекомендуете?", type="yes_no")
        self.tx = Item.objects.create(section=s, code="c", text="Что улучшить?", type="text", required=False)
        Derived.objects.create(version=self.v, code="S", title="Удовлетворённость", method="score")
        self.v.publish()
        self.c = Campaign.objects.create(title="Опрос", version=self.v, org_unit=self.dep,
                                         closes_on=timezone.localdate() + timedelta(days=5), min_respondents=3)
        self.c.add_codes(5)
        self.codes = [a.code for a in self.c.codes.all()]

    def vote(self, code, scale="4", yn="yes", text=""):
        return self.client.post(reverse("student:vote", args=[code]),
                                {f"i{self.sc.pk}": scale, f"i{self.yn.pk}": yn, f"i{self.tx.pk}": text})


class AnonymityTests(Base):
    def test_code_has_no_link_to_answers(self):
        """Устройство данных: у кода нет полей, по которым его можно связать с ответом."""
        fields = {f.name for f in AccessCode._meta.get_fields()}
        self.assertEqual(fields, {"id", "campaign", "code", "used"})
        for model in (Counter, TextAnswer):
            names = {f.name for f in model._meta.get_fields()}
            self.assertFalse(names & {"code", "access_code", "user", "created_at", "submitted_at", "ip"})

    def test_vote_counts_and_burns_code(self):
        r = self.vote(self.codes[0], "4", "yes", "Больше практики")
        self.assertContains(r, "анонимно")
        self.assertTrue(AccessCode.objects.get(code=self.codes[0]).used)
        self.assertEqual(Counter.objects.get(item=self.sc, value="4").count, 1)
        self.assertEqual(TextAnswer.objects.get().text, "Больше практики")
        self.c.refresh_from_db()
        self.assertEqual(self.c.response_count, 1)

    def test_code_works_once(self):
        self.vote(self.codes[0])
        r = self.vote(self.codes[0], "1")
        self.assertContains(r, "уже ответили")
        self.assertFalse(Counter.objects.filter(item=self.sc, value="1").exists())

    def test_submit_twice_in_code_is_rejected_atomically(self):
        answers, _ = validate(self.c, {f"i{self.sc.pk}": "5", f"i{self.yn.pk}": "no"})
        submit(self.codes[1], answers)
        with self.assertRaises(VoteError):
            submit(self.codes[1], answers)
        self.assertEqual(Counter.objects.get(item=self.sc, value="5").count, 1)

    def test_required_missing_does_not_burn_code(self):
        r = self.client.post(reverse("student:vote", args=[self.codes[0]]), {f"i{self.sc.pk}": "4"})
        self.assertContains(r, "Ответьте, пожалуйста")
        self.assertFalse(AccessCode.objects.get(code=self.codes[0]).used)

    def test_closed_campaign_rejects(self):
        self.c.is_open = False
        self.c.save()
        self.assertContains(self.vote(self.codes[0]), "закрыт")
        self.c.is_open = True
        Campaign.objects.filter(pk=self.c.pk).update(closes_on=timezone.localdate() - timedelta(days=1))
        self.assertContains(self.vote(self.codes[0]), "закрыт")

    def test_unknown_code_and_lowercase(self):
        self.assertContains(self.vote("NOSUCHCODE"), "не найден")
        r = self.vote(self.codes[2].lower())
        self.assertContains(r, "анонимно")

    def test_public_page_needs_no_login(self):
        r = self.client.get(reverse("student:vote", args=[self.codes[0]]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Понятно?")


class ResultsTests(Base):
    def test_results_hidden_below_threshold(self):
        self.vote(self.codes[0])
        self.vote(self.codes[1])
        self.client.force_login(self.head)
        r = self.client.get(reverse("feedback:detail", args=[self.c.pk]))
        self.assertContains(r, "Итоги пока скрыты")
        self.assertNotIn("rows", r.context)

    def test_summary_and_score(self):
        for code, sc, yn in zip(self.codes, ("5", "3", "4"), ("yes", "no", "yes")):
            self.vote(code, sc, yn)
        self.c.refresh_from_db()
        rows, derived = summary(self.c)
        scale = next(r for r in rows if r["item"] == self.sc)
        self.assertEqual(scale["mean"], Decimal("4.00"))
        self.assertEqual(next(r for r in rows if r["item"] == self.yn)["yes_pct"], 67)
        # балл: шкала (4-1)/4 = 0.75, «да» 2/3 → (0.75 + 0.667) / 2 = 70.8 %
        self.assertEqual(derived[0]["value"], Decimal("70.8"))

    def test_texts_moderated_before_department_sees(self):
        for code, t in zip(self.codes, ("Хорошо", "Плохо объясняют", "")):
            self.vote(code, text=t)
        self.client.force_login(self.head)
        r = self.client.get(reverse("feedback:detail", args=[self.c.pk]))
        self.assertNotContains(r, "Плохо объясняют")
        self.client.force_login(self.director)
        t = TextAnswer.objects.get(text="Плохо объясняют")
        self.client.post(reverse("feedback:moderate", args=[t.pk]), {"decision": "public"})
        self.client.force_login(self.head)
        self.assertContains(self.client.get(reverse("feedback:detail", args=[self.c.pk])), "Плохо объясняют")

    def test_access(self):
        self.client.force_login(self.other_head)
        self.assertEqual(self.client.get(reverse("feedback:detail", args=[self.c.pk])).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("feedback:detail", args=[self.c.pk])).status_code, 403)
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("feedback:codes", args=[self.c.pk])).status_code, 403)


class ManageTests(Base):
    def test_director_creates_campaign_with_codes_and_qr(self):
        self.client.force_login(self.director)
        r = self.client.post(reverse("feedback:create"), {
            "title": "Новый", "version": self.v.pk, "org_unit": self.dep.pk, "label": "2 курс",
            "closes_on": (timezone.localdate() + timedelta(days=7)).isoformat(), "min_respondents": 5, "code_count": 12})
        c = Campaign.objects.get(title="Новый")
        self.assertRedirects(r, reverse("feedback:detail", args=[c.pk]))
        self.assertEqual(c.codes.count(), 12)
        page = self.client.get(reverse("feedback:codes", args=[c.pk]))
        self.assertEqual(page.content.decode().count("<svg"), 12)
        self.assertContains(page, f"<code>{c.codes.first().code}</code>")

    def test_threshold_cannot_be_below_3(self):
        self.client.force_login(self.director)
        self.client.post(reverse("feedback:create"), {
            "title": "Мало", "version": self.v.pk, "org_unit": self.dep.pk,
            "closes_on": timezone.localdate().isoformat(), "min_respondents": 1, "code_count": 5})
        self.assertFalse(Campaign.objects.filter(title="Мало").exists())

    def test_student_survey_not_offered_in_inspections(self):
        from inspections.forms import InspectionForm

        self.assertNotIn(self.v, list(InspectionForm().fields["instruments"].queryset))


class TajikTests(Base):
    def test_student_sees_tajik_question_when_language_tg(self):
        self.sc.text_tg = "Фаҳмо буд?"
        self.sc.save()
        url = reverse("student:vote", args=[self.codes[0]])
        self.assertContains(self.client.get(url), "Понятно?")
        self.client.post(reverse("set_language"), {"language": "tg", "next": url})
        r = self.client.get(url)
        self.assertContains(r, "Фаҳмо буд?")
        self.assertContains(r, "Рекомендуете?")  # нет перевода — показывается русский текст, а не пусто


class LoopTests(Base):
    """«Вы сказали — мы сделали» и доля ответивших."""

    def test_head_records_change_students_see_it(self):
        from .models import Change

        self.client.force_login(self.head)
        self.client.post(reverse("feedback:change_add", args=[self.c.pk]),
                         {"said": "Мало практики", "done": "Добавили занятия в симуляционном центре", "is_public": "on"})
        self.assertEqual(Change.objects.count(), 1)
        self.client.logout()
        self.assertContains(self.client.get(reverse("student:entry")), "Добавили занятия в симуляционном центре")
        self.assertContains(self.client.get(reverse("student:vote", args=[self.codes[0]])), "Добавили занятия")

    def test_other_department_cannot_record(self):
        from .models import Change

        self.client.force_login(self.other_head)
        r = self.client.post(reverse("feedback:change_add", args=[self.c.pk]), {"said": "x", "done": "y"})
        self.assertEqual((r.status_code, Change.objects.count()), (403, 0))

    def test_hidden_change_not_shown_to_students(self):
        from .models import Change

        Change.objects.create(campaign=self.c, said="a", done="Секретная мера", is_public=False)
        self.assertNotContains(self.client.get(reverse("student:entry")), "Секретная мера")

    def test_low_response_rate_warns_after_close(self):
        self.vote(self.codes[0])
        Campaign.objects.filter(pk=self.c.pk).update(closes_on=timezone.localdate() - timedelta(days=1))
        self.client.force_login(self.director)
        r = self.client.get(reverse("feedback:detail", args=[self.c.pk]))
        self.assertEqual(r.context["rate"], 20)
        self.assertContains(r, "Итог может не отражать мнение всей группы")

    def test_default_min_respondents_from_settings(self):
        from core.models import Setting

        Setting.objects.create(key="feedback_min_respondents", value="8")
        self.client.force_login(self.director)
        r = self.client.get(reverse("feedback:create"))
        self.assertEqual(r.context["form"]["min_respondents"].initial, 8)


class OtherRespondentsTests(Base):
    def test_graduate_survey_for_faculty_can_be_created(self):
        inst = Instrument.objects.create(code="gr", title="Опрос выпускников", kind="survey", respondent="graduate")
        v = InstrumentVersion.objects.create(instrument=inst)
        Item.objects.create(section=Section.objects.create(version=v, title="Р"), code="a", text="Готов?", type="scale")
        v.publish()
        fac = self.dep.parent
        self.client.force_login(self.director)
        r = self.client.post(reverse("feedback:create"), {
            "title": "Выпуск 2025", "version": v.pk, "org_unit": fac.pk, "closes_on": (timezone.localdate() + timedelta(days=30)).isoformat(),
            "min_respondents": "5", "code_count": "40"})
        c = Campaign.objects.get(title="Выпуск 2025")
        self.assertRedirects(r, reverse("feedback:detail", args=[c.pk]))
        self.assertEqual((c.org_unit, c.codes.count()), (fac, 40))


class StudentPageWhileLoggedInTests(Base):
    def test_director_can_open_student_pages(self):
        """Дефект: вошедший в систему сотрудник открывал /s/ — ошибка 500 (ссылки меню искались среди адресов студентов)."""
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(reverse("student:entry")).status_code, 200)
        self.assertEqual(self.client.get(reverse("student:vote", args=[self.codes[0]])).status_code, 200)
