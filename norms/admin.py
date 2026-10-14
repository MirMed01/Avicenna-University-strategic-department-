from django.contrib import admin

from .models import Framework, FrameworkVersion, Indicator, LevelAssignment, NormNode


class VersionInline(admin.TabularInline):
    model = FrameworkVersion
    extra = 0


@admin.register(Framework)
class FrameworkAdmin(admin.ModelAdmin):
    list_display = ("title", "code")
    inlines = [VersionInline]


class IndicatorInline(admin.TabularInline):
    model = Indicator
    extra = 0
    fields = ("code", "title", "unit", "direction", "threshold_weak", "threshold_medium", "threshold_high")


@admin.register(NormNode)
class NormNodeAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "kind", "version")
    list_filter = ("version__framework", "kind")
    search_fields = ("code", "title")
    inlines = [IndicatorInline]


admin.site.register(LevelAssignment)
