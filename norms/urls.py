from django.urls import path

from . import views

app_name = "norms"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.framework_create, name="framework_create"),
    path("<int:pk>/", views.version_detail, name="version"),
    path("<int:version_pk>/nodes/new/", views.node_create, name="node_create"),
    path("<int:version_pk>/level/", views.level_set, name="level_set"),
    path("nodes/<int:pk>/edit/", views.node_edit, name="node_edit"),
    path("nodes/<int:pk>/delete/", views.node_delete, name="node_delete"),
    path("nodes/<int:node_pk>/indicators/new/", views.indicator_create, name="indicator_create"),
    path("indicators/<int:pk>/edit/", views.indicator_edit, name="indicator_edit"),
    path("indicators/<int:pk>/delete/", views.indicator_delete, name="indicator_delete"),
    path("levels/<int:pk>/remove/", views.level_remove, name="level_remove"),
]
