from django.urls import path
from . import views

app_name = "leaves"

urlpatterns = [
    path("", views.moje_zadosti, name="moje_zadosti"),
    path("nova/", views.nova_zadost, name="nova_zadost"),
    path("ke-schvaleni/", views.ke_schvaleni, name="ke_schvaleni"),
    path("<int:pk>/", views.detail_zadosti, name="detail_zadosti"),
    path("<int:pk>/schvalit/", views.schvalit, name="schvalit"),
    path("<int:pk>/schvalit-sam/", views.schvalit_sam, name="schvalit_sam"),
    path("<int:pk>/zamitnou/", views.zamitnou, name="zamitnou"),
    path("<int:pk>/stornovat/", views.stornovat, name="stornovat"),
    path("<int:pk>/zrusit/", views.zrusit, name="zrusit"),
    path("zruseni/<int:pk>/schvalit/", views.schvalit_zruseni, name="schvalit_zruseni"),
    path("zruseni/<int:pk>/schvalit-sam/", views.schvalit_zruseni_sam, name="schvalit_zruseni_sam"),
    path("zruseni/<int:pk>/zamitnout/", views.zamitnout_zruseni, name="zamitnout_zruseni"),
]
