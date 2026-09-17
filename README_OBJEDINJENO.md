# Objedinjeni generator — SEO + PDP u jednom prolazu

`generate_all.py` pokreće oba alata nad istom ulaznom tablicom, u jednom prolazu.

```bash
pip install -r requirements_pdp.txt
cp .env.example .env

python generate_all.py -i eljekarna24_proizvodi_75_kom.xlsx --dry-run   # proba
python generate_all.py -i eljekarna24_proizvodi_75_kom.xlsx --limit 2   # test
python generate_all.py -i eljekarna24_proizvodi_75_kom.xlsx             # sve
```

## Što se dobiva spajanjem

- **Stranica proizvoda dohvaća se jednom** i dijeli između oba alata
  (zajednički HTML cache) — prije su je dohvaćala oba zasebno.
- **Jedan Bedrock klijent** i jedan `.env` za sve pozive.
- **Jedan indeks**: `out_all/sadrzaj_indeks.xlsx` / `.csv` sa svim stupcima —
  ulazni stupci, pa `SEO …` (title, meta, pikseli, status, napomene, QA
  usporedba) i `PDP …` (kategorija, status, verifikacija, izvori, putanje
  datoteka), plus zbirni stupac **Ukupni status** (OK samo ako su oba OK).
- **Jedan resume**: `out_all/results.jsonl` — prekinuti run nastavlja gdje je
  stao za oba alata istovremeno.
- PDP datoteke ostaju po proizvodu: `out_all/pdp/PDP_<SKU>_<naziv>.md` i `.docx`.

## Opcije

`--only seo|pdp|both` (zadano both) · `--limit N` · `--sku <SKU>` (više puta) ·
`--force` · `--retry-review` · `--max-attempts 3` · `--search-results 3` ·
`--no-web-search` · `--no-fetch` · `--no-verify` · `--refresh-cache` ·
`--dry-run` · `-o <mapa>`

Logika nije duplicirana: `generate_all.py` je samo orkestracija i koristi
`seo_meta_generator.py`, `pdp_generator.py` i `pdp_templates.py`, koji i dalje
rade i samostalno.
