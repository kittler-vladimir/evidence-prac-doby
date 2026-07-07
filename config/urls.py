from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Skrýt postranní panel s aplikacemi/modely — nutil k rozbalování/sbalování
# přes «/» na každé stránce a zabíral místo bez přidané hodnoty. Bez něj se
# admin ovládá stejně jako dřív, jen přes odkazy na hlavní stránce a drobečkovou navigaci.
admin.site.enable_nav_sidebar = False

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls", namespace="accounts")),
    path("dochazka/", include("timetracking.urls", namespace="timetracking")),
    path("dovolena/", include("leaves.urls", namespace="leaves")),
    path("reporty/", include("reports.urls", namespace="reports")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
