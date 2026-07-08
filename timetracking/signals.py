import time

from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver

from accounts.models import Employee
from .models import WorkSession, WorkdaySummary, Pohyb

# {employee_pk: timestamp} zaměstnanců, jejichž smazání právě probíhá (viz
# oznac_zamestnance_ke_smazani). Značka má TTL strop, aby se nezasekla
# navždy, pokud by kaskáda mazání skončila výjimkou/rollbackem někde mezi
# oznac_zamestnance_ke_smazani a odznac_zamestnance_po_smazani — tahle
# mutace je čistě v paměti procesu, takže ji DB rollback sám nevrátí zpět.
_zamestnanci_ke_smazani = {}
_ZNACKA_TTL_SEKUND = 30


def _prave_se_maze(employee_id):
    oznaceno_v = _zamestnanci_ke_smazani.get(employee_id)
    return oznaceno_v is not None and time.monotonic() - oznaceno_v < _ZNACKA_TTL_SEKUND


@receiver(post_save, sender=WorkSession)
def prepocitej_po_ulozeni(sender, instance, **kwargs):
    """Po uložení session přepočítej denní souhrn."""
    if instance.konec:
        WorkdaySummary.prepocitej(instance.employee, instance.zacatek.date())


@receiver(post_delete, sender=WorkSession)
def prepocitej_po_smazani(sender, instance, **kwargs):
    """Po smazání session přepočítej denní souhrn (viz oznac_zamestnance_ke_smazani)."""
    if not _prave_se_maze(instance.employee_id):
        WorkdaySummary.prepocitej(instance.employee, instance.zacatek.date())


@receiver(post_save, sender=Pohyb)
def prepocitej_po_ulozeni_pohybu(sender, instance, **kwargs):
    """Po uzavření pohybu (konec vyplněn) přepočítej denní souhrn dne, kdy začal pracovní blok."""
    if instance.konec:
        WorkdaySummary.prepocitej(instance.work_session.employee, instance.work_session.zacatek.date())


@receiver(post_delete, sender=Pohyb)
def prepocitej_po_smazani_pohybu(sender, instance, **kwargs):
    """Po smazání pohybu přepočítej denní souhrn (viz oznac_zamestnance_ke_smazani)."""
    if not _prave_se_maze(instance.work_session.employee_id):
        WorkdaySummary.prepocitej(instance.work_session.employee, instance.work_session.zacatek.date())


@receiver(pre_delete, sender=Employee)
def oznac_zamestnance_ke_smazani(sender, instance, **kwargs):
    """
    Django při kaskádovém mazání (např. smazání User → Employee →
    WorkSession/Pohyb → WorkdaySummary) pošle pre_delete signály pro
    úplně všechny zasažené objekty ještě předtím, než cokoliv skutečně
    smaže z databáze — teprve pak postupně maže po jednotlivých modelech
    a po každém z nich posílá post_delete.

    Díky tomu tenhle signál spolehlivě proběhne dřív, než post_delete
    u WorkSession/Pohyb výše. Bez něj by přepočet denního souhrnu při
    mazání session/pohybu jako vedlejší efekt smazání zaměstnance znovu
    založil WorkdaySummary řádek, který kolektor smazání už nestihne
    zahrnout do svého plánu — a po smazání Employee by zůstal osiřelý
    (neplatná FK).
    """
    _zamestnanci_ke_smazani[instance.pk] = time.monotonic()


@receiver(post_delete, sender=Employee)
def odznac_zamestnance_po_smazani(sender, instance, **kwargs):
    _zamestnanci_ke_smazani.pop(instance.pk, None)
