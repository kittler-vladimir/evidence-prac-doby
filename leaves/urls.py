from django.urls import path
from . import views

app_name = "leaves"

urlpatterns = [
    path("", views.moje_zadosti, name="moje_zadosti"),
    path("nova/", views.nova_zadost, name="nova_zadost"),
    path("ke-schvaleni/", views.ke_schvaleni, name="ke_schvaleni"),
    path("<int:pk>/", views.detail_zadosti, name="detail_zadosti"),
    path("<int:pk>/schvalit/", views.schvalit, name="schvalit"),
    path("<int:pk>/zamitnou/", views.zamitnou, name="zamitnou"),
    path("<int:pk>/stornovat/", views.stornovat, name="stornovat"),
]
