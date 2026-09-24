#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zajednička pravila za title, meta opis i PDP (eljekarna24).

Provedba dokumenata "Upute za generator" i "Audit title, meta opis i PDP":
  Z1  hijerarhija izvora kroz allowlist domena (u kodu, ne u promptu)
  Z2  izlaz spreman za copy/paste, bez internih napomena
  Z3  bez uspoređivanja šifri drugih trgovina
  Z4  bez crtica u tekstu za kupca

Modul ne zove model. Sve su provjere determinističke.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Z1. Allowlist domena
# ---------------------------------------------------------------------------

PRIMARNA_DOMENA = "eljekarna24.hr"
SEKUNDARNA_DOMENA = "webljekarna.vasezdravlje.com"

# Službene hrvatske stranice brendova. Popis održava tim, ne model.
# Ključ je normalizirani naziv brenda iz ulazne tablice.
BREND_DOMENE: dict[str, tuple[str, ...]] = {
    "eucerin": ("eucerin.hr",),
    "avene": ("eau-thermale-avene.com.hr", "avene.hr"),
    "larocheposay": ("laroche-posay.com.hr",),
    "vichy": ("vichy.hr",),
    "solgar": ("solgar.hr",),
    "microlife": ("microlife.hr",),
    "salvit": ("salvit.hr",),
    "apwell": ("apwell.hr",),
    "nan": ("nan.hr", "nestlebaby.hr"),
    "nestle": ("nestlebaby.hr",),
    "sagas": ("sagas.hr",),
    "masterofpharmacy": ("masterofpharmacy.hr",),
    "transferpoint": ("transferpoint.hr",),
    "bioderma": ("bioderma.hr",),
    "cetaphil": ("cetaphil.hr",),
    "uriage": ("uriage.hr",),
}

# Domene koje su izričito zabranjene (druge ljekarne, tražilice, marketplace).
# Popis je dokumentacijski; blokira ih ionako allowlist.
ZABRANJENE_DOMENE = (
    "ljekarne.hr",
    "ljekarne-plantak.hr", "onlineljekarna.hr", "pharmacy.hr", "ljekarnaonline.hr",
    "bing.com", "google.com", "amazon.com", "amazon.de", "ebay.com", "emag.hr",
)

# Nastavci koji označavaju stranicu brenda za drugo tržište.
STRANA_TRZISTA = (".rs", ".us", ".co.uk", ".in", ".sa", ".au", ".de", ".fr",
                  ".it", ".si", ".ba", ".com.tr", ".ru", ".pl")


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _norm_brend(brend: str) -> str:
    return re.sub(r"[^a-z0-9]", "",
                  unicodedata.normalize("NFD", (brend or "").lower())
                  .encode("ascii", "ignore").decode())


def dopustene_domene(brend: str) -> tuple[str, ...]:
    """Hijerarhija izvora (klijent, verzija 3):
       1. eljekarna24.hr
       2. webljekarna.vasezdravlje.com
       3. službena hrvatska stranica brenda
    Sve ostalo se odbacuje."""
    return ((PRIMARNA_DOMENA, SEKUNDARNA_DOMENA)
            + BREND_DOMENE.get(_norm_brend(brend), ()))


def prioritet_izvora(url: str, brend: str = "") -> int:
    """1, 2 ili 3 prema hijerarhiji; 0 ako izvor nije dopušten."""
    host = _host(url)
    if host.endswith(PRIMARNA_DOMENA):
        return 1
    if host.endswith(SEKUNDARNA_DOMENA):
        return 2
    for d in BREND_DOMENE.get(_norm_brend(brend), ()):
        if host == d or host.endswith("." + d):
            return 3
    return 0


def je_primarni(url: str) -> bool:
    return _host(url).endswith(PRIMARNA_DOMENA)


def je_dopusten(url: str, brend: str) -> tuple[bool, str]:
    """Vrati (dopušteno, razlog). Sve izvan allowliste se odbacuje."""
    host = _host(url)
    if not host:
        return False, "neispravan URL"
    for zabranjena in ZABRANJENE_DOMENE:
        if host == zabranjena or host.endswith("." + zabranjena):
            return False, f"zabranjena domena ({host})"
    for dopustena in dopustene_domene(brend):
        if host == dopustena or host.endswith("." + dopustena):
            return True, "dopušteno"
    if any(host.endswith(nastavak) for nastavak in STRANA_TRZISTA):
        return False, f"stranica brenda za drugo tržište ({host})"
    return False, f"izvan allowliste ({host})"


# ---------------------------------------------------------------------------
# Rječnik zapisa brendova i linija
# ---------------------------------------------------------------------------

RJECNIK_ZAPISA: dict[str, str] = {
    "avene": "Avène", "eau thermale avene": "Avène",
    "la roche posay": "La Roche-Posay", "laroche posay": "La Roche-Posay",
    "la roche-posay": "La Roche-Posay",
    "eucerin": "Eucerin", "urearepair": "UreaRepair", "urea repair": "UreaRepair",
    "vichy": "Vichy", "liftactiv": "Liftactiv", "dercos": "Dercos",
    "anthelios": "Anthelios", "effaclar": "Effaclar", "cicaplast": "Cicaplast",
    "hydraphase": "Hydraphase", "uvmune": "UVMUNE",
    "solgar": "Solgar", "microlife": "Microlife", "salvit": "Salvit",
    "apwell": "ApWell", "sagas": "Sagas", "nan": "NAN", "optipro": "Optipro",
    "comfortis": "Comfortis", "supremepro": "Supremepro",
    "master of pharmacy": "Master of Pharmacy",
    "transfer point": "Transfer Point",
}

# Kratice i oznake koje smiju ostati velikim slovima.
DOZVOLJENE_VERZALE = {
    "SPF", "UVA", "UVB", "UVMUNE", "IU", "PC", "AFIB", "AFib", "RC", "DHA",
    "ARA", "EAN", "INCI", "PAO", "MSM", "CoQ10", "B3", "B5", "B6", "B12",
    "D3", "K1", "K2", "C+", "NAN", "ML", "PH", "pH5", "Q10", "OK",
}


def primijeni_rjecnik(tekst: str) -> str:
    """Ujednači zapis brendova i linija (npr. RC-01 -> RC 01, Urea Repair)."""
    out = tekst or ""
    for kriv, ispravan in sorted(RJECNIK_ZAPISA.items(), key=lambda x: -len(x[0])):
        out = re.sub(rf"\b{re.escape(kriv)}\b", ispravan, out, flags=re.IGNORECASE)
    # Sagas linije: RC-01 / RC01 -> RC 01
    out = re.sub(r"\bRC[-\s]?(\d{1,2})\b", r"RC \1", out, flags=re.IGNORECASE)
    return out


# ---------------------------------------------------------------------------
# Promo oznake i multipakiranje
# ---------------------------------------------------------------------------

PROMO_UZORCI = [
    re.compile(r"\b\d+\s*\+\s*\d+\s*(gratis|besplatno)\b", re.IGNORECASE),
    re.compile(r"\bgratis\b", re.IGNORECASE),
    re.compile(r"\bakcij\w*", re.IGNORECASE),
    re.compile(r"\bpoklon\w*", re.IGNORECASE),
    re.compile(r"\bpopust\w*", re.IGNORECASE),
    re.compile(r"\bpromo\b", re.IGNORECASE),
    re.compile(r"\bspecijalna ponuda\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*za\s*\d+\b", re.IGNORECASE),
]

# "3x18 tableta", "3 x 18 tableta", "a18" -> normalizirani zapis
MULTIPAK_RE = re.compile(
    rf"\b(\d+)\s*[x×]\s*(\d+)\s*({JEDINICE})\b" if False else
    r"\b(\d+)\s*[x×]\s*(\d+)\s*([A-Za-zČĆŽŠĐčćžšđ]+)\b")


def ukloni_promo(naziv: str) -> str:
    """Iz naziva makni promotivne oznake; količina ostaje stvarni sadržaj."""
    out = naziv or ""
    for uzorak in PROMO_UZORCI:
        out = uzorak.sub(" ", out)
    out = re.sub(r"\s*[-,]\s*(?=$|[,.])", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" ,-")


def normaliziraj_multipak(tekst: str) -> str:
    """Multipakiranje u dogovorenom formatu: „3 × 18 tableta“."""
    def zamjena(m):
        return f"{m.group(1)} × {m.group(2)} {m.group(3)}"
    return MULTIPAK_RE.sub(zamjena, tekst or "")


# ---------------------------------------------------------------------------
# Z4. Crtice
# ---------------------------------------------------------------------------

EN_DASH, EM_DASH = "\u2013", "\u2014"
RASPON_RE = re.compile(rf"(?<=\d)\s*[{EN_DASH}{EM_DASH}]\s*(?=\d)")


def _ukloni_crtice_redak(redak: str) -> str:
    cuvaj = "\x00"
    out = RASPON_RE.sub(cuvaj, redak)                       # sakrij raspone brojeva
    out = re.sub(rf"\s*[{EN_DASH}{EM_DASH}]\s*", ", ", out)  # crtica -> zarez
    out = out.replace(cuvaj, EN_DASH)                       # vrati raspone
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r",\s*([.!?;:])", r"\1", out)
    out = re.sub(r"(?<=[.!?])\s*,\s+", " ", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out


def ukloni_crtice(tekst: str) -> str:
    """Makni crtice iz teksta za kupca; rasponi brojeva ostaju (22-42 cm).

    Radi po retcima kako bi struktura Markdowna (naslovi, tablice) ostala
    nedirnuta.
    """
    if not tekst:
        return tekst
    obrada = [_ukloni_crtice_redak(r) if not r.strip().startswith("|")
              else _ukloni_crtice_redak(r)
              for r in tekst.splitlines()]
    return "\n".join(obrada)


def nadi_crtice(tekst: str) -> list[str]:
    """Crtice koje nisu dopušteni raspon brojeva."""
    ocisceno = RASPON_RE.sub(" ", tekst or "")
    return [m.group(0) for m in re.finditer(rf"[{EN_DASH}{EM_DASH}]", ocisceno)]


# ---------------------------------------------------------------------------
# Z2. Interne napomene koje ne smiju u tekst za kupca
# ---------------------------------------------------------------------------

INTERNI_UZORCI: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\[S\d+\]"), "oznaka izvora [S…]"),
    (re.compile(r"\bKONFLIKT\w*", re.IGNORECASE), "napomena o konfliktu"),
    (re.compile(r"\bpotvrdit\w+\s+(prema|na pakiranju|s klijentom|u PIM|prije objave)",
                re.IGNORECASE), "interna uputa „potvrditi“"),
    (re.compile(r"\btreba potvrditi\b", re.IGNORECASE), "interna uputa „potvrditi“"),
    (re.compile(r"\bprovjerit\w+\s+(koji|je li|na pakiranju|prije objave)",
                re.IGNORECASE), "interna uputa „provjeriti“"),
    (re.compile(r"Prije lokalne objave", re.IGNORECASE), "interna uputa"),
    (re.compile(r"prema dostupnoj dokumentaciji", re.IGNORECASE), "interna uputa"),
    (re.compile(r"za internu provjeru", re.IGNORECASE), "interna oznaka"),
    (re.compile(r"tip,\s*namjena,\s*ciljana skupina", re.IGNORECASE),
     "uputa iz predloška umjesto popunjenih brzih podataka"),
    (re.compile(r"\bizvor(i|a)?\s*:\s*\[?S\d", re.IGNORECASE), "popis izvora"),
]

# Tekst iz klijentovih predložaka koji SMIJE ostati.
DOZVOLJENI_PREDLOSCI = (
    "Prije uporabe provjeri aktualni sastav na pakiranju.",
    "Prije uporabe provjerite sve alergene na aktualnoj deklaraciji.",
    "Provjerite odgovara li priložena manšeta opsegu nadlaktice korisnika.",
    "Unijeti točno prema aktualnoj deklaraciji ili PIM-u.",
    "Navesti samo ako je potvrđena na deklaraciji ili u dokumentaciji točnog proizvoda.",
    "Obvezna provjera prije objave",
    "[Dopuniti iskustvima iz prakse ljekarnika eLjekarna24 prije objave.]",
    "[Blok se puni automatski iz sustava recenzija.]",
    "Puni INCI sastav s aktualne deklaracije (umetnuti točan popis bez prijevoda i skraćivanja).",
)


def _bez_dozvoljenih(tekst: str) -> str:
    out = tekst or ""
    for dozvoljeno in DOZVOLJENI_PREDLOSCI:
        out = out.replace(dozvoljeno, " ")
    return out


def nadi_interne_napomene(tekst: str) -> list[str]:
    """Interne napomene u tekstu za kupca (bez dopuštenog teksta predložaka)."""
    provjera = _bez_dozvoljenih(tekst)
    nalazi = []
    for uzorak, opis in INTERNI_UZORCI:
        m = uzorak.search(provjera)
        if m:
            nalazi.append(f"„{m.group(0).strip()}“ ({opis})")
    nisko = provjera.lower()
    for domena in ZABRANJENE_DOMENE:
        # traži se PUNA domena (pharmacy.hr), ne dio riječi, da brend
        # „Master of Pharmacy“ ne bi bio prepoznat kao druga ljekarna
        if re.search(rf"\b{re.escape(domena)}\b", nisko):
            nalazi.append(f"spominjanje druge trgovine ili tražilice ({domena})")
            break
    return nalazi


# ---------------------------------------------------------------------------
# Zabranjene riječi (lista iz uputa)
# ---------------------------------------------------------------------------

ZABRANJENE_RIJECI = [
    (r"\boptimal\w*", "optimalan"), (r"\bnajbolj\w*", "najbolji"),
    (r"\bnajosjetljivij\w*", "najosjetljiviji"), (r"\bjedini\w*", "jedini"),
    (r"\bultra\b", "ultra"), (r"\bidealn?\w*", "idealan"),
    (r"\bsavrsen\w*", "savršen"), (r"\bsprjecav\w*", "sprječava"),
    (r"\bsprecav\w*", "sprječava"), (r"\blijeci\b", "liječi"),
    (r"\bakcij\w*", "akcija"), (r"\bcijen\w*", "cijena"),
    (r"\bdostav\w*", "dostava"), (r"\bgratis\b", "gratis"),
    (r"\bkupite\b", "kupite"), (r"\bkupi\b", "kupi"),
    (r"\bnaruc\w*", "naručite"), (r"\bpopust\w*", "popust"),
    (r"\bzalih\w*", "zaliha"), (r"\bvrhunsk\w*", "vrhunski"),
    (r"\bnajucinkovitij\w*", "najučinkovitiji"),
    (r"\bklinicki dokazano\b", "klinički dokazano"),
    (r"\bzlatni standard\b", "zlatni standard"),
]
ZABRANJENE_RE = [(re.compile(p), naziv) for p, naziv in ZABRANJENE_RIJECI]

IZUZECI_RE = [
    re.compile(r"dojenje je najbolji nacin prehrane dojenceta"),
    re.compile(r"\bnajvise\b"), re.compile(r"\bnajmanje\b"),
    re.compile(r"\bnajkasnije\b"), re.compile(r"\bnajranije\b"),
]


def _norm(s: str) -> str:
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def nadi_zabranjene_rijeci(tekst: str) -> list[str]:
    normirano = _norm(tekst)
    for izuzetak in IZUZECI_RE:
        normirano = izuzetak.sub(" ", normirano)
    nalazi = []
    for uzorak, naziv in ZABRANJENE_RE:
        m = uzorak.search(normirano)
        if m:
            nalazi.append(f"„{m.group(0)}“ ({naziv})")
    return nalazi


# ---------------------------------------------------------------------------
# Tvrdnje bez objašnjenja
# ---------------------------------------------------------------------------

TVRDNJE_TESTIRANO = [
    (re.compile(r"\bklinički (dokazano|testiran\w*)", re.IGNORECASE), "klinički testirano"),
    (re.compile(r"\bdermatološki testiran\w*", re.IGNORECASE), "dermatološki testirano"),
    (re.compile(r"\btestiran\w*\s+(pod|na)\b", re.IGNORECASE), "testirano"),
    (re.compile(r"\bpreporučeno od (dermatologa|liječnika)", re.IGNORECASE),
     "preporučeno od stručnjaka"),
]
OBJASNJENJE_RE = re.compile(
    r"(\d+\s*ispitanik|\bmetod\w+|\bnakon \d+\s*(tjedn|dan|mjesec)|"
    r"\binstrumentaln\w+|\bklinička procjena\b|\bpod nadzorom dermatologa na\b)",
    re.IGNORECASE)


def nadi_tvrdnje_bez_objasnjenja(tekst: str) -> list[str]:
    """„Testirano“ i slično bez navođenja što je i kako testirano."""
    nalazi = []
    for uzorak, naziv in TVRDNJE_TESTIRANO:
        for m in uzorak.finditer(tekst or ""):
            okolina = (tekst or "")[max(0, m.start() - 200): m.end() + 260]
            if not OBJASNJENJE_RE.search(okolina):
                nalazi.append(f"„{m.group(0)}“ ({naziv}) bez objašnjenja što je "
                              "i kako testirano")
                break
    return nalazi


# ---------------------------------------------------------------------------
# Skraćivanje titla po cijelim segmentima
# ---------------------------------------------------------------------------

ZAVRSNE_ZABRANJENE = {"za", "i", "s", "sa", "od", "protiv", "uz", "te", "u",
                      "na", "iz", "bez", "&", "-", ","}

JEDINICE = (r"ml|l|g|kg|mg|mcg|µg|IU|cm|mm|%|tableta|tablete|tableti|kapsula|"
            r"kapsule|kapsuli|vrećica|vrećice|komad|komada|bombona|žele bombona|"
            r"šumećih tableta|vrećica")
KOLICINA_RE = re.compile(rf"\b\d+(?:[.,]\d+)?\s*(?:{JEDINICE})\b", re.IGNORECASE)

OPCI_PRIDJEVI = ("intenzivn", "nježn", "njezn", "blag", "napredn", "poseb",
                 "svakodnevn", "učinkovit", "ucinkovit", "bogat", "lagan",
                 "svjež", "svjez", "prirodn", "hranjiv", "umirujuć", "umirujuc",
                 "osvježavajuć", "obnavljajuć", "zaštitn", "zastitn", "njegujuć")

# Tip proizvoda je zaštićen i nikad se ne uklanja (klijent, verzija 3, t. 2).
ZASTICENI_TIPOVI = (
    "krema", "kreme", "serum", "seruma", "sprej", "spreja", "balzam", "balzama",
    "gel", "gela", "losion", "losiona", "mlijeko", "mlijeka", "fluid", "fluida",
    "maska", "maske", "ulje", "ulja", "pjena", "pjene", "šampon", "sampon",
    "regenerator", "sirup", "sirupa", "tablete", "tableta", "tabletе",
    "kapsule", "kapsula", "vrećice", "vrecice", "prašak", "prah", "kapi",
    "tlakomjer", "inhalator", "vaga", "toplomjer", "formula", "formule",
    "napitak", "bombone", "štapić", "stapic", "štapiću", "stapicu",
    "dezodorans", "puder", "ruž", "maskara", "pasta", "otopina", "sol",
    "njega", "njegu", "njege", "kupka", "sapun", "gel-krema", "emulzija",
    "koncentrat", "tonik", "piling", "melem", "mast", "sprej", "roll-on",
    "tinktura", "čaj", "caj", "granule", "pastile", "lizalice", "flaster",
)

# Nastavci pridjeva: title ne smije završiti pridjevom (t. 2).
PRIDJEVSKI_NASTAVCI = ("ni", "na", "no", "ne", "nu", "ki", "ka", "ko", "ski",
                       "ški", "čki", "an", "na", "ivi", "ova", "ovo", "ovi",
                       "asti", "ast", "ljiv", "ljiva", "ljivo")


def sadrzi_tip(tekst: str) -> str:
    """Vrati zaštićeni tip proizvoda pronađen u tekstu, ako postoji."""
    nisko = f" {(tekst or '').lower()} "
    for tip in ZASTICENI_TIPOVI:
        if f" {tip} " in nisko:
            return tip
    return ""


def zavrsava_pridjevom(title: str) -> bool:
    """Zadnja riječ je opći pridjev (npr. „…hidratantna“)."""
    if not title:
        return False
    zadnja = re.sub(r"[^\wČĆŽŠĐčćžšđ]+$", "", title.split()[-1]).lower()
    if not zadnja or zadnja in ZASTICENI_TIPOVI:
        return False
    zadnja_bez = _norm(zadnja)
    if any(zadnja_bez.startswith(_norm(p)) for p in OPCI_PRIDJEVI):
        return True
    if len(zadnja) >= 6 and zadnja.endswith(PRIDJEVSKI_NASTAVCI):
        # brojevi, jedinice i imena nisu pridjevi
        if not re.search(r"\d", zadnja) and zadnja not in ZASTICENI_TIPOVI:
            return True
    return False


PAK_JEDINICE = (r"ml|l|kg|g|tableta|tablete|tableti|kapsula|kapsule|kapsuli|"
                r"vrećica|vrećice|vrecica|vrecice|komad|komada|bombona|"
                r"šumećih tableta|sumecih tableta|kom")
KOLICINA_PAK_RE = re.compile(
    rf"\b(\d+(?:[.,]\d+)?)\s*(?:{PAK_JEDINICE})\b", re.IGNORECASE)


def kolicina_pakiranja(tekst: str) -> str:
    """Količina PAKIRANJA (mg, mcg, µg, IU su jačina i ne broje se)."""
    nalazi = list(KOLICINA_PAK_RE.finditer(tekst or ""))
    return nalazi[-1].group(0).strip() if nalazi else ""


def kolicina_iz(tekst: str) -> str:
    """Zadnja količina s jedinicom u tekstu (npr. „100 tableta“)."""
    nalazi = KOLICINA_RE.findall(tekst or "")
    m = list(KOLICINA_RE.finditer(tekst or ""))
    return m[-1].group(0).strip() if m else ""


def segmenti_titla(naziv: str) -> list[str]:
    """Razdvoji PDP naziv na cjeline: zarez i crtica su granice segmenata."""
    dijelovi = re.split(rf"\s*[,{EN_DASH}{EM_DASH}]\s*|\s+-\s+", naziv or "")
    return [d.strip() for d in dijelovi if d.strip()]


def zavrsava_lose(title: str) -> bool:
    if not title:
        return True
    zadnja = re.sub(r"[^\wČĆŽŠĐčćžšđ&]+$", "", title.split()[-1]).lower()
    if zadnja in ZAVRSNE_ZABRANJENE:
        return True
    if re.fullmatch(r"\d+(?:[.,]\d+)?", zadnja):      # broj bez jedinice
        return True
    return False


def skrati_po_segmentima(naziv: str, stane, obavezno: list[str] | None = None) -> str:
    """Skraćuj uklanjanjem cijelih segmenata dok title ne stane.

    `stane(tekst) -> bool` je mjera iz koda (pikseli).
    Nikad se ne uklanja segment koji sadrži količinu ili obavezni pojam.
    """
    obavezno = [o for o in (obavezno or []) if o]
    segmenti = segmenti_titla(naziv)
    if not segmenti:
        return naziv

    def spoji(dijelovi):
        tekst = " ".join(d.strip() for d in dijelovi if d.strip())
        return re.sub(r"\s{2,}", " ", tekst).strip()

    def nuzan(seg: str) -> bool:
        if KOLICINA_RE.search(seg):
            return True
        if sadrzi_tip(seg):                     # tip proizvoda je zaštićen
            return True
        return any(_norm(o) and _norm(o) in _norm(seg) for o in obavezno)

    trenutni = list(segmenti)
    if stane(spoji(trenutni)):
        return spoji(trenutni)

    # 1) ukloni segmente koji nisu nužni, s kraja prema početku
    for i in range(len(trenutni) - 1, 0, -1):
        if nuzan(trenutni[i]):
            continue
        kandidat = trenutni[:i] + trenutni[i + 1:]
        if spoji(kandidat):
            trenutni = kandidat
            if stane(spoji(trenutni)):
                return spoji(trenutni)

    # 2) ukloni opće pridjeve unutar prvog segmenta
    rijeci = spoji(trenutni).split()
    filtrirane = [r for r in rijeci
                  if not any(_norm(r).startswith(p) for p in OPCI_PRIDJEVI)]
    if filtrirane and not stane(spoji(trenutni)) and len(filtrirane) < len(rijeci):
        kandidat = " ".join(filtrirane)
        if stane(kandidat):
            return kandidat
        rijeci = filtrirane

    # 3) zadnji izlaz: količina (i sve iza nje) je rep koji ostaje, a režu se
    #    riječi neposredno ispred repa, s kraja prema početku
    kolicina = kolicina_iz(" ".join(rijeci))
    rep: list[str] = []
    if kolicina:
        nisko = [r.lower() for r in rijeci]
        dijelovi = kolicina.lower().split()
        for i in range(len(rijeci) - len(dijelovi), -1, -1):
            if nisko[i:i + len(dijelovi)] == dijelovi:
                rep = rijeci[i:]
                rijeci = rijeci[:i]
                break
    # Reži po CIJELIM prijedložnim frazama, nikad usred fraze:
    # „Krema SPF50 za suhu i osjetljivu kožu lica 50 ml“
    #   -> „Krema SPF50 50 ml“, a ne „Krema SPF50 za suhu 50 ml“.
    PRIJEDLOZI = {"za", "s", "sa", "od", "protiv", "u", "na", "iz", "bez",
                  "uz", "prema", "kod", "po"}
    while not stane(" ".join(rijeci + rep)):
        granice = [i for i, w in enumerate(rijeci)
                   if w.lower().strip(",.") in PRIJEDLOZI and i > 0]
        if not granice:
            break
        rijeci = rijeci[:granice[-1]]
    # tek ako ni to nije dovoljno, miču se pojedinačne riječi s kraja;
    # zaštićeni tip proizvoda se preskače (t. 2)
    while len(rijeci) > 2 and not stane(" ".join(rijeci + rep)):
        zadnja_r = rijeci[-1].lower().strip(",.")
        stiti_se = (zadnja_r in ZASTICENI_TIPOVI
                    or any(_norm(zadnja_r) and _norm(zadnja_r) in _norm(o)
                           for o in obavezno))
        if stiti_se:
            rep = [rijeci[-1]] + rep       # varijanta i tip idu u zaštićeni rep
            rijeci = rijeci[:-1]
            continue
        rijeci = rijeci[:-1]
    # glava ne smije završiti prijedlogom ili veznikom („…šampon protiv 200 ml“)
    while len(rijeci) > 1 and zavrsava_lose(" ".join(rijeci)):
        rijeci = rijeci[:-1]
    rezultat = " ".join(rijeci + rep).strip(" ,")
    while rezultat and zavrsava_lose(rezultat):
        rezultat = " ".join(rezultat.split()[:-1]).strip(" ,")
    # title ne smije završiti pridjevom (t. 2), ni neposredno ispred količine
    def _bez_pridjeva_na_kraju(tekst: str) -> str:
        rijeci_t = tekst.split()
        kol = kolicina_pakiranja(tekst) or kolicina_iz(tekst)
        rep_t: list[str] = []
        if kol:
            dijelovi = kol.lower().split()
            nisko_t = [w.lower() for w in rijeci_t]
            for i in range(len(rijeci_t) - len(dijelovi), -1, -1):
                if nisko_t[i:i + len(dijelovi)] == dijelovi:
                    rep_t, rijeci_t = rijeci_t[i:], rijeci_t[:i]
                    break
        while len(rijeci_t) > 2 and zavrsava_pridjevom(" ".join(rijeci_t)):
            rijeci_t = rijeci_t[:-1]
        while len(rijeci_t) > 1 and zavrsava_lose(" ".join(rijeci_t)):
            rijeci_t = rijeci_t[:-1]
        return " ".join(rijeci_t + rep_t).strip(" ,")

    rezultat = _bez_pridjeva_na_kraju(rezultat)
    return rezultat or spoji(segmenti[:1])
