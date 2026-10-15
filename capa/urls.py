from django.urls import path

from . import views

app_name = "capa"
urlpatterns = [
    path("", views.index, name="index"),
    path("problems/", views.problems, name="problems"),
    path("problems/new/", views.problem_form, name="problem_create"),
    path("problems/<int:pk>/", views.problem_form, name="problem_edit"),
    path("problems/groups/new/", views.group_form, name="group_create"),
    path("problems/groups/<int:pk>/", views.group_form, name="group_edit"),
    path("from-finding/<int:finding_pk>/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/do/<str:action>/", views.transition, name="transition"),
    path("<int:pk>/followup/", views.schedule_followup, name="followup"),
    path("<int:pk>/actions/add/", views.action_add, name="action_add"),
    path("actions/<int:action_pk>/delete/", views.action_delete, name="action_delete"),
    path("actions/<int:action_pk>/report/", views.action_report, name="action_report"),
]
