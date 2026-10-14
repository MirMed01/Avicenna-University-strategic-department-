from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from org.models import OrgUnit

from .models import SELF_REQUEST_ROLES, Role, RoleAssignment, User


def unit_choices_field(label=_("Подразделение"), required=True):
    f = forms.ModelChoiceField(OrgUnit.objects.filter(is_active=True).order_by("path"), label=label, required=required)
    f.label_from_instance = lambda u: ("— " * u.depth) + u.name
    return f


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email")

    error_messages = {
        "invalid_login": _("Неверный email или пароль."),
        "inactive": _("Доступ ещё не открыт. Дождитесь подтверждения администратора."),
    }


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Пароль ещё раз"), widget=forms.PasswordInput)
    requested_role = forms.ChoiceField(label=_("Кем вы работаете"), choices=[(r.value, r.label) for r in SELF_REQUEST_ROLES])
    requested_unit = unit_choices_field(_("Ваше подразделение (кафедра, факультет или центр)"))

    class Meta:
        model = User
        fields = ["full_name", "email", "position", "academic_degree", "academic_title", "requested_role", "requested_unit"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("Этот email уже зарегистрирован."))
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p1 != p2:
            self.add_error("password2", _("Пароли не совпадают."))
        elif p1:
            try:
                validate_password(p1)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.is_active = False
        if commit:
            user.save()
        return user


class RoleAssignmentForm(forms.Form):
    role = forms.ChoiceField(label=_("Роль"), choices=Role.choices)
    org_unit = unit_choices_field()

    def clean(self):
        data = super().clean()
        role, unit = data.get("role"), data.get("org_unit")
        if role in (Role.HEAD, Role.TEACHER) and unit and unit.kind != OrgUnit.Kind.DEPARTMENT:
            self.add_error("org_unit", _("Для заведующего и преподавателя выберите кафедру."))
        if role == Role.DEAN and unit and unit.kind != OrgUnit.Kind.FACULTY:
            self.add_error("org_unit", _("Для декана выберите факультет."))
        return data


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "position", "academic_degree", "academic_title"]
