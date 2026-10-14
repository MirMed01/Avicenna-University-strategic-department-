from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, RoleAssignment, User
from core.models import AuditLog

from .models import OrgUnit

K = OrgUnit.Kind


def make_tree():
    uni = OrgUnit.objects.create(kind=K.UNIVERSITY, name="ТГМУ")
    med = OrgUnit.objects.create(kind=K.FACULTY, name="Медицинский", parent=uni)
    ped = OrgUnit.objects.create(kind=K.FACULTY, name="Педиатрический", parent=uni)
    surg = OrgUnit.objects.create(kind=K.DEPARTMENT, name="Хирургия", parent=med)
    return uni, med, ped, surg


class OrgUnitModelTests(TestCase):
    def test_path_built_from_ids(self):
        uni, med, _, surg = make_tree()
        self.assertEqual(surg.path, f"/{uni.pk}/{med.pk}/{surg.pk}/")

    def test_move_department_rewrites_path(self):
        uni, med, ped, surg = make_tree()
        surg.parent = ped
        surg.save()
        surg.refresh_from_db()
        self.assertEqual(surg.path, f"/{uni.pk}/{ped.pk}/{surg.pk}/")
        self.assertNotIn(surg, med.descendants())

    def test_move_faculty_rewrites_nested_paths(self):
        uni, med, _, surg = make_tree()
        center = OrgUnit.objects.create(kind=K.CENTER, name="Центр", parent=uni)
        uni2 = OrgUnit.objects.create(kind=K.UNIVERSITY, name="Второй")
        med.parent = uni2
        med.save()
        surg.refresh_from_db()
        self.assertEqual(surg.path, f"/{uni2.pk}/{med.pk}/{surg.pk}/")
        self.assertTrue(center.path.startswith(f"/{uni.pk}/"))

    def test_department_cannot_contain_units(self):
        _, _, _, surg = make_tree()
        bad = OrgUnit(kind=K.DEPARTMENT, name="Подкафедра", parent=surg)
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_cannot_move_into_own_child(self):
        uni, med, _, _ = make_tree()
        sub = OrgUnit.objects.create(kind=K.CENTER, name="Центр факультета", parent=med)
        med.parent = sub
        with self.assertRaises(ValidationError):
            med.full_clean()

    def test_delete_blockers(self):
        _, med, _, surg = make_tree()
        self.assertTrue(med.delete_blockers())  # есть кафедра
        self.assertEqual(surg.delete_blockers(), [])
        u = User.objects.create_user("t@x.tj", "pass12345!", full_name="Т")
        RoleAssignment.objects.create(user=u, role=Role.TEACHER, org_unit=surg)
        self.assertTrue(surg.delete_blockers())


class OrgViewsTests(TestCase):
    def setUp(self):
        self.uni, self.med, self.ped, self.surg = make_tree()
        self.director = User.objects.create_user("d@x.tj", "pass12345!", full_name="Директор", is_active=True)
        RoleAssignment.objects.create(user=self.director, role=Role.DIRECTOR, org_unit=self.uni)
        self.teacher = User.objects.create_user("t@x.tj", "pass12345!", full_name="Преподаватель", is_active=True)
        RoleAssignment.objects.create(user=self.teacher, role=Role.TEACHER, org_unit=self.surg)

    def test_director_adds_department(self):
        self.client.force_login(self.director)
        r = self.client.post(reverse("org:create"), {"kind": K.DEPARTMENT, "name": "Новая кафедра", "parent": self.med.pk, "order": 0})
        self.assertEqual(r.status_code, 302)
        new = OrgUnit.objects.get(name="Новая кафедра")
        self.assertEqual(new.parent, self.med)
        self.assertTrue(AuditLog.objects.filter(description__contains="Новая кафедра").exists())

    def test_director_renames_and_moves(self):
        self.client.force_login(self.director)
        empty = OrgUnit.objects.create(kind=K.DEPARTMENT, name="Старое имя", parent=self.med)
        self.client.post(reverse("org:edit", args=[empty.pk]), {"kind": K.DEPARTMENT, "name": "Новое имя", "parent": self.ped.pk, "order": 1})
        empty.refresh_from_db()
        self.assertEqual((empty.name, empty.parent), ("Новое имя", self.ped))

    def test_director_deletes_empty_department(self):
        self.client.force_login(self.director)
        empty = OrgUnit.objects.create(kind=K.DEPARTMENT, name="Пустая", parent=self.med)
        self.client.post(reverse("org:delete", args=[empty.pk]))
        self.assertFalse(OrgUnit.objects.filter(pk=empty.pk).exists())

    def test_department_with_staff_is_not_deleted_only_closed(self):
        self.client.force_login(self.director)
        self.client.post(reverse("org:delete", args=[self.surg.pk]))
        self.assertTrue(OrgUnit.objects.filter(pk=self.surg.pk).exists())
        self.client.post(reverse("org:toggle", args=[self.surg.pk]))
        self.surg.refresh_from_db()
        self.assertFalse(self.surg.is_active)

    def test_closing_faculty_closes_its_departments(self):
        self.client.force_login(self.director)
        self.client.post(reverse("org:toggle", args=[self.med.pk]))
        self.surg.refresh_from_db()
        self.assertFalse(self.surg.is_active)

    def test_teacher_cannot_edit_structure(self):
        self.client.force_login(self.teacher)
        r = self.client.post(reverse("org:create"), {"kind": K.DEPARTMENT, "name": "Х", "parent": self.med.pk, "order": 0})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(reverse("org:tree")).status_code, 200)
