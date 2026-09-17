# Provedba klijentovih uputa nakon testiranja

Sve niže navedeno ugrađeno je kao **default u kodu** (promptovi + deterministički
validatori), ne kao opcionalna napomena. Datoteke u `prompts/` ostaju za buduće
sitne dopune i dodaju se povrh ovih pravila.

## A. Title tag i meta opis (eljekarna24_title_meta_uputa.docx)

| Klijentovo pravilo | Gdje je provedeno |
| --- | --- |
| Separator `\|` (U+007C), nikad `│` (U+2502) | `BRAND_SUFFIX` |
| Nastavak `\| eljekarna24` samo ako stane u 550 px | `finalize_title()` |
| Količina se NIKAD ne uklanja pri skraćivanju | `trim_title_to_px(keep_qty=…)` — skraćuje sredinu, čuva rep s količinom; validator odbija title bez količine |
| Bez zareza ispred količine | `COMMA_BEFORE_QTY_RE` |
| Jedinica punom riječju (100 tableta, ne 100 tab) | `UNIT_ABBREV_RE` |
| Razmak između broja i jedinice (75 ml) | `NO_SPACE_UNIT_RE` |
| Title počinje **generiranim** nazivom iz PDP-a | `canonical_name` — runner vadi naziv iz PDP-a i prosljeđuje ga SEO-u |
| Namjena u meti je OBVEZNA | `PURPOSE_RE`; ako se ne može potvrditi → `namjena_potvrdjena=false` → **TREBA PROVJERA**, namjena se ne izmišlja |
| Bez superlativa (idealan, idealno…) | prošireni `FORBIDDEN_PATTERNS` |
| Jedinstven title i meta po URL-u | provjera duplikata kroz cijeli skup |
| Izvor 1 = eljekarna24 (obvezan) | bez stranice → status **GREŠKA** |
| Izvor 2 = službena stranica brenda, svaki podatak označen | `BrandSource`; stupci *Izvor – brend*, *Preuzeto s brend stranice*, *Napomena za provjeru*; redak ide u TREBA PROVJERA |
| Nikad treći izvori (forumi, konkurenti, tražilice) | `brand_source_for()` prihvaća samo domenu brenda |

Novi stupci: **Namjena**, **Izvor – eljekarna24**, **Izvor – brend**,
**Preuzeto s brend stranice**, **Napomena za provjeru**.

## B. PDP opisi (eljekarna24_PDP_opisi_uputa_nakon_testiranja.docx)

Novi tok: `SOURCE → STRUKTURIRANA EKSTRAKCIJA → PISAC → KONTROLA FORMATA →
FACT-CHECK → COVERAGE CHECK`.

- **Ekstrakcija prije pisanja** (`pdp_extract.py`): zaseban poziv modelu gradi
  inventar činjenica — vrijednost + izvor + status (FOUND / NOT FOUND /
  DERIVED / CONFLICT), po kategorijskim popisima polja iz upute.
- **Hard fields** (doza, puni sastav/INCI, aktivne tvari i koncentracije, način
  uporabe, upozorenja, identifikatori, specifikacije, dobna faza) ne smiju
  nestati ni biti skraćeni; pisac ih dobiva označene u promptu.
- **Coverage check** nakon pisanja uspoređuje inventar s finalnim PDP-om i
  vraća pisca na dopunu ako je podatak izgubljen ili zamijenjen placeholderom.
- **Puni INCI/sastav** prenosi se doslovno kada je pronađen (uvodi se s „INCI:“
  / „Sastav:“); propisani placeholder samo kada podatak stvarno ne postoji.
- **Konflikt izvora** se ne spaja i ne rješava samovoljno → status
  **CONFLICT / REVIEW**.

Novi statusi: **NEDOSTAJE PODATAK IZ IZVORA**, **CONFLICT / REVIEW**,
**GREŠKA EKSTRAKCIJE** (uz OK i TREBA PROVJERA).
Novi stupci: **Ekstrahiranih polja**, **Coverage check**, **Konflikt izvora**.

Web pretraga za PDP ostaje (klijent je izričito ne ukida) — za SEO ostaje samo
eljekarna24 + službeni brend.

Nove zastavice: `--no-extract`, `--no-coverage` (za dijagnostiku; u normalnom
radu se ne koriste).

## C. Hijerarhija izvora (naknadna uputa)

| Prioritet | Izvor | Kako se koristi |
| --- | --- | --- |
| **1** | Stranica proizvoda s linka iz ulazne tablice | Uvijek prvo. Kad podatak postoji ondje, koristi se ta vrijednost. |
| **2** | `webljekarna.vasezdravlje.com` (zadani sekundarni izvor) | Samo za podatke kojih nema na prioritetu 1. Traži se `site:` pretragom po brendu i nazivu. |
| **3** | Ostali web izvori (službena stranica brenda i dr.) | Tek kad podatka nema ni na 1 ni na 2. |

Prioritet određuje **koja se vrijednost koristi**, ali ako izvori daju različitu
konkretnu vrijednost, konflikt se i dalje označava (**CONFLICT / REVIEW**) i ne
rješava se samovoljnim odabirom ili spajanjem.

Za SEO (title/meta) vrijedi ista hijerarhija, ali se koriste samo prioriteti
1–2 te službena stranica brenda; forumi, konkurentski webshopovi i tražilice
ne. Korišteni sekundarni izvor upisuje se u stupce *Izvor – brend* /
*Preuzeto s brend stranice*, a redak dobiva *Napomena za provjeru*.

Isključivanje: `--no-secondary`.

## D. Definitivni izrazi

Zabranjeni u oba alata (prompt + deterministička kontrola) osim ako su doslovno
potvrđeni u izvorima uz metodu ili mjerenje: *najbolji, najučinkovitiji,
najsigurniji, najnježniji, najpopularniji, najprodavaniji, jedini, nema premca,
zlatni standard, prvi izbor, apsolutno, uvijek djeluje, svima odgovara, bez
iznimke, trenutni rezultati, bez ikakvih nuspojava, potpuno bezopasan,
idealan/idealno, savršen, vrhunski*, plus opći uzorak `naj…iji`.

Iznimke: obvezne zakonske rečenice (npr. „Dojenje je najbolji način prehrane
dojenčeta.“) i mjerni izrazi (*najviše, najmanje, najkasnije, najranije*).
