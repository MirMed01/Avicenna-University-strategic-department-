from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from norms.models import FrameworkVersion

from .models import Assessment, Cycle, EvidenceFile, Rating


class CycleForm(forms.ModelForm):
    class Meta:
        model = Cycle
        fields = ["title", "version", "programme", "org_unit", "deadline", "lead"]
        widgets = {"deadline": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].queryset = FrameworkVersion.objects.filter(nodes__kind="criterion").distinct().select_related("framework")
        self.fields["org_unit"].queryset = self.fields["org_unit"].queryset.filter(kind="faculty", is_active=True)
        self.fields["lead"].queryset = User.objects.filter(is_active=True)


class AssessmentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ["rating", "responsible", "evidence", "justification", "measures"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in ("evidence", "justification", "measures")}

    def __init__(self, *args, can_assign=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = User.objects.filter(is_active=True)
        if not can_assign:
            del self.fields["responsible"]

    def clean(self):
        data = super().clean()
        if data.get("rating") in (Rating.IMPROVE, Rating.UNSATISFACTORY) and not (data.get("measures") or "").strip():
            self.add_error("measures", _("Для этой оценки опишите меры по улучшению — так требует структура самоотчёта IAAR."))
        return data


class EvidenceFileForm(forms.ModelForm):
    class Meta:
        model = EvidenceFile
        fields = ["title", "file"]


class AssignForm(forms.Form):
    standard = forms.CharField(widget=forms.HiddenInput)
    responsible = forms.ModelChoiceField(User.objects.filter(is_active=True), label=_("Кто готовит весь стандарт"))
