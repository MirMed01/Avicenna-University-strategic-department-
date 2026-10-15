from django.urls import path

from . import views

app_name = "feedback"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/codes/", views.codes, name="codes"),
    path("<int:pk>/codes/add/", views.add_codes, name="add_codes"),
    path("<int:pk>/toggle/", views.toggle, name="toggle"),
    path("texts/<uuid:pk>/", views.moderate, name="moderate"),
    path("<int:pk>/changes/add/", views.change_add, name="change_add"),
    path("changes/<int:pk>/delete/", views.change_delete, name="change_delete"),
]

public_urlpatterns = [
    path("", views.entry, name="entry"),
    path("<str:code>/", views.vote, name="vote"),
]
