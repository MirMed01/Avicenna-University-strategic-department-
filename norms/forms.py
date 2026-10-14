from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Framework, FrameworkVersion, Indicator, LevelAssignment, NormNode


class FrameworkForm(forms.ModelForm):
    version = forms.CharField(label=_("Редакция"), max_length=50)
    effective_from = forms.DateField(label=_("Действует с"), required=False, widget=forms.DateInput(attrs={"type": "date"}))
    source_url = forms.URLField(label=_("Ссылка на документ"), required=False)

    class Meta:
        model = Framework
        fields = ["code", "title", "description"]


class NormNodeForm(forms.ModelForm):
    class Meta:
        model = NormNode
        fields = ["kind", "code", "title", "text", "order"]


class IndicatorForm(forms.ModelForm):
    class Meta:
        model = Indicator
        fields = [
            "code", "title", "unit", "direction",
            "threshold_weak", "threshold_medium", "threshold_high",
            "measurement", "note", "order",
        ]


class LevelAssignmentForm(forms.ModelForm):
    class Meta:
        model = LevelAssignment
        fields = ["org_unit", "level"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["org_unit"].queryset = self.fields["org_unit"].queryset.filter(is_active=True).order_by("path")
        self.fields["org_unit"].label_from_instance = lambda u: ("— " * u.depth) + u.name
