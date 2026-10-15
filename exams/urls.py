from django.urls import path

from . import views

app_name = "exams"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.upload, name="upload"),
    path("template.xlsx", views.template, name="template"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/delete/", views.delete, name="delete"),
]
