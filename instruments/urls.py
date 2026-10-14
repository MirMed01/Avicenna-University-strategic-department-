from django.urls import path

from . import views

app_name = "instruments"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.version, name="version"),
    path("<int:pk>/try/", views.try_fill, name="try"),
    path("<int:pk>/publish/", views.publish, name="publish"),
    path("<int:pk>/new-version/", views.new_version, name="new_version"),
    path("<int:version_pk>/sections/new/", views.section_form, name="section_create"),
    path("<int:version_pk>/sections/<int:pk>/", views.section_form, name="section_edit"),
    path("<int:version_pk>/derived/new/", views.derived_form, name="derived_create"),
    path("<int:version_pk>/derived/<int:pk>/", views.derived_form, name="derived_edit"),
    path("sections/<int:section_pk>/items/new/", views.item_form, name="item_create"),
    path("sections/<int:section_pk>/items/<int:pk>/", views.item_form, name="item_edit"),
    path("instrument/<int:pk>/edit/", views.edit, name="edit"),
    path("delete/<str:kind>/<int:pk>/", views.delete_part, name="delete"),
]
