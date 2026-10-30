#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi klijentovih pravila iz obje upute nakon testiranja."""
import json
import sys
import threading

import generate_all as A
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

# 1. separator │ (U+2502) i „eLjekarna24” prema PDP templateu ver.11
check("separator je │ eLjekarna24 (template ver.11)",
      S.BRAND_SUFFIX == " \u2502 eLjekarna24", repr(S.BRAND_SUFFIX))
full, px, _ = S.finalize_title("Solgar Vitamin K1 100 mcg 100 tableta")
check("primjer stane u 550 px s nastavkom",
      full.endswith("\u2502 eLjekarna24") and px <= S.TITLE_MAX_PX,
      f"({len(full)} znakova, {px:.0f} px)")

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

print("\n=== Objedinjeni runner ===")

canon = A.canonical_name_from_md(T.primjer_za("A"))
check("kanonski naziv izvučen iz PDP-a",
      canon == "Ferozomal mikrogranule za izravnu primjenu, 30 vrećica", f"({canon})")

srcs = [P.Source("S1", P.KIND_PRIMARY, "https://eljekarna24.hr/x", "t", "a"),
        P.Source("S2", P.KIND_BRAND, "https://www.laroche-posay.com.hr/effaclar", "t",
                 "b" * 300),
        P.Source("S3", P.KIND_COMPARE, "https://webljekarna.vasezdravlje.com/p", "t",
                 "c" * 300, razina=3)]
bs = A.brand_source_for(srcs, "La Roche-Posay")
check("SEO brend izvor: službena hrvatska domena",
      bs is not None and "laroche-posay.com.hr" in bs.url)
check("SEO: usporedna ljekarna nije brend izvor",
      A.brand_source_for([srcs[0], srcs[2]], "La Roche-Posay") is None)
check("strana domena brenda se ne koristi",
      R.je_dopusten("https://laroche-posay.rs/p", "La Roche-Posay")[0] is False)
blok = P.sources_block(srcs)
check("prompt označava razine izvora i zabranu kopiranja",
      "RAZINA 2" in blok and "RAZINA 3" in blok and "NE kopira" in blok)

md_seo = A.ugradi_seo(T.primjer_za("A"), "Ferozomal 30 vrećica \u2502 eLjekarna24",
                      "Nova meta.")
check("SEO alat upisuje title i meta u PDP",
      "| Meta title | Ferozomal 30 vrećica \u2502 eLjekarna24 |" in md_seo
      and "| Meta description | Nova meta. |" in md_seo)

print("\n=== Definitivni izrazi ===")
for izraz in ("Najbolji izbor za kožu.", "Najučinkovitiji proizvod u ponudi.",
              "Apsolutno siguran za sve.", "Zlatni standard njege."):
    check(f"zabranjeno: {izraz[:28]}",
          bool(S.find_forbidden(izraz)) and bool(P.find_forbidden(izraz)))
for izraz in ("Dojenje je najbolji način prehrane dojenčeta.",
              "Majčino mlijeko najbolja je hrana za dojenče.",
              "Uzmi najviše jednu tabletu dnevno.",
              "Najkasnije 30 minuta prije obroka."):
    check(f"dopušteno: {izraz[:32]}", not P.find_forbidden(izraz))

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
