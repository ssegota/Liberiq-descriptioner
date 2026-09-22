#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi klijentovih pravila iz obje upute nakon testiranja."""
import json
import sys
import threading

import generate_all as A
import pdp_extract as X
import pdp_generator as P
import pravila as R
import pdp_templates as T
import seo_meta_generator as S

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


print("=== SEO: title/meta uputa ===")

PROD = S.Product("Vitamini, minerali i kolageni", "Solgar", "C1",
                 "SOLGAR VITAMIN K1 100 MCG 100 TABLETA", "https://eljekarna24.hr/x/")
PAGE = S.PageData(fetched=True, content=(
    "Solgar Vitamin K1 100 mcg, 100 tableta. Za odrasle. Vitamin K doprinosi "
    "normalnom zgrušavanju krvi i održavanju normalnih kostiju. Jedna tableta dnevno."))

# 1. separator | (U+007C), ne │ (U+2502)
check("separator je | (U+007C)", S.BRAND_SUFFIX == " | eljekarna24" and
      "\u2502" not in S.BRAND_SUFFIX, repr(S.BRAND_SUFFIX))
full, px, _ = S.finalize_title("Solgar Vitamin K1 100 mcg 100 tableta")
check("klijentov primjer: 51 znak / ~466 px",
      len(full) == 51 and 460 <= px <= 470, f"({len(full)} znakova, {px:.0f} px)")

# 2. zarez ispred količine
c = S.Candidate(title_core="Solgar Vitamin K1 100 mcg, 100 tableta",
                meta="Solgar Vitamin K1 za odrasle, 100 tableta. Doprinosi zgrušavanju krvi.")
errs = S.validate_candidate(c, PROD, PAGE, set(), set())
check("zarez ispred količine odbijen", any("Zarez ispred količine" in e for e in errs))

# 3. kratica jedinice
c = S.Candidate(title_core="Solgar Vitamin K1 100 mcg 100 tab",
                meta="Solgar Vitamin K1 za odrasle, 100 tableta. Doprinosi zgrušavanju krvi.")
errs = S.validate_candidate(c, PROD, PAGE, set(), set())
check("kratica jedinice (100 tab) odbijena",
      any("Kratica jedinice" in e for e in errs))

# 4. razmak između broja i jedinice
c = S.Candidate(title_core="Eucerin pH5 krema za ruke 75ml",
                meta="Eucerin pH5 krema za ruke 75 ml za suhu kožu. S dekspantenolom.")
errs = S.validate_candidate(c, S.Product("K", "Eucerin", "C2",
                                         "EUCERIN PH5 KREMA ZA RUKE 75 ML", "u"),
                            S.PageData(fetched=True, content="75 ml, za suhu kožu, dekspantenol"),
                            set(), set())
check("broj i jedinica bez razmaka odbijeno",
      any("razmak" in e for e in errs))

# 5. namjena u meti je OBVEZNA
c = S.Candidate(title_core="Solgar Vitamin K1 100 mcg 100 tableta",
                meta="Solgar Vitamin K1 100 mcg dodatak je prehrani. Pakiranje sadrži 100 tableta.")
errs = S.validate_candidate(c, PROD, PAGE, set(), set())
check("meta bez namjene odbijena", any("ne sadrži namjenu" in e for e in errs))

# klijentov TREBA primjer prolazi
c_ok = S.Candidate(
    title_core="Solgar Vitamin K1 100 mcg 100 tableta",
    meta=("Solgar Vitamin K1 100 mcg za odrasle, 100 tableta. Vitamin K doprinosi "
          "normalnom zgrušavanju krvi i održavanju normalnih kostiju."),
    namjena="za odrasle")
check("klijentov 'TREBA' primjer prolazi",
      S.validate_candidate(c_ok, PROD, PAGE, set(), set()) == [],
      str(S.validate_candidate(c_ok, PROD, PAGE, set(), set())[:2]))

# 6. superlativ "idealan"
c = S.Candidate(title_core="Solgar Vitamin K1 100 mcg 100 tableta",
                meta="Idealan za odrasle, 100 tableta. Vitamin K doprinosi zgrušavanju krvi.")
check("superlativ 'Idealan' odbijen",
      any("idealn" in e.lower() for e in S.validate_candidate(c, PROD, PAGE, set(), set())))

# 7. količina se NIKAD ne gubi pri skraćivanju
qty = S.quantity_tokens(PROD.naziv)
long_title = ("Solgar Vitamin K1 vrlo dugačak naziv s mnogo sporednih značajki "
              "dodataka i opisa 100 tableta")
tr = S.trim_title_to_px(long_title, S.TITLE_CORE_TARGET_PX, keep_qty=qty)
check("skraćivanje čuva količinu",
      bool(S.quantity_tokens(tr) & qty) and
      S.text_width_px(tr, S.TITLE_FONT_PX) <= S.TITLE_CORE_TARGET_PX, f"({tr})")

# 8. title mora početi KANONSKIM nazivom iz PDP-a
canon = "Eucerin pH5 losion za pranje – blago čišćenje za suhu i osjetljivu kožu 200 ml"
c = S.Candidate(title_core="Nivea losion za pranje 200 ml",
                meta="Nivea losion za pranje 200 ml za suhu kožu. S dekspantenolom.")
errs = S.validate_candidate(c, S.Product("K", "Eucerin", "C3",
                                         "EUCERIN PH5 LOSION 200 ML", "u"),
                            S.PageData(fetched=True, content="200 ml suha koža dekspantenol"),
                            set(), set(), canonical_name=canon)
check("title koji ne počinje kanonskim nazivom odbijen",
      any("ne počinje nazivom" in e for e in errs))

# 9. bez stranice na eljekarna24 -> GREŠKA
res = S.process_product(PROD, S.PageData(fetched=False), None, set(), set(),
                        threading.Lock(), 1)
check("bez izvora 1 redak je GREŠKA", res.status == "GREŠKA")

# 10. stupci izvora
rec = S.RowResult(product=PROD, page=PAGE).to_record()
check("novi stupci izvora postoje",
      all(k in rec for k in ("Izvor – eljekarna24", "Izvor – brend",
                             "Preuzeto s brend stranice", "Napomena za provjeru",
                             "Namjena")))

# 11. podatak s brend stranice -> TREBA PROVJERA + oznaka
class BrandClient:
    def generate(self, sys_p, user):
        assert "[BREND]" in user
        return json.dumps({
            "title": "Solgar Vitamin K1 100 mcg 100 tableta",
            "meta_description": ("Solgar Vitamin K1 100 mcg za odrasle, 100 tableta. "
                                 "Vitamin K doprinosi normalnom zgrušavanju krvi."),
            "specs_used": ["100 mcg"], "namjena": "za odrasle",
            "namjena_potvrdjena": True,
            "podaci_s_brend_stranice": ["zemlja podrijetla"]}, ensure_ascii=False)
    model_id = "mock"

res = S.process_product(PROD, PAGE, BrandClient(), set(), set(), threading.Lock(), 1,
                        brand_source=S.BrandSource(url="https://solgar.com/k1",
                                                   text="Zemlja podrijetla: SAD"))
rec = res.to_record()
check("brend izvor -> status OK, oznaka u stupcima (blagi način)",
      res.status == "OK" and rec["Napomena za provjeru"].startswith("TREBA PROVJERA"))
S.postavi_strogi_nacin(True)
res_strogo = S.process_product(PROD, PAGE, BrandClient(), set(), set(),
                               threading.Lock(), 1,
                               brand_source=S.BrandSource(url="https://solgar.hr/k1",
                                                          text="Zemlja podrijetla: SAD"))
check("--strogo: brend izvor -> TREBA PROVJERA",
      res_strogo.status == "TREBA PROVJERA", f"({res_strogo.status})")
S.postavi_strogi_nacin(False)
check("brend izvor -> popunjeni stupci",
      rec["Izvor – brend"] == "https://solgar.com/k1" and
      "zemlja podrijetla" in rec["Preuzeto s brend stranice"] and
      rec["Napomena za provjeru"].startswith("TREBA PROVJERA"))

# 12. nepotvrđena namjena -> TREBA PROVJERA
class NoPurpose(BrandClient):
    def generate(self, sys_p, user):
        return json.dumps({
            "title": "Solgar Vitamin K1 100 mcg 100 tableta",
            "meta_description": "Solgar Vitamin K1 100 mcg za odrasle, 100 tableta. Sadrži vitamin K.",
            "specs_used": [], "namjena": "", "namjena_potvrdjena": False,
            "podaci_s_brend_stranice": []}, ensure_ascii=False)

res = S.process_product(PROD, PAGE, NoPurpose(), set(), set(), threading.Lock(), 1)
check("nepotvrđena namjena -> TREBA PROVJERA",
      res.status == "TREBA PROVJERA" and
      any("Namjena nije potvrđena" in n for n in res.notes))

print("\n=== PDP: uputa nakon testiranja ===")

PPROD = P.Product("Kozmetika", "La Roche-Posay", "C4",
                  "LA ROCHE POSAY EFFACLAR DUO+M 40 ML", "https://eljekarna24.hr/y/")
SRC = [P.Source("S1", "stranica proizvoda", PPROD.url, "t",
                "Effaclar Duo+M 40 ml. INCI: Aqua, Glycerin, Niacinamide, Zinc PCA, "
                "Salicylic Acid. Nanositi ujutro i navečer na očišćeno lice. "
                "EAN 3337875863377.")]

# 13. inventar: parsiranje, hard fields, konflikt
inv_json = json.dumps({"cinjenice": [
    {"polje": "puni_sastav", "vrijednost": "Aqua, Glycerin, Niacinamide, Zinc PCA, Salicylic Acid",
     "izvor": "[S1]", "status": "FOUND"},
    {"polje": "nacin_uporabe", "vrijednost": "Nanositi ujutro i navečer na očišćeno lice",
     "izvor": "[S1]", "status": "FOUND"},
    {"polje": "identifikatori", "vrijednost": "EAN 3337875863377", "izvor": "[S1]",
     "status": "FOUND"},
    {"polje": "pao", "vrijednost": "", "izvor": "", "status": "NOT FOUND"},
    {"polje": "svojstva", "vrijednost": "30 ml vs 40 ml", "izvor": "[S1] vs [S2]",
     "status": "CONFLICT", "konflikt": "[S1] 40 ml vs [S2] 30 ml"},
]}, ensure_ascii=False)
inv = X.parse_inventory(inv_json, "cosmetics")
check("inventar parsiran", inv.ok and len(inv.facts) == 5)
check("hard fields prepoznati", len(inv.hard_found()) == 3,
      f"({[f.polje for f in inv.hard_found()]})")
check("konflikt prepoznat", len(inv.conflicts()) == 1)
check("neispravan JSON -> GREŠKA EKSTRAKCIJE",
      not X.parse_inventory("nije json", "cosmetics").ok)

# 14. coverage check hvata izgubljeni INCI
md_ok = T.EXAMPLES["cosmetics"].replace(
    "Puni INCI sastav s aktualne deklaracije (umetnuti točan popis bez prijevoda i skraćivanja).",
    "INCI: Aqua, Glycerin, Niacinamide, Zinc PCA, Salicylic Acid. Nanositi ujutro i navečer "
    "na očišćeno lice. Konflikt izvora označen za provjeru.")
md_lost = T.EXAMPLES["cosmetics"]
gaps_ok = X.coverage_check(inv, md_ok)
gaps_lost = X.coverage_check(inv, md_lost)
check("coverage: potpun PDP prolazi", gaps_ok == [], str(gaps_ok[:2]))
check("coverage: izgubljeni INCI detektiran",
      any("puni_sastav" in g for g in gaps_lost), f"({len(gaps_lost)} problema)")
check("coverage: neoznačen konflikt detektiran",
      any("Konflikt izvora" in g for g in gaps_lost))

# 15. placeholder umjesto vrijednosti
md_ph = md_lost.replace("| EAN | 3337875863377 |",
                        "| EAN | Unijeti točno prema aktualnoj deklaraciji ili PIM-u. |")
check("placeholder umjesto pronađene vrijednosti detektiran",
      len(X.placeholder_instead_of_value(inv, md_ph)) > 0)
check("„Obvezna provjera prije objave“ nije lažna prijava",
      X.placeholder_instead_of_value(inv, md_lost) == [])

# 16. pipeline: ekstrakcija -> pisac -> coverage -> OK
class PDPClient:
    model_id = verify_model_id = "mock"
    def __init__(self): self.n = 0
    def extract(self, s, u): return inv_json
    def generate(self, s, u):
        assert "INVENTAR" in u and "HARD FIELD" in s
        self.n += 1
        doc = md_lost if self.n == 1 else md_ok
        return doc + '\n\n```json\n{"nedostaje": [], "konflikti": [], ' \
                     '"koristeni_izvori": ["S1"]}\n```'

    def verify(self, s, u):
        return json.dumps({"prolazi": True, "nepotkrijepljene_tvrdnje": [],
                           "napomena": ""}, ensure_ascii=False)

cl = PDPClient()
res, md = P.process_product(PPROD, "cosmetics", SRC, cl, 3, True)
check("pipeline: coverage vratio pisca na dopunu", cl.n >= 2, f"(poziva: {cl.n})")
check("pipeline: konflikt ne ide u tekst nego u interni status",
      res.status != "OK" and res.conflicts, f"({res.status})")
check("pipeline: inventar zapisan u rezultat",
      res.inventory is not None and len(res.inventory.found()) == 3)

# 17. status NEDOSTAJE PODATAK IZ IZVORA
class LosingClient(PDPClient):
    def generate(self, s, u): return md_lost
res2, _ = P.process_product(PPROD, "cosmetics", SRC, LosingClient(), 2, True)
check("status NEDOSTAJE PODATAK IZ IZVORA",
      res2.status == "NEDOSTAJE PODATAK IZ IZVORA", f"({res2.status})")
check("coverage zapisan u rezultat", len(res2.coverage) > 0)

# 18. GREŠKA EKSTRAKCIJE
class BadExtract(PDPClient):
    def extract(self, s, u): return "ovo nije json"
res3, md3 = P.process_product(PPROD, "cosmetics", SRC, BadExtract(), 2, True)
check("status GREŠKA EKSTRAKCIJE", res3.status == "GREŠKA EKSTRAKCIJE" and md3 == "")

# 19. novi stupci u PDP zapisu
rec = res.to_record()
check("PDP stupci: coverage/konflikt/ekstrakcija",
      all(k in rec for k in ("Ekstrahiranih polja", "Coverage check",
                             "Konflikt izvora")))

print("\n=== Objedinjeni runner ===")

# 20. kanonski naziv iz PDP-a
canon = A.canonical_name_from_md(T.EXAMPLES["cosmetics"])
check("kanonski naziv izvučen iz PDP-a",
      canon.startswith("La Roche-Posay Effaclar Duo+M krema"), f"({canon[:40]}…)")

# 21. brand source samo sa službene domene brenda
srcs = [P.Source("S1", "stranica proizvoda", "https://eljekarna24.hr/x", "t", "a"),
        P.Source("S2", P.SECONDARY_LABEL,
                 "https://www.laroche-posay.com.hr/effaclar", "t", "b" * 300),
        P.Source("S3", "web", "https://neki-forum.hr/tema", "t", "c" * 300)]
bs = A.brand_source_for(srcs, "La Roche-Posay")
check("brend izvor prepoznat sa službene hrvatske domene",
      bs is not None and "laroche-posay.com.hr" in bs.url)
check("treći izvor se ne koristi za SEO",
      A.brand_source_for([srcs[0], srcs[2]], "La Roche-Posay") is None)
check("strana domena brenda se ne koristi",
      R.je_dopusten("https://laroche-posay.rs/p", "La Roche-Posay")[0] is False)

# 22. prioritet statusa u zbirnom retku
r = A.combined_record(PPROD, None, res2, "m", True)
check("zbirni status preuzima najozbiljniju oznaku",
      r["Ukupni status"] == "NEDOSTAJE PODATAK IZ IZVORA",
      f"({r['Ukupni status']})")

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")

print("\n=== Hijerarhija izvora i definitivni izrazi ===")

# 23. hijerarhija: S1 link, S2 vasezdravlje, S3+ ostali
srcs = [P.Source("S1", "stranica proizvoda", "https://eljekarna24.hr/x", "t", "a"),
        P.Source("S2", P.SECONDARY_LABEL, "https://solgar.hr/proizvod", "t", "b"),
        P.Source("S3", "web", "https://webljekarna.vasezdravlje.com/p", "t", "c")]
blok = P.sources_block(srcs)
check("prompt označava PRIORITET 1 i 2 (bez trećih izvora)",
      "PRIORITET 1" in blok and "PRIORITET 2" in blok and "PRIORITET 3" not in blok)
check("vasezdravlje je zabranjen izvor",
      R.je_dopusten("https://webljekarna.vasezdravlje.com/p", "Solgar")[0] is False)

# 24. SEO sekundarni izvor: vasezdravlje ima prednost pred brendom
bs = A.brand_source_for(srcs, "Solgar")
check("SEO izvor 2 je službena stranica brenda",
      bs is not None and "solgar.hr" in bs.url, f"({bs.url if bs else None})")
bs3 = A.brand_source_for([srcs[0], srcs[2]], "Solgar")
check("SEO: druga ljekarna se ne koristi", bs3 is None)

# 25. definitivni izrazi
for izraz in ("Najbolji izbor za kožu.", "Najučinkovitiji proizvod u ponudi.",
              "Jedini proizvod koji to radi.", "Apsolutno siguran za sve.",
              "Zlatni standard njege.", "Uvijek djeluje."):
    check(f"zabranjeno: {izraz[:28]}",
          bool(S.find_forbidden(izraz)) and bool(P.find_forbidden(izraz)))

# 26. dopušteni izrazi
for izraz in ("Dojenje je najbolji način prehrane dojenčeta.",
              "Uzmi najviše jednu tabletu dnevno.",
              "Najkasnije 30 minuta prije obroka."):
    check(f"dopušteno: {izraz[:32]}",
          not S.find_forbidden(izraz) and not P.find_forbidden(izraz))

# 27. pravila su u promptovima
check("pravilo u SEO promptu", "definitivni izrazi" in S.build_system_prompt().lower())
check("pravilo u PDP promptu",
      "ZABRANA DEFINITIVNIH IZRAZA" in P.build_gen_system("cosmetics"))
check("hijerarhija u PDP promptu",
      "PRIORITET 2" in P.build_gen_system("cosmetics") and
      "službena hrvatska stranica brenda" in P.build_gen_system("cosmetics"))
check("hijerarhija u promptu ekstrakcije",
      "PRIORITET 1" in X.build_extract_system("cosmetics"))

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
