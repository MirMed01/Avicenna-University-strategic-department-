from django import forms

from accounts.models import Role, User
from instruments.models import InstrumentVersion
from org.models import OrgUnit

from .models import Finding, Inspection


class InspectionForm(forms.ModelForm):
    instruments = forms.ModelMultipleChoiceField(
        InstrumentVersion.objects.none(), label="Инструменты (по одному заполнению; добавить ещё можно позже)",
        widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Inspection
        fields = ["title", "org_unit", "lead_expert", "due_date", "note"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        units = OrgUnit.objects.filter(is_active=True, kind__in=[OrgUnit.Kind.DEPARTMENT, OrgUnit.Kind.FACULTY]).order_by("path")
        self.fields["org_unit"].queryset = units
        self.fields["org_unit"].label_from_instance = lambda u: ("— " * u.depth) + u.name
        self.fields["lead_expert"].queryset = User.objects.filter(
            is_active=True, roles__role__in=[Role.EXPERT, Role.DIRECTOR]).distinct()
        self.fields["instruments"].queryset = InstrumentVersion.objects.filter(
            status=InstrumentVersion.Status.PUBLISHED).exclude(instrument__respondent="student").select_related("instrument").order_by("instrument__title")
        self.fields["instruments"].label_from_instance = lambda v: f"{v.instrument.title} (в.{v.number}) — заполняет: {v.instrument.get_respondent_display().lower()}"


class AddTaskForm(forms.Form):
    version = forms.ModelChoiceField(InstrumentVersion.objects.filter(status=InstrumentVersion.Status.PUBLISHED).exclude(
        instrument__respondent="student"), label="Инструмент")
    label = forms.CharField(label="Уточнение", required=False, help_text="Например: «занятие доц. Н., 3 курс».")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].label_from_instance = lambda v: f"{v.instrument.title} (в.{v.number})"


class FindingForm(forms.ModelForm):
    class Meta:
        model = Finding
        fields = ["severity", "text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 2})}
