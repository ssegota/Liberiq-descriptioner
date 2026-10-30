# -*- coding: utf-8 -*-
"""
Regulatorna pravila koja se provjeravaju u kodu, ne u promptu.

  - zdravstvene tvrdnje: samo iz Uredbe (EU) br. 432/2012 (pročišćeni tekst
    koji je klijent priložio, regulativa/tvrdnje_432_2012.json),
  - uvjet „izvor” iz Priloga Uredbi (EZ) br. 1924/2006: najmanje 15 % NRV-a
    po preporučenoj dnevnoj dozi (NRV iz Priloga XIII. Uredbe 1169/2011),
  - najveće dopuštene količine vitamina i minerala u dodacima prehrani
    (Pravilnik NN 160/2013, Prilog I.),
  - izvadci iz Priloga II. (druge tvari, posebna upozorenja) i Priloga III.
    (zabranjene biljne vrste) za sastojke konkretnog proizvoda,
  - obrazac prve rečenice kratkog opisa prema zadnjoj znamenci EAN-a.

Modul ne zove model. regulativa/ se gradi iz klijentovih PDF-ova
(vidi README_KLIJENT_PRAVILA.md, odjeljak Verzija 4).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "regulativa"

PRAG_IZVOR = 15.0        # % NRV-a: „izvor” vitamina/minerala (Prilog 1924/2006)
PRAG_VISOK_UDIO = 30.0   # % NRV-a: „visok udio”


def _norm(s: str) -> str:
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Nutrijenti: NRV (1169/2011, Prilog XIII.) i najveće doze (NN 160/2013, Prilog I.)
# ---------------------------------------------------------------------------
# kljuc: (naziv u dokumentu tvrdnji, jedinica, NRV, najveća dnevna doza u
#         dodatku prehrani, sinonimi u izvorima)

NUTRIJENTI: dict[str, tuple[str, str, float, float | None, tuple[str, ...]]] = {
    "vitamin_a": ("Vitamin A", "µg", 800, 1500, ("vitamin a", "retinol", "retinil")),
    "vitamin_d": ("Vitamin D", "µg", 5, 10, ("vitamin d", "vitamin d3", "kolekalciferol",
                                             "ergokalciferol")),
    "vitamin_e": ("Vitamin E", "mg", 12, 200, ("vitamin e", "tokoferol")),
    "vitamin_k": ("Vitamin K", "µg", 75, 100, ("vitamin k", "vitamin k1", "vitamin k2",
                                               "filokinon", "menakinon")),
    "vitamin_c": ("Vitamin C", "mg", 80, 800, ("vitamin c", "askorbinsk", "askorbat")),
    "tiamin": ("Tiamin", "mg", 1.1, 25, ("tiamin", "vitamin b1")),
    "riboflavin": ("Riboflavin", "mg", 1.4, 25, ("riboflavin", "vitamin b2")),
    "niacin": ("Niacin", "mg", 16, 35, ("niacin", "vitamin b3", "nikotinamid")),
    "vitamin_b6": ("Vitamin B6", "mg", 1.4, 20, ("vitamin b6", "piridoksin")),
    "folat": ("Folat", "µg", 200, 600, ("folat", "folna kiselina", "vitamin b9",
                                        "metilfolat", "metiltetrahidrofolat")),
    "vitamin_b12": ("Vitamin B12", "µg", 2.5, 25, ("vitamin b12", "cijanokobalamin",
                                                   "cijanokobolamin", "metilkobalamin",
                                                   "kobalamin")),
    "biotin": ("Biotin", "µg", 50, 150, ("biotin", "vitamin b7", "vitamin h")),
    "pantotenska": ("Pantotenska kiselina", "mg", 6, 18, ("pantotensk", "vitamin b5",
                                                          "pantotenat")),
    "kalij": ("Kalij", "mg", 2000, 2000, ("kalij",)),
    "klorid": ("Klorid", "mg", 800, 800, ("klorid",)),
    "kalcij": ("Kalcij", "mg", 800, 1500, ("kalcij",)),
    "fosfor": ("Fosfor", "mg", 700, 1400, ("fosfor",)),
    "magnezij": ("Magnezij", "mg", 375, 375, ("magnezij",)),
    "zeljezo": ("Željezo", "mg", 14, 30, ("zeljez",)),
    "cink": ("Cink", "mg", 10, 15, ("cink",)),
    "bakar": ("Bakar", "mg", 1, 3, ("bakar", "bakr")),
    "mangan": ("Mangan", "mg", 2, 4, ("mangan",)),
    "fluorid": ("Fluorid", "mg", 3.5, 10, ("fluor",)),
    "selen": ("Selen", "µg", 55, 100, ("selen",)),
    "krom": ("Krom", "µg", 40, 150, ("krom",)),
    "molibden": ("Molibden", "µg", 50, 100, ("molibden",)),
    "jod": ("Jod", "µg", 150, 225, ("jod",)),
}

# Tvari bez NRV-a čije tvrdnje imaju vlastiti uvjet (količina u tvrdnji).
OSTALE_TVARI: dict[str, tuple[str, ...]] = {
    "EPA i DHA": ("epa", "dha", "omega 3", "eikosapentaen", "dokosaheksaen"),
    "DHA": ("dha", "dokosaheksaen"),
    "Beta-glukani": ("beta glukan", "beta 1 3", "glukan"),
    "Glukomanan": ("glukomanan",),
    "Kreatin": ("kreatin",),
    "Melatonin": ("melatonin",),
    "Laktulosa": ("laktuloz",),
    "Bjelančevine": ("bjelancevin", "protein"),
    "Kolin": ("kolin",),
    "Biljni steroli": ("sterol", "stanol"),
    "Vlakna": ("vlakn", "psyllium", "pektin", "inulin"),
    "Kofein": ("kofein",),
    "Voda": ("voda ",),
}


def _jedinica_u(jed: str) -> str:
    j = (jed or "").strip().lower().replace("mcg", "µg").replace("μg", "µg").replace("ug", "µg")
    return {"µg": "µg", "mg": "mg", "g": "g", "iu": "IU", "i.j.": "IU", "ij": "IU"}.get(j, j)


def u_jedinicu(kolicina: float, jed: str, cilj: str, kljuc: str = "") -> float | None:
    """Pretvori količinu u ciljnu jedinicu (µg/mg/g; IU za vitamine A/D/E)."""
    jed = _jedinica_u(jed)
    if jed == cilj:
        return kolicina
    if jed == "IU":
        if kljuc == "vitamin_d":
            kolicina, jed = kolicina * 0.025, "µg"
        elif kljuc == "vitamin_a":
            kolicina, jed = kolicina * 0.3, "µg"
        elif kljuc == "vitamin_e":
            kolicina, jed = kolicina * 0.67, "mg"
        else:
            return None
    faktor = {"g": 1e6, "mg": 1e3, "µg": 1.0}
    if jed in faktor and cilj in faktor:
        return kolicina * faktor[jed] / faktor[cilj]
    return None


@lru_cache(maxsize=1)
def _sinonimi() -> list[tuple[str, str]]:
    # najdulji prvi, da „vitamin b12” ne bude prepoznat kao „vitamin b1”
    parovi = [(_norm(s), k) for k, v in NUTRIJENTI.items() for s in v[4]]
    return sorted(parovi, key=lambda x: -len(x[0]))


def prepoznaj_nutrijent(naziv: str) -> str | None:
    n = " " + _norm(naziv) + " "
    for s, kljuc in _sinonimi():
        # sinonim koji završava brojem mora biti cijela riječ (b1 ≠ b12)
        kraj = r"\b" if s[-1].isdigit() else ""
        if re.search(rf"(?<![a-z0-9]){re.escape(s)}{kraj}", n):
            return kljuc
    return None


def prepoznaj_ostalu_tvar(naziv: str) -> str | None:
    n = " " + _norm(naziv) + " "
    for tvar, sinonimi in OSTALE_TVARI.items():
        if any((" " + _norm(s)) in n for s in sinonimi):
            return tvar
    return None


# ---------------------------------------------------------------------------
# Dokument tvrdnji
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def tvrdnje() -> list[dict]:
    path = DIR / "tvrdnje_432_2012.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


GLAGOLI_RE = re.compile(
    r"^(.*?)\s+(doprinos[ie]|pridonos[ie]|ima(ju)? ulogu u|povećava(ju)?|"
    r"održava(ju)?|smanjuje|potiče|poboljšava|pomaže)\b", re.IGNORECASE)


def tvrdnje_za(naziv_u_dokumentu: str) -> list[dict]:
    """Tvrdnje čiji subjekt je točno ta tvar (npr. „Vitamin C”)."""
    cilj = _norm(naziv_u_dokumentu)
    out = []
    for t in tvrdnje():
        m = GLAGOLI_RE.match(t["tvrdnja"])
        subjekt = _norm(m.group(1)) if m else ""
        if subjekt == cilj or subjekt.startswith(cilj + " "):
            out.append(t)
    return out


def predikat(tvrdnja: str) -> str:
    """Tvrdnja bez subjekta („doprinosi normalnom …”)."""
    m = GLAGOLI_RE.match(tvrdnja)
    return tvrdnja[m.end(1):].strip() if m else tvrdnja


@dataclass
class AktivnaTvar:
    tvar: str
    kolicina: float | None
    jedinica: str
    oblik: str = ""
    kljuc: str | None = None          # nutrijent iz NUTRIJENTI
    ostala: str | None = None         # tvar iz OSTALE_TVARI
    nrv_posto: float | None = None
    iznad_maksimuma: bool = False
    maksimum: str = ""


@dataclass
class Procjena:
    tvari: list[AktivnaTvar] = field(default_factory=list)
    dopustene: dict[str, list[dict]] = field(default_factory=dict)   # tvar -> tvrdnje
    nedopustene: dict[str, str] = field(default_factory=dict)        # tvar -> razlog
    upozorenja: list[str] = field(default_factory=list)              # za internu datoteku

    def predikati(self) -> list[str]:
        return [predikat(t["tvrdnja"]) for ts in self.dopustene.values() for t in ts]


def _broj(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"\d+(?:[.,]\d+)?", str(x).replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def procijeni(aktivne: list[dict], dodatak_prehrani: bool = True) -> Procjena:
    """aktivne: [{"tvar","kolicina","jedinica","oblik"}] po DNEVNOJ dozi."""
    p = Procjena()
    for a in aktivne or []:
        naziv = str(a.get("tvar") or "").strip()
        if not naziv:
            continue
        t = AktivnaTvar(tvar=naziv, kolicina=_broj(a.get("kolicina")),
                        jedinica=str(a.get("jedinica") or ""),
                        oblik=str(a.get("oblik") or ""))
        t.kljuc = prepoznaj_nutrijent(naziv)
        if not t.kljuc:
            t.ostala = prepoznaj_ostalu_tvar(naziv + " " + t.oblik)
        p.tvari.append(t)

        if t.kljuc:
            doc_naziv, jed, nrv, maks, _ = NUTRIJENTI[t.kljuc]
            kol = (u_jedinicu(t.kolicina, t.jedinica, jed, t.kljuc)
                   if t.kolicina is not None else None)
            if kol is not None:
                t.nrv_posto = round(kol / nrv * 100)
                if dodatak_prehrani and maks is not None and kol > maks + 1e-9:
                    t.iznad_maksimuma = True
                    t.maksimum = f"{maks:g} {jed}"
                    p.upozorenja.append(
                        f"{naziv}: {t.kolicina:g} {t.jedinica} po dnevnoj dozi veće je "
                        f"od najveće dopuštene količine {maks:g} {jed} (NN 160/2013, "
                        "Prilog I.) — u Tabu 4 označeno za provjeru")
            ts = tvrdnje_za(doc_naziv)
            if kol is None:
                p.nedopustene[naziv] = ("količina po dnevnoj dozi nije poznata, "
                                        "uvjet tvrdnje nije moguće provjeriti")
            elif t.nrv_posto < PRAG_IZVOR:
                p.nedopustene[naziv] = (f"{t.nrv_posto} % NRV-a po dnevnoj dozi, "
                                        f"manje od {PRAG_IZVOR:g} % (nije „izvor”)")
            elif ts:
                p.dopustene[naziv] = ts
        elif t.ostala:
            ts = tvrdnje_za(t.ostala) or [x for x in tvrdnje()
                                          if _norm(t.ostala) in _norm(x["tvrdnja"])[:60]]
            if ts:
                # uvjet je količina iz tvrdnje: provjerava je model i stručna
                # provjera; kod ne može pouzdano parsirati sve oblike uvjeta
                p.dopustene[naziv] = ts
        else:
            p.nedopustene[naziv] = "tvar nema odobrenih tvrdnji u dokumentu tvrdnji"
    return p


def blok_za_prompt(p: Procjena, tvrdnje_dopustene: bool) -> str:
    """Tekst koji ide modelu: % PU, dopuštene tvrdnje s uvjetima, zabrane."""
    if not p.tvari:
        return ("Aktivne tvari s količinama po dnevnoj dozi nisu izvučene iz izvora. "
                "Tablicu aktivnih tvari popuni samo potvrđenim podacima; "
                "zdravstvene tvrdnje NE koristi.")
    redovi = ["IZRAČUN (kod; ne upisuje se u dokument osim % PU u tablici Taba 4):"]
    for t in p.tvari:
        kol = f"{t.kolicina:g} {t.jedinica}" if t.kolicina is not None else "?"
        nrv = f"{t.nrv_posto} % PU" if t.nrv_posto is not None else "bez PU"
        maks = (f"  → IZNAD NAJVEĆE DOPUŠTENE KOLIČINE ({t.maksimum}, NN 160/2013 "
                "Prilog I.): količinu u Tabu 4 označi [PROVJERITI: …]"
                if t.iznad_maksimuma else "")
        redovi.append(f"- {t.tvar}: {kol} po dnevnoj dozi, {nrv}{maks}")
    if not tvrdnje_dopustene:
        redovi.append("\nZa ovaj proizvod zdravstvene i prehrambene tvrdnje NISU "
                      "dopuštene nigdje u dokumentu.")
        return "\n".join(redovi)
    redovi.append("\nODOBRENE TVRDNJE ČIJI JE UVJET „IZVOR” ISPUNJEN (jedini dopušteni "
                  "tekst tvrdnji; biraj samo one relevantne za namjenu proizvoda, "
                  "prenesi doslovno):")
    if not p.dopustene:
        redovi.append("(nema — blok tvrdnji izostavi)")
    for tvar, ts in p.dopustene.items():
        redovi.append(f"* {tvar}:")
        for t in ts:
            uvjet = t.get("uvjet", "")
            posebno = ("" if "Prilog" in uvjet and "IZVOR" in uvjet.upper()
                       else f"  [UVJET: {uvjet}]")
            dodatno = f"  [OGRANIČENJE/UPOZORENJE: {t['ogranicenja']}]" \
                if t.get("ogranicenja") else ""
            redovi.append(f"  - {t['tvrdnja']}{posebno}{dodatno}")
    if p.nedopustene:
        redovi.append("\nZA OVE TVARI TVRDNJE SE NE KORISTE (smiju se navesti samo kao "
                      "činjenica s količinom):")
        for tvar, razlog in p.nedopustene.items():
            redovi.append(f"- {tvar}: {razlog}")
    return "\n".join(redovi)


# ---------------------------------------------------------------------------
# Provjera bloka tvrdnji u gotovom dokumentu
# ---------------------------------------------------------------------------

VEZNICI = set("sadrzi sadrze koji koja koje doprinosi doprinose pridonosi pridonose "
              "ima imaju ulogu u i te kao sto a ili na za s sa od se".split())


def neodobrene_tvrdnje(stavke: list[str], p: Procjena) -> list[str]:
    """Za svaku stavku „Sadrži X koji …” vrati dio teksta koji nije pokriven
    odobrenim tvrdnjama (uz rečenicu o unosu iz uvjeta)."""
    pokriveno = sorted({_norm(x) for x in p.predikati()}, key=len, reverse=True)
    uvjeti = [_norm(s) for ts in p.dopustene.values() for t in ts
              for s in re.split(r"(?<=\.)\s+", t.get("uvjet", ""))
              if "koristan učinak" in s.lower()]
    tvari_tokeni = set()
    for t in p.tvari:
        tvari_tokeni |= set(_norm(t.tvar).split())
        if t.kljuc:
            tvari_tokeni |= set(_norm(NUTRIJENTI[t.kljuc][0]).split())
            for s in NUTRIJENTI[t.kljuc][4]:
                tvari_tokeni |= set(_norm(s).split())
    greske = []
    for stavka in stavke:
        ostatak = " " + _norm(stavka) + " "
        for u in uvjeti:
            ostatak = ostatak.replace(" " + u + " ", " ")
        for frag in pokriveno:
            ostatak = ostatak.replace(" " + frag + " ", " ")
            # skraćeni oblik iza zajedničkog glagola („… doprinosi A, B te C”)
            bez_glagola = re.sub(r"^(doprinosi|doprinose|pridonosi|ima ulogu u|"
                                 r"povecava|odrzava) ", "", frag)
            ostatak = ostatak.replace(" " + bez_glagola + " ", " ")
        visak = [w for w in ostatak.split()
                 if w not in VEZNICI and w not in tvari_tokeni and not w.isdigit()]
        if len(visak) >= 2:
            greske.append(f"„{stavka.strip()[:120]}” — tekst koji nije u odobrenim "
                          f"tvrdnjama: {' '.join(visak[:12])}")
    return greske


# ---------------------------------------------------------------------------
# Pravilnik NN 160/2013: Prilog II. i III.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _prilog(br: str) -> list[str]:
    path = DIR / f"nn160_prilog_{br}.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def izvadak_priloga_ii(nazivi: list[str], okolina: int = 4) -> str:
    """Retci Priloga II. u kojima se spominje sastojak proizvoda."""
    linije = _prilog("II")
    norm = [_norm(l) for l in linije]
    pogodci: set[int] = set()
    for naziv in nazivi:
        for rijec in [w for w in _norm(naziv).split() if len(w) >= 5][:3]:
            for i, l in enumerate(norm):
                if re.search(rf"\b{re.escape(rijec)}", l):
                    pogodci.update(range(max(0, i - 1), min(len(linije), i + okolina)))
    if not pogodci:
        return ""
    return "\n".join(re.sub(r"\s{3,}", "  |  ", linije[i].strip())
                     for i in sorted(pogodci) if linije[i].strip())[:4000]


def zabranjene_biljke(tekst: str) -> list[str]:
    """Latinski nazivi iz Priloga III. koji se pojavljuju u tekstu."""
    t = _norm(tekst)
    nadjeno = []
    for l in _prilog("III"):
        m = re.match(r"\s*([A-Z][a-z]+ [a-z]{3,}(?: [a-z]+\.?)?)", l)
        if not m:
            continue
        lat = _norm(m.group(1))
        if len(lat.split()) >= 2 and lat in t:
            nadjeno.append(m.group(1).strip())
    return sorted(set(nadjeno))


# ---------------------------------------------------------------------------
# Obrazac prve rečenice kratkog opisa (opća pravila, „Kako opis ne postaje šablona”)
# ---------------------------------------------------------------------------

OBRASCI = [
    ("01", "ključnim podatkom s brojem: sastojak i količina, specifikacija, "
           "koncentracija, volumen"),
    ("23", "oblikom, teksturom ili načinom uporabe"),
    ("45", "kutom proizvoda"),
    ("67", "time za koga je proizvod, točno prema deklaraciji ili uputi"),
    ("89", "nazivom proizvoda („[Naziv] je …”), a ostatak rečenice sadrži kut "
           "proizvoda"),
]


def obrazac_prve_recenice(ean: str, pocetna_formula: bool = False) -> tuple[str, str]:
    """(oznaka, opis). Bez EAN-a: kut proizvoda. Početna formula preskače
    obrasce 0/1 i 4/5 („uzima se sljedeći”)."""
    znam = re.sub(r"\D", "", ean or "")
    if not znam:
        idx = 2
        if pocetna_formula:
            idx = 3
        return ("bez EAN-a", OBRASCI[idx][1])
    idx = next(i for i, (z, _) in enumerate(OBRASCI) if znam[-1] in z)
    if pocetna_formula and idx in (0, 2):
        idx += 1
    return (f"EAN završava s {znam[-1]}", OBRASCI[idx][1])


def obrazac_je_naziv(opis: str) -> bool:
    return opis.startswith("nazivom proizvoda")
