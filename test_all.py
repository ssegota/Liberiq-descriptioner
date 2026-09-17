#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline test objedinjenog runnera: dijeljeni cache (jedan dohvat), spojeni
redak, indeks sa svim stupcima, --only načini."""
import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import generate_all as A
import pdp_generator as P
import pdp_templates as T
import json as _json
import seo_meta_generator as S

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


OUT = Path(tempfile.mkdtemp(prefix="liberiq_test_all_"))
import shutil
(OUT / "pdp").mkdir(parents=True, exist_ok=True)
CACHE = OUT / ".cache" / "html"

PROD = P.Product("Kozmetika", "La Roche-Posay", "TST1",
                 "LA ROCHE POSAY EFFACLAR DUO+M KREMA 40 ML",
                 "https://eljekarna24.hr/test-effaclar/")

HTML = """<html><head><title>Stara stranica</title>
<meta name="description" content="Stari meta opis."></head><body>
<div class="woocommerce-product-details__short-description">
Effaclar Duo+M krema za masnu kožu sklonu nepravilnostima, 40 ml. Za odrasle i
adolescente od 10 godina. Sastojci: niacinamid, glicerin, Zinc PCA, salicilna
kiselina. EAN 3337875863377. Nanosi se ujutro i navečer, može kao podloga za
šminku. Klinička procjena: 66 % manje mitesera nakon 4 tjedna na 45 ispitanika,
44 % manje nepravilnosti na 45 ispitanika, 45 % manje tragova na 42 ispitanika,
24 sata hidratacije na 24 ispitanika. Proizvođač La Roche-Posay Laboratoire
Dermatologique CAI, 86270 La Roche-Posay, Francuska.
</div></body></html>"""

# --- mrežni sloj: brojimo stvarne HTTP dohvate ---
fetch_count = {"n": 0}


class FakeResp:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    text = HTML

    def raise_for_status(self):
        return None


import requests
_orig_get = requests.get


def fake_get(url, **kw):
    fetch_count["n"] += 1
    return FakeResp()


requests.get = fake_get

args = SimpleNamespace(no_fetch=False, refresh_cache=False, no_web_search=True,
                       search_results=0)

page, sources = A.gather_shared(PROD, "cosmetics", CACHE, args)
check("dijeljeni dohvat: stranica preuzeta", page.fetched and len(page.content) > 100)
check("dijeljeni dohvat: PDP dobio isti izvor [S1]",
      len(sources) == 1 and sources[0].sid == "S1" and len(sources[0].text) > 100)
check("dijeljeni dohvat: SAMO JEDAN HTTP poziv za oba alata",
      fetch_count["n"] == 1, f"({fetch_count['n']})")
check("QA polja sa stranice", page.existing_title == "Stara stranica" and
      page.existing_meta == "Stari meta opis.")

# ponovni poziv -> sve iz cachea, bez novih dohvata
A.gather_shared(PROD, "cosmetics", CACHE, args)
check("cache: ponovni prolaz bez HTTP poziva", fetch_count["n"] == 1,
      f"({fetch_count['n']})")

requests.get = _orig_get

# --- mock model za oba alata ---
GOOD_PDP = T.EXAMPLES["cosmetics"]
SEO_JSON = json.dumps({
    "title": "La Roche-Posay Effaclar Duo+M krema 40 ml",
    "meta_description": ("La Roche-Posay Effaclar Duo+M krema 40 ml za masnu kožu "
                         "sklonu nepravilnostima. S niacinamidom za njegu lica."),
    "specs_used": ["40 ml", "niacinamid"]}, ensure_ascii=False)


class MockClient:
    def extract(self, system, user):
        return _json.dumps({"cinjenice": [
            {"polje": "namjena", "vrijednost": "", "izvor": "",
             "status": "NOT FOUND"}]}, ensure_ascii=False)

    model_id = "mock-opus"
    verify_model_id = "mock-opus"

    def generate(self, system, user):
        return GOOD_PDP if "KOSTUR" in user else SEO_JSON

    def verify(self, system, user):
        return json.dumps({"prolazi": True, "nepotkrijepljene_tvrdnje": [],
                           "napomena": ""}, ensure_ascii=False)


client = MockClient()
lock = threading.Lock()
seo_res = S.process_product(PROD, page, client, set(), set(), lock, 2)
pdp_res, md = P.process_product(PROD, "cosmetics", sources, client, 2, True)
check("SEO prošao kroz objedinjeni klijent", seo_res.status.startswith("OK"),
      f"({seo_res.status})")
check("PDP prošao kroz objedinjeni klijent", pdp_res.status.startswith("OK"),
      f"({pdp_res.status})")

# --- spojeni redak ---
rec = A.combined_record(PROD, seo_res, pdp_res, client.model_id, page.fetched)
check("redak: ulazni stupci", all(rec.get(c) for c in A.INPUT_COLS))
check("redak: SEO stupci prefiksirani",
      rec["SEO Title tag"].startswith("La Roche-Posay") and
      isinstance(rec["SEO Title px"], float))
check("redak: PDP stupci prefiksirani",
      rec["PDP Kategorija predloška"] == "kozmetika" and
      rec["PDP Verifikacija (2. agent)"] == "prolazi")
check("redak: ukupni status OK", rec["Ukupni status"] == "OK")
check("redak: nema sudara imena stupaca (Status)",
      "Status" not in rec and "Pokušaji" not in rec and "Napomene" not in rec)

# jedan alat pao -> ukupni status TREBA PROVJERA
pdp_res.status = "TREBA PROVJERA"
rec_bad = A.combined_record(PROD, seo_res, pdp_res, client.model_id, True)
check("redak: jedan pao -> ukupni TREBA PROVJERA",
      rec_bad["Ukupni status"] == "TREBA PROVJERA")
pdp_res.status = "OK"

# samo SEO / samo PDP
rec_seo = A.combined_record(PROD, seo_res, None, "m", True)
rec_pdp = A.combined_record(PROD, None, pdp_res, "m", True)
check("--only seo: nema PDP stupaca", not any(k.startswith("PDP ") for k in rec_seo))
check("--only pdp: nema SEO stupaca", not any(k.startswith("SEO ") for k in rec_pdp))
check("--only seo: status iz SEO-a", rec_seo["Ukupni status"] == "OK")

# --- indeks ---
xlsx, csv = A.write_index([rec, rec_bad], OUT)
check("indeks zapisan", xlsx.exists() and csv.exists())
import pandas as pd
df = pd.read_excel(xlsx)
need = ["SEO Title tag", "SEO Meta px", "PDP MD datoteka", "Ukupni status",
        "Stranica dohvaćena"]
check("indeks: svi ključni stupci prisutni",
      all(c in df.columns for c in need),
      f"({len(df.columns)} stupaca)")

# --- resume ---
jl = OUT / "results.jsonl"
jl.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
done = A.load_done(jl)
check("resume: redak učitan po SKU", done.get("TST1", {}).get("Ukupni status") == "OK")

shutil.rmtree(OUT, ignore_errors=True)

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
