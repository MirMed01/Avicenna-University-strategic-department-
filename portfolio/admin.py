from django.contrib import admin

from .models import PortfolioEntry


@admin.register(PortfolioEntry)
class PortfolioEntryAdmin(admin.ModelAdmin):
    list_display = ("owner", "kind", "title", "date_start", "status")
    list_filter = ("kind", "status")
    search_fields = ("title", "owner__full_name")
