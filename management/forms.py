from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import User

from .models import Decision, Review

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["title", "date", "period_from", "period_to", "participants", "changes", "resources", "conclusions"]
        widgets = {"date": DATE, "period_from": DATE, "period_to": DATE,
                   **{f: forms.Textarea(attrs={"rows": 3}) for f in ("participants", "changes", "resources", "conclusions")}}

    def clean(self):
        d = super().clean()
        if d.get("period_from") and d.get("period_to") and d["period_from"] > d["period_to"]:
            raise forms.ValidationError(_("Начало периода позже конца."))
        return d


class DecisionForm(forms.ModelForm):
    class Meta:
        model = Decision
        fields = ["text", "responsible", "due_date"]
        widgets = {"text": forms.Textarea(attrs={"rows": 2}), "due_date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = User.objects.filter(is_active=True).order_by("full_name")


class DecisionReportForm(forms.ModelForm):
    class Meta:
        model = Decision
        fields = ["state", "result"]
        widgets = {"result": forms.Textarea(attrs={"rows": 2})}
