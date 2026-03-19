from django.urls import path

from . import views

urlpatterns = [
    path("", views.ValidatorHomeView.as_view(), name="validator_home"),
]
