from django.urls import path
from . import views

app_name = "timetracking"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("prichod/", views.clock_in, name="clock_in"),
    path("odchod/", views.clock_out, name="clock_out"),
    path("mesic/", views.prehled_mesice, name="prehled_mesice"),
    path("opravit/<int:pk>/", views.opravit_session, name="opravit_session"),
    path("pridat/", views.pridat_session, name="pridat_session"),
]
