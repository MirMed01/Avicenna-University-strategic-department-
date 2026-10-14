from django.urls import path

from . import views

app_name = "org"
urlpatterns = [
    path("", views.tree, name="tree"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("<int:pk>/toggle/", views.toggle_active, name="toggle"),
]
