from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import WorkSession, WorkdaySummary


@receiver(post_save, sender=WorkSession)
def prepocitej_po_ulozeni(sender, instance, **kwargs):
    """Po uložení session přepočítej denní souhrn."""
    if instance.konec:
        WorkdaySummary.prepocitej(instance.employee, instance.zacatek.date())


@receiver(post_delete, sender=WorkSession)
def prepocitej_po_smazani(sender, instance, **kwargs):
    """Po smazání session přepočítej denní souhrn."""
    WorkdaySummary.prepocitej(instance.employee, instance.zacatek.date())
