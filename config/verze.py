"""Verze aplikace (soubor VERSION) a přehled změn (CHANGELOG.md) pro zobrazení v aplikaci (#124).

Bez závislosti na Djangu — importuje ho i `settings.py`. Chybějící nebo nečitelný soubor
nikdy nevyvolá výjimku, stránky se jen zobrazí bez údaje.
"""
from pathlib import Path

NEZNAMA_VERZE = "neznámá"


def precti_verzi(cesta):
    """Verze z prvního řádku souboru `cesta`, nebo „neznámá“ (chybí, prázdný, nečitelný)."""
    try:
        radky = Path(cesta).read_text(encoding="utf-8").strip().splitlines()
    except (OSError, UnicodeDecodeError):
        return NEZNAMA_VERZE
    return radky[0].strip() if radky and radky[0].strip() else NEZNAMA_VERZE


def nacti_zmeny(cesta):
    """`[{"nadpis": "25. 11. 2026", "polozky": ["…", …]}]` z CHANGELOG.md, v pořadí souboru
    (nejnovější nahoře), nebo None, když soubor nejde přečíst. Rozumí jen nadpisům `## …`
    a odrážkám `- …`; úvodní text a vše ostatní se přeskočí. Výstup je čistý text —
    šablona ho escapuje, takže HTML ze souboru se nikdy nevykreslí."""
    try:
        text = Path(cesta).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    dny = []
    for radek in text.splitlines():
        radek = radek.strip()
        if radek.startswith("## "):
            dny.append({"nadpis": radek[3:].strip(), "polozky": []})
        elif radek.startswith("- ") and dny:
            dny[-1]["polozky"].append(radek[2:].strip())
    return dny
