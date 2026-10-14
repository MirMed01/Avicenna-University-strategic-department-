from django.urls import path

from . import views

app_name = "accreditation"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/assign/", views.assign, name="assign"),
    path("<int:pk>/report.docx", views.export_docx, name="docx"),
    path("criterion/<int:pk>/", views.assessment, name="assessment"),
    path("criterion/<int:pk>/upload/", views.upload, name="upload"),
    path("file/<int:pk>/", views.download, name="file"),
]
