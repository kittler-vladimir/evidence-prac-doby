from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("", views.reports_urls, name="index"),
    path("tym/", views.prehled_tymu, name="prehled_tymu"),
    path("export/xlsx/", views.export_xlsx, name="export_xlsx"),
    path("pritomnost/", views.prehled_pritomnosti, name="prehled_pritomnosti"),
    path("vyhledat/", views.vyhledat_zamestnance, name="vyhledat_zamestnance"),
]
