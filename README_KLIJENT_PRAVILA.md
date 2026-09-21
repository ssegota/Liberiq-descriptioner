# Provedba klijentovih pravila

Izvori: *Pravila meta opis i title tag eljekarna24*, *PDP struktura* s četiri
predloška, *Audit title, meta opis i PDP* i *Upute za generator* (21. 9. 2026.).
Sve je ugrađeno kao default u kodu; datoteke u `prompts/` služe za dopune.

## Z. Zajednička pravila

| Pravilo | Provedba |
| --- | --- |
| **Z1 Hijerarhija izvora** | `pravila.py`: allowlist domena. Izvor 1 je stranica proizvoda na eljekarna24, izvor 2 je službena hrvatska stranica brenda. Sve ostalo (druge ljekarne, tražilice, marketplace, strana tržišta) odbacuje se prije slanja modelu. Provjera je u kodu, ne u promptu. |
| **Z2 Spremno za copy/paste** | `nadi_interne_napomene()` odbija `[S1]`, „KONFLIKT“, „potvrditi“, „provjeriti“, „Prije lokalne objave“, „prema dostupnoj dokumentaciji“ i spominjanje drugih trgovina. Model te podatke vraća u završnom JSON-u, koji se odvaja od dokumenta i ide u internu datoteku. |
| **Z3 Bez uspoređivanja šifri** | Šifre drugih trgovina nisu izvor, pa lažni konflikti SKU-a više ne nastaju. |
| **Z4 Bez crtica** | `ukloni_crtice()` mijenja – i — zarezom ili točkom, radi po retcima pa struktura ostaje. Rasponi brojeva (22–42 cm, 6–12 mjeseci) i crtice u nazivima ostaju. |

## Title tag

- Gradi se iz generiranog PDP naziva, samo riječi iz njega, istim redoslijedom
  (validator odbija riječi kojih ondje nema).
- Uvijek ostaju brend, linija, tip, varijanta (nijansa, SPF, Riche, jakost) i
  količina s jedinicom (`obavezni_pojmovi()`).
- Skraćivanje ide po cijelim segmentima (`skrati_po_segmentima()`): prvo namjena
  iza crtice ili zareza, zatim opći pridjevi, zatim sporedne značajke. Fraza se
  nikad ne reže na pola.
- Ne završava prijedlogom, veznikom, znakom ni brojem bez jedinice.
- Bez zareza ispred količine, razmak između broja i jedinice, bez crtica.
- Nastavak ` | eljekarna24` (U+007C) dodaje kod, samo ako sve stane u 550 px.

## Meta opis

- Prva rečenica: naziv bez količine, namjena, količina. Druga rečenica: jedna
  ili dvije specifikacije iz dopuštenih izvora.
- Namjena unutar prvih 100 znakova, obvezna.
- Količina samo jednom; „Pakiranje od“, „Volumen“, „Dostupno u“ se odbijaju.
- Mora sadržavati brend iz titla; količina mora biti ista u PDP nazivu, titlu i
  meta opisu.
- Najviše 960 px, bez CTA-a, cijene, zalihe, dostave i crtica.
- Tvrdnje po kategoriji: dodaci prehrani samo odobrene tvrdnje doslovno iz
  izvora; hrana za dojenčad samo namjena i dob; medicinski proizvodi samo
  tvrdnje iz upute; kozmetika doslovno iz izvora.

## PDP

- **Brzi podaci:** šest popunjenih polja (tip proizvoda, namjena, ciljana
  skupina, područje primjene, tekstura/oblik, pakiranje). Uputa iz predloška
  nikad ne ostaje u izlazu; validator hvata prazna polja.
- **Sastojci:** točno 3 ili 4 istaknuta, zatim puni sastav ili INCI doslovno.
  Nutritivna tablica ide zasebno.
- **Obvezni podaci:** EAN, proizvođač i pakiranje. Ako ih nema, ostaje tekst iz
  predloška, a status je TREBA PROVJERA.
- **Kliničke studije:** svaki redak mora imati rezultat, vrijeme, broj
  ispitanika, metodu i izvor, inače se izostavlja cijeli blok.
- **Zabranjene formulacije:** „klinički dokazano“, „testirano“, „dermatološki
  testirano“ bez objašnjenja što je i kako testirano.
- **Hrana za dojenčad:** obvezna rečenica „Dojenje je najbolji način prehrane
  dojenčeta.“; početna hrana bez prehrambenih i zdravstvenih tvrdnji.
- **Naziv:** Brend + naziv + glavna karakteristika + količina na kraju, bez
  crtice, bez znaka |, bez namjene u nazivu.

## Statusi

| Status | Kada |
| --- | --- |
| OK | Validator nema nijednu napomenu. |
| TREBA PROVJERA | Nakon 3 pokušaja i dalje ima napomena, nedostaje obvezan podatak (EAN, proizvođač, puni sastav) ili je korišten izvor 2. |
| GREŠKA | Stranica eljekarna24 nije dohvaćena. Ne generira se ni SEO ni PDP. |

Statusi „OK (skraćeno)“ i „CONFLICT / REVIEW“ su ukinuti.

## Izlazne datoteke

- `title_meta_za_klijenta.xlsx` (+ .csv): Sekcija, Brend, SKU, Naziv, URL,
  Title tag, Title (px), Meta opis, Meta opis (px). Bez internih stupaca.
- `interno.xlsx` (+ .csv): Status, Izvor – eljekarna24, Izvor – brend, Preuzeto
  s brend stranice, Nedostaje, Konflikti, Napomena validatora, PDP status,
  putanja PDP datoteke, trajanje, model.
- `pdp/PDP_<SKU>_<naziv>.docx` i `.md`: jedan dokument po proizvodu, čist za
  copy/paste.
- `sadrzaj_indeks.xlsx`: puni tehnički indeks (ostaje za dijagnostiku).

## Održavanje allowliste

Domene po brendu su u `pravila.py`, rječnik `BREND_DOMENE`. Dodavanje novog
brenda je jedan redak. Rječnik zapisa brendova i linija je `RJECNIK_ZAPISA`.

## Otvorena pitanja za klijenta

Zarez ispred količine u PDP nazivu, zapis naziva linija (RC 01, UreaRepair,
UVMUNE), tvrdnje za prijelaznu formulu i mlijeko za malu djecu, izvor EAN-a i
proizvođača (PIM ili stranica eljekarna24).
