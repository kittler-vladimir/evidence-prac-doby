from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("prihlaseni/", views.LoginView.as_view(), name="login"),
    path("odhlaseni/", views.LogoutView.as_view(), name="logout"),
    path("profil/", views.profil, name="profil"),
    # Admin správa zaměstnanců
    path("zamestnanci/", views.seznam_zamestnancu, name="seznam_zamestnancu"),
    path("zamestnanci/pridat/", views.pridat_zamestnance, name="pridat_zamestnance"),
    path("zamestnanci/<int:pk>/upravit/", views.upravit_zamestnance, name="upravit_zamestnance"),
    path("zamestnanci/<int:pk>/presunout/", views.presunout_zamestnance, name="presunout_zamestnance"),
]
