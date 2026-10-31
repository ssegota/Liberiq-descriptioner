# Liberiq Descriptioner

Generator SEO title/meta tagova i PDP opisa proizvoda za **eljekarna24**, na
Claude modelima preko **AWS Bedrocka**, prema klijentovim **PDP templateima
ver.11** (11 templateova A–K) i checklistama za dodatke prehrani, biljne dodatke
i dječju hranu. Pravila i što je gdje provedeno:
**[README_KLIJENT_PRAVILA.md](README_KLIJENT_PRAVILA.md)** (odjeljak Verzija 4).

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
| `--search-results 3` | broj usporednih izvora (Vaše zdravlje, Prima Pharme…) |
| `--pim-dir mapa` | HR ambalaža / deklaracija / PIM po proizvodu (SKU ili EAN u nazivu datoteke) |
| `--workers 4` | koliko proizvoda se obrađuje istodobno |
| `--rescue-model …` | model za dodatne pokušaje kad pisac ne prođe kontrolu (zadano Opus 5.5; `""` isključuje) |
| `--rescue-attempts 2` | broj dodatnih pokušaja tim modelom |
| `--batch auto\|on\|off` | Bedrock batch, pola cijene; `auto` = za 100+ proizvoda kad je postavljen ([docs/BATCH_SETUP.md](docs/BATCH_SETUP.md)) |
| `--effort-extract low` | razmišljanje za klasifikaciju i ekstrakciju (`low`/`medium`/`high`/`off`) |
| `--effort-generate medium` | razmišljanje za pisanje opisa i SEO |
| `--effort-verify medium` | razmišljanje za stručnu provjeru |
| `--no-secondary` | bez stranice brenda i usporednih izvora |
| `--no-web-search` | samo stranica proizvoda |
| `--no-fetch` | bez dohvaćanja išta (samo naziv iz tablice) |
| `--no-verify` | preskoči stručnu provjeru (drugi agent) |
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
| `OK` | prošlo sve kontrole i stručnu provjeru, bez crvenih oznaka |
| `OK, PROVJERITI CRVENO` | prošlo sve; crveno označene podatke provjeriti na ambalaži prije objave |
| `ZAUSTAVLJENO` | zabranjena biljna vrsta (NN 160/2013, Prilog III.) |
| `GREŠKA EKSTRAKCIJE` | nije moguće pouzdano izvući strukturirana polja |
| `GREŠKA` | nema stranice proizvoda na eLjekarni24 |

Status „TREBA PROVJERA” je ukinut (31. 10. 2026.): isporučuje se najbolja verzija
nakon svih pokušaja (osnovni model + `--rescue-model`), a preostale napomene kontrole
ostaju samo u `results.jsonl`. Retke s greškom ponovi s `--retry-review`.

---

## Kako radi

```
ULAZNA TABLICA
     │
     ├─ izvori (jedan dohvat, dijeljen između oba alata)
     │    razina 1: HR ambalaža / deklaracija / PIM (--pim-dir)
     │    razina 2: eLjekarna24 + službena stranica brenda
     │    razina 3: Vaše zdravlje, Prima Pharme (+ Notino, MAKEUP, Douglas za kozmetiku)
     │
     ├─ PDP:  klasifikacija (template A–K, podvrsta) → ekstrakcija (isti proizvod?)
     │        → regulativa u kodu (tvrdnje 432/2012, % PU, NN 160/2013, obrazac prve
     │          rečenice prema EAN-u) → pisac (pravila + template + checklista)
     │        → automatska kontrola → coverage → stručna provjera (drugi agent)
     │            └── iz PDP-a izlazi kanonski naziv proizvoda
     │
     └─ SEO:  generiranje → pikselska i sadržajna kontrola → ispravci
                  (title počinje kanonskim nazivom; title i meta upisuju se u PDP)
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
| `pdp_generator.py` | PDP: izvori, klasifikacija, pisac, automatska kontrola, stručna provjera, DOCX |
| `pdp_extract.py` | strukturirana ekstrakcija, klasifikacija i coverage check |
| `pdp_templates.py` | metapodaci templateova A–K (tabovi, tablica podataka, FAQ, tvrdnje) |
| `regulativa.py` | tvrdnje 432/2012, % PU, najveće doze, Prilozi II. i III. NN 160/2013, obrazac prve rečenice |
| `predlosci/` | klijentovi dokumenti ver.11 (doslovno u promptu) i odobreni primjeri |
| `regulativa/` | dokument tvrdnji (JSON) i prilozi Pravilnika NN 160/2013 |
| `alati/uvezi_predloske.py` | uvoz nove verzije klijentovih dokumenata |
| `prompts_cfg.py` | vanjski promptovi i napomene |
| `test_*.py` | offline testovi (bez Bedrocka) |

Oba generatora rade i samostalno (`python seo_meta_generator.py -i …`,
`python pdp_generator.py -i …`) ako treba popraviti samo jedan dio.

---

## Testovi

```bash
make test          # test_v4, test_upute, test_klijent, test_all, test_prompts
```

Testovi ne zovu Bedrock ni mrežu — koriste mock klijente, pa su besplatni i
brzi. Pokrivaju klijentova pravila, hijerarhiju izvora, coverage check,
pikselsko mjerenje, skraćivanje koje čuva količinu i MD→DOCX konverziju, a
`test_v4.py` pravila templatea ver.11: tvrdnje i uvjete, % PU, najveće doze,
odabir templatea, obrasce prve rečenice, validator na odobrenim primjerima i
scraping eLjekarne24.

---

## Rješavanje problema

| Poruka / simptom | Uzrok i rješenje |
| --- | --- |
| `Nedostaje u .env: …` | nepotpun `.env` |
| `[ValidationException]` | pogrešan model ID — provjeri `aws bedrock list-inference-profiles` |
| `[AccessDeniedException]` | IAM nema `bedrock:InvokeModel` ili model nije odobren u Bedrock konzoli |
| `[ThrottlingException]` | rate limit; alat sam ponavlja, a prekinuti run nastavlja gdje je stao |
| `Stranica dohvaćena = ne` | URL nedostupan ili blokiran; `--refresh-cache` za ponovni pokušaj |
| DOCX se ne stvara | `pip install python-docx` |
