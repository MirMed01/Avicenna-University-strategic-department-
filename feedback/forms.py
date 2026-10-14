from django import forms
from django.utils.translation import gettext_lazy as _

from instruments.models import Instrument, InstrumentVersion
from org.models import OrgUnit

from .models import Campaign


class CampaignForm(forms.ModelForm):
    code_count = forms.IntegerField(label=_("Сколько кодов напечатать (по числу студентов в группе)"), min_value=1, max_value=300, initial=25)

    class Meta:
        model = Campaign
        fields = ["title", "version", "org_unit", "label", "closes_on", "min_respondents"]
        widgets = {"closes_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].queryset = InstrumentVersion.objects.filter(
            status=InstrumentVersion.Status.PUBLISHED, instrument__respondent=Instrument.Respondent.STUDENT).select_related("instrument")
        self.fields["version"].label_from_instance = lambda v: _("%(title)s (в.%(number)s)") % {"title": v.instrument.title, "number": v.number}
        self.fields["org_unit"].queryset = OrgUnit.objects.filter(is_active=True, kind=OrgUnit.Kind.DEPARTMENT).order_by("name")
        self.fields["min_respondents"].help_text = _("Не меньше 3. Пока ответов меньше, итоги не видны никому — так нельзя вычислить, кто что ответил.")
