from django.urls import path

from . import views

app_name = "portfolio"
urlpatterns = [
    path("", views.my, name="my"),
    path("new/", views.create, name="create"),
    path("queue/", views.queue, name="queue"),
    path("user/<int:user_pk>/", views.show, name="show"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("<int:pk>/submit/", views.submit, name="submit"),
    path("<int:pk>/review/", views.review, name="review"),
    path("<int:pk>/file/", views.download, name="file"),
]
