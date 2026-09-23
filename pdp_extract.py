#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strukturirana ekstrakcija prije pisanja + coverage check nakon pisanja.

Provedba klijentove upute nakon testiranja (PDP opisi):
    SOURCE → STRUKTURIRANA EKSTRAKCIJA → PISAC → KONTROLA FORMATA
           → FACT-CHECK → COVERAGE CHECK

Model ne smije istodobno iz raw sourcea birati podatke i pisati tekst: prvo se
izrađuje inventar činjenica (vrijednost + izvor + status), pa se piše PDP, a
zatim se provjerava da nijedan pronađeni podatak nije izgubljen ili zamijenjen
placeholderom.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import prompts_cfg

# ---------------------------------------------------------------------------
# Polja koja se obvezno pokušavaju izvući (klijentova uputa, sekcija 05)
# ---------------------------------------------------------------------------

COMMON_FIELDS = [
    ("naziv_brend_pakiranje", "naziv, brend, oblik i pakiranje"),
    ("namjena", "namjena i potvrđene funkcije / claimovi"),
    ("upozorenja", "upozorenja, ograničenja i uvjeti čuvanja"),
    ("posebne_karakteristike", "posebne karakteristike proizvoda kada su potvrđene"),
    ("studije", "studije / mjereni rezultati i njihov kontekst"),
    ("proizvodjac", "proizvođač / odgovorna osoba / zemlja podrijetla"),
    ("identifikatori", "EAN, UPC, SKU i drugi identifikatori (svaki kao odvojeno polje)"),
]

CATEGORY_FIELDS = {
    "supplement": [
        ("doza", "preporučena dnevna doza i konkretan način uzimanja"),
        ("aktivne_tvari", "aktivne tvari, oblik tvari i količine po jedinici / dnevnoj dozi"),
        ("puni_sastav", "puni sastav i pomoćne tvari kada su dostupne"),
    ],
    "cosmetics": [
        ("aktivni_sastojci", "aktivni sastojci i koncentracije kada su navedene"),
        ("puni_sastav", "puni INCI"),
        ("nacin_uporabe", "način uporabe, učestalost, jutro/večer i redoslijed u rutini"),
        ("tip_koze", "potrebe / tip kože i područje primjene"),
        ("svojstva", "tekstura, završetak, miris i druga potvrđena svojstva"),
        ("pao", "PAO / rok nakon otvaranja kada postoji"),
    ],
    "device": [
        ("nacin_uporabe", "koraci uporabe prema uputi"),
        ("specifikacije", "tehničke značajke, mjerni rasponi, veličine i pribor"),
        ("puni_sastav", "sadržaj pakiranja (popis pribora)"),
        ("validacija", "validacija, norme i dokumentacija kada su navedene"),
    ],
    "formula": [
        ("doza", "priprema obroka i tablica hranjenja prema deklaraciji"),
        ("aktivne_tvari", "nutritivne vrijednosti i ključne skupine sastojaka"),
        ("puni_sastav", "puni sastav i alergeni"),
        ("dobna_faza", "dobna faza i tip formule"),
    ],
}

# Hard fields — ne smiju nestati iz finalnog PDP-a (klijent, sekcija 08)
HARD_FIELDS = {"doza", "puni_sastav", "aktivne_tvari", "aktivni_sastojci",
               "nacin_uporabe", "upozorenja", "identifikatori", "specifikacije",
               "dobna_faza"}

# Polja koja blokiraju i kad nemaju brojeva: gubitak sastava ili doze je
# najteži propust iz audita. Ostala tvrda polja su prozna (upute, upozorenja)
# pa ih model prevodi i preoblikuje, što doslovno podudaranje ne može mjeriti.
UVIJEK_TVRDA = {"puni_sastav", "aktivne_tvari", "aktivni_sastojci",
                "identifikatori", "doza", "dobna_faza"}

STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT FOUND"
STATUS_CONFLICT = "CONFLICT"
STATUS_DERIVED = "DERIVED"

# Samo doslovni placeholderi iz klijentovih predložaka. Rečenice tipa
# "Obvezna provjera prije objave" dio su predloška i NISU placeholder.
PLACEHOLDER_HINTS = [
    "unijeti točno prema aktualnoj deklaraciji ili pim",
    "navesti samo ako je potvrđena",
]


def fields_for(category: str) -> list[tuple[str, str]]:
    return CATEGORY_FIELDS.get(category, []) + COMMON_FIELDS


# ---------------------------------------------------------------------------
# Model inventara
# ---------------------------------------------------------------------------

@dataclass
class Fact:
    polje: str
    vrijednost: str = ""
    izvor: str = ""
    status: str = STATUS_NOT_FOUND
    konflikt: str = ""

    @property
    def found(self) -> bool:
        return self.status in (STATUS_FOUND, STATUS_DERIVED)

    @property
    def is_hard(self) -> bool:
        return self.polje in HARD_FIELDS


@dataclass
class Inventory:
    facts: list = field(default_factory=list)
    raw: str = ""
    ok: bool = True
    error: str = ""

    def found(self) -> list:
        return [f for f in self.facts if f.found and f.vrijednost.strip()]

    def conflicts(self) -> list:
        return [f for f in self.facts if f.status == STATUS_CONFLICT]

    def hard_found(self) -> list:
        return [f for f in self.found() if f.is_hard]

    def as_prompt_block(self) -> str:
        if not self.facts:
            return "(inventar prazan)"
        lines = []
        for f in self.facts:
            if f.status == STATUS_CONFLICT:
                lines.append(f"- {f.polje}: KONFLIKT — {f.konflikt or f.vrijednost} "
                             f"[{f.izvor}] → obvezno označiti za provjeru, NE spajati")
            elif f.found and f.vrijednost.strip():
                mark = " (HARD FIELD — ne smije nestati)" if f.is_hard else ""
                lines.append(f"- {f.polje}: {f.vrijednost} [{f.izvor}]{mark}")
            else:
                lines.append(f"- {f.polje}: NIJE PRONAĐENO → koristi placeholder "
                             "ili izostavi")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt ekstrakcije
# ---------------------------------------------------------------------------

def build_extract_system(category: str) -> str:
    polja = "\n".join(f"  {k} — {opis}" for k, opis in fields_for(category))
    default = f"""Ti si ekstraktor činjenica za stranice proizvoda internetske ljekarne.
Iz priloženih izvora [S1..Sn] izvlačiš strukturirani inventar činjenica. NE pišeš
prodajni tekst i NE zaključuješ ništa što ne piše u izvorima.

POLJA KOJA OBVEZNO POKUŠAVAŠ IZVUĆI:
{polja}

HIJERARHIJA IZVORA
- PRIORITET 1 je stranica proizvoda s linka iz ulazne tablice: kad podatak
  postoji ondje, uzmi TU vrijednost i kao izvor navedi taj [Sx].
- PRIORITET 2 je zadani sekundarni izvor (webljekarna.vasezdravlje.com):
  koristi se za podatke kojih nema na prioritetu 1.
- PRIORITET 3 su ostali web izvori: tek kad podatka nema ni na 1 ni na 2.
- Prioritet određuje koja vrijednost ide u "vrijednost", ali ako se konkretne
  vrijednosti među izvorima RAZLIKUJU, status je svejedno "CONFLICT" i u
  "konflikt" navedi obje vrijednosti s oznakama izvora.

PRAVILA
1. Za svako polje vrati vrijednost DOSLOVNO kako stoji u izvoru (bez
   prepričavanja, skraćivanja ili prevođenja). Puni sastav / INCI prenosi se u
   CIJELOSTI, bez izostavljanja i bez "i ostalo".
2. Uz svaku vrijednost navedi oznaku izvora ([S1], [S2] …).
3. status = "FOUND" kad je podatak u izvorima; "NOT FOUND" kad ga nema;
   "DERIVED" kad je izračunat iz potvrđenih polja (npr. trajanje pakiranja);
   "CONFLICT" kad dva izvora daju RAZLIČITU konkretnu vrijednost.
4. Konfliktne vrijednosti se NE spajaju i NE bira se jedna: status "CONFLICT",
   a u "konflikt" upiši obje vrijednosti s oznakama izvora.
5. Ne izmišljaj. Ako podatka nema, status je "NOT FOUND" i vrijednost prazna.
6. Identifikatore (EAN, UPC, SKU) prenosi znamenku po znamenku, bez ispravljanja.
7. Opće znanje modela nije izvor.

FORMAT ODGOVORA — isključivo validan JSON, bez teksta prije i poslije:
{{"cinjenice": [
   {{"polje": "...", "vrijednost": "...", "izvor": "[S1]",
     "status": "FOUND|NOT FOUND|DERIVED|CONFLICT", "konflikt": ""}}
]}}
Vrati redak za SVAKO navedeno polje, i kad je NOT FOUND."""
    return prompts_cfg.with_notes(
        prompts_cfg.render("pdp_extract_system", default, kategorija=category,
                           polja=polja),
        "pdp_extract_napomene")


def build_extract_user(product, sources_block: str) -> str:
    return f"""PROIZVOD
Naziv: {product.naziv}
Brend: {product.brend or "-"}
SKU: {product.sku}
URL: {product.url}

IZVORI:
<<<IZVORI
{sources_block}
IZVORI>>>

Izvuci inventar činjenica. Vrati samo JSON."""


def parse_inventory(text: str, category: str) -> Inventory:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S)
    data = None
    for chunk in (cleaned, *re.findall(r"\{.*\}", cleaned, flags=re.S)):
        try:
            parsed = json.loads(chunk)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and "cinjenice" in parsed:
            data = parsed
            break
    if data is None:
        return Inventory(raw=text or "", ok=False,
                         error="ekstrakcija nije vratila valjan JSON")

    known = {k for k, _ in fields_for(category)}
    facts = []
    for row in data.get("cinjenice") or []:
        if not isinstance(row, dict) or not row.get("polje"):
            continue
        status = str(row.get("status", STATUS_NOT_FOUND)).upper().replace("_", " ")
        if status not in (STATUS_FOUND, STATUS_NOT_FOUND, STATUS_CONFLICT,
                          STATUS_DERIVED):
            status = STATUS_FOUND if row.get("vrijednost") else STATUS_NOT_FOUND
        facts.append(Fact(polje=str(row["polje"]).strip(),
                          vrijednost=str(row.get("vrijednost", "") or "").strip(),
                          izvor=str(row.get("izvor", "") or "").strip(),
                          status=status,
                          konflikt=str(row.get("konflikt", "") or "").strip()))
    inv = Inventory(facts=facts, raw=text or "")
    if not facts:
        inv.ok, inv.error = False, "inventar je prazan"
    missing = known - {f.polje for f in facts}
    if len(missing) == len(known):
        inv.ok, inv.error = False, "nijedno traženo polje nije vraćeno"
    return inv


# ---------------------------------------------------------------------------
# Coverage check (deterministički)
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    import unicodedata
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _key_bits(value: str) -> list[str]:
    """Karakteristični dijelovi vrijednosti: brojevi s jedinicom i duže riječi."""
    bits = re.findall(r"\d+(?:[.,]\d+)?\s*(?:mg|mcg|µg|ml|g|kg|l|iu|%|cm|"
                      r"tablet\w*|kapsul\w*|komad\w*|mjesec\w*)", value, re.IGNORECASE)
    bits += re.findall(r"\b\d{8,14}\b", value)              # EAN/UPC
    bits += [w for w in re.findall(r"\b[A-Za-zČĆŽŠĐčćžšđ-]{6,}\b", value)][:6]
    return bits


SKU_RE = re.compile(r"\b[A-Z]{1,3}\d{5,8}\b")


def _ocisti_identifikatore(vrijednost: str) -> str:
    """Iz identifikatora zadrži samo EAN/UPC znamenke.

    Interne šifre trgovina (SKU) ne ulaze u PDP po uputama, pa se ne
    provjeravaju niti smatraju izgubljenim podatkom.
    """
    return " ".join(re.findall(r"\b\d{8,14}\b", vrijednost or ""))


def coverage_check(inv: Inventory, md: str) -> list[str]:
    """Vrati popis pronađenih podataka koji NISU završili u finalnom PDP-u."""
    problems: list[str] = []
    md_norm = _norm(md)
    md_low = md.lower()

    for fact in inv.found():
        if fact.polje == "identifikatori":
            ean = _ocisti_identifikatore(fact.vrijednost)
            if not ean:
                continue                       # nema EAN-a, samo SKU: preskoči
            if not any(d in md_norm for d in ean.split()):
                problems.append(
                    "EAN pronađen u izvorima nije prenesen u Tab 5: "
                    f"{ean}.")
            continue
        bits = _key_bits(fact.vrijednost)
        # popis odvojen zarezima (sastojci, dobne faze) -> usporedi po stavkama
        if "," in (fact.vrijednost or ""):
            stavke = [s.strip() for s in re.split(r"[,;]", fact.vrijednost)
                      if len(s.strip()) >= 4]
            if len(stavke) >= 2:
                bits = [re.sub(r"\(.*?\)", " ", s).strip()[:28] for s in stavke]
        if not bits:
            bits = [fact.vrijednost[:40]]
        def _nadjen(b: str) -> bool:
            nb = _norm(b)
            if not nb:
                return False
            if nb in md_norm:
                return True
            # raspon zapisan riječima: „6–12 mjeseci“ vs „6 do 12 mjeseci“
            brojevi = re.findall(r"\d+", b)
            if len(brojevi) >= 2:
                return all(br in md_norm for br in brojevi)
            return False

        hit = sum(1 for b in bits if _nadjen(b))
        ratio = hit / len(bits) if bits else 1.0
        # prozni sadržaj (upute, namjena, svojstva) model prevodi i preoblikuje,
        # pa se blokirajućim smatra samo gubitak konkretnih vrijednosti
        ima_konkretno = bool(re.search(r"\d", fact.vrijednost or ""))
        tvrdo = fact.is_hard and (fact.polje in UVIJEK_TVRDA or ima_konkretno)
        threshold = 0.5 if tvrdo else 0.34
        if ratio < threshold:
            label = "HARD FIELD" if tvrdo else "podatak"
            problems.append(
                f"{label} '{fact.polje}' pronađen u izvorima "
                f"({fact.vrijednost[:110]}...) nije prenesen u PDP — prenesi ga "
                "u odgovarajući dio strukture.")

    # placeholder umjesto postojeće vrijednosti
    for fact in inv.found():
        if not fact.is_hard:
            continue
        for hint in PLACEHOLDER_HINTS:
            idx = md_low.find(hint)
            while idx != -1:
                window = md_low[max(0, idx - 160): idx + 160]
                if fact.polje.split("_")[0][:5] in _norm(window) or \
                        any(_norm(b) and _norm(b) in _norm(window)
                            for b in _key_bits(fact.vrijednost)[:2]):
                    break
                idx = md_low.find(hint, idx + 1)
            else:
                continue
            break

    # neoznačeni konflikti
    for fact in inv.conflicts():
        marker = any(w in md_low for w in ("konflikt", "razlikuju se izvori",
                                           "izvori se razlikuju",
                                           "vrijednosti se razlikuju",
                                           "podatak se razlikuje"))
        if not marker:
            problems.append(
                f"Konflikt izvora za '{fact.polje}' ({fact.konflikt or fact.vrijednost}) "
                "nije označen u PDP-u — vrijednosti se ne spajaju nego se konflikt "
                "vidljivo označava za provjeru.")
    return problems


# Polje iz inventara -> naziv retka u Tab 5 u kojem se očekuje vrijednost
POLJE_U_REDAK = {
    "identifikatori": "ean",
    "proizvodjac": "proizvođač",
    "pakiranje": "pakiranje",
}


def placeholder_instead_of_value(inv: Inventory, md: str) -> list[str]:
    """Placeholder na mjestu gdje izvor ima konkretnu vrijednost.

    Provjerava se SAMO redak tablice u kojem bi vrijednost trebala stajati,
    a ne cijeli dokument (inače „Obvezna provjera prije objave“ iz predloška
    okida na svakom proizvodu).
    """
    out = []
    for fact in inv.found():
        redak_naziv = POLJE_U_REDAK.get(fact.polje)
        if not redak_naziv:
            continue
        vrijednost = (_ocisti_identifikatore(fact.vrijednost)
                      if fact.polje == "identifikatori" else fact.vrijednost)
        if not vrijednost.strip():
            continue
        for redak in md.splitlines():
            if not redak.strip().startswith("|"):
                continue
            if redak_naziv not in redak.lower():
                continue
            celije = [c.strip() for c in redak.strip().strip("|").split("|")]
            sadrzaj = " ".join(celije[1:]).lower()
            ima_placeholder = any(h in sadrzaj for h in PLACEHOLDER_HINTS)
            ima_vrijednost = any(_norm(b) and _norm(b) in _norm(sadrzaj)
                                 for b in (_key_bits(vrijednost) or [vrijednost]))
            if ima_placeholder and not ima_vrijednost:
                out.append(
                    f"„{redak_naziv}“ je pronađen u izvorima ({vrijednost[:40]}), "
                    "ali je u Tabu 5 ostao placeholder. Upiši konkretnu vrijednost.")
            break
    return out
