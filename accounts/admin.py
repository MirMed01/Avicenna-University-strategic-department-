from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import RoleAssignment, User


class RoleInline(admin.TabularInline):
    model = RoleAssignment
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("full_name",)
    list_display = ("full_name", "email", "is_active", "position")
    search_fields = ("full_name", "email")
    inlines = [RoleInline]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Сотрудник", {"fields": ("full_name", "position", "academic_degree", "academic_title")}),
        ("Заявка", {"fields": ("requested_unit", "requested_role")}),
        ("Доступ", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"fields": ("email", "full_name", "password1", "password2")}),)
