from django import forms

from instruments.forms import indicator_field
from norms.models import NormNode

from .models import Process, Risk


class ProcessForm(forms.ModelForm):
    class Meta:
        model = Process
        fields = ["code", "title", "level", "parent", "group", "is_key", "purpose", "owner_position", "owner", "suppliers", "inputs", "outputs",
                  "customers", "resources", "documents", "improvement", "is_digital", "norm_nodes", "indicators", "instruments", "order", "is_active"]
        widgets = {f: forms.Textarea(attrs={"rows": 2}) for f in
                   ("purpose", "suppliers", "inputs", "outputs", "customers", "resources", "documents", "improvement")}
        widgets.update({"norm_nodes": forms.SelectMultiple(attrs={"size": 12}), "indicators": forms.SelectMultiple(attrs={"size": 10}),
                        "instruments": forms.SelectMultiple(attrs={"size": 10})})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        indicator_field(self.fields["indicators"])
        nodes = self.fields["norm_nodes"]
        nodes.queryset = NormNode.objects.select_related("version__framework").order_by(
            "version__framework__title", "order", "code")
        nodes.label_from_instance = lambda n: f"{n.version.framework.title} — {n.code} {n.title[:70]}"
        self.fields["parent"].queryset = Process.objects.filter(parent__isnull=True).exclude(pk=self.instance.pk)
        from accounts.models import User

        self.fields["owner"].queryset = User.objects.filter(is_active=True).order_by("full_name")


class RiskForm(forms.ModelForm):
    class Meta:
        model = Risk
        fields = ["title", "likelihood", "impact", "measures", "responsible", "review_date", "is_closed"]
        widgets = {"measures": forms.Textarea(attrs={"rows": 2}),
                   "review_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
