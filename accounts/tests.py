from django.test import TestCase
from django.urls import reverse

from org.models import OrgUnit

from .models import Role, RoleAssignment, User
from .permissions import can_verify_portfolio, can_view_portfolio, units_in_scope

K = OrgUnit.Kind


class Base(TestCase):
    def setUp(self):
        self.uni = OrgUnit.objects.create(kind=K.UNIVERSITY, name="ТГМУ")
        self.med = OrgUnit.objects.create(kind=K.FACULTY, name="Медицинский", parent=self.uni)
        self.ped = OrgUnit.objects.create(kind=K.FACULTY, name="Педиатрический", parent=self.uni)
        self.surg = OrgUnit.objects.create(kind=K.DEPARTMENT, name="Хирургия", parent=self.med)
        self.ther = OrgUnit.objects.create(kind=K.DEPARTMENT, name="Терапия", parent=self.med)
        self.kids = OrgUnit.objects.create(kind=K.DEPARTMENT, name="Детские болезни", parent=self.ped)

    def user(self, email, role=None, unit=None):
        u = User.objects.create_user(email, "pass12345!", full_name=email.split("@")[0], is_active=True)
        if role:
            RoleAssignment.objects.create(user=u, role=role, org_unit=unit)
        return u


class PermissionTests(Base):
    def test_dean_scope_is_own_faculty(self):
        dean = self.user("dean@x.tj", Role.DEAN, self.med)
        scope = set(units_in_scope(dean, (Role.DEAN,)))
        self.assertEqual(scope, {self.med, self.surg, self.ther})

    def test_head_verifies_only_own_department(self):
        head = self.user("head@x.tj", Role.HEAD, self.surg)
        mine = self.user("t1@x.tj", Role.TEACHER, self.surg)
        other = self.user("t2@x.tj", Role.TEACHER, self.ther)
        self.assertTrue(can_verify_portfolio(head, mine))
        self.assertFalse(can_verify_portfolio(head, other))
        self.assertFalse(can_view_portfolio(head, other))

    def test_dean_verifies_whole_faculty_but_not_other(self):
        dean = self.user("dean@x.tj", Role.DEAN, self.med)
        self.assertTrue(can_verify_portfolio(dean, self.user("t1@x.tj", Role.TEACHER, self.ther)))
        self.assertFalse(can_verify_portfolio(dean, self.user("t2@x.tj", Role.TEACHER, self.kids)))

    def test_nobody_verifies_self(self):
        head = self.user("head@x.tj", Role.HEAD, self.surg)
        RoleAssignment.objects.create(user=head, role=Role.TEACHER, org_unit=self.surg)
        self.assertFalse(can_verify_portfolio(head, head))

    def test_rector_views_all_but_does_not_verify(self):
        rector = self.user("r@x.tj", Role.RECTOR, self.uni)
        t = self.user("t@x.tj", Role.TEACHER, self.kids)
        self.assertTrue(can_view_portfolio(rector, t))
        self.assertFalse(can_verify_portfolio(rector, t))

    def test_teacher_cannot_view_colleague(self):
        a = self.user("a@x.tj", Role.TEACHER, self.surg)
        b = self.user("b@x.tj", Role.TEACHER, self.surg)
        self.assertFalse(can_view_portfolio(a, b))


class RegistrationTests(Base):
    def test_register_creates_inactive_request(self):
        r = self.client.post(reverse("accounts:register"), {
            "full_name": "Иванов Иван", "email": "Ivan@X.tj", "position": "доцент",
            "academic_degree": "к.м.н.", "academic_title": "",
            "requested_role": Role.TEACHER, "requested_unit": self.surg.pk,
            "password1": "Kanon-2026-pass", "password2": "Kanon-2026-pass"})
        self.assertEqual(r.status_code, 200)
        u = User.objects.get(email="ivan@x.tj")
        self.assertFalse(u.is_active)
        self.assertFalse(self.client.login(email="ivan@x.tj", password="Kanon-2026-pass"))

    def test_register_cannot_request_director(self):
        r = self.client.post(reverse("accounts:register"), {
            "full_name": "Х", "email": "h@x.tj", "requested_role": Role.DIRECTOR, "requested_unit": self.uni.pk,
            "password1": "Kanon-2026-pass", "password2": "Kanon-2026-pass"})
        self.assertFalse(User.objects.filter(email="h@x.tj").exists())
        self.assertEqual(r.status_code, 200)

    def test_director_approves_with_role(self):
        director = self.user("d@x.tj", Role.DIRECTOR, self.uni)
        u = User.objects.create_user("new@x.tj", "pass12345!", full_name="Новый", is_active=False,
                                     requested_role=Role.TEACHER, requested_unit=self.surg)
        self.client.force_login(director)
        self.client.post(reverse("accounts:user_detail", args=[u.pk]), {"role": Role.TEACHER, "org_unit": self.surg.pk})
        u.refresh_from_db()
        self.assertTrue(u.is_active)
        self.assertTrue(RoleAssignment.objects.filter(user=u, role=Role.TEACHER, org_unit=self.surg).exists())

    def test_teacher_role_requires_department(self):
        director = self.user("d@x.tj", Role.DIRECTOR, self.uni)
        u = self.user("new@x.tj")
        self.client.force_login(director)
        self.client.post(reverse("accounts:user_detail", args=[u.pk]), {"role": Role.TEACHER, "org_unit": self.med.pk})
        self.assertFalse(RoleAssignment.objects.filter(user=u).exists())

    def test_users_page_only_for_managers(self):
        self.client.force_login(self.user("t@x.tj", Role.TEACHER, self.surg))
        self.assertEqual(self.client.get(reverse("accounts:users")).status_code, 403)
