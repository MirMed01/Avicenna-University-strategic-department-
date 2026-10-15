from django.urls import path

from . import views

app_name = "management"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/refresh/", views.refresh, name="refresh"),
    path("<int:pk>/held/", views.mark_held, name="held"),
    path("<int:pk>/decisions/add/", views.decision_add, name="decision_add"),
    path("decisions/<int:pk>/", views.decision_report, name="decision_report"),
]
