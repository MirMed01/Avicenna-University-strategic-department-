from django import forms

from .models import OrgUnit


class OrgUnitForm(forms.ModelForm):
    class Meta:
        model = OrgUnit
        fields = ["kind", "name", "short_name", "parent", "order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = OrgUnit.objects.exclude(kind=OrgUnit.Kind.DEPARTMENT).order_by("path")
        if self.instance.pk:
            qs = qs.exclude(path__startswith=self.instance.path)
        self.fields["parent"].queryset = qs
        self.fields["parent"].label_from_instance = lambda u: ("— " * u.depth) + u.name
