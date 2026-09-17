#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vanjski promptovi — uređivanje bez diranja koda.

Svi promptovi oba generatora prolaze kroz ovaj modul. Za svaki prompt postoje
dvije razine podešavanja, obje kao obične .md datoteke u mapi `prompts/`:

  1. NAPOMENE (preporučeno za komentare klijenta) — datoteka se DODAJE na kraj
     ugrađenog prompta kao zaseban odjeljak. Ugrađena pravila ostaju netaknuta.
         prompts/seo_napomene.md              → SEO title/meta
         prompts/pdp_napomene.md              → svi PDP proizvodi
         prompts/pdp_napomene_cosmetics.md    → samo kozmetika
         prompts/pdp_napomene_supplement.md   → samo dodaci prehrani
         prompts/pdp_napomene_device.md       → samo uređaji
         prompts/pdp_napomene_formula.md      → samo mliječne formule
         prompts/verify_napomene.md           → kontrolor činjenica

  2. OVERRIDE (potpuna zamjena prompta) — ako datoteka postoji, ona u cijelosti
     zamjenjuje ugrađeni prompt. Podržani su {placeholderi} navedeni u
     zaglavlju svake predloške datoteke.
         prompts/seo_system.md
         prompts/pdp_system.md
         prompts/verify_system.md

Mapa se stvara naredbom:  python prompts_cfg.py --init [--dir prompts]
Time se u nju zapisuju AKTUALNI ugrađeni promptovi kao polazište za uređivanje.

Ako datoteka ne postoji, koristi se ugrađeni prompt — alati rade i bez mape.
"""

from __future__ import annotations

import argparse
from pathlib import Path

_DIR = Path("prompts")
_CACHE: dict[str, str | None] = {}

NOTE_HEADER = "DODATNE UPUTE (imaju prednost pred općim stilom, ali NE ukidaju " \
              "pravila o činjeničnoj točnosti i formatu)"


class _SafeDict(dict):
    """Nepoznat {placeholder} ostaje kakav jest umjesto da digne KeyError."""

    def __missing__(self, key):
        return "{" + key + "}"


def set_dir(path) -> None:
    global _DIR
    _DIR = Path(path)
    _CACHE.clear()


def get_dir() -> Path:
    return _DIR


def _read(name: str) -> str | None:
    if name in _CACHE:
        return _CACHE[name]
    path = _DIR / f"{name}.md"
    text = None
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        # uvodni komentar predloška (redci koji počinju s "<!--" blokom) se miče
        if raw.lstrip().startswith("<!--") and "-->" in raw:
            raw = raw.split("-->", 1)[1]
        text = raw.strip() or None
    _CACHE[name] = text
    return text


def render(name: str, default: str, **vars) -> str:
    """Vrati override iz datoteke (s popunjenim placeholderima) ili ugrađeni prompt."""
    override = _read(name)
    if override is None:
        return default
    return override.format_map(_SafeDict(vars))


def with_notes(prompt: str, *names: str) -> str:
    """Dodaj sadržaj datoteka s napomenama na kraj prompta."""
    blocks = [t for t in (_read(n) for n in names) if t]
    if not blocks:
        return prompt
    return prompt + "\n\n" + NOTE_HEADER + "\n" + "\n\n".join(blocks)


def active() -> list[str]:
    """Popis datoteka koje su trenutno u uporabi (za ispis pri pokretanju)."""
    if not _DIR.exists():
        return []
    return sorted(p.name for p in _DIR.glob("*.md"))


# ---------------------------------------------------------------------------
# Inicijalizacija mape s aktualnim ugrađenim promptovima
# ---------------------------------------------------------------------------

_NOTE_TEMPLATES = {
    "seo_napomene": """<!--
Napomene za SEO title/meta. Sadržaj ove datoteke dodaje se na kraj ugrađenog
prompta. Ovdje upisuj komentare klijenta: ton, preferirane formulacije,
zabranjene riječi, pravila po brendovima i slično.
Prazna datoteka = bez dodatnih uputa.
-->

- (primjer) Brend piši točno kako stoji na pakiranju, uključujući dijakritike.
""",
    "pdp_napomene": """<!--
Napomene za SVE PDP proizvode, bez obzira na kategoriju. Dodaju se na kraj
ugrađenog prompta pisca.
-->

- (primjer) Obraćanje kupcu uvijek na "vi".
""",
    "pdp_napomene_cosmetics": """<!--
Napomene samo za kozmetiku. Dodaju se uz pdp_napomene.md.
-->
""",
    "pdp_napomene_supplement": """<!--
Napomene samo za dodatke prehrani. Dodaju se uz pdp_napomene.md.
-->
""",
    "pdp_napomene_device": """<!--
Napomene samo za uređaje i medicinske proizvode. Dodaju se uz pdp_napomene.md.
-->
""",
    "pdp_napomene_formula": """<!--
Napomene samo za mliječne formule. Dodaju se uz pdp_napomene.md.
-->
""",
    "verify_napomene": """<!--
Napomene za kontrolora činjenica (drugi agent). Ovdje se navodi što dodatno
treba prijaviti ili što se izričito NE prijavljuje.
-->
""",
}

_OVERRIDE_HEADERS = {
    "seo_system": """<!--
OVERRIDE ugrađenog SEO prompta. Dok ova datoteka postoji, u cijelosti zamjenjuje
ugrađeni prompt. Za obične dopune koristi seo_napomene.md.

Dostupni placeholderi:
  {TITLE_MAX_PX} {TITLE_CORE_TARGET_PX} {META_MAX_PX} {META_TARGET_CHARS}
  {BRAND_SUFFIX}

Pozor: mijenjanje tvrdih pravila (pikselski limiti, zabranjeni izrazi, redoslijed
naziva) traži i izmjenu validatora u seo_meta_generator.py — inače će model
raditi jedno, a automatska kontrola tražiti drugo.
-->

""",
    "pdp_system": """<!--
OVERRIDE ugrađenog PDP prompta pisca. Dok ova datoteka postoji, u cijelosti
zamjenjuje ugrađeni prompt. Za obične dopune koristi pdp_napomene*.md.

Dostupni placeholderi:
  {kategorija}  - naziv kategorije (npr. kozmetika)
  {tabovi}      - popis obveznih naziva tabova za tu kategoriju
  {brza_traka}  - obvezna linija polja brze trake
  {extra}       - ugrađene posebne upute kategorije
  {PLACEHOLDER_UNKNOWN} {PLACEHOLDER_ORIGIN}

Pozor: nazivi tabova, obvezne rečenice i struktura provjeravaju se
deterministički u pdp_generator.py (validate_pdp) i pdp_templates.py.
-->

""",
    "verify_system": """<!--
OVERRIDE prompta kontrolora činjenica. Format odgovora (JSON s poljima
"prolazi", "nepotkrijepljene_tvrdnje", "napomena") mora ostati nepromijenjen jer
ga kod parsira.
-->

""",
}


def init(dir_path=None) -> Path:
    """Stvori mapu s napomenama i aktualnim ugrađenim promptovima."""
    target = Path(dir_path) if dir_path else _DIR
    target.mkdir(parents=True, exist_ok=True)

    for name, content in _NOTE_TEMPLATES.items():
        path = target / f"{name}.md"
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    # ugrađeni promptovi kao polazište za override (zapisuju se s nastavkom
    # .primjer.md da se ne aktiviraju slučajno)
    set_dir(target)
    _CACHE.clear()
    import pdp_generator as P  # noqa: PLC0415
    import seo_meta_generator as S  # noqa: PLC0415

    samples = {
        "seo_system": S.build_system_prompt(),
        "pdp_system": P.build_gen_system("cosmetics"),
        "verify_system": P.VERIFY_SYSTEM_DEFAULT,
    }
    for name, text in samples.items():
        path = target / f"{name}.primjer.md"
        path.write_text(_OVERRIDE_HEADERS[name] + text + "\n", encoding="utf-8")

    return target


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Stvori/osvježi mapu s promptovima za uređivanje.")
    ap.add_argument("--init", action="store_true", help="stvori mapu i datoteke")
    ap.add_argument("--dir", default="prompts", help="mapa (zadano: prompts)")
    args = ap.parse_args()
    if not args.init:
        ap.error("koristi --init")
    target = init(args.dir)
    print(f"Mapa spremna: {target}/")
    for p in sorted(target.glob("*.md")):
        kind = "override (preimenuj bez .primjer da aktiviraš)" \
            if ".primjer." in p.name else "napomene (uredi i spremi)"
        print(f"  {p.name:36s} {kind}")


if __name__ == "__main__":
    main()
