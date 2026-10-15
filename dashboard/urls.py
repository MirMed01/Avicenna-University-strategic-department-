from django.urls import path

from . import views

app_name = "dashboard"
urlpatterns = [
    path("", views.index, name="index"),
    path("strategy/<int:indicator_pk>/", views.strategy_value, name="strategy_value"),
    path("unit/<int:unit_pk>/history/", views.unit_history_view, name="history"),
    path("export.xlsx", views.export_xlsx, name="xlsx"),
    path("report.docx", views.export_docx, name="docx"),
]
