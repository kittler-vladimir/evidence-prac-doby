from django.conf import settings


def verze_aplikace(request):
    """Verze aplikace do všech šablon (patička v base.html) — viz config/verze.py."""
    return {"verze_aplikace": settings.VERZE_APLIKACE}
