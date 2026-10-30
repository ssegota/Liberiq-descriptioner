# -*- coding: utf-8 -*-
"""
PDP templateovi eLjekarne24, verzija 11 (klijentovi dokumenti iz listopada 2026.).

Tekst pravila NIJE prepisan u kod: klijentovi dokumenti su u mapi predlosci/
(opća pravila, 11 templateova A–K, tri checkliste, odobreni primjeri) i
ulaze u prompt doslovno. Ovaj modul drži samo ono što kod mora znati da bi
dokument mogao provjeriti: nazive i redoslijed tabova, retke tablice
podataka, koji template ima brzu traku, FAQ i tvrdnje, te koji se template
smije koristiti u kojoj kategoriji.

Nova verzija templatea = nove datoteke u predlosci/ (+ eventualno izmjena
TEMPLATE_META ako se promijene nazivi tabova ili redci tablice).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PREDLOSCI = Path(__file__).resolve().parent / "predlosci"

# ---------------------------------------------------------------------------
# Kategorije webshopa -> dokument kategorije (predlosci/kategorije/NN.md)
# ---------------------------------------------------------------------------

KATEGORIJE = {
    "01": "Kozmetika",
    "02": "Vitamini i dodaci prehrani",
    "03": "Bebe, djeca i mame",
    "04": "Zdravlje",
    "05": "Lifestyle",
    "06": "Parfemi i parfemski setovi",
    "07": "Beauty uređaji",
    "08": "Medicinski uređaji",
    "09": "Rehabilitacijski program",
    "10": "Dijagnostički testovi i zaštita",
}

# Sekcija iz ulazne tablice -> kategorija. Nepoznata sekcija ("Cijeli
# webshop") smije koristiti bilo koji template; bira ga klasifikator.
SEKCIJA_U_KATEGORIJU = {
    "kozmetika": "01",
    "vitamini, minerali i kolageni": "02",
    "vitamini i dodaci prehrani": "02",
    "beta glukani": "02",
    "mliječne formule": "03",
    "mlijecne formule": "03",
    "bebe, djeca i mame": "03",
    "zdravlje": "04",
    "lifestyle": "05",
    "parfemi i parfemski setovi": "06",
    "parfemi": "06",
    "beauty uređaji": "07",
    "beauty uredaji": "07",
    "medicinski uređaji": "08",
    "medicinski uredaji": "08",
    "rehabilitacijski program": "09",
    "dijagnostički testovi i zaštita": "10",
    "dijagnosticki testovi i zastita": "10",
}

# ---------------------------------------------------------------------------
# Metapodaci templateova (ono što validator provjerava)
# ---------------------------------------------------------------------------
# tabs: (broj, naziv, neobvezan). Neobvezan tab smije izostati, ali ostali
#       zadržavaju broj iz templatea.
# data_tab / data_rows: tab s tablicom „Podatak | Vrijednost” i njezini redci.
# quickbar: brza traka na vrhu Taba 1.  faq: FAQ dopušten.
# claims: blok odobrenih zdravstvenih tvrdnji (dokument tvrdnji 432/2012).

TEMPLATE_META: dict[str, dict] = {
    "A": {
        "naziv": "Dodaci prehrani",
        "tabs": [(1, "Opis i prednosti", False),
                 (2, "Doza i kome je namijenjen", False),
                 (3, "Kako se uzima?", False),
                 (4, "Sastojci i sastav", False),
                 (5, "Upozorenja i podaci", False)],
        "data_tab": 5,
        "data_rows": ["EAN", "Zemlja podrijetla",
                      "Proizvođač / subjekt u poslovanju s hranom", "Brend"],
        "quickbar": True, "faq": True, "faq_max": 4, "claims": True,
        "kratki_opis": (2, 3),
        "obvezne_recenice": [
            "Dodatak prehrani nije nadomjestak ili zamjena uravnoteženoj "
            "prehrani. Preporučene dnevne doze ne smiju se prekoračiti. "
            "Čuvati izvan dohvata djece.",
            "Važno je pridržavati se uravnotežene i raznovrsne prehrane te "
            "zdravog načina života.",
        ],
        "checkliste": ["dodaci_prehrani"],
        "primjer": "A_ferozomal.md",
    },
    "B": {
        "naziv": "Kozmetika i dermokozmetika",
        "tabs": [(1, "Opis i prednosti", False),
                 (2, "Je li za moju kožu?", True),
                 (3, "Kako se koristi", False),
                 (4, "Sastojci", False),
                 (5, "Podaci i upozorenja", False)],
        "data_tab": 5,
        "data_rows": ["Pakiranje", "Brend", "Odgovorna osoba",
                      "Zemlja podrijetla", "EAN"],
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "C": {
        "naziv": "Hrana za dojenčad i dječja hrana",
        "tabs": [(1, "Opis i ključne informacije", False),
                 (2, "Priprema i hranjenje", False),
                 (3, "Sastav, alergeni i nutritivne vrijednosti", False),
                 (4, "Čuvanje i sigurnost", False),
                 (5, "Pakiranje i proizvođač", False)],
        "data_tab": 5,
        "data_rows": ["Pakiranje", "Brend",
                      "Proizvođač / subjekt u poslovanju s hranom",
                      "Zemlja podrijetla", "EAN"],
        "quickbar": True, "faq": True, "faq_max": 3, "claims": True,
        "kratki_opis": (1, 2),
        "checkliste": ["djecja_hrana"],
        "primjer": "C_nan_supremepro_1.md",
    },
    "D": {
        "naziv": "Medicinski uređaji",
        "tabs": [(1, "Opis i prednosti", False),
                 (2, "Upute za korištenje", False),
                 (3, "Funkcije i specifikacije", False),
                 (4, "U pakiranju, održavanje i jamstvo", False),
                 (5, "Validacija, dokumentacija i podaci", False)],
        "data_tab": 5,
        "data_rows": ["Pakiranje", "Brend", "Model / referentna oznaka",
                      "Proizvođač / ovlašteni predstavnik",
                      "Zemlja podrijetla", "EAN"],
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "E": {
        "naziv": "Beauty uređaji",
        "tabs": [(1, "Opis i prednosti", False),
                 (2, "Za koga je i usporedba modela", False),
                 (3, "Kako se koristi", False),
                 (4, "Specifikacije, u pakiranju i održavanje", False),
                 (5, "Sigurnost i podaci", False)],
        "data_tab": 5, "data_rows": None,
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "F": {
        "naziv": "Ortoze, steznici, kompresivne čarape i kućna njega",
        "tabs": [(1, "Opis i namjena", False),
                 (2, "Odabir veličine", False),
                 (3, "Kako se nosi", False),
                 (4, "Materijal i održavanje", False),
                 (5, "Upozorenja i podaci", False)],
        "data_tab": 5, "data_rows": None,
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "G": {
        "naziv": "Pelene i ulošci za inkontinenciju",
        "tabs": [(1, "Opis i prednosti", False),
                 (2, "Odabir razine i veličine", False),
                 (3, "Kako se koristi", False),
                 (4, "Podaci i upozorenja", False)],
        "data_tab": 4, "data_rows": None,
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "H": {
        "naziv": "Dijagnostički testovi i zaštita",
        "tabs": None,  # ovisi o varijanti (H1/H2), vidi VARIJANTE
        "data_tab": None, "data_rows": None,
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "I": {
        "naziv": "Parfemi i parfemski setovi",
        "tabs": [(1, "Opis mirisa", False),
                 (2, "Mirisne note", False),
                 (3, "Kako nanositi", True),
                 (4, "Sastojci, upozorenja i podaci", False)],
        "data_tab": 4, "data_rows": None,
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "J": {
        "naziv": "Lifestyle proizvodi",
        "tabs": [(1, "Opis i prednosti", False),
                 (2, "Materijal, dimenzije i održavanje", False),
                 (3, "Kako se koristi", True),
                 (4, "Upozorenja i podaci", False)],
        "data_tab": 4, "data_rows": None,
        "quickbar": True, "faq": True, "faq_max": 4, "claims": False,
        "kratki_opis": (1, 2),
    },
    "K": {
        "naziv": "Bezreceptni lijekovi i homeopatski proizvodi",
        "tabs": None,  # K1 / K2
        "data_tab": 4, "data_rows": None,
        "quickbar": True, "faq": False, "faq_max": 0, "claims": False,
        "kratki_opis": (1, 3),
        "obvezne_recenice": [
            "Prije upotrebe pažljivo pročitajte uputu o lijeku, a o rizicima "
            "i nuspojavama upitajte svog liječnika ili ljekarnika.",
        ],
    },
}

VARIJANTE = {
    "H1": [(1, "Opis", False), (2, "Kada testirati", False),
           (3, "Kako se koristi", False), (4, "Kako pročitati rezultat", False),
           (5, "Upozorenja i podaci", False)],
    "H2": [(1, "Opis i namjena", False), (2, "Veličina i materijal", False),
           (3, "Kako se koristi", False), (4, "Upozorenja i podaci", False)],
    "K1": [(1, "Za što se koristi", False), (2, "Doziranje i primjena", False),
           (3, "Upozorenja, kontraindikacije i nuspojave", False),
           (4, "Sastav i podaci", False)],
    "K2": [(1, "Opis", False), (2, "Doziranje i primjena", False),
           (3, "Upozorenja", False), (4, "Sastav i podaci", False)],
    # kućna njega bolesnika: Tab 2 postaje „Dimenzije i nosivost”
    "F-kucna-njega": [(1, "Opis i namjena", False),
                      (2, "Dimenzije i nosivost", False),
                      (3, "Kako se nosi", False),
                      (4, "Materijal i održavanje", False),
                      (5, "Upozorenja i podaci", False)],
}

# Podvrste koje mijenjaju pravila (određuje klasifikator prema deklaraciji).
PODVRSTE = {
    "A": ["dodatak prehrani", "biljni dodatak prehrani",
          "biljni čaj (nije dodatak prehrani)"],
    "C": ["početna formula", "prijelazna formula", "dječja hrana",
          "prerađena hrana na bazi žitarica", "druga hrana za djecu"],
    "D": ["uređaj s elektronikom", "jednostavni medicinski proizvod"],
    "F": ["ortoza / steznik / čarapa", "kućna njega bolesnika"],
    "H": ["H1", "H2"],
    "K": ["K1", "K2"],
}

POCETNA_FORMULA = "početna formula"


def tabs_for(letter: str, podvrsta: str = "") -> list[tuple[int, str, bool]]:
    meta = TEMPLATE_META[letter]
    if letter in ("H", "K"):
        return VARIJANTE.get(podvrsta) or VARIJANTE[f"{letter}1"]
    if letter == "F" and podvrsta == "kućna njega bolesnika":
        return VARIJANTE["F-kucna-njega"]
    return meta["tabs"]


def faq_dopusten(letter: str, podvrsta: str = "") -> bool:
    if letter == "C" and podvrsta == POCETNA_FORMULA:
        return False
    return TEMPLATE_META[letter]["faq"]


def tvrdnje_dopustene(letter: str, podvrsta: str = "") -> bool:
    if letter == "C":
        return podvrsta != POCETNA_FORMULA
    return TEMPLATE_META[letter]["claims"]


def label(letter: str) -> str:
    return f"{letter}: {TEMPLATE_META[letter]['naziv']}"


# Zadržano zbog postojećih stupaca u indeksu.
CATEGORY_LABELS = {k: label(k) for k in TEMPLATE_META}

# ---------------------------------------------------------------------------
# Klijentovi dokumenti
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _read(rel: str) -> str:
    path = PREDLOSCI / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def opca_pravila() -> str:
    return _read("opca_pravila.md")


def template_tekst(letter: str) -> str:
    return _read(f"templateovi/{letter}.md")


def checkliste_za(letter: str, podvrsta: str = "") -> list[tuple[str, str]]:
    """[(naziv, tekst)] checkliste koje vrijede uz template."""
    if letter == "A":
        if podvrsta == "biljni dodatak prehrani":
            return [("Checklista: biljni dodaci prehrani",
                     _read("checkliste/biljni_dodaci_prehrani.md"))]
        return [("Checklista: dodaci prehrani",
                 _read("checkliste/dodaci_prehrani.md"))]
    if letter == "C":
        return [("Checklista: dječja hrana i hrana za dojenčad",
                 _read("checkliste/djecja_hrana.md"))]
    return []


def primjer_za(letter: str) -> str:
    """Primjer gotovog dokumenta u izlaznom formatu (samo A i C su odobreni)."""
    name = TEMPLATE_META[letter].get("primjer")
    return _read(f"primjeri/format/{name}") if name else ""


def odabir_tekst(kategorija: str | None) -> str:
    if kategorija:
        return _read(f"kategorije/{kategorija}.md")
    return "\n\n".join(_read(f"kategorije/{k}.md") for k in KATEGORIJE)


@lru_cache(maxsize=None)
def dopusteni_templateovi(kategorija: str | None) -> tuple[str, ...]:
    """Templateovi navedeni u dokumentu kategorije; sve ako je nepoznata."""
    if not kategorija:
        return tuple(TEMPLATE_META)
    found = re.findall(r"Template ([A-K]):", _read(f"kategorije/{kategorija}.md"))
    return tuple(dict.fromkeys(found)) or tuple(TEMPLATE_META)


def kategorija_za(sekcija: str) -> str | None:
    return SEKCIJA_U_KATEGORIJU.get((sekcija or "").strip().lower())


# ---------------------------------------------------------------------------
# Heuristični odabir (bez modela) — za dry-run i kao zadana vrijednost
# ---------------------------------------------------------------------------

_HEUR = [
    ("K", ("homeopat", "lijek bez recepta", "vaporub")),
    ("C", ("nan ", "formula", "mliječna hrana", "mlijecna hrana", "kašica",
           "kasica", "aptamil", "bebivita", "hipp")),
    ("D", ("tlakomjer", "inhalator", "vaga", "toplomjer", "aspirator",
           "senzor", "adapter", "tens", "izdajalic", "fiziološk", "flaster")),
    ("H", ("test za", "test na", "maska", "rukavic", "dezinf")),
    ("I", ("parfem", "toaletna voda", "edp", "edt")),
    ("G", ("pelen", "uložak", "ulozak", "inkontinen")),
    ("F", ("ortoz", "steznik", "kompresivn", "hodalic")),
    ("A", ("vitamin", "mineral", "kolagen", "glukan", "kapsul", "tablet",
           "vrećic", "vrecic", "sirup", "žele bombon", "zele bombon",
           "dodatak prehrani", "magnezij", "željezo", "zeljezo", "selen",
           "omega", "probiotik", "kapi")),
    ("B", ("krema", "serum", "šampon", "sampon", "losion", "gel", "sprej",
           "balzam", "mlijeko", "spf", "deo", "termalna", "pjena", "sindet")),
]


def category_for(sekcija: str, naziv: str = "") -> str:
    """Najvjerojatniji template prema sekciji i nazivu (bez modela)."""
    allowed = dopusteni_templateovi(kategorija_za(sekcija))
    if len(allowed) == 1:
        return allowed[0]
    text = f" {(naziv or '').lower()} "
    for letter, words in _HEUR:
        if letter in allowed and any(w in text for w in words):
            return letter
    return allowed[0]


def podvrsta_heuristika(letter: str, naziv: str = "") -> str:
    n = (naziv or "").lower()
    if letter == "C":
        if re.search(r"\bpre\b|\b1\b", n):
            return POCETNA_FORMULA
        if re.search(r"\b2\b", n):
            return "prijelazna formula"
        if re.search(r"\b[34]\b", n):
            return "druga hrana za djecu"
        return POCETNA_FORMULA if "formula" in n or "nan" in n else "dječja hrana"
    if letter == "D":
        return ("uređaj s elektronikom"
                if re.search(r"tlakomjer|inhalator|vaga|toplomjer|senzor|tens", n)
                else "jednostavni medicinski proizvod")
    return (PODVRSTE.get(letter) or [""])[0]


# ---------------------------------------------------------------------------
# Izlazni format (kostur) — isti za sve templateove, tabovi iz metapodataka
# ---------------------------------------------------------------------------

def build_skeleton(letter: str, podvrsta: str = "") -> str:
    meta = TEMPLATE_META[letter]
    lines = [
        "# [Naziv proizvoda, isti kao H1]",
        "",
        "## SEO elementi",
        "",
        "| Element | Tekst |",
        "| --- | --- |",
        "| Meta title | [naziv, vrsta ili oblik, pakiranje] │ eLjekarna24 |",
        "| Meta description | [do ~155 znakova; kreće od kuta proizvoda] |",
        "| H1 | [jednak nazivu proizvoda] |",
        "| Alt tekst | [naziv i pakiranje] |",
        "",
        "## Prvi ekran",
        "",
        "**Naziv proizvoda:** [naziv]",
        "",
        "**Kratki opis:** [%d–%d rečenice]" % meta["kratki_opis"],
        "",
    ]
    for n, title, optional in tabs_for(letter, podvrsta):
        lines.append(f"## Tab {n}: {title}")
        lines.append("")
        if n == 1:
            if letter == "C":
                lines += ["**VAŽNA NAPOMENA:** [napomena o dojenju]", ""]
            if meta["quickbar"]:
                lines += ["**Brza traka:** [oznaka] · [oznaka] · [oznaka]", ""]
            lines += ["### [podnaslov s činjenicom o ovom proizvodu]", "",
                      "[odlomak]", ""]
            if tvrdnje_dopustene(letter, podvrsta):
                lines += ["- Sadrži [sastojak] koji doprinosi [odobrena tvrdnja].",
                          ""]
        else:
            lines += ["[sadržaj prema templateu" +
                      (" — tab je neobvezan, izostavi ga ako nema što jasno reći"
                       if optional else "") + "]", ""]
        if n == meta.get("data_tab") and meta.get("data_rows"):
            lines += ["| Podatak | Vrijednost |", "| --- | --- |"]
            lines += [f"| {row} | [vrijednost] |" for row in meta["data_rows"]]
            lines.append("")
    if faq_dopusten(letter, podvrsta):
        lines += ["## Česta pitanja", "",
                  "**[Pitanje?]**", "", "[Odgovor, najviše 2–3 rečenice.]", "",
                  "(FAQ je neobvezan: izostavi cijeli odjeljak ako nema dobrog pitanja.)"]
    return "\n".join(lines).rstrip() + "\n"
