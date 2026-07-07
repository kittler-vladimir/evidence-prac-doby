from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import WorkSession, WorkdaySummary, Pohyb


@receiver(post_save, sender=WorkSession)
def prepocitej_po_ulozeni(sender, instance, **kwargs):
    """Po uložení session přepočítej denní souhrn."""
    if instance.konec:
        WorkdaySummary.prepocitej(instance.employee, instance.zacatek.date())


@receiver(post_delete, sender=WorkSession)
def prepocitej_po_smazani(sender, instance, **kwargs):
    """Po smazání session přepočítej denní souhrn."""
    WorkdaySummary.prepocitej(instance.employee, instance.zacatek.date())


@receiver(post_save, sender=Pohyb)
def prepocitej_po_ulozeni_pohybu(sender, instance, **kwargs):
    """Po uzavření pohybu (konec vyplněn) přepočítej denní souhrn dne, kdy začal pracovní blok."""
    if instance.konec:
        WorkdaySummary.prepocitej(instance.work_session.employee, instance.work_session.zacatek.date())


@receiver(post_delete, sender=Pohyb)
def prepocitej_po_smazani_pohybu(sender, instance, **kwargs):
    """Po smazání pohybu přepočítej denní souhrn."""
    WorkdaySummary.prepocitej(instance.work_session.employee, instance.work_session.zacatek.date())
