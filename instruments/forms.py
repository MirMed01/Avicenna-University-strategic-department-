from django import forms

from norms.models import Indicator

from .models import Derived, Instrument, Item, Section


def indicator_field(f):
    f.queryset = Indicator.objects.select_related("node__version__framework").order_by(
        "node__version__framework__title", "node__order", "order", "code")
    f.label_from_instance = lambda i: f"{i.node.version.framework.title} — {i.code} {i.title[:80]}"
    return f


class InstrumentForm(forms.ModelForm):
    class Meta:
        model = Instrument
        fields = ["code", "title", "kind", "respondent", "description", "source_title", "source_url"]


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ["title", "text", "order"]


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["code", "text", "help", "type", "options", "required", "weight", "indicator", "order"]

    def __init__(self, *args, section=None, **kwargs):
        super().__init__(*args, **kwargs)
        if section is not None:
            self.instance.section = section
        indicator_field(self.fields["indicator"])


class DerivedForm(forms.ModelForm):
    class Meta:
        model = Derived
        fields = ["code", "title", "method", "numerator", "denominator", "section", "indicator", "order"]

    def __init__(self, *args, version=None, **kwargs):
        super().__init__(*args, **kwargs)
        version = version or self.instance.version
        self.instance.version = version
        numbers = Item.objects.filter(section__version=version, type=Item.Type.NUMBER)
        for f in ("numerator", "denominator"):
            self.fields[f].queryset = numbers
            self.fields[f].label_from_instance = lambda i: f"{i.code} {i.text[:80]}"
        self.fields["section"].queryset = version.sections.all()
        indicator_field(self.fields["indicator"])
