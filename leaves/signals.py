from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

from .models import ZadostOStav


def _posli_email(subject: str, template: str, context: dict, recipients: list[str]):
    """Pomocná funkce pro odesílání e-mailu."""
    if not recipients:
        return
    body = render_to_string(template, context)
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


@receiver(post_save, sender=ZadostOStav)
def notifikace_zadost(sender, instance, created, **kwargs):
    """
    Odesílá e-mailové notifikace:
    - při vytvoření žádosti → schvalovateli
    - při schválení → zaměstnanci
    - při zamítnutí → zaměstnanci
    """
    zadost = instance

    if created:
        # Notifikace schvalovateli
        if zadost.schvalovatele and zadost.schvalovatele.email:
            _posli_email(
                subject=f"Nová žádost o {zadost.typ.nazev.lower()} – {zadost.employee.jmeno}",
                template="leaves/emails/nova_zadost.txt",
                context={"zadost": zadost},
                recipients=[zadost.schvalovatele.email],
            )
        return

    # Poslat jen při skutečném přechodu stavu, ne při každém dalším uložení
    # už vyřízené žádosti (viz ZadostOStav.save()).
    if not getattr(zadost, "_stav_se_zmenil", True):
        return

    # Při změně stavu
    if zadost.stav == ZadostOStav.Stav.SCHVALENO:
        _posli_email(
            subject=f"Vaše žádost o {zadost.typ.nazev.lower()} byla schválena",
            template="leaves/emails/schvaleno.txt",
            context={"zadost": zadost},
            recipients=[zadost.employee.email],
        )

    elif zadost.stav == ZadostOStav.Stav.ZAMITNUTO:
        _posli_email(
            subject=f"Vaše žádost o {zadost.typ.nazev.lower()} byla zamítnuta",
            template="leaves/emails/zamitnuto.txt",
            context={"zadost": zadost},
            recipients=[zadost.employee.email],
        )
