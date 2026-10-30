# -*- coding: utf-8 -*-
"""
Strukturirana ekstrakcija činjenica PRIJE pisanja PDP-a i coverage check.

Ekstrakcija vraća:
  - inventar činjenica po poljima templatea (vrijednost, izvor, status,
    potvrda: koliko neovisnih izvora potvrđuje podatak),
  - strukturirane podatke koje kod koristi za regulatorne provjere: deklarirana
    vrsta proizvoda, EAN, dnevna doza, aktivne tvari s količinama, oznaka
    sladila, ekološki certifikat, biljne vrste,
  - procjenu je li svaki izvor ISTI proizvod i pakiranje (checklista,
    poglavlje 1: „prije pisanja provjeri da je riječ o istom proizvodu”).
Izvori koji nisu isti proizvod ne idu piscu.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import prompts_cfg

# ---------------------------------------------------------------------------
# Polja po templateu
# ---------------------------------------------------------------------------

COMMON_FIELDS = [
    ("naziv_pakiranje", "naziv proizvoda točno s deklaracije, oblik i pakiranje (neto količina / broj komada)"),
    ("namjena", "namjena / za koga je proizvod, točno kako stoji u izvoru"),
    ("upozorenja", "SVA upozorenja s deklaracije ili upute, doslovno"),
    ("cuvanje", "uvjeti čuvanja, rok nakon otvaranja"),
    ("posebnosti", "potvrđene posebnosti: oblik, tehnologija, okus, tekstura, veganski, bez glutena/laktoze, certifikati"),
    ("proizvodjac", "proizvođač / subjekt u poslovanju s hranom / odgovorna osoba: NAZIV I ADRESA; za proizvođače izvan EU i uvoznik/distributer u EU"),
    ("zemlja_podrijetla", "zemlja podrijetla, samo ako je izričito navedena"),
    ("ean", "EAN / barkod (znamenke)"),
]

TEMPLATE_FIELDS = {
    "A": [
        ("doza", "preporučena dnevna doza i način uzimanja, doslovno"),
        ("aktivne_tvari", "aktivne tvari, oblik tvari i količina po dnevnoj dozi, % PU ako je naveden"),
        ("puni_sastav", "puni popis sastojaka uključujući pomoćne tvari, doslovno"),
        ("trajanje_pakiranja", "koliko dana traje pakiranje uz preporučenu dozu (DERIVED ako je izračunato)"),
    ],
    "B": [
        ("aktivni_sastojci", "istaknuti aktivni sastojci i koncentracije kada su navedene"),
        ("puni_sastav", "puni INCI, doslovno"),
        ("nacin_uporabe", "način uporabe, učestalost, jutro/večer"),
        ("tip_koze", "tip kože ili kose, problem, područje primjene, dob"),
        ("ucinci", "učinci koje BREND navodi za taj proizvod"),
        ("tekstura", "tekstura, osjećaj na koži, miris"),
        ("spf", "SPF, UVA oznaka, kategorija zaštite"),
        ("oznake", "hipoalergeno, nekomedogeno, bez parfema, dermatološki testirano — samo ako stoji na deklaraciji"),
        ("ispitivanja", "rezultati ispitivanja s brojkama i metodologijom"),
    ],
    "C": [
        ("vrsta_i_dob", "vrsta proizvoda (početna/prijelazna formula, dječja hrana…) i dob točno s deklaracije"),
        ("napomena_o_dojenju", "napomena o dojenju s deklaracije ili HR stranice brenda, doslovno"),
        ("priprema", "koraci pripreme doslovno, veličina mjerice, omjer praha i vode"),
        ("tablica_hranjenja", "tablica hranjenja po dobi (dob, ml vode, mjerice, obroci)"),
        ("upozorenje_priprema", "upozorenje o nepravilnoj pripremi, doslovno"),
        ("puni_sastav", "puni sastav s alergenima, doslovno"),
        ("alergeni", "alergeni"),
        ("nutritivne_vrijednosti", "nutritivne vrijednosti (na 100 ml gotovog obroka / 100 g), vitamini i minerali"),
        ("gluten", "prisutnost ili odsutnost glutena, ako je navedeno"),
    ],
    "D": [
        ("nacin_uporabe", "koraci uporabe prema uputi, savjeti za točan rezultat"),
        ("specifikacije", "tehničke specifikacije: raspon, točnost, memorija, napajanje, dimenzije, masa, manšeta"),
        ("funkcije", "funkcije i tehnologije kako ih opisuje proizvođač"),
        ("u_pakiranju", "sadržaj pakiranja"),
        ("jamstvo", "jamstvo i servis"),
        ("validacija", "klinička validacija: protokol i izvor"),
        ("model", "model / referentna oznaka"),
    ],
}
GENERIC_FIELDS = [
    ("nacin_uporabe", "način uporabe prema uputi"),
    ("specifikacije", "specifikacije, materijal, veličine, dimenzije"),
    ("sastav", "sastav / materijal / INCI / djelatne tvari"),
    ("u_pakiranju", "sadržaj pakiranja"),
]

HARD_FIELDS = {"doza", "puni_sastav", "aktivne_tvari", "aktivni_sastojci",
               "nacin_uporabe", "upozorenja", "ean", "specifikacije",
               "vrsta_i_dob", "priprema", "nutritivne_vrijednosti",
               "napomena_o_dojenju", "proizvodjac", "sastav"}
UVIJEK_TVRDA = {"puni_sastav", "aktivne_tvari", "ean", "doza", "vrsta_i_dob",
                "nutritivne_vrijednosti"}

STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT FOUND"
STATUS_CONFLICT = "CONFLICT"
STATUS_DERIVED = "DERIVED"

POTVRDA_VISE = "više izvora"
POTVRDA_JEDAN = "jedan izvor"
POTVRDA_USPOREDNI = "samo usporedni izvor"


def fields_for(letter: str) -> list[tuple[str, str]]:
    return TEMPLATE_FIELDS.get(letter, GENERIC_FIELDS) + COMMON_FIELDS


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
    potvrda: str = ""

    @property
    def found(self) -> bool:
        return self.status in (STATUS_FOUND, STATUS_DERIVED)

    @property
    def is_hard(self) -> bool:
        return self.polje in HARD_FIELDS

    @property
    def nepotvrden(self) -> bool:
        # podatak s eLjekarne24 ili stranice brenda (razina 2) piše se normalno;
        # crveno je ono što je samo kod usporedne ljekarne (opća pravila)
        return self.found and self.potvrda == POTVRDA_USPOREDNI


@dataclass
class Inventory:
    facts: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    raw: str = ""
    ok: bool = True
    error: str = ""

    def found(self) -> list:
        return [f for f in self.facts if f.found and f.vrijednost.strip()]

    def conflicts(self) -> list:
        return [f for f in self.facts if f.status == STATUS_CONFLICT]

    def get(self, polje: str) -> Fact | None:
        return next((f for f in self.facts if f.polje == polje), None)

    @property
    def ean(self) -> str:
        e = re.sub(r"\D", "", str(self.meta.get("ean") or ""))
        if not e:
            f = self.get("ean")
            e = re.sub(r"\D", "", f.vrijednost) if f and f.found else ""
        return e if 8 <= len(e) <= 14 else ""

    @property
    def aktivne_tvari(self) -> list[dict]:
        a = self.meta.get("aktivne_tvari")
        return [x for x in a if isinstance(x, dict)] if isinstance(a, list) else []

    def isti_proizvod(self) -> dict[str, bool]:
        out = {}
        for sid, v in (self.meta.get("isti_proizvod") or {}).items():
            out[str(sid).strip("[] ")] = str(v).strip().lower() not in ("ne", "false", "no")
        return out

    def as_prompt_block(self) -> str:
        if not self.facts:
            return "(inventar prazan)"
        lines = []
        for f in self.facts:
            if f.status == STATUS_CONFLICT:
                lines.append(f"- {f.polje}: IZVORI SE NE SLAŽU — {f.konflikt or f.vrijednost} "
                             f"[{f.izvor}] → upiši OBA podatka, oba kao [PROVJERITI: …]")
            elif f.found and f.vrijednost.strip():
                oznake = []
                if f.is_hard:
                    oznake.append("OBVEZNO PRENIJETI")
                if f.nepotvrden:
                    oznake.append(f"potvrda: {f.potvrda} → piši kao [PROVJERITI: …]")
                extra = f" ({'; '.join(oznake)})" if oznake else ""
                lines.append(f"- {f.polje}: {f.vrijednost} [{f.izvor}]{extra}")
            else:
                lines.append(f"- {f.polje}: NIJE PRONAĐENO → opisni dio izostavi; "
                             "obvezni redak tablice ostavi prazan s nazivom "
                             "retka kao [PROVJERITI: naziv retka]")
        meta = {k: v for k, v in self.meta.items() if k != "isti_proizvod" and v}
        if meta:
            lines.append("STRUKTURIRANI PODACI: " + json.dumps(meta, ensure_ascii=False))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt ekstrakcije
# ---------------------------------------------------------------------------

def build_extract_system(letter: str) -> str:
    polja = "\n".join(f"  {k} — {opis}" for k, opis in fields_for(letter))
    default = f"""Ti si ekstraktor činjenica za stranice proizvoda internetske ljekarne
eLjekarna24. Iz priloženih izvora [S1..Sn] izvlačiš strukturirani inventar
činjenica. NE pišeš prodajni tekst i NE zaključuješ ništa što ne piše u izvorima.

POLJA KOJA OBVEZNO POKUŠAVAŠ IZVUĆI:
{polja}

RAZINE IZVORA (opća pravila PDP templatea)
1. Hrvatska ambalaža, deklaracija, PIM ili uputa (ako je priložena).
2. eLjekarna24 i službena stranica brenda ili HR distributera — ISTA razina.
3. Usporedni izvori (Vaše zdravlje, Prima Pharme, Notino, MAKEUP, Douglas):
   samo za usporedbu podataka.
- Ako se izvori RAZLIČITIH razina ne slažu, vrijedi viša razina: status je
  "FOUND" s vrijednošću više razine, a razliku upiši u "konflikt" kao napomenu.
- Status "CONFLICT" samo kad se razlikuju izvori ISTE razine (npr. eLjekarna24 i
  stranica brenda): tada u "konflikt" upiši obje vrijednosti s oznakama izvora.
- Isti podatak na više ljekarni NIJE neovisna potvrda. Neovisnom potvrdom se
  smatraju ambalaža/PIM, stranica brenda ili HR distributera i službeni registri.
- Strane stranice istog proizvoda ne koriste se za sastav, doze i upozorenja ako
  se ne slažu s hrvatskim izvorom.

POTVRDA (za svako pronađeno polje)
- "više izvora": podatak potvrđuju barem dva izvora od kojih je barem jedan
  neovisan (ambalaža/PIM ili stranica brenda/distributera), ili je na ambalaži/PIM-u.
- "jedan izvor": podatak je samo u jednom izvoru razine 1–2.
- "samo usporedni izvor": podatak je samo kod usporedne ljekarne ili webshopa.

ISTI PROIZVOD
Za svaki izvor procijeni je li riječ o POTPUNO istom proizvodu i pakiranju kao
na eLjekarni24 (naziv, oblik, faza/dob, veličina ili broj komada, sastav).
Izvor drugog pakiranja, druge jačine, druge faze ili druge varijante = "ne".

PRAVILA
1. Vrijednosti DOSLOVNO kako stoje u izvoru (bez prepričavanja i skraćivanja).
   Puni sastav / INCI / upozorenja prenose se U CIJELOSTI.
2. Uz svaku vrijednost navedi oznaku izvora ([S1], [S2] …).
3. status: "FOUND", "NOT FOUND", "DERIVED" (izračunato iz potvrđenih polja,
   npr. trajanje pakiranja), "CONFLICT".
4. Ne izmišljaj. Opće znanje modela nije izvor.
5. Identifikatore prenosi znamenku po znamenku. Šifre trgovina (SKU) ne prenosi.

STRUKTURIRANI PODACI ("meta"):
- "regulatorna_kategorija": kako je proizvod DEKLARIRAN (npr. "dodatak prehrani",
  "dodatak prehrani sa sladilima", "kozmetički proizvod", "medicinski proizvod",
  "in vitro dijagnostički medicinski proizvod", "lijek", "homeopatski lijek",
  "tradicionalni biljni lijek", "početna hrana za dojenčad", "prijelazna hrana za
  dojenčad", "mlijeko za malu djecu", "dječja hrana", "hrana", "biocidni proizvod",
  "osobna zaštitna oprema", "ostalo") ili "" ako nije navedeno.
- "oznaka_uz_naziv": "sa sladilom" / "sa sladilima" / "sa šećerom i sladilom" ako
  tako piše UZ NAZIV na deklaraciji, inače "".
- "ean": EAN ili "".
- "dnevna_doza": preporučena dnevna doza (npr. "1 vrećica", "2 kapsule") ili "".
- "aktivne_tvari": [{{"tvar": "Željezo", "oblik": "željezov pirofosfat",
  "kolicina": 30, "jedinica": "mg"}}] — količina PO DNEVNOJ DOZI (preračunaj iz
  količine po jedinici ako je dnevna doza više jedinica). Samo vitamini,
  minerali i druge aktivne tvari s količinom; prazno ako ih nema.
- "biljne_vrste": [{{"hr": "brusnica", "lat": "Vaccinium macrocarpon",
  "dio": "plod", "oblik": "ekstrakt 25:1", "kolicina": "500 mg"}}] ili [].
- "eko_certifikat": šifra kontrolnog tijela i oznaka uzgoja ili naziv
  kozmetičkog certifikata, ako su navedeni; inače "".
- "isti_proizvod": {{"S1": "da", "S2": "ne", ...}} za svaki izvor.
- "promocija_na_stranici": "da" ako izvor S1 (eLjekarna24) prikazuje popust,
  akciju, kupon ili gratis; inače "ne".

FORMAT ODGOVORA — isključivo validan JSON, bez teksta prije i poslije:
{{"cinjenice": [
   {{"polje": "...", "vrijednost": "...", "izvor": "[S1]",
     "status": "FOUND|NOT FOUND|DERIVED|CONFLICT", "konflikt": "",
     "potvrda": "više izvora|jedan izvor|samo usporedni izvor"}}
 ],
 "meta": {{...}}}}
Vrati redak za SVAKO navedeno polje, i kad je NOT FOUND."""
    return prompts_cfg.with_notes(
        prompts_cfg.render("pdp_extract_system", default, kategorija=letter,
                           polja=polja),
        "pdp_extract_napomene")


def build_extract_user(product, sources_block: str) -> str:
    return f"""PROIZVOD
Naziv: {product.naziv}
Brend: {product.brend or "-"}
URL: {product.url}

IZVORI:
<<<IZVORI
{sources_block}
IZVORI>>>

Izvuci inventar činjenica. Vrati samo JSON."""


def _parse_json(text: str, key: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S)
    for chunk in (cleaned, *re.findall(r"\{.*\}", cleaned, flags=re.S)):
        try:
            parsed = json.loads(chunk)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and key in parsed:
            return parsed
    return None


def parse_inventory(text: str, letter: str) -> Inventory:
    data = _parse_json(text, "cinjenice")
    if data is None:
        return Inventory(raw=text or "", ok=False,
                         error="ekstrakcija nije vratila valjan JSON")
    known = {k for k, _ in fields_for(letter)}
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
                          konflikt=str(row.get("konflikt", "") or "").strip(),
                          potvrda=str(row.get("potvrda", "") or "").strip().lower()))
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    inv = Inventory(facts=facts, meta=meta, raw=text or "")
    if not facts:
        inv.ok, inv.error = False, "inventar je prazan"
    elif not known & {f.polje for f in facts}:
        inv.ok, inv.error = False, "nijedno traženo polje nije vraćeno"
    return inv


# ---------------------------------------------------------------------------
# Klasifikacija: koji template i koja podvrsta
# ---------------------------------------------------------------------------

def build_classify_system(odabir: str, dopusteni: list[str], podvrste: dict) -> str:
    pv = "\n".join(f"  {k}: {', '.join(v)}" for k, v in podvrste.items()
                   if k in dopusteni)
    return f"""Određuješ koji PDP template eLjekarne24 vrijedi za proizvod. Template se
bira prema VRSTI proizvoda kako je deklariran, a ne prema kategoriji webshopa.

UPUTA KLIJENTA ZA ODABIR:
{odabir}

Dopušteni templateovi: {", ".join(dopusteni)}.
Podvrste (biraj točno jednu ako template ima podvrste):
{pv or "  (nema)"}

Pravila: proizvod registriran kao (tradicionalni) biljni lijek ili lijek bez
recepta je K; medicinski proizvod je D (ili H za testove i zaštitu); hrana za
dojenčad i dječja hrana je C, a čajevi i dodaci za trudnice i dojilje A.
Vrsta hrane za dojenčad određuje se prema deklaraciji, ne prema broju faze.
Biljni dodatak prehrani = sadrži ekstrakt, prah ili ulje biljke.

Vrati ISKLJUČIVO JSON: {{"template": "A", "podvrsta": "...", "razlog": "..."}}"""


def build_classify_user(product, s1_text: str) -> str:
    return (f"Naziv: {product.naziv}\nBrend: {product.brend}\n"
            f"Sekcija: {product.sekcija}\n\nSTRANICA PROIZVODA (izvadak):\n"
            f"{(s1_text or '')[:3500]}")


def parse_classification(text: str) -> dict:
    return _parse_json(text, "template") or {}


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
    bits += re.findall(r"\b\d{8,14}\b", value)              # EAN
    bits += [w for w in re.findall(r"\b[A-Za-zČĆŽŠĐčćžšđ-]{6,}\b", value)][:6]
    return bits


def coverage_check(inv: Inventory, md: str) -> list[str]:
    """Pronađeni obvezni podaci koji NISU završili u PDP-u."""
    problems: list[str] = []
    md_norm = _norm(md)

    for fact in inv.found():
        if fact.polje == "ean":
            ean = inv.ean
            if ean and ean not in md_norm:
                problems.append(f"EAN {ean} pronađen u izvorima nije upisan u tablicu podataka.")
            continue
        if not fact.is_hard:
            continue
        bits = _key_bits(fact.vrijednost)
        if "," in (fact.vrijednost or ""):
            stavke = [s.strip() for s in re.split(r"[,;]", fact.vrijednost)
                      if len(s.strip()) >= 4]
            if len(stavke) >= 2:
                bits = [re.sub(r"\(.*?\)", " ", s).strip()[:28] for s in stavke]
        if not bits:
            continue

        def _nadjen(b: str) -> bool:
            nb = _norm(b)
            if not nb:
                return False
            if nb in md_norm:
                return True
            brojevi = re.findall(r"\d+", b)
            return len(brojevi) >= 2 and all(br in md_norm for br in brojevi)

        ratio = sum(1 for b in bits if _nadjen(b)) / len(bits)
        ima_konkretno = bool(re.search(r"\d", fact.vrijednost or ""))
        tvrdo = fact.polje in UVIJEK_TVRDA or ima_konkretno
        if tvrdo and ratio < 0.5:
            problems.append(
                f"OBVEZAN PODATAK '{fact.polje}' pronađen u izvorima "
                f"({fact.vrijednost[:110]}…) nije prenesen u PDP — prenesi ga "
                "u odgovarajući tab.")

    for fact in inv.conflicts():
        if "[PROVJERITI" not in md:
            problems.append(
                f"Izvori se ne slažu za '{fact.polje}' ({fact.konflikt or fact.vrijednost}); "
                "upiši oba podatka, oba kao [PROVJERITI: …].")
    return problems
