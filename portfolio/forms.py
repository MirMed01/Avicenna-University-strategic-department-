from django import forms

from .models import PortfolioEntry


class PortfolioEntryForm(forms.ModelForm):
    class Meta:
        model = PortfolioEntry
        fields = [
            "kind", "title", "organization", "date_start", "date_end", "hours",
            "indexing", "doi_or_url", "details", "file",
        ]
        widgets = {
            "date_start": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "date_end": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }


class ReviewForm(forms.Form):
    comment = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea(attrs={"rows": 2}))
