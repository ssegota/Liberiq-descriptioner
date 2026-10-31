#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline test objedinjenog runnera (template ver.11): dohvat eLjekarna24
(BigCommerce) jednom za oba alata, klasifikacija, ekstrakcija, PDP s
regulatornom kontrolom, SEO upisan u PDP, spojeni redak, indeks i resume."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import generate_all as A
import pdp_generator as P
import pdp_templates as T
import seo_meta_generator as S

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


OUT = Path(tempfile.mkdtemp(prefix="liberiq_test_all_"))
(OUT / "pdp").mkdir(parents=True, exist_ok=True)
CACHE = OUT / ".cache" / "html"

PROD = P.Product("Vitamini, minerali i kolageni", "Alkaloid", "TST1",
                 "FEROZOMAL MIKROGRANULE 30 VREĆICA",
                 "https://eljekarna24.hr/ferozomal-test/")

SASTAV = ("Sladilo: sorbitol (iz kukuruza ili pšenice); željezov pirofosfat, "
          "maltodekstrin, L-askorbinska kiselina (vitamin C), arome, regulator "
          "kiselosti: limunska kiselina; cijanokobolamin (vitamin B12), tvar protiv "
          "zgrudnjavanja: silicijev dioksid; sladila: sukraloza, acesulfam K.")

HTML = f"""<html><head><title>Ferozomal | eLjekarna24</title>
<meta name="description" content="Stari meta opis."></head><body>
<h1 class="productView-title">FEROZOMAL MIKROGRANULE 30 VREĆICA</h1>
<div class="productView-info"><dt class="productView-info-name">SKU:</dt>
<dd class="productView-info-value">TST1</dd>
<dt class="productView-info-name">UPC:</dt><dd class="productView-info-value">5310001272814</dd></div>
<div class="pv-desc-short">Ferozomal je dodatak prehrani sa sladilima.</div>
<div class="pv-tabs-section"><div class="pv-desc-source">
<p>Ferozomal mikrogranule za izravnu primjenu, 30 vrećica. Dodatak prehrani sa sladilima.
Željezo u liposomu, bez metalnog okusa. Okus limuna i šumskog voća. Za odrasle.</p>
<p><strong>Sastav</strong>: jedna vrećica (1,8 g) sadrži željezo 30 mg (214 % PU),
vitamin C 80 mg (100 % PU), vitamin B12 2,5 µg (100 % PU).</p>
<p><strong>Sastojci</strong>: {SASTAV}</p>
<p><strong>Primjena</strong>: 1 vrećica dnevno, sadržaj otopiti izravno u ustima.</p>
<p>Prekomjerno konzumiranje može imati laksativni učinak.
Proizvođač: Fine Foods &amp; Pharmaceuticals N.T.M. S.p.A., Italija.</p>
</div></div></body></html>"""

fetch_count = {"n": 0}


class FakeResp:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    text = HTML

    def raise_for_status(self):
        return None


import requests  # noqa: E402

_orig_get = requests.get


def fake_get(url, **kw):
    fetch_count["n"] += 1
    return FakeResp()


requests.get = fake_get
args = SimpleNamespace(no_fetch=False, refresh_cache=False, no_web_search=True,
                       search_results=0, pim_dir="")

page, sources = A.gather_shared(PROD, "A", CACHE, args)
check("dohvat: stranica preuzeta", page.fetched)
check("dohvat: BigCommerce opis (.pv-desc-source) izvučen",
      "željezov pirofosfat" in sources[0].text and "Primjena" in sources[0].text)
check("dohvat: EAN iz polja UPC", P.ean_sa_stranice(sources[0].text) == "5310001272814")
check("dohvat: SEO dobiva isti puni tekst", "Sastojci" in page.content)
check("dohvat: SAMO JEDAN HTTP poziv za oba alata", fetch_count["n"] == 1,
      f"({fetch_count['n']})")
A.gather_shared(PROD, "A", CACHE, args)
check("cache: ponovni prolaz bez HTTP poziva", fetch_count["n"] == 1)
requests.get = _orig_get

GOOD_PDP = T.primjer_za("A")
PDP_JSON = ('\n\n```json\n{"izvori": {"S1": "sastav, doza, EAN, upozorenja"}, '
            '"nedostaje": ["zemlja podrijetla"], "konflikti": [], '
            '"provjeriti": ["proizvođač samo u jednom izvoru"], '
            '"kut": "liposom", "namjena": "željezo"}\n```')
INV = json.dumps({
    "cinjenice": [
        {"polje": "puni_sastav", "vrijednost": SASTAV, "izvor": "[S1]",
         "status": "FOUND", "potvrda": "jedan izvor"},
        {"polje": "doza", "vrijednost": "1 vrećica dnevno", "izvor": "[S1]",
         "status": "FOUND", "potvrda": "jedan izvor"},
        {"polje": "ean", "vrijednost": "5310001272814", "izvor": "[S1]",
         "status": "FOUND", "potvrda": "jedan izvor"},
        {"polje": "zemlja_podrijetla", "vrijednost": "", "izvor": "",
         "status": "NOT FOUND"},
    ],
    "meta": {"regulatorna_kategorija": "dodatak prehrani sa sladilima",
             "oznaka_uz_naziv": "sa sladilima", "ean": "5310001272814",
             "dnevna_doza": "1 vrećica",
             "aktivne_tvari": [
                 {"tvar": "Željezo", "oblik": "željezov pirofosfat", "kolicina": 30,
                  "jedinica": "mg"},
                 {"tvar": "Vitamin C", "kolicina": 80, "jedinica": "mg"},
                 {"tvar": "Vitamin B12", "kolicina": 2.5, "jedinica": "µg"}],
             "isti_proizvod": {"S1": "da"}, "promocija_na_stranici": "ne"}},
    ensure_ascii=False)
SEO_JSON = json.dumps({
    "title": "Ferozomal mikrogranule za izravnu primjenu 30 vrećica",
    "meta_description": ("Ferozomal mikrogranule za odrasle, 30 vrećica. Dodatak "
                         "prehrani sa željezom, vitaminom C i B12."),
    "namjena": "za odrasle", "namjena_potvrdjena": True,
    "specs_used": []}, ensure_ascii=False)


class MockClient:
    model_id = verify_model_id = "mock"

    def __init__(self):
        self.calls = []

    def extract(self, system, user):
        self.calls.append("extract")
        if "Određuješ koji PDP template" in system:
            return json.dumps({"template": "A", "podvrsta": "dodatak prehrani",
                               "razlog": "deklarirano kao dodatak prehrani"})
        return INV

    def generate(self, system, user):
        self.calls.append("generate")
        if "KOSTUR IZLAZNOG FORMATA" in user:
            assert "Checklista za izradu PDP opisa" in system
            assert "Vitamin C povećava apsorpciju željeza" in user
            assert "EAN završava s 4" in user
            return GOOD_PDP + PDP_JSON
        return SEO_JSON

    def verify(self, system, user):
        self.calls.append("verify")
        return json.dumps({"prolazi": True, "greske": [], "napomena": ""})


client = MockClient()
letter, podvrsta, razlog = P.klasificiraj(PROD, sources, client)
check("klasifikacija: template A, dodatak prehrani",
      (letter, podvrsta) == ("A", "dodatak prehrani"), f"({letter}, {podvrsta})")
pdp_res, md = P.process_product(PROD, letter, sources, client, 2, True,
                                podvrsta=podvrsta)
check("PDP: prošao kontrolu u prvom pokušaju", pdp_res.attempts == 1,
      f"({pdp_res.attempts}; {pdp_res.notes[:2]})")
check("PDP: status OK s crvenim oznakama",
      pdp_res.status == P.STATUS_PROVJERITI, f"({pdp_res.status})")
check("PDP: crvene oznake popisane za internu datoteku",
      any("Zemlja podrijetla" in x for x in pdp_res.provjeriti))
check("PDP: tablica izvora dodana na kraj",
      "## Izvori (ne objavljuje se)" in md and "sastav, doza, EAN" in md)
check("PDP: JSON blok nije u dokumentu", "```json" not in md)



class RescueClient(MockClient):
    rescue_model_id = "mock-opus"

    def generate(self, system, user, model_id=None):
        if "KOSTUR IZLAZNOG FORMATA" in user:
            self.calls.append(model_id or "osnovni")
            if model_id == "mock-opus":
                assert "SVE DOSAD NAĐENE GREŠKE" in user and "NAJBOLJA DOSADAŠNJA" in user
                return GOOD_PDP + PDP_JSON
            return GOOD_PDP.replace("Važno je pridržavati se", "Zahvaljujući tome, važno je "
                                    "pridržavati se") + PDP_JSON
        return SEO_JSON


rc = RescueClient()
res_r, md_r = P.process_product(PROD, letter, sources, rc, 2, True, podvrsta=podvrsta)
check("dodatni pokušaj Opusom: osnovni model 2× pao, Opus ispravio",
      rc.calls.count("osnovni") == 2 and rc.calls.count("mock-opus") == 1
      and res_r.status == P.STATUS_PROVJERITI, f"({res_r.status}, {rc.calls})")

seo_res = S.process_product(PROD, page, client, set(), set(), threading.Lock(), 2,
                            canonical_name=A.canonical_name_from_md(md),
                            dodatne_upute=A.seo_upute(letter, podvrsta, md))
check("SEO prošao", seo_res.status.startswith("OK"), f"({seo_res.status}; {seo_res.notes[:2]})")
check("SEO title s nastavkom │ eLjekarna24", seo_res.title.endswith("│ eLjekarna24"),
      f"({seo_res.title})")
md2 = A.ugradi_seo(md, seo_res.title, seo_res.meta)
check("SEO upisan u PDP", f"| Meta title | {seo_res.title} |" in md2)

docx = OUT / "pdp" / "t.docx"
P.md_to_docx(md2, docx)
from docx import Document  # noqa: E402

crveni = [r.text for p in Document(str(docx)).tables[-2].rows for c in p.cells
          for para in c.paragraphs for r in para.runs
          if r.font.color and r.font.color.rgb is not None]
check("DOCX: neprovjereni podatak crvenom bojom",
      any("Zemlja podrijetla" in t for t in crveni), f"({crveni})")

rec = A.combined_record(PROD, seo_res, pdp_res, client.model_id, page.fetched)
check("redak: ulazni stupci", all(rec.get(c) for c in A.INPUT_COLS))
check("redak: PDP template i crvene oznake",
      rec["PDP Kategorija predloška"].startswith("A:") and rec["PDP Za provjeru (crveno)"])
check("redak: ukupni status nosi crvene oznake",
      rec["Ukupni status"] == P.STATUS_PROVJERITI, f"({rec['Ukupni status']})")
pdp_res.status = "TREBA PROVJERA"
r_bez = A.combined_record(PROD, seo_res, pdp_res, "m", True)
check("redak: TREBA PROVJERA ukinut -> status po crvenim oznakama",
      r_bez["Ukupni status"] == P.STATUS_PROVJERITI and r_bez["PDP Status"] == P.STATUS_PROVJERITI,
      f"({r_bez['Ukupni status']})")
t = A.za_tablicu(r_bez)
check("tablica: bez stupaca napomena i verifikacije",
      not any(k.endswith(("Napomene", "Verifikacija (2. agent)", "Pokušaji")) for k in t))
pdp_res.status = P.STATUS_PROVJERITI
check("--only seo: nema PDP stupaca",
      not any(k.startswith("PDP ") for k in A.combined_record(PROD, seo_res, None, "m", True)))

xlsx, csv = A.write_index([rec], OUT)
interno = A.write_interni_file([rec], OUT)
import pandas as pd  # noqa: E402

df = pd.read_excel(interno)
check("interno: crvene oznake i template", "Za provjeru (crveno)" in df.columns and
      str(df.loc[0, "Template"]).startswith("A:"))
jl = OUT / "results.jsonl"
jl.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
check("resume: redak učitan po SKU", "TST1" in A.load_done(jl))

shutil.rmtree(OUT, ignore_errors=True)
print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
