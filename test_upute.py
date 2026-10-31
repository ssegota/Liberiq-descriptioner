#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi pravila za title/meta i zajedničkih pravila (Upute, Audit, verzije 3 i 4).
PDP pravila templatea ver.11 testira test_v4.py."""
import sys
import threading

import generate_all as A
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
    ("https://webljekarna.vasezdravlje.com/p", "Avène", True, "usporedni izvor"),
    ("https://primapharme.hr/p", "Avène", True, "usporedni izvor"),
    ("https://www.notino.hr/p", "Avène", True, "usporedni izvor (kozmetika)"),
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

KONFLIKT SKU-a: eljekarna24 navodi C001146, ljekarne-plantak.hr navodi C002360.
Potvrditi prema pakiranju.
Prije lokalne objave provjeriti koji je ispravan, prema dostupnoj dokumentaciji."""
nalazi = R.nadi_interne_napomene(prljavo)
for trazeno in ("[S2]", "KONFLIKT", "potvrdit"):
    check(f"hvata „{trazeno}“", any(trazeno.lower() in n.lower() for n in nalazi))
check("hvata spominjanje zabranjene trgovine",
      any("trgovine" in n for n in
          R.nadi_interne_napomene("Dostupno i na ljekarne-plantak.hr")))
check("brend „Master of Pharmacy“ nije lažna prijava",
      R.nadi_interne_napomene("Master of Pharmacy Broncho Release sirup 150 ml") == [])

cisto = ("| [PROVJERITI: Zemlja podrijetla] |  |\n"
         "| Proizvođač | [PROVJERITI: Fine Foods, Italija] |")
check("oznaka [PROVJERITI: …] smije ostati",
      R.nadi_interne_napomene(cisto) == [], str(R.nadi_interne_napomene(cisto)))
check("stari placeholder se hvata",
      R.nadi_interne_napomene("| EAN | Unijeti točno prema aktualnoj deklaraciji ili PIM-u. |") != [])

print("\n=== Razine izvora, template ver.11 ===")
check("eLjekarna24 je razina 2",
      R.prioritet_izvora("https://eljekarna24.hr/p", "NAN") == 2)
check("stranica brenda je razina 2 (ista kao eLjekarna24)",
      R.prioritet_izvora("https://nan.hr/p", "NAN") == 2)
check("Vaše zdravlje je usporedni izvor (razina 3)",
      R.prioritet_izvora("https://webljekarna.vasezdravlje.com/p", "NAN") == 3)
check("Prima Pharme je usporedni izvor (razina 3)",
      R.prioritet_izvora("https://primapharme.hr/p", "NAN") == 3)
check("ostale ljekarne i dalje zabranjene",
      R.prioritet_izvora("https://ljekarne.hr/p", "NAN") == 0)

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
      len(P.parse_headings(R.ukloni_crtice(T.primjer_za("C")))) ==
      len(P.parse_headings(T.primjer_za("C"))))
check("podredak nutritivne tablice (| – od kojih …) ostaje",
      "| – od kojih šećeri | 7,6 g |" in R.ukloni_crtice("| – od kojih šećeri | 7,6 g |"))
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
                 meta=("Solgar Vitamin K1 za odrasle, 100 tableta. Pakiranje "
                       "sadrži 100 tableta i 50 tableta.")), "više puta"),
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

print("\n=== Izlazne datoteke ===")
check("klijentski stupci točno prema uputama",
      A.KLIJENT_COLS == ["Sekcija", "Brend", "SKU", "Naziv", "URL", "Title tag",
                         "Title (px)", "Meta opis", "Meta opis (px)"])
check("interni stupci sadrže tražena polja",
      all(c in A.INTERNI_COLS for c in
          ("Status", "Template", "Za provjeru (crveno)", "Regulatorno",
           "Izvor – eljekarna24", "Izvor – brend",
           "Preuzeto s brend stranice", "Nedostaje", "Konflikti")))
check("nema stupca „Napomena validatora” (TREBA PROVJERA ukinut)",
      "Napomena validatora" not in A.INTERNI_COLS)
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

# blagi način: nedostatak EAN-a ne obara status
check("blagi način je zadani", P.STROGI_NACIN is False and S.STROGI_NACIN is False)


print("\n=== Verzija 3: klijentove izmjene ===")

# PDP t.1 promo oznake i multipakiranje
check("promo oznaka „2+1 GRATIS“ uklonjena",
      "GRATIS" not in R.ukloni_promo("MAGNEZIJ B6 ŠUMEĆE TABLETE A18 2+1 GRATIS"))
check("„akcija“ i „poklon“ uklonjeni",
      R.ukloni_promo("Krema akcija poklon 50 ml").strip() == "Krema 50 ml")
check("multipakiranje u formatu 3 × 18",
      "3 × 18 tableta" in R.normaliziraj_multipak("pakiranje 3x18 tableta"))

# ver.11 (mijenja v3 t.1): meta title je „[naziv, vrsta, pakiranje] │ eLjekarna24”,
# pa nastavak ostaje, a skraćuje se naziv (brend, tip, varijanta, količina ostaju)
dugi = "Avène Sun Krema SPF50 za osjetljivu kožu lica 50 ml"
puni, px, nap = S.finalize_title(dugi)
check("nastavak ostaje, naziv se skraćuje",
      puni.endswith("│ eLjekarna24") and px <= 550 and "SPF50" in puni
      and "50 ml" in puni, f"({puni}, {px:.0f} px)")

# SEO t.2 tip proizvoda zaštićen, bez pridjeva na kraju
k = R.skrati_po_segmentima(
    "Vichy Liftactiv Collagen Specialist dnevna hidratantna krema 50 ml",
    stane=lambda x: S.text_width_px(x, 20) <= 430,
    obavezno=S.obavezni_pojmovi("Vichy Liftactiv Collagen Specialist krema 50 ml"))
check("tip proizvoda sačuvan pri kraćenju", R.sadrzi_tip(k) != "", f"({k})")
check("title ne završava pridjevom", not R.zavrsava_pridjevom(k), f"({k})")

# SEO t.3 duplikat dobiva varijantu
check("duplikat se razlikuje varijantom",
      "SPF30" in S.dodaj_varijantu("Avène Sun Krema 50 ml",
                                   "AVENE SUN KREMA SPF30 50 ML"))

# SEO t.5 nedoslovna specifikacija je greška
prod_s = S.Product("Kozmetika", "Avène", "C1", "AVENE SUN KREMA SPF50 50 ML",
                   "https://eljekarna24.hr/x/")
page_s = S.PageData(fetched=True, content="Avene Sun krema SPF50 50 ml, vrlo "
                                          "visoka zaštita od UVA i UVB zraka")
kand = S.Candidate(title_core="Avène Sun krema SPF50 50 ml",
                   meta="Avène Sun krema SPF50 za zaštitu lica, 50 ml. Vrlo "
                        "visoka zaštita od UVA i UVB zraka.",
                   namjena="za zaštitu lica",
                   specs_used=["patentirani filter nove generacije"])
check("nedoslovna specifikacija je greška",
      any("nije doslovno pronađena" in e for e in
          S.validate_candidate(kand, prod_s, page_s, set(), set())))

# SEO t.6 uspoređuje se količina pakiranja, ne svaki broj
kand2 = S.Candidate(title_core="Solgar Vitamin K1 100 mcg 100 tableta",
                    meta="Solgar Vitamin K1 100 mcg za odrasle, 100 tableta. "
                         "Vitamin K doprinosi normalnom zgrušavanju krvi.",
                    namjena="za odrasle",
                    specs_used=["Vitamin K doprinosi normalnom zgrušavanju krvi"])
prod_k = S.Product("V", "Solgar", "C2", "SOLGAR VITAMIN K1 100 MCG 100 TABLETA",
                   "https://eljekarna24.hr/y/")
page_k = S.PageData(fetched=True, content="Solgar Vitamin K1 100 mcg, 100 tableta, "
                                          "za odrasle. Vitamin K doprinosi "
                                          "normalnom zgrušavanju krvi.")
check("jačina (100 mcg) nije količina pakiranja",
      S.validate_candidate(kand2, prod_k, page_k, set(), set()) == [],
      str(S.validate_candidate(kand2, prod_k, page_k, set(), set())[:2]))
check("količina pakiranja se čita ispravno",
      R.kolicina_pakiranja("Solgar Vitamin K1 100 mcg 100 tableta") == "100 tableta")

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
