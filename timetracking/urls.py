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
    path("pohyb/zahajit/", views.start_pohyb, name="start_pohyb"),
    path("pohyb/navrat/", views.return_pohyb, name="return_pohyb"),
    path("pohyb/pridat/", views.pridat_pohyb, name="pridat_pohyb"),
]
