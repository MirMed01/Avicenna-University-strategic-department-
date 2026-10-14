import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, RoleAssignment, User
from org.models import OrgUnit

from .models import EntryKind, PortfolioEntry

S = PortfolioEntry.Status
MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class PortfolioTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        uni = OrgUnit.objects.create(kind="university", name="ТГМУ")
        med = OrgUnit.objects.create(kind="faculty", name="Мед", parent=uni)
        self.surg = OrgUnit.objects.create(kind="department", name="Хирургия", parent=med)
        self.ther = OrgUnit.objects.create(kind="department", name="Терапия", parent=med)

        def mk(email, role, unit):
            u = User.objects.create_user(email, "pass12345!", full_name=email)
            RoleAssignment.objects.create(user=u, role=role, org_unit=unit)
            return u

        self.teacher = mk("t@x.tj", Role.TEACHER, self.surg)
        self.colleague = mk("c@x.tj", Role.TEACHER, self.surg)
        self.head = mk("h@x.tj", Role.HEAD, self.surg)
        self.other_head = mk("o@x.tj", Role.HEAD, self.ther)

    def add(self, **extra):
        data = {"kind": EntryKind.PUBLICATION, "title": "Статья", "organization": "Журнал", "date_start": "2026-03-01",
                "date_end": "", "hours": "", "indexing": "scopus", "doi_or_url": "10.1000/x", "details": "", "submit": "1"}
        data.update(extra)
        self.client.force_login(self.teacher)
        return self.client.post(reverse("portfolio:create"), data)

    def test_teacher_adds_entry_and_submits(self):
        self.add()
        e = PortfolioEntry.objects.get()
        self.assertEqual((e.owner, e.status), (self.teacher, S.SUBMITTED))

    def test_indexing_only_for_publications(self):
        r = self.add(kind=EntryKind.TRAINING)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(PortfolioEntry.objects.exists())

    def test_head_verifies_own_department_entry(self):
        self.add()
        e = PortfolioEntry.objects.get()
        self.assertIn(e, list(self._queue(self.head)))
        self.client.force_login(self.head)
        self.client.post(reverse("portfolio:review", args=[e.pk]), {"decision": "verify", "comment": ""})
        e.refresh_from_db()
        self.assertEqual((e.status, e.reviewed_by), (S.VERIFIED, self.head))

    def _queue(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("portfolio:queue")).context["entries"]

    def test_other_department_head_cannot_verify_or_see(self):
        self.add()
        e = PortfolioEntry.objects.get()
        self.assertNotIn(e, list(self._queue(self.other_head)))
        r = self.client.post(reverse("portfolio:review", args=[e.pk]), {"decision": "verify"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(reverse("portfolio:show", args=[self.teacher.pk])).status_code, 403)

    def test_reject_requires_comment(self):
        self.add()
        e = PortfolioEntry.objects.get()
        self.client.force_login(self.head)
        self.client.post(reverse("portfolio:review", args=[e.pk]), {"decision": "reject", "comment": ""})
        e.refresh_from_db()
        self.assertEqual(e.status, S.SUBMITTED)
        self.client.post(reverse("portfolio:review", args=[e.pk]), {"decision": "reject", "comment": "Нет DOI"})
        e.refresh_from_db()
        self.assertEqual(e.status, S.REJECTED)

    def test_editing_verified_entry_sends_it_back_to_review(self):
        self.add()
        e = PortfolioEntry.objects.get()
        e.status = S.VERIFIED
        e.save()
        self.client.force_login(self.teacher)
        self.client.post(reverse("portfolio:edit", args=[e.pk]), {
            "kind": EntryKind.PUBLICATION, "title": "Статья (испр.)", "organization": "Журнал", "date_start": "2026-03-01",
            "indexing": "scopus", "doi_or_url": "", "details": "", "draft": "1"})
        e.refresh_from_db()
        self.assertEqual((e.title, e.status), ("Статья (испр.)", S.SUBMITTED))

    def test_colleague_cannot_edit_or_view_file(self):
        self.add(file=SimpleUploadedFile("cert.pdf", b"%PDF-1.4 test", content_type="application/pdf"))
        e = PortfolioEntry.objects.get()
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(reverse("portfolio:edit", args=[e.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("portfolio:file", args=[e.pk])).status_code, 404)
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("portfolio:file", args=[e.pk])).status_code, 200)

    def test_rejects_executable_upload(self):
        self.add(file=SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream"))
        self.assertFalse(PortfolioEntry.objects.exists())

    def test_summary_counts_only_verified(self):
        self.add()
        self.add(title="Вторая")
        e = PortfolioEntry.objects.first()
        e.status = S.VERIFIED
        e.save()
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("portfolio:my"))
        self.assertEqual(r.context["summary"]["scopus_wos"], 1)
