from django.urls import path

from . import views

app_name = "processes"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.process_form, name="create"),
    path("risks/", views.risk_map, name="risks"),
    path("strategy/", views.save_strategy, name="save_strategy"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.process_form, name="edit"),
    path("<int:pk>/risks/new/", views.risk_form, name="risk_create"),
    path("risks/<int:risk_pk>/", views.risk_form, name="risk_edit"),
]
