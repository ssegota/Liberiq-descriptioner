#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi pravila iz dokumenata „Upute za generator“ i „Audit“ (21. 9. 2026.)."""
import json
import sys
import threading

import generate_all as A
import pdp_extract as X
import pdp_generator as P
import pdp_templates as T
import pravila as R
import seo_meta_generator as S

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


print("=== Z1. Hijerarhija izvora (allowlist u kodu) ===")

primjeri = [
    ("https://eljekarna24.hr/proizvod", "Avène", True, "izvor 1"),
    ("https://www.eau-thermale-avene.com.hr/p", "Avène", True, "izvor 2"),
    ("https://webljekarna.vasezdravlje.com/p", "Avène", False, "druga ljekarna"),
    ("https://ljekarne.hr/p", "Solgar", False, "druga ljekarna"),
    ("https://ljekarne-plantak.hr/p", "Solgar", False, "druga ljekarna"),
    ("https://onlineljekarna.hr/p", "Solgar", False, "druga ljekarna"),
    ("https://www.bing.com/search", "Solgar", False, "tražilica"),
    ("https://www.amazon.com/dp/X", "Solgar", False, "marketplace"),
    ("https://laroche-posay.rs/p", "La Roche-Posay", False, "drugo tržište"),
    ("https://laroche-posay-me.com/p", "La Roche-Posay", False, "engleska verzija"),
    ("https://solgar.hr/p", "Solgar", True, "izvor 2"),
]
for url, brend, ocekivano, opis in primjeri:
    dopusteno, razlog = R.je_dopusten(url, brend)
    check(f"{opis}: {url[:42]}", dopusteno is ocekivano, f"({razlog})")

check("URL izvan eljekarna24 kao ulazni: nema izvora",
      not R.je_primarni("https://drugaljekarna.hr/p"))

print("\n=== Z2. Izlaz spreman za copy/paste ===")

prljavo = """### Tab 5

| EAN | 123 [S2] |
| --- | --- |

KONFLIKT SKU-a: eljekarna24 navodi C001146, webljekarna.vasezdravlje.com navodi C002360.
Potvrditi prema pakiranju.
Prije lokalne objave provjeriti koji je ispravan, prema dostupnoj dokumentaciji."""
nalazi = R.nadi_interne_napomene(prljavo)
for trazeno in ("[S2]", "KONFLIKT", "potvrdit"):
    check(f"hvata „{trazeno}“", any(trazeno.lower() in n.lower() for n in nalazi))
check("hvata spominjanje druge ljekarne",
      any("trgovine" in n for n in nalazi), f"({len(nalazi)} nalaza)")
check("brend „Master of Pharmacy“ nije lažna prijava",
      R.nadi_interne_napomene("Master of Pharmacy Broncho Release sirup 150 ml") == [])

cisto = ("| EAN | Unijeti točno prema aktualnoj deklaraciji ili PIM-u. |\n"
         "| Obvezna provjera prije objave | Naziv, količina i EAN moraju "
         "odgovarati aktualnoj ambalaži. |")
check("tekst iz klijentovog predloška smije ostati",
      R.nadi_interne_napomene(cisto) == [], str(R.nadi_interne_napomene(cisto)))

print("\n=== Z3. Bez uspoređivanja šifri drugih trgovina ===")
check("SKU druge trgovine nije izvor",
      R.je_dopusten("https://webljekarna.vasezdravlje.com/p", "NAN")[0] is False)

print("\n=== Z4. Bez crtica ===")
check("crtica u tekstu se uklanja",
      R.ukloni_crtice("Avène Sun Krema SPF50 – zaštita od sunca.") ==
      "Avène Sun Krema SPF50, zaštita od sunca.")
check("raspon brojeva ostaje",
      "22–42 cm" in R.ukloni_crtice("Manšeta 22–42 cm."))
check("6–12 mjeseci ostaje", "6–12" in R.ukloni_crtice("Za dob 6–12 mjeseci."))
check("crtica u nazivu ostaje", "La Roche-Posay" in
      R.ukloni_crtice("La Roche-Posay Effaclar — krema"))
check("struktura Markdowna ostaje",
      len(P.parse_headings(R.ukloni_crtice(T.EXAMPLES["cosmetics"]))) ==
      len(P.parse_headings(T.EXAMPLES["cosmetics"])))
check("detekcija crtica", R.nadi_crtice("a – b") and not R.nadi_crtice("22–42"))

print("\n=== Title: skraćivanje po segmentima ===")

def stane(px):
    return lambda t: S.text_width_px(t, S.TITLE_FONT_PX) <= px

# audit: „Vichy Dercos Energetski Šampon protiv 200 ml“ (prekinuto na „protiv“)
naziv = "Vichy Dercos Energetski šampon protiv opadanja kose 200 ml"
skraceno = R.skrati_po_segmentima(naziv, stane(430),
                                  obavezno=S.obavezni_pojmovi(naziv))
check("ne završava prijedlogom", not R.zavrsava_lose(skraceno), f"({skraceno})")
check("količina sačuvana", "200 ml" in skraceno, f"({skraceno})")

# audit: „Sagas RC-01 Collagen Hyaluron Complex 60“ (broj bez jedinice)
naziv2 = "Sagas RC 01 Collagen Hyaluron Complex, 60 kapsula"
s2 = R.skrati_po_segmentima(naziv2, stane(430), obavezno=S.obavezni_pojmovi(naziv2))
check("broj ima jedinicu", not R.zavrsava_lose(s2) and "kapsula" in s2, f"({s2})")

# audit: varijanta „Riche“ se ne smije izgubiti
naziv3 = "La Roche-Posay Hydraphase HA Riche intenzivna hidratantna njega 50 ml"
s3 = R.skrati_po_segmentima(naziv3, stane(430), obavezno=S.obavezni_pojmovi(naziv3))
check("varijanta Riche sačuvana", "Riche" in s3, f"({s3})")
check("količina sačuvana (50 ml)", "50 ml" in s3, f"({s3})")

# namjena iza crtice se uklanja prva
naziv4 = "Solgar Vitamin K1 100 mcg 100 tableta – za normalno zgrušavanje krvi"
s4 = R.skrati_po_segmentima(naziv4, stane(430), obavezno=S.obavezni_pojmovi(naziv4))
check("namjena iza crtice uklonjena",
      "zgrušavanje" not in s4 and "100 tableta" in s4, f"({s4})")

print("\n=== Title i meta: validator ===")

PROD = S.Product("Vitamini, minerali i kolageni", "Solgar", "C1",
                 "SOLGAR VITAMIN K1 100 MCG 100 TABLETA",
                 "https://eljekarna24.hr/x/")
PAGE = S.PageData(fetched=True, content=(
    "Solgar Vitamin K1 100 mcg, 100 tableta, za odrasle. Vitamin K doprinosi "
    "normalnom zgrušavanju krvi."))
CANON = "Solgar Vitamin K1 100 mcg 100 tableta"

dobar = S.Candidate(
    title_core=CANON,
    meta=("Solgar Vitamin K1 100 mcg za odrasle, 100 tableta. Vitamin K "
          "doprinosi normalnom zgrušavanju krvi."),
    namjena="za odrasle")
check("klijentov primjer prolazi",
      S.validate_candidate(dobar, PROD, PAGE, set(), set(), CANON) == [],
      str(S.validate_candidate(dobar, PROD, PAGE, set(), set(), CANON)[:2]))

losi = [
    ("riječi kojih nema u PDP nazivu",
     S.Candidate(title_core="Solgar Vitamin K1 digitalni 100 mcg 100 tableta",
                 meta=dobar.meta), "kojih nema u PDP nazivu"),
    ("crtica u titlu",
     S.Candidate(title_core="Solgar Vitamin K1 100 mcg – 100 tableta",
                 meta=dobar.meta), "crticu"),
    ("title završava veznikom",
     S.Candidate(title_core="Solgar Vitamin K1 100 tableta i",
                 meta=dobar.meta), "prijedlogom"),
    ("namjena izvan prvih 100 znakova",
     S.Candidate(title_core=CANON,
                 meta=("Solgar Vitamin K1 100 mcg, 100 tableta, vitamin K1 "
                       "prema deklaraciji proizvoda i podacima s pakiranja. "
                       "Namijenjen odraslima.")),
     "prvih 100 znakova"),
    ("formulacija „Pakiranje od“",
     S.Candidate(title_core=CANON,
                 meta="Solgar Vitamin K1 za odrasle. Pakiranje od 100 tableta."),
     "Pakiranje od"),
    ("količina dvaput u meti",
     S.Candidate(title_core=CANON,
                 meta=("Solgar Vitamin K1 za odrasle, 100 tableta. Dostupno u "
                       "100 tableta.")), "više puta"),
    ("zabranjena riječ",
     S.Candidate(title_core=CANON,
                 meta="Solgar Vitamin K1 za odrasle, 100 tableta. Optimalan unos."),
     "Zabranjena riječ"),
]
for opis, kandidat, ocekivano in losi:
    errs = S.validate_candidate(kandidat, PROD, PAGE, set(), set(), CANON)
    check(f"odbija: {opis}", any(ocekivano.lower() in e.lower() for e in errs),
          "" if any(ocekivano.lower() in e.lower() for e in errs) else str(errs[:2]))

print("\n=== Statusi ===")
check("nema statusa OK (skraćeno)",
      "OK (skraćeno)" not in open("seo_meta_generator.py", encoding="utf-8").read())
check("nema statusa CONFLICT / REVIEW",
      "CONFLICT / REVIEW" not in open("pdp_generator.py", encoding="utf-8").read())

res = S.process_product(PROD, S.PageData(fetched=False), None, set(), set(),
                        threading.Lock(), 1)
check("bez stranice eljekarna24 status je GREŠKA", res.status == "GREŠKA")

print("\n=== PDP: nova pravila ===")

PPROD = P.Product("Kozmetika", "La Roche-Posay", "C2",
                  "LRP EFFACLAR DUO+M 40 ML", "https://eljekarna24.hr/y/")
SRC = [P.Source("S1", "stranica proizvoda", PPROD.url, "t",
                "EAN 3337875863377, niacinamid, glicerin, Zinc PCA, salicilna "
                "kiselina, 40 ml, 66 % manje mitesera nakon 4 tjedna na 45 "
                "ispitanika klinička procjena, 44 % na 45 ispitanika, 45 % na 42 "
                "ispitanika, 24 sata hidratacije na 24 ispitanika instrumentalno "
                "mjerenje")]

check("brza traka ima šest polja", len(T.BRZA_TRAKA_POLJA) == 6)
check("primjeri imaju popunjenu brzu traku",
      all("| Tip proizvoda |" in T.EXAMPLES[c] for c in T.EXAMPLES))
check("primjeri bez uputa iz predloška",
      all(not R.nadi_interne_napomene(T.EXAMPLES[c]) for c in T.EXAMPLES))
check("primjeri bez crtica",
      all(not R.nadi_crtice(T.EXAMPLES[c]) for c in T.EXAMPLES))

errs = P.validate_pdp(T.EXAMPLES["cosmetics"], PPROD, "cosmetics", SRC)
check("kanonski primjer prolazi nova pravila", errs == [], str(errs[:3]))

# nepopunjena brza traka
lose = T.EXAMPLES["cosmetics"].replace("| Namjena | njega masne kože sklone nepravilnostima |",
                                       "| Namjena |  |")
check("prazno polje brze trake se hvata",
      any("nije popunjeno" in e for e in P.validate_pdp(lose, PPROD, "cosmetics", SRC)))

# previše istaknutih sastojaka
redak = "| Dodatni sastojak | opis |\n"
lose2 = T.EXAMPLES["cosmetics"].replace(
    "| Salicilna kiselina | Sastojak koji se često nalazi u njezi kože sklone začepljenim porama. |",
    "| Salicilna kiselina | Sastojak koji se često nalazi u njezi kože sklone začepljenim porama. |\n"
    + redak * 3)
check("više od 4 istaknuta sastojka se hvata",
      any("3 ili 4" in e for e in P.validate_pdp(lose2, PPROD, "cosmetics", SRC)))

# kliničke studije bez metode
lose3 = T.EXAMPLES["cosmetics"].replace(
    "| 24 sata hidratacije | Instrumentalno mjerenje na 24 ispitanika. |",
    "| 24 sata hidratacije | Podaci nisu navedeni u dostupnom izvoru. |")
check("redak studija bez metode se hvata",
      any("Kliničke studije" in e for e in P.validate_pdp(lose3, PPROD, "cosmetics", SRC)))

# testirano bez objašnjenja
lose4 = T.EXAMPLES["cosmetics"].replace("### Tab 3: Kako se koristi?",
                                        "Formula je klinički testirana.\n\n### Tab 3: Kako se koristi?")
check("„klinički testirana“ bez objašnjenja se hvata",
      any("bez objašnjenja" in e for e in P.validate_pdp(lose4, PPROD, "cosmetics", SRC)))

# interne napomene u tekstu
lose5 = T.EXAMPLES["cosmetics"].replace("### Tab 4: Sastojci",
                                        "KONFLIKT: [S2] navodi drugu vrijednost, potvrditi.\n\n### Tab 4: Sastojci")
errs5 = P.validate_pdp(lose5, PPROD, "cosmetics", SRC)
check("interne napomene u PDP-u se hvataju",
      any("Interna napomena" in e for e in errs5))

# crtice
lose6 = T.EXAMPLES["cosmetics"].replace("Krema za svakodnevnu njegu",
                                        "Krema — za svakodnevnu njegu")
check("crtica u PDP-u se hvata",
      any("crtica" in e.lower() for e in P.validate_pdp(lose6, PPROD, "cosmetics", SRC)))

print("\n=== Odvajanje internog JSON-a od dokumenta ===")
odgovor = T.EXAMPLES["cosmetics"] + '\n\n```json\n{"nedostaje": ["EAN"], ' \
          '"konflikti": ["doza"], "koristeni_izvori": ["S1"]}\n```'
doc, js = P.odvoji_json_blok(odgovor)
check("JSON odvojen od dokumenta", "```json" not in doc and js.get("nedostaje") == ["EAN"])
check("dokument ostaje potpun", len(P.parse_headings(doc)) == len(P.parse_headings(T.EXAMPLES["cosmetics"])))

print("\n=== Izlazne datoteke ===")
check("klijentski stupci točno prema uputama",
      A.KLIJENT_COLS == ["Sekcija", "Brend", "SKU", "Naziv", "URL", "Title tag",
                         "Title (px)", "Meta opis", "Meta opis (px)"])
check("interni stupci sadrže tražena polja",
      all(c in A.INTERNI_COLS for c in
          ("Status", "Izvor – eljekarna24", "Izvor – brend",
           "Preuzeto s brend stranice", "Nedostaje", "Konflikti",
           "Napomena validatora")))
check("klijentska datoteka nema internih stupaca",
      not any(c in A.KLIJENT_COLS for c in
              ("Status", "Pokušaji", "Napomene", "Izvori", "Model")))

print("\n=== Rječnik zapisa ===")
check("RC-01 -> RC 01", "RC 01" in R.primijeni_rjecnik("Sagas RC-01 Collagen"))
check("Urea Repair -> UreaRepair", "UreaRepair" in R.primijeni_rjecnik("Eucerin Urea Repair"))
check("la roche posay -> La Roche-Posay",
      "La Roche-Posay" in R.primijeni_rjecnik("la roche posay Effaclar"))


print("\n=== Ispravci nakon drugog testnog runa ===")

# rezanje riječi (u štapiću -> u štiku) mora biti odbijeno
prod_b = S.Product("Kozmetika", "Avène", "C002170",
                   "Avene Cold Cream Nutrition balzam za usne",
                   "https://eljekarna24.hr/x/")
page_b = S.PageData(fetched=True, content=(
    "Cold Cream Nutrition balzam za usne u štapiću, hranjivi, za suhe i "
    "ispucale usne, za cijelu obitelj od 2 godine."))
canon_b = "Avène Cold Cream Nutrition hranjivi balzam za usne u štapiću"
lose = S.Candidate(title_core="Avène Cold Cream Nutrition balzam za usne u štiku",
                   meta="Avène Cold Cream Nutrition balzam za usne za suhe usne. "
                        "Hranjiva njega.", namjena="za suhe usne")
check("odbija skraćenu riječ („štiku“)",
      any("ne postoji u nazivu" in e for e in
          S.validate_candidate(lose, prod_b, page_b, set(), set(), canon_b)))

# skraćivanje ne reže usred fraze
t = "Avène Sun Krema SPF50 za suhu i osjetljivu kožu lica 50 ml"
k = R.skrati_po_segmentima(t, stane=lambda x: S.text_width_px(x, 20) <= 430,
                           obavezno=S.obavezni_pojmovi(t))
check("reže cijelu prijedložnu frazu, ne dio",
      "za suhu" not in k and "50 ml" in k, f"({k})")

# EAN iz inventara automatski ide u Tab 5
inv_ean = X.parse_inventory(json.dumps({"cinjenice": [
    {"polje": "identifikatori", "vrijednost": "EAN 3282770149487",
     "izvor": "[S1]", "status": "FOUND"}]}, ensure_ascii=False), "cosmetics")
md_ph = T.EXAMPLES["cosmetics"].replace(
    "| EAN | 3337875863377 |",
    "| EAN | Unijeti točno prema aktualnoj deklaraciji ili PIM-u. |")
novi, upisano = P.upisi_ean(md_ph, inv_ean)
check("EAN iz izvora automatski upisan", upisano and "3282770149487" in novi)

# popis sastojaka: podudaranje po stavkama
inv_lista = X.parse_inventory(json.dumps({"cinjenice": [
    {"polje": "aktivni_sastojci",
     "vrijednost": "Niacinamid, Glicerin (navedeni implicitno kroz opis), Zinc PCA",
     "izvor": "[S1]", "status": "FOUND"}]}, ensure_ascii=False), "cosmetics")
check("popis sastojaka se uspoređuje po stavkama",
      not any(g.startswith("HARD FIELD") for g in
              X.coverage_check(inv_lista, T.EXAMPLES["cosmetics"])))

# blagi način: nedostatak EAN-a ne obara status
check("blagi način je zadani", P.STROGI_NACIN is False and S.STROGI_NACIN is False)

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
