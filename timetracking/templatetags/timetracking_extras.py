from django import template

from timetracking.bilance import format_minut

register = template.Library()


@register.filter
def minuty_hm(minuty):
    """Minuty jako 'Xh Ymin' (z absolutní hodnoty)."""
    if minuty in (None, ""):
        return ""
    return format_minut(minuty)


@register.filter
def minuty_hm_znamenko(minuty):
    """Minuty jako 'Xh Ymin'; záporná hodnota s '−' (pro bilanci)."""
    if minuty in (None, ""):
        return ""
    return format_minut(minuty, se_znamenkem=True)
