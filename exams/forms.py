from django import forms
from django.utils.translation import gettext_lazy as _

from .models import ExamAnalysis


class UploadForm(forms.ModelForm):
    file = forms.FileField(label=_("Файл Excel (.xlsx) с ответами"),
                           help_text=_("Первая строка — номера заданий; вторая (по желанию) — «Ключ» с верными ответами; "
                                       "дальше — по строке на студента. Первый столбец (номер студента) программа пропускает и не сохраняет. "
                                       "Без строки «Ключ» в ячейках — 1 (верно) или 0 (неверно)."))

    class Meta:
        model = ExamAnalysis
        fields = ["title", "org_unit", "kind", "exam_date", "note"]
        widgets = {"exam_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, units=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["org_unit"].queryset = units

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(_("Нужен файл Excel в формате .xlsx."))
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError(_("Файл больше 5 МБ."))
        return f
