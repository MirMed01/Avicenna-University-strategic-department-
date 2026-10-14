from django.urls import path

from . import views

app_name = "inspections"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/do/<str:action>/", views.transition, name="transition"),
    path("<int:pk>/recalc/", views.recalc, name="recalc"),
    path("<int:pk>/tasks/add/", views.add_task, name="add_task"),
    path("<int:pk>/findings/add/", views.add_finding, name="add_finding"),
    path("findings/<int:pk>/delete/", views.delete_finding, name="delete_finding"),
    path("tasks/<int:task_pk>/", views.fill, name="fill"),
    path("tasks/<int:task_pk>/reopen/", views.reopen_task, name="reopen_task"),
]
