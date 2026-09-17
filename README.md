# Liberiq Descriptioner

Generator SEO title/meta tagova i PDP opisa proizvoda za **eljekarna24**, na
Claude modelima preko **AWS Bedrocka**.

Za svaki proizvod iz ulazne tablice alat prikupi izvore, generira sadržaj prema
klijentovim pravilima, automatski ga provjeri (format, činjenice, potpunost) i
isporuči **jednu Excel tablicu + PDP opise u MD i DOCX formatu**.

---

## Sadržaj

- [Brzi početak](#brzi-početak)
- [Pokretanje](#pokretanje)
- [Izlaz](#izlaz)
- [Kako radi](#kako-radi)
- [Podešavanje promptova](#podešavanje-promptova)
- [Struktura projekta](#struktura-projekta)
- [Testovi](#testovi)
- [Rješavanje problema](#rješavanje-problema)

---

## Brzi početak

Potreban je Python 3.10+.

```bash
git clone https://github.com/<organizacija>/Liberiq-descriptioner.git
cd Liberiq-descriptioner

python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env        # upiši AWS ključeve i model ID
```

Ili, ako je `make` dostupan:

```bash
make setup      # venv + ovisnosti + .env iz predloška
make test       # offline testovi, bez trošenja tokena
make dry-run    # prikaz izvora i promptova za prvi proizvod
make sample     # pravi run na 2 proizvoda
```

### `.env`

```ini
BEDROCK_AWS_ACCESS_KEY_ID=
BEDROCK_AWS_SECRET_ACCESS_KEY=
BEDROCK_AWS_REGION=eu-central-1
BEDROCK_TEXT_MODEL_ID=eu.anthropic.claude-opus-4-1-20250805-v1:0
# neobavezno: drugi (jeftiniji) model za kontrolora činjenica
# BEDROCK_VERIFY_MODEL_ID=
```

Točan model ID za svoj račun i regiju provjeri s:

```bash
aws bedrock list-inference-profiles --region eu-central-1
```

### Ulazna tablica

XLSX ili CSV. Obavezni su stupci **Naziv** i **URL**; korisni su i **Sekcija**
(određuje PDP predložak), **Brend** i **SKU**.

| Sekcija | Brend | SKU | Naziv | URL |
| --- | --- | --- | --- | --- |
| Kozmetika | Avène | C002167 | AVENE SUN KREMA SPF50 50 ML | https://eljekarna24.hr/... |

---

## Pokretanje

```bash
# 1. proba bez trošenja tokena — pokaže izvore i promptove
python generate_all.py -i proizvodi.xlsx --dry-run

# 2. test na dva proizvoda
python generate_all.py -i proizvodi.xlsx --limit 2

# 3. cijeli set
python generate_all.py -i proizvodi.xlsx
```

Run se može prekinuti i nastaviti — svaki obrađeni proizvod odmah se zapisuje u
`out_all/results.jsonl`, pa ponovno pokretanje preskače gotove.

### Opcije

| Opcija | Značenje |
| --- | --- |
| `-i, --input` | ulazna tablica (XLSX ili CSV) |
| `-o, --output` | izlazna mapa (zadano `out_all`) |
| `--only seo\|pdp\|both` | što generirati (zadano oboje) |
| `--limit N` | samo prvih N proizvoda |
| `--sku C002167` | samo taj SKU (može više puta) |
| `--retry-review` | ponovno generiraj samo retke koji nisu OK |
| `--force` | ignoriraj postojeće rezultate i kreni ispočetka |
| `--max-attempts 3` | broj krugova ispravaka po proizvodu |
| `--search-results 3` | broj web izvora prioriteta 3 |
| `--no-secondary` | bez zadanog sekundarnog izvora |
| `--no-web-search` | samo stranica proizvoda |
| `--no-fetch` | bez dohvaćanja išta (samo naziv iz tablice) |
| `--no-verify` | preskoči kontrolora činjenica |
| `--no-extract` / `--no-coverage` | preskoči ekstrakciju / coverage check |
| `--refresh-cache` | ponovno dohvati izvore |
| `--prompts-dir prompts` | mapa s vanjskim promptovima |
| `--show-prompts` | ispiši konačne promptove i izađi |
| `--dry-run` | bez Bedrocka: izvori + promptovi |

---

## Izlaz

```
out_all/
├── sadrzaj_indeks.xlsx        ← jedna tablica sa svime
├── sadrzaj_indeks.csv
├── pdp/
│   ├── PDP_C002167_avene-sun-krema-spf50-50-ml.md
│   ├── PDP_C002167_avene-sun-krema-spf50-50-ml.docx
│   └── ...
├── results.jsonl              ← nastavak prekinutog rada
└── .cache/html/               ← dohvaćene stranice
```

**`sadrzaj_indeks.xlsx`** — jedan redak po proizvodu: ulazni stupci, pa `SEO …`
(title, meta, pikseli, namjena, status, izvori, QA usporedba sa starim tagovima)
i `PDP …` (kategorija, status, verifikacija, coverage, konflikti, putanje
datoteka), plus zbirni **Ukupni status**.

### Statusi

| Status | Značenje |
| --- | --- |
| `OK` | prošlo sve kontrole |
| `OK (skraćeno)` | SEO prošao nakon determinističkog skraćivanja |
| `TREBA PROVJERA` | nešto nije prošlo ni nakon svih pokušaja |
| `NEDOSTAJE PODATAK IZ IZVORA` | coverage check našao izgubljen podatak |
| `CONFLICT / REVIEW` | izvori daju različite vrijednosti |
| `GREŠKA EKSTRAKCIJE` | nije moguće pouzdano izvući strukturirana polja |
| `GREŠKA` | nema stranice proizvoda (SEO zahtijeva izvor 1) |

Retke koji nisu OK regeneriraj s `--retry-review`.

---

## Kako radi

```
ULAZNA TABLICA
     │
     ├─ izvori (jedan dohvat, dijeljen između oba alata)
     │    prioritet 1: stranica proizvoda s linka
     │    prioritet 2: webljekarna.vasezdravlje.com
     │    prioritet 3: ostali web izvori
     │
     ├─ PDP:  ekstrakcija → pisac → kontrola formata → fact-check → coverage check
     │            └── iz PDP-a izlazi kanonski naziv proizvoda
     │
     └─ SEO:  generiranje → pikselska i sadržajna kontrola → ispravci
                  (title mora počinjati kanonskim nazivom iz PDP-a)
```

Detaljna pravila i gdje su provedena: **[README_KLIJENT_PRAVILA.md](README_KLIJENT_PRAVILA.md)**.
Objedinjeni runner: **[README_OBJEDINJENO.md](README_OBJEDINJENO.md)**.

---

## Podešavanje promptova

Promptovi se uređuju bez diranja koda:

```bash
python prompts_cfg.py --init        # stvori mapu prompts/
python generate_all.py -i proizvodi.xlsx --show-prompts
```

Napomene klijenta idu u `prompts/seo_napomene.md`, `prompts/pdp_napomene.md` i
po kategoriji (`pdp_napomene_cosmetics.md` itd.) — dodaju se na kraj ugrađenog
prompta. Potpuna zamjena prompta ide kroz `seo_system.md` / `pdp_system.md`.
Upute: **[README_PROMPTOVI.md](README_PROMPTOVI.md)**.

---

## Struktura projekta

| Datoteka | Uloga |
| --- | --- |
| `generate_all.py` | objedinjeni runner (SEO + PDP, jedan izlaz) |
| `seo_meta_generator.py` | title i meta: generiranje, pikselsko mjerenje, validacija |
| `pdp_generator.py` | PDP: izvori, pisac, kontrola formata, fact-check |
| `pdp_extract.py` | strukturirana ekstrakcija i coverage check |
| `pdp_templates.py` | predlošci i primjeri po kategorijama |
| `prompts_cfg.py` | vanjski promptovi i napomene |
| `test_*.py` | offline testovi (bez Bedrocka) |

Oba generatora rade i samostalno (`python seo_meta_generator.py -i …`,
`python pdp_generator.py -i …`) ako treba popraviti samo jedan dio.

---

## Testovi

```bash
make test          # ili: python test_klijent.py && python test_all.py && python test_prompts.py
```

Testovi ne zovu Bedrock ni mrežu — koriste mock klijente, pa su besplatni i
brzi. Pokrivaju klijentova pravila, hijerarhiju izvora, coverage check,
pikselsko mjerenje, skraćivanje koje čuva količinu i MD→DOCX konverziju.

---

## Rješavanje problema

| Poruka / simptom | Uzrok i rješenje |
| --- | --- |
| `Nedostaje u .env: …` | nepotpun `.env` |
| `[ValidationException]` | pogrešan model ID — provjeri `aws bedrock list-inference-profiles` |
| `[AccessDeniedException]` | IAM nema `bedrock:InvokeModel` ili model nije odobren u Bedrock konzoli |
| `[ThrottlingException]` | rate limit; alat sam ponavlja, a prekinuti run nastavlja gdje je stao |
| Puno `TREBA PROVJERA` | pogledaj stupce *Napomene* i *Coverage check*; često znači da stranica proizvoda nema dovoljno sadržaja |
| `Stranica dohvaćena = ne` | URL nedostupan ili blokiran; `--refresh-cache` za ponovni pokušaj |
| DOCX se ne stvara | `pip install python-docx` |
