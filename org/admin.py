from django.contrib import admin

from .models import OrgUnit


@admin.register(OrgUnit)
class OrgUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "parent", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "short_name")
