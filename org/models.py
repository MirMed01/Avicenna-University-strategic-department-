from django.core.exceptions import ValidationError
from django.db import models, transaction


class OrgUnit(models.Model):
    """Подразделение: университет → факультет → кафедра (и центры, отделы).

    path — цепочка id от корня: «/1/4/17/». По нему проверяется «своё подразделение и всё, что ниже».
    """

    class Kind(models.TextChoices):
        UNIVERSITY = "university", "Университет"
        FACULTY = "faculty", "Факультет"
        DEPARTMENT = "department", "Кафедра"
        CENTER = "center", "Центр"
        DIVISION = "division", "Отдел"

    # Кто может быть родителем у какого вида подразделения.
    ALLOWED_PARENTS = {
        Kind.UNIVERSITY: (),
        Kind.FACULTY: (Kind.UNIVERSITY,),
        Kind.DEPARTMENT: (Kind.FACULTY, Kind.UNIVERSITY),
        Kind.CENTER: (Kind.UNIVERSITY, Kind.FACULTY),
        Kind.DIVISION: (Kind.UNIVERSITY, Kind.CENTER),
    }

    kind = models.CharField("вид", max_length=20, choices=Kind.choices)
    name = models.CharField("название", max_length=255)
    short_name = models.CharField("краткое название", max_length=100, blank=True)
    parent = models.ForeignKey(
        "self", verbose_name="входит в", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    path = models.CharField(max_length=255, db_index=True, editable=False, default="")
    is_active = models.BooleanField("действует", default=True)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "подразделение"
        verbose_name_plural = "подразделения"

    def __str__(self):
        return self.name

    @property
    def depth(self):
        return self.path.count("/") - 2

    def clean(self):
        allowed = self.ALLOWED_PARENTS.get(self.kind, ())
        if self.parent is None:
            if self.kind != self.Kind.UNIVERSITY:
                raise ValidationError({"parent": "Укажите, куда входит подразделение."})
            return
        if self.parent.kind not in allowed:
            raise ValidationError(
                {"parent": f"«{self.get_kind_display()}» не может входить в «{self.parent.get_kind_display()}»."}
            )
        if self.pk and (self.parent_id == self.pk or self.parent.path.startswith(self.path or "\0")):
            raise ValidationError({"parent": "Подразделение не может входить само в себя или в своё дочернее."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        old_path = self.path
        super().save(*args, **kwargs)
        new_path = f"{self.parent.path if self.parent else '/'}{self.pk}/"
        if new_path != old_path:
            OrgUnit.objects.filter(pk=self.pk).update(path=new_path)
            self.path = new_path
            if old_path:
                # Переезд: переписать пути всех вложенных подразделений.
                for child in OrgUnit.objects.filter(path__startswith=old_path).exclude(pk=self.pk):
                    OrgUnit.objects.filter(pk=child.pk).update(path=new_path + child.path[len(old_path):])

    def descendants(self, include_self=True):
        qs = OrgUnit.objects.filter(path__startswith=self.path)
        return qs if include_self else qs.exclude(pk=self.pk)

    def ancestors(self):
        ids = [int(x) for x in self.path.strip("/").split("/") if x]
        return OrgUnit.objects.filter(pk__in=ids).exclude(pk=self.pk).order_by("path")

    def delete_blockers(self):
        """Причины, по которым подразделение нельзя удалить (тогда его можно только закрыть)."""
        reasons = []
        if self.children.exists():
            reasons.append(f"внутри есть подразделения ({self.children.count()})")
        n = self.role_assignments.count()
        if n:
            reasons.append(f"к нему привязаны сотрудники ({n})")
        k = self.inspections.count()
        if k:
            reasons.append(f"у него есть проверки ({k})")
        return reasons
