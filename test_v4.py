#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi pravila PDP templatea ver.11 i checklista (listopad 2026.).
Bez Bedrocka i mreže."""
import json
import re
import sys

import pdp_extract as X
import pdp_generator as P
import pdp_templates as T
import pravila as R
import regulativa as G

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


def ima(errs, tekst):
    return any(tekst.lower() in e.lower() for e in errs)


print("=== Klijentovi dokumenti u predlosci/ ===")
for k in T.TEMPLATE_META:
    check(f"template {k} postoji", T.template_tekst(k).startswith(f"## Template {k}:"))
check("opća pravila učitana", "Kako opis ne postaje šablona" in T.opca_pravila())
for k in ("A", "C"):
    check(f"checklista za {k}", T.checkliste_za(k) and len(T.checkliste_za(k)[0][1]) > 10000)
check("biljna checklista za biljni dodatak",
      "biljni" in T.checkliste_za("A", "biljni dodatak prehrani")[0][0])
check("10 dokumenata kategorija", all(T.odabir_tekst(k) for k in T.KATEGORIJE))

# nazivi tabova u kodu = nazivi u klijentovom templateu (nema razilaženja)
for k, meta in T.TEMPLATE_META.items():
    if not meta["tabs"]:
        continue
    tekst = T.template_tekst(k)
    for n, naziv, _ in meta["tabs"]:
        check(f"{k} Tab {n} „{naziv}” je u templateu",
              re.search(rf"Tab {n}: {re.escape(naziv)}", tekst) is not None)
    if meta.get("data_rows"):
        for red in meta["data_rows"]:
            check(f"{k} redak tablice „{red}” je u templateu", f"| {red}" in tekst)

print("\n=== Odabir templatea ===")
check("Kozmetika -> samo B", T.dopusteni_templateovi("01") == ("B",))
check("Bebe -> C, B, A, D, J", set(T.dopusteni_templateovi("03")) == set("CBADJ"))
check("Cijeli webshop -> svi", len(T.dopusteni_templateovi(T.kategorija_za("Cijeli webshop"))) == 11)
check("tlakomjer -> D", T.category_for("Cijeli webshop", "Microlife tlakomjer BP A2") == "D")
check("NAN -> C", T.category_for("Mliječne formule", "NAN 1 Optipro 800 g") == "C")
check("NAN 1 -> početna formula", T.podvrsta_heuristika("C", "NAN 1 Optipro 800 g") == T.POCETNA_FORMULA)
check("NAN 2 -> prijelazna", T.podvrsta_heuristika("C", "NAN 2 Optipro 800 g") == "prijelazna formula")
check("početna formula: bez FAQ-a i tvrdnji",
      not T.faq_dopusten("C", T.POCETNA_FORMULA) and not T.tvrdnje_dopustene("C", T.POCETNA_FORMULA))
check("prijelazna formula: tvrdnje prema dokumentu tvrdnji",
      T.tvrdnje_dopustene("C", "prijelazna formula"))
check("K nema FAQ", not T.faq_dopusten("K", "K1"))
check("klasifikacija: parsiranje odgovora",
      X.parse_classification('```json\n{"template": "A", "podvrsta": "x"}\n```')["template"] == "A")

print("\n=== Regulativa: tvrdnje 432/2012, NRV, NN 160/2013 ===")
check("dokument tvrdnji učitan", len(G.tvrdnje()) > 200)
check("tvrdnje za željezo", len(G.tvrdnje_za("Željezo")) == 7)
check("vitamin B12 nije tiamin (B1)", G.prepoznaj_nutrijent("Vitamin B12") == "vitamin_b12")
check("folna kiselina -> folat", G.prepoznaj_nutrijent("folna kiselina") == "folat")
p = G.procijeni([{"tvar": "Željezo", "kolicina": 30, "jedinica": "mg"},
                 {"tvar": "Vitamin C", "kolicina": 80, "jedinica": "mg"},
                 {"tvar": "Vitamin D3", "kolicina": 1000, "jedinica": "IU"},
                 {"tvar": "Selen", "kolicina": 5, "jedinica": "mcg"},
                 {"tvar": "Ashwagandha ekstrakt", "kolicina": 300, "jedinica": "mg"}])
nrv = {t.tvar: t.nrv_posto for t in p.tvari}
check("% PU željeza = 214", nrv["Željezo"] == 214)
check("IU -> µg (1000 IU = 25 µg = 500 %)", nrv["Vitamin D3"] == 500)
check("selen 5 µg (9 %) nije „izvor” -> bez tvrdnji", "Selen" in p.nedopustene)
check("biljka bez odobrenih tvrdnji", "Ashwagandha ekstrakt" in p.nedopustene)
check("vitamin D 25 µg iznad najveće doze (10 µg)",
      any(t.iznad_maksimuma for t in p.tvari if t.tvar == "Vitamin D3"))
check("upozorenje za internu datoteku", any("NN 160/2013" in u for u in p.upozorenja))
dobre = ["Sadrži željezo koje doprinosi normalnom stvaranju crvenih krvnih stanica i "
         "hemoglobina, normalnom prijenosu kisika u tijelu te smanjenju umora i iscrpljenosti.",
         "Sadrži vitamin C koji povećava apsorpciju željeza."]
check("odobrene tvrdnje prolaze", G.neodobrene_tvrdnje(dobre, p) == [],
      str(G.neodobrene_tvrdnje(dobre, p)))
check("izmišljena tvrdnja se hvata",
      G.neodobrene_tvrdnje(["Sadrži željezo koje jača imunitet i daje energiju."], p) != [])
check("tvrdnja za tvar ispod 15 % NRV-a se hvata",
      G.neodobrene_tvrdnje(["Sadrži selen koji doprinosi normalnoj funkciji štitnjače."], p) != [])
check("zabranjena biljka (Prilog III.)", G.zabranjene_biljke("Atropa belladonna") != [])
check("izvadak Priloga II. za beta glukan", "glukan" in G.izvadak_priloga_ii(["beta glukan"]).lower())

print("\n=== Obrazac prve rečenice prema EAN-u ===")
check("EAN …4 -> kut", G.obrazac_prve_recenice("5310001272814")[1] == "kutom proizvoda")
check("EAN …9 -> naziv", G.obrazac_je_naziv(G.obrazac_prve_recenice("123456789")[1]))
check("bez EAN-a -> kut", G.obrazac_prve_recenice("")[1] == "kutom proizvoda")
check("početna formula preskače 0/1 i 4/5",
      G.obrazac_prve_recenice("7613035854444", True)[1].startswith("time za koga"))

print("\n=== Validator na odobrenom primjeru (Ferozomal, Template A) ===")
MD = T.primjer_za("A")
PROD = P.Product("Vitamini, minerali i kolageni", "Alkaloid", "C050999",
                 "FEROZOMAL 30 VREĆICA", "https://eljekarna24.hr/f/")
SRC = [P.Source("S1", P.KIND_PRIMARY, PROD.url, "t", MD)]
PROC = G.procijeni([{"tvar": "Željezo", "kolicina": 30, "jedinica": "mg"},
                    {"tvar": "Vitamin C", "kolicina": 80, "jedinica": "mg"},
                    {"tvar": "Vitamin B12", "kolicina": 2.5, "jedinica": "µg"}])
UP = P.Upute(obrazac="EAN završava s 4", obrazac_opis="kutom proizvoda")
META = {"oznaka_uz_naziv": "sa sladilima"}


def v(md, letter="A", podvrsta="dodatak prehrani", up=UP, src=SRC, prod=PROD):
    return P.validate_pdp(md, prod, letter, podvrsta, src, None, PROC, up, META)


check("odobreni primjer prolazi", v(MD) == [], str(v(MD)[:3]))
slucajevi = [
    ("izmišljena tvrdnja",
     MD.replace("koji povećava apsorpciju željeza.", "koji jača imunitet i daje energiju."),
     "dokumenta tvrdnji"),
    ("doza uz tvrdnju",
     MD.replace("koji povećava apsorpciju željeza.", "koji povećava apsorpciju željeza (80 mg)."),
     "ne pišu doza"),
    ("„doprinosi” izvan bloka tvrdnji",
     MD.replace("Sadržaj vrećice otapa se", "Doprinosi energiji. Sadržaj vrećice otapa se"),
     "samo u bloku tvrdnji"),
    ("nedostaje obvezna rečenica",
     MD.replace("Važno je pridržavati se uravnotežene i raznovrsne prehrane te zdravog "
                "načina života.", ""), "obvezna rečenica"),
    ("bez „dodatak prehrani” u prvoj rečenici",
     MD.replace("Ferozomal je dodatak prehrani sa sladilima u", "Ferozomal dolazi u"),
     "„dodatak prehrani”"),
    ("bez „sa sladilima”",
     MD.replace("dodatak prehrani sa sladilima u", "dodatak prehrani u"), "sa sladilima"),
    ("navođenje izvora",
     MD.replace("Sadržaj vrećice otapa se", "Prema proizvođaču, sadržaj vrećice otapa se"),
     "navođenje izvora"),
    ("zabranjena fraza", MD.replace("Sadržaj vrećice otapa se", "Zahvaljujući tome, sadržaj se otapa"),
     "zahvaljujući"),
    ("prazan glagol", MD.replace("Sadržaj vrećice otapa se", "Vrećica pruža brzo otapanje i otapa se"),
     "pruža"),
    ("općeniti podnaslov", MD.replace("### Mikrogranule koje se otapaju u ustima",
                                      "### Zašto ga odabrati"), "općenit"),
    ("SKU u tekstu", MD.replace("| Brend | Alkaloid |", "| Brend | Alkaloid C050999 |"), "SKU"),
    ("% PU u brzoj traci", MD.replace("Željezo 30 mg po vrećici", "Željezo 214 % PU"), "% PU"),
    ("slogan u brzoj traci", MD.replace("Za odrasle", "Za energiju"), "skraćenu tvrdnju"),
    ("crveni podatak u brzoj traci",
     MD.replace("· Za odrasle ·", "· [PROVJERITI: Za odrasle] ·"), "brzu traku"),
    ("pogrešan naziv taba", MD.replace("## Tab 3: Kako se uzima?", "## Tab 3: Upute"), "nije u templateu"),
    ("dodatni tab", MD.replace("## Česta pitanja", "## Tab 6: Savjet ljekarnika\n\nTekst.\n\n## Česta pitanja"),
     "nije u templateu"),
    ("tablica podataka bez retka",
     MD.replace("| Brend | Alkaloid |\n", ""), "točno ove retke"),
    ("prazan redak bez oznake",
     MD.replace("| [PROVJERITI: Zemlja podrijetla] |  |", "| Zemlja podrijetla |  |"),
     "[PROVJERITI"),
    ("meta title bez │ eLjekarna24",
     MD.replace("30 vrećica │ eLjekarna24", "30 vrećica | eljekarna24"), "│ eLjekarna24"),
    ("FAQ odgovor bez podatka",
     MD.replace("To je upozorenje propisano za proizvode u kojima sladila poput sorbitola "
                "čine više od 10 % sastava. Sorbitol je prvi na popisu sastojaka, što znači "
                "da ga ima najviše.", "Posavjetujte se s ljekarnikom."), "konkretan podatak"),
    ("broj kojeg nema u izvorima",
     MD.replace("Namijenjen je odraslima.", "Namijenjen je odraslima. Vrećica ima 2 g."), "'2g'"),
    ("tvrdnja o podnošljivosti oblika",
     MD.replace("Zato mikrogranule ne ostavljaju metalni okus u ustima.",
                "Zato ne nadražuje sluznicu želuca i bolje se podnosi."), "djelovanju oblika"),
    ("[PROVJERITI] oko cijele rečenice",
     MD.replace("Sadržaj vrećice otapa se izravno u ustima, pa ne trebate gutati tabletu ni "
                "kapsulu niti pripremati napitak.",
                "[PROVJERITI: Sadržaj vrećice otapa se izravno u ustima, pa ne trebate gutati "
                "tabletu ni kapsulu niti pripremati napitak.]"), "cijelu rečenicu"),
    ("uskličnik", MD.replace("ne trebate gutati tabletu", "ne trebate gutati tabletu!"), "uskličnik"),
    ("šablonski početak", MD.replace("**Kratki opis:** Bez metalnog okusa",
                                     "**Kratki opis:** Ovaj proizvod je bez metalnog okusa"),
     "ne smije počinjati"),
]
for opis, md, ocekivano in slucajevi:
    errs = v(md)
    check(f"hvata: {opis}", ima(errs, ocekivano), "" if ima(errs, ocekivano) else str(errs[:3]))

check("obrazac: naziv na početku kad je zadan kut",
      ima(v(MD.replace("**Kratki opis:** Bez metalnog okusa, jer je željezo zatvoreno u liposom: "
                       "Ferozomal je",
                       "**Kratki opis:** Ferozomal mikrogranule su, bez metalnog okusa, jer je "
                       "željezo zatvoreno u liposom,")), "zadani obrazac"))
check("kontrola serije: isti početak",
      ima(v(MD, up=P.Upute(obrazac="x", obrazac_opis="kutom proizvoda",
                           zauzeti_poceci=["Bez metalnog okusa, jer"])), "Kontrola serije"))
RECENICA = ("Sadržaj vrećice otapa se izravno u ustima, pa ne trebate gutati "
            "tabletu ni kapsulu niti pripremati napitak.")
usp = [P.Source("S1", P.KIND_PRIMARY, PROD.url, "t", MD.replace(RECENICA, ""))] + [P.Source("S2", P.KIND_COMPARE, "https://primapharme.hr/x", "t",
                      "Sadržaj vrećice otapa se izravno u ustima, pa ne trebate gutati "
                      "tabletu ni kapsulu niti pripremati napitak.", razina=3)]
check("kopiran tekst usporedne ljekarne se hvata", ima(v(MD, src=usp), "usporedne"))
check("isti tekst na eLjekarni24 smije se preuzeti",
      not ima(v(MD, src=SRC + usp[1:]), "usporedne"))

print("\n=== Validator: Template C (NAN, početna formula) ===")
MDC = T.primjer_za("C")
PC = P.Product("Mliječne formule", "NAN", "C033999", "NAN SUPREMEPRO 1 800 G",
               "https://eljekarna24.hr/n/")
SC = [P.Source("S1", P.KIND_PRIMARY, PC.url, "t", MDC)]
UC = P.Upute(obrazac="EAN završava s 4", obrazac_opis="time za koga je proizvod")


def vc(md, podvrsta=T.POCETNA_FORMULA):
    return P.validate_pdp(md, PC, "C", podvrsta, SC, None, G.procijeni([]), UC, {})


check("odobreni primjer prolazi", vc(MDC) == [], str(vc(MDC)[:3]))
check("početna formula: FAQ se hvata",
      ima(vc(MDC + "\n## Česta pitanja\n\n**Koliko mjerica?**\n\nTri mjerice.\n"), "FAQ se"))
check("početna formula: tvrdnja se hvata",
      ima(vc(MDC.replace("### Sastav na bazi mlijeka",
                         "- Sadrži DHA koja doprinosi razvoju vida.\n\n### Sastav na bazi mlijeka")),
          "nisu dopuštene"))
check("početna formula: sastojak u brzoj traci se hvata",
      ima(vc(MDC.replace("· Sadrži mlijeko", "· S DHA i ARA")), "brza traka početne"))
check("napomena o dojenju mora biti prva",
      ima(vc(MDC.replace("**VAŽNA NAPOMENA:**", "**Napomena:**")), "napomenom o dojenju"))
check("prijelazna formula smije imati FAQ",
      not ima(vc(MDC + "\n## Česta pitanja\n\n**Koliko mjerica?**\n\nTri mjerice.\n",
                 "prijelazna formula"), "FAQ se"))

print("\n=== Ekstrakcija i coverage ===")
inv = X.parse_inventory(json.dumps({
    "cinjenice": [{"polje": "puni_sastav", "vrijednost": "Aqua, Glycerin, Niacinamide",
                   "izvor": "[S1]", "status": "FOUND", "potvrda": "jedan izvor"},
                  {"polje": "ean", "vrijednost": "3337875863377", "izvor": "[S1]",
                   "status": "FOUND"}],
    "meta": {"ean": "3337875863377", "isti_proizvod": {"S1": "da", "S2": "ne"}}}), "B")
check("inventar parsiran", inv.ok and len(inv.facts) == 2)
check("EAN iz meta", inv.ean == "3337875863377")
check("izvor drugog pakiranja prepoznat", inv.isti_proizvod() == {"S1": True, "S2": False})
check("jedan izvor razine 2 -> bez crvene oznake", "potvrda: jedan izvor" not in inv.as_prompt_block())
inv_u = X.parse_inventory(json.dumps({"cinjenice": [
    {"polje": "proizvodjac", "vrijednost": "Fine Foods, Italija", "izvor": "[S3]",
     "status": "FOUND", "potvrda": "samo usporedni izvor"}]}), "A")
check("samo usporedni izvor -> [PROVJERITI]", "PROVJERITI" in inv_u.as_prompt_block())
check("domena brenda prepoznata", R.je_stranica_brenda("https://www.laroche-posay.com.hr/p", "La Roche-Posay")
      and R.je_stranica_brenda("https://www.alkaloid.com.mk/p", "Alkaloid") is False
      and R.je_stranica_brenda("https://www.microlife.com/p", "Microlife"))
check("coverage: izgubljen INCI i EAN", len(X.coverage_check(inv, "# X\n")) == 2)
check("coverage: potpun opis prolazi",
      X.coverage_check(inv, "INCI: Aqua, Glycerin, Niacinamide\n| EAN | 3337875863377 |") == [])
check("neispravan JSON", not X.parse_inventory("nije json", "A").ok)

print("\n=== Izlaz: crvene oznake, tablica izvora, EAN ===")
check("oznake za provjeru izvučene",
      P.oznake_za_provjeru(MD) == ["cijanokobolamin", "cijanokobolamin", "Zemlja podrijetla",
                                   "Fine Foods & Pharmaceuticals N.T.M. S.p.A., Italija"])
md_ean = MD.replace("| EAN | 5310001272814 |", "| [PROVJERITI: EAN] |  |")
novi, ok = P.upisi_ean(md_ean, "5310001272814")
check("EAN iz izvora upisan u prazan redak", ok and "| EAN | 5310001272814 |" in novi)
izv = P.dodaj_tablicu_izvora(MD, SRC, {"S1": "sastav"})
check("tablica izvora: ID | naziv i URL | datum | što potvrđuje",
      "| S1 | eLjekarna24, https://eljekarna24.hr/f/ |" in izv and "| sastav |" in izv)
raw = MD + '\n```json\n{"izvori": {"S1": "x"}, "nedostaje": []}\n```'
doc, js = P.odvoji_json_blok(raw)
check("JSON odvojen od dokumenta", "```json" not in doc and js["izvori"]["S1"] == "x")
check("model-ova tablica izvora se uklanja",
      "## Izvori" not in P.clean_markdown(MD + "\n## Izvori\n\n| S1 | x |\n"))

print("\n=== Opis bez crvenih oznaka + nesigurnosti ===")
nes = P.nesigurnosti(MD)
check("nesigurnosti: obvezan podatak koji nedostaje",
      any(n["vrsta"] == P.NESIGURNOST_NEDOSTAJE and n["polje"] == "Zemlja podrijetla" for n in nes))
check("nesigurnosti: nepotvrđen podatak s mjestom",
      any(n["podatak"].startswith("Fine Foods") and n["sekcija"].startswith("Tab 5") for n in nes))
konf = P.nesigurnosti("## Tab 5: X\n\n| Podatak | Vrijednost |\n| --- | --- |\n"
                      "| Pakiranje | [PROVJERITI: 30 kapsula] / [PROVJERITI: 60 kapsula] |\n")
check("nesigurnosti: neslaganje izvora", len(konf) == 2 and
      all(n["vrsta"] == P.NESIGURNOST_NESLAGANJE for n in konf))
cisto = P.bez_oznaka(MD)
check("opis bez oznaka", "[PROVJERITI" not in cisto)
check("prazan obvezan redak izostavljen", "Zemlja podrijetla" not in cisto.split("## Tab 5")[1])
check("označena vrijednost ostaje kao tekst",
      "| Proizvođač / subjekt u poslovanju s hranom | Fine Foods & Pharmaceuticals" in cisto)

print("\n=== Scraping eLjekarna24 (BigCommerce) ===")
html = """<html><body><h1 class="productView-title">NAN 1</h1>
<div class="productView-info"><dt class="productView-info-name">UPC:</dt>
<dd class="productView-info-value">7613036362238</dd></div>
<div class="pv-desc-short">Kratki opis.</div>
<div class="pv-tabs-section"><div class="pv-tabs-content"></div>
<div class="pv-desc-source"><p><strong>SASTOJCI</strong>: mlijeko, ulje, laktoza, vitamini i minerali</p>
<ul><li><p>prvo</p></li><li><p>drugo</p></li></ul></div></div></body></html>"""
t = P.extract_product_page(html)
check("opis iz .pv-desc-source", "SASTOJCI" in t and "mlijeko, ulje" in t)
check("natuknice sačuvane", "- prvo" in t and "- drugo" in t)
check("EAN iz UPC polja", P.ean_sa_stranice(t) == "7613036362238")

print("\n=== Pravila pisanja ===")
check("„Majčino mlijeko najbolja je hrana” nije superlativ",
      not R.nadi_zabranjene_rijeci("Majčino mlijeko najbolja je hrana za dojenče."))
check("liječnik nije „liječi”", not R.nadi_zabranjene_rijeci("Posavjetujte se s liječnikom."))
check("medicinski rječnik dopušten za lijek (K)",
      R.nadi_zabranjene_rijeci("Ublažava simptome.", lijek=True) == [] and
      R.nadi_zabranjene_rijeci("Ublažava simptome.") != [])
check("spominjanje druge ljekarne", R.nadi_interne_napomene("Kao na Prima Pharme.") != [])

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
