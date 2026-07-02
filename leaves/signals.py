from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

from .models import ZadostODovolenou


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


@receiver(post_save, sender=ZadostODovolenou)
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
                subject=f"Nová žádost o dovolenou – {zadost.employee.jmeno}",
                template="leaves/emails/nova_zadost.txt",
                context={"zadost": zadost},
                recipients=[zadost.schvalovatele.email],
            )
        return

    # Při změně stavu
    if zadost.stav == ZadostODovolenou.Stav.SCHVALENO:
        _posli_email(
            subject="Vaše žádost o dovolenou byla schválena",
            template="leaves/emails/schvaleno.txt",
            context={"zadost": zadost},
            recipients=[zadost.employee.email],
        )

    elif zadost.stav == ZadostODovolenou.Stav.ZAMITNUTO:
        _posli_email(
            subject="Vaše žádost o dovolenou byla zamítnuta",
            template="leaves/emails/zamitnuto.txt",
            context={"zadost": zadost},
            recipients=[zadost.employee.email],
        )
