from django import forms

from accounts.models import User
from instruments.forms import indicator_field

from django.utils.translation import gettext_lazy as _

from .models import Action, Cause, Plan, Problem, ProblemGroup

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def people_field(f):
    f.queryset = User.objects.filter(is_active=True).order_by("full_name")
    return f


class PlanCreateForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["problem", "title", "root_cause", "owner", "due_date", "effectiveness_criterion"]
        widgets = {"due_date": DATE, "root_cause": forms.Textarea(attrs={"rows": 3}),
                   "effectiveness_criterion": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, suggested=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Problem.objects.filter(is_active=True)
        self.fields["problem"].queryset = qs
        if suggested:
            # Подсказанные по показателю — первыми в списке.
            ids = [p.pk for p in suggested]
            self.fields["problem"].choices = [("", "---------")] + [
                (p.pk, f"★ {p}") for p in suggested] + [(p.pk, str(p)) for p in qs if p.pk not in ids]
        people_field(self.fields["owner"])


class PlanEditForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["title", "root_cause", "owner", "due_date", "effectiveness_criterion"]
        widgets = PlanCreateForm.Meta.widgets

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        people_field(self.fields["owner"])


class ActionForm(forms.ModelForm):
    class Meta:
        model = Action
        fields = ["type", "title", "responsible", "due_date"]
        widgets = {"due_date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        people_field(self.fields["responsible"])


class ProblemForm(forms.ModelForm):
    cause_set = forms.MultipleChoiceField(label=_("Тип причины"), choices=Cause.choices, required=False,
                                          widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Problem
        fields = ["group", "code", "title", "description", "typical_actions", "indicators", "is_active"]
        widgets = {"indicators": forms.SelectMultiple(attrs={"size": 8})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        indicator_field(self.fields["indicators"])
        self.fields["group"].queryset = ProblemGroup.objects.filter(is_active=True)
        if self.instance.pk:
            self.fields["cause_set"].initial = self.instance.cause_list()
        self.order_fields(["group", "code", "title", "description", "cause_set"])

    def save(self, commit=True):
        self.instance.causes = ",".join(self.cleaned_data["cause_set"])
        return super().save(commit)


class ProblemGroupForm(forms.ModelForm):
    class Meta:
        model = ProblemGroup
        fields = ["code", "title", "order", "is_active"]
