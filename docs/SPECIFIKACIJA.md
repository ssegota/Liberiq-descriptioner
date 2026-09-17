# Liberiq Descriptioner — specifikacija softvera

**Verzija 1.0 · 17.09.2026.**

Sustav za automatsko generiranje SEO title i meta tagova te PDP opisa proizvoda za webshop eljekarna24, na Claude modelima preko AWS Bedrocka.

---

## 1. Uvod

### 1.1. Svrha dokumenta

Ovaj dokument opisuje rad softvera **Liberiq Descriptioner** — sustava za automatsko generiranje SEO title i meta tagova te PDP opisa proizvoda za webshop eljekarna24. Namijenjen je razvojnom timu, uredničkom timu koji provjerava izlaz prije objave te naručitelju kao opis isporučenog rješenja.

### 1.2. Opseg

Sustav pokriva cjelokupan put od ulazne tablice proizvoda do gotovog, provjerenog sadržaja spremnog za uredničku provjeru i objavu. Ne pokriva objavu na webshop, upravljanje PIM sustavom niti prijevode (prijevodi su predviđeni kao zasebna faza).

### 1.3. Ključna svojstva

- **Dvostruka kontrola**: sve što model napiše provjerava se determinističkim validatorom (pravila, pikseli, struktura) i drugim modelom (činjenice).
- **Nema izmišljanja**: svaki broj s jedinicom, identifikator i specifikacija mora postojati u izvorima; što se ne može potvrditi, ne objavljuje se.
- **Nema gubitka podataka**: coverage check hvata podatke koji su postojali u izvorima, ali nisu završili u finalnom opisu.
- **Prekid i nastavak**: svaki obrađeni proizvod odmah se zapisuje, pa se prekinuti posao nastavlja bez ponovnog trošenja tokena.
- **Podesivi promptovi**: pravila i napomene uređuju se kao tekstualne datoteke, bez diranja koda.

### 1.4. Pojmovnik

| Pojam | Značenje |
| --- | --- |
| PDP | Product Detail Page — stranica proizvoda; ovdje označava strukturirani opis proizvoda s tabovima. |
| Title tag / meta opis | Naslov i opis stranice koje tražilica prikazuje u rezultatima pretrage. |
| Inventar činjenica | Strukturirani popis podataka izvučenih iz izvora prije pisanja teksta. |
| Hard field | Podatak koji ne smije nestati iz opisa: doza, puni sastav, koncentracije, upozorenja, identifikatori. |
| Coverage check | Provjera je li podatak koji postoji u izvorima završio u gotovom opisu. |
| Kanonski naziv | Naziv proizvoda generiran u PDP-u; obvezni početak title taga. |
| Krug ispravaka | Ponovni poziv modelu s popisom prekršenih pravila. |

## 2. Arhitektura i tok rada

### 2.1. Pregled

Sustav se sastoji od objedinjenog runnera i dvaju generatora koji dijele prikupljene izvore i isti Bedrock klijent. PDP generator izvršava se prvi jer iz njega proizlazi kanonski naziv proizvoda koji SEO generator koristi kao obvezni početak title taga.

![Slika 1. Pregled toka: od ulazne tablice do isporučenog sadržaja.](diagrams/tok_pregled.png)

*Slika 1. Pregled toka: od ulazne tablice do isporučenog sadržaja.*

PDP generator izvršava se prvi jer iz njega proizlazi kanonski naziv proizvoda koji SEO generator koristi kao obvezni početak title taga. Oba generatora dijele isti dohvat izvora i isti Bedrock klijent.

### 2.2. Moduli

| Modul | Odgovornost |
| --- | --- |
| generate_all.py | Objedinjeni runner: redoslijed izvršavanja, dijeljenje izvora, zbirni indeks, resume, CLI. |
| seo_meta_generator.py | Title i meta: prompt, pikselsko mjerenje, validacija pravila, skraćivanje, krugovi ispravaka. |
| pdp_generator.py | PDP: prikupljanje izvora, prompt pisca, kontrola formata, kontrolor činjenica, MD→DOCX. |
| pdp_extract.py | Strukturirana ekstrakcija činjenica prije pisanja i coverage check nakon pisanja. |
| pdp_templates.py | Predlošci i referentni primjeri po kategorijama, obvezne fraze, fiksni blokovi. |
| prompts_cfg.py | Vanjski promptovi i napomene (override i dopune). |

### 2.3. Model i izvršavanje

Pozivi idu na Claude modele preko AWS Bedrock Converse API-ja. Model za generiranje i model za kontrolu činjenica mogu biti različiti (`BEDROCK_TEXT_MODEL_ID` i `BEDROCK_VERIFY_MODEL_ID`). Obrada je sekvencijalna radi kontrole rate limita; na throttling se čeka s eksponencijalnim odmakom, a prekinuti posao nastavlja se iz zapisa.

### 2.4. Slijed poziva

![Slika 6. Redoslijed poziva prema izvorima i modelima za jedan proizvod.](diagrams/pozivi.png)

*Slika 6. Redoslijed poziva prema izvorima i modelima za jedan proizvod.*

Po proizvodu se izvodi najmanje četiri poziva modelu (ekstrakcija, pisanje PDP-a, provjera činjenica, generiranje title i meta taga), a svaki neuspjeli krug dodaje jedan poziv pisca uz ponovljenu kontrolu.

## 3. Ulaz

### 3.1. Ulazna tablica

XLSX ili CSV. Nazivi stupaca prepoznaju se i u varijantama (brand → Brend, šifra → SKU, link → URL). Vrijednosti se čitaju kao tekst, pa brendovi poput „NAN“ ostaju sačuvani.

| Stupac | Obavezan | Opis i uloga u obradi |
| --- | --- | --- |
| Sekcija | ne | Kategorija iz webshopa. Određuje PDP predložak: Kozmetika → kozmetika; Vitamini, minerali i kolageni te Beta glukani → dodatak prehrani; Mliječne formule → mliječna formula; Cijeli webshop → uređaj. Ako je prazna, kategorija se pogađa iz naziva. |
| Brend | ne | Marka proizvoda. Provjerava se da naziv i title počinju brendom; ulazi u upite pretrage i rangiranje izvora. |
| SKU | ne | Interna šifra. Ključ za nastavak rada, filtriranje i nazive izlaznih datoteka. Ako nedostaje, koristi se URL. |
| Naziv | **da** | Naziv iz baze, često velikim slovima. Referenca za normalizaciju, količinu i ključne riječi. |
| URL | **da** | Stranica proizvoda — izvor prioriteta 1. Bez nje SEO redak dobiva status GREŠKA. |

### 3.2. Hijerarhija izvora

| Prioritet | Izvor | Pravilo korištenja |
| --- | --- | --- |
| 1 | Stranica proizvoda s linka iz tablice | Uvijek prvo. Kad podatak postoji ondje, koristi se ta vrijednost. |
| 2 | webljekarna.vasezdravlje.com | Zadani sekundarni izvor; traži se site: pretragom po brendu i nazivu. Samo za podatke kojih nema na prioritetu 1. |
| 3 | Ostali web izvori | Službena stranica brenda i drugi izvori; tek kad podatka nema na 1 ni 2. Za SEO se koristi isključivo službena stranica brenda — forumi, konkurentski webshopovi i tražilice ne. |

![Slika 2. Hijerarhija izvora i postupanje s konfliktom.](diagrams/hijerarhija_izvora.png)

*Slika 2. Hijerarhija izvora i postupanje s konfliktom.*

> **Prioritet i konflikt**  
> Prioritet određuje koja se vrijednost koristi. Ako izvori daju različitu konkretnu vrijednost, konflikt se svejedno vidljivo označava statusom CONFLICT / REVIEW i ne rješava se samovoljnim odabirom ni spajanjem.

### 3.3. Ekstrakcija sadržaja stranice

Sa stranice proizvoda čitaju se: JSON-LD (schema.org Product), og:description, standardni blokovi opisa i tablica atributa. Redci s cijenom, zalihom i dostavom uklanjaju se prije slanja modelu. Dohvaćeni HTML kešira se po URL-u, pa ponovni prolaz ne opterećuje izvore.

### 3.4. Konfiguracija

| Varijabla | Opis |
| --- | --- |
| `BEDROCK_AWS_ACCESS_KEY_ID` | AWS pristupni ključ |
| `BEDROCK_AWS_SECRET_ACCESS_KEY` | AWS tajni ključ |
| `BEDROCK_AWS_REGION` | regija, npr. eu-central-1 |
| `BEDROCK_TEXT_MODEL_ID` | model za generiranje (inference profil) |
| `BEDROCK_VERIFY_MODEL_ID` | neobavezno: model za kontrolora činjenica |

## 4. Obrada: SEO title i meta

### 4.1. Mjerenje duljine

Duljina se mjeri u pikselima, ne u znakovima: title u Arialu 20 px (limit **550 px**), meta opis u Arialu 14 px (limit **960 px**). Mjerenje koristi ugrađenu tablicu širina glifova, uz podršku za dijakritike. Broj znakova prikazuje se samo kao pomoćni podatak.

### 4.2. Pravila title taga

- Počinje **kanonskim nazivom** proizvoda iz PDP-a, ne starim nazivom s weba.
- Nastavak ` | eljekarna24` (znak U+007C) dodaje se samo ako ukupno stane u 550 px; inače se izostavlja.
- Količina se piše na kraju, **bez zareza** ispred.
- Jedinica se piše punom riječju: „100 tableta“, ne „100 tab“.
- Između broja i jedinice ide razmak: „75 ml“.
- Pri skraćivanju uklanjaju se CTA, opći pridjevi i sporedne značajke; naziv, tip proizvoda, **količina** i glavna namjena nikada.
- Bez riječi pisanih velikim slovima (osim brenda i standardnih kratica), bez akcija, cijena, dostave i definitivnih izraza.
- Jedinstven po URL-u; kod istog proizvoda u dva pakiranja razlikuje ga količina.

### 4.3. Pravila meta opisa

- Struktura: naziv + **namjena** + jedna do dvije provjerljive specifikacije.
- Namjena je obvezna. Ako se ne može potvrditi iz izvora, ne izmišlja se — redak dobiva status TREBA PROVJERA.
- Najviše 960 px; završava potpunom rečenicom, bez poziva na akciju.
- Bez cijene, zalihe i dostave (ti se podaci iskazuju kroz schemu).
- Jedinstven i vezan uz sadržaj točno te stranice.

### 4.4. Zabranjeni izrazi

Deterministički se odbijaju promotivne poruke, cijene, dostava, pozivi na akciju te definitivni i apsolutni izrazi koji nisu specifično dokazani u izvorima: *najbolji, najučinkovitiji, najsigurniji, jedini, zlatni standard, prvi izbor, apsolutno, uvijek djeluje, svima odgovara, bez iznimke, idealan, savršen, vrhunski* i slično, uključujući opći uzorak „naj…iji“. Iznimke su obvezne zakonske rečenice (primjerice „Dojenje je najbolji način prehrane dojenčeta.“) i mjerni izrazi (*najviše, najmanje, najkasnije*).

### 4.5. Tok ispravaka

![Slika 4. Tok generiranja i kontrole title taga i meta opisa.](diagrams/seo_tok.png)

*Slika 4. Tok generiranja i kontrole title taga i meta opisa.*

Model vraća JSON s title tagom, meta opisom, korištenim specifikacijama, namjenom i oznakom je li namjena potvrđena. Validator vraća popis prekršenih pravila, koji se šalje natrag modelu na ispravak (zadano do tri kruga). Ako preostane samo problem duljine, primjenjuje se determinističko skraćivanje koje čuva količinu: prvo se skraćuje s kraja, a ako bi time ispala količina, skraćuje se sredina i rep s količinom ostaje.

### 4.6. Primjer

|  | Prije | Poslije |
| --- | --- | --- |
| Title | Solgar Vitamin K1 100 mcg, 100 tab │ eljekarna24 | Solgar Vitamin K1 100 mcg 100 tableta | eljekarna24 |
| Što je ispravljeno | zarez ispred količine, kratica jedinice, pogrešan znak separatora | 467 px, unutar limita 550 px |
| Meta | Solgar Vitamin K1 100 mcg dodatak je prehrani. Pakiranje sadrži 100 tableta. | Solgar Vitamin K1 100 mcg za odrasle, 100 tableta. Vitamin K doprinosi normalnom zgrušavanju krvi. |
| Što je ispravljeno | nema namjene, količina tek u zadnjoj rečenici | naziv, namjena i količina u prvoj rečenici |

## 5. Obrada: PDP opisi

### 5.1. Tok

![Slika 3. Tok PDP generatora: ekstrakcija, pisanje i tri kontrole.](diagrams/pdp_tok.png)

*Slika 3. Tok PDP generatora: ekstrakcija, pisanje i tri kontrole.*

Pisac ne bira podatke i ne piše tekst istodobno. Prvo se gradi inventar činjenica, zatim se piše dokument, pa se provjerava i točnost i potpunost.

1. **Strukturirana ekstrakcija** — zaseban poziv modelu gradi inventar: polje, vrijednost doslovno iz izvora, oznaka izvora i status (FOUND, NOT FOUND, DERIVED, CONFLICT).
2. **Pisac** — dobiva inventar s označenim hard fieldovima i piše PDP prema predlošku kategorije.
3. **Kontrola formata** — deterministička provjera strukture, naslova, obveznih fraza i zabranjenih izraza.
4. **Kontrolor činjenica** — drugi model provjerava je li svaka tvrdnja potkrijepljena izvorima i vraća popis nepotkrijepljenih.
5. **Coverage check** — usporedba inventara s gotovim dokumentom: je li išta pronađeno izgubljeno ili zamijenjeno placeholderom.

### 5.2. Hard fields

Podaci koji ne smiju nestati ni biti skraćeni: doza i način uporabe, puni sastav odnosno INCI, aktivne tvari i koncentracije, upozorenja, identifikatori (EAN, UPC, SKU), tehničke specifikacije i dobna faza. Puni sastav prenosi se doslovno i u cijelosti; propisani placeholder koristi se isključivo kada podatak stvarno nije pronađen.

### 5.3. Struktura dokumenta

- **Prvi ekran** — naziv proizvoda (brend + naziv + glavna karakteristika + količina), kratki opis u jednoj rečenici, brza traka s 3–4 ključne prednosti.
- **Istaknuti blok** — tablica prilagođena kategoriji.
- **Šest tabova** — nazivi točno prema kategoriji; Tab 1 ima 80–150 riječi, Tab 5 nosi tablicu podataka, Tab 6 je fiksni savjet ljekarnika.
- **Kliničke studije** — samo kozmetika i samo uz potvrđene rezultate s metodom mjerenja.
- **Ocjene i recenzije** — fiksni blok; recenzije dolaze iz sustava.
- **FAQ** — 3 do 5 pitanja utemeljenih na izvorima.

### 5.4. Tabovi po kategoriji

| Kategorija | Tabovi 1–5 (Tab 6 je uvijek „Savjet ljekarnika“) |
| --- | --- |
| kozmetika | Opis i prednosti · Je li za moju kožu? · Kako se koristi? · Sastojci · Podatci i upozorenja |
| dodatak prehrani | Opis i prednosti · Doza i kome je namijenjen · Kako se uzima? · Sastojci i sastav · Upozorenja i podatci |
| uređaj | Opis i prednosti · Upute za korištenje? · Funkcije i specifikacije · Validacija i dokumentacija · Podaci i upute |
| mliječna formula | Opis i ključne informacije · Priprema i hranjenje · Sastav, alergeni i nutritivne vrijednosti · Čuvanje i sigurnost · Pakiranje i proizvođač |

### 5.5. Obvezne rečenice po kategoriji

Dodaci prehrani moraju sadržavati napomenu da dodatak nije zamjena za uravnoteženu prehranu i upozorenje o nepremašivanju preporučene dnevne doze. Mliječne formule moraju sadržavati rečenicu „Dojenje je najbolji način prehrane dojenčeta.“ i upućivanje na tablicu hranjenja s deklaracije. Uređaji moraju upućivati na hrvatsku uputu za uporabu i navesti da uređaj ne postavlja dijagnozu.

### 5.6. Inventar činjenica

Inventar je međukorak koji se ne objavljuje, ali određuje sve što slijedi. Za svako polje bilježi se vrijednost doslovno iz izvora, oznaka izvora i status.

| Status | Značenje | Posljedica |
| --- | --- | --- |
| FOUND | Podatak je pronađen u izvorima. | Mora završiti u opisu; ako je hard field, ne smije biti skraćen. |
| NOT FOUND | Podatka nema ni u jednom izvoru. | Koristi se propisani placeholder ili se izostavlja. |
| DERIVED | Izračunato iz potvrđenih polja. | Dopušteno uz oslonac na potvrđene vrijednosti. |
| CONFLICT | Izvori daju različitu konkretnu vrijednost. | Označava se za provjeru; vrijednosti se ne spajaju. |

## 6. Izlaz

### 6.1. Struktura izlazne mape

```
out_all/
├── sadrzaj_indeks.xlsx        jedna tablica sa svim rezultatima
├── sadrzaj_indeks.csv         isti sadržaj u CSV-u
├── pdp/
│   ├── PDP_<SKU>_<naziv>.md   PDP opis u Markdownu
│   └── PDP_<SKU>_<naziv>.docx isti opis u Word formatu
├── results.jsonl              zapis za nastavak prekinutog rada
└── .cache/html/               keširane dohvaćene stranice
```

### 6.2. Stupci zbirne tablice

Jedan redak po proizvodu. Ulazni stupci prenose se nepromijenjeni radi sparivanja, SEO stupci nose prefiks „SEO“, PDP stupci prefiks „PDP“.

| Stupac | Sadržaj |
| --- | --- |
| Sekcija · Brend · SKU · Naziv · URL | Prijepis ulazne tablice. |
| Stranica dohvaćena | Je li izvor prioriteta 1 uspješno pročitan. |
| SEO Title tag | Konačni title s nastavkom webshopa ako stane u limit. |
| SEO Title px · SEO Title znakova | Izmjerena širina (Arial 20 px) i broj znakova. |
| SEO Meta opis | Konačni meta opis. |
| SEO Meta px · SEO Meta znakova | Izmjerena širina (Arial 14 px) i broj znakova. |
| SEO Namjena | Namjena proizvoda kako je potvrđena u izvorima. |
| SEO Status · SEO Pokušaji | Ishod i broj krugova generiranja. |
| SEO Napomene | Preostale greške i bilješke. |
| SEO Korištene specifikacije | Doslovne fraze iz izvora — revizijski trag. |
| SEO Izvor – eljekarna24 | URL izvora prioriteta 1. |
| SEO Izvor – brend | URL sekundarnog izvora ako je korišten. |
| SEO Preuzeto s brend stranice | Koji su točno podaci preuzeti izvan prioriteta 1. |
| SEO Napomena za provjeru | Oznaka obvezne ljudske provjere za takav redak. |
| SEO Postojeći title / meta (QA) | Zatečene vrijednosti sa stranice za usporedbu staro/novo. |
| PDP Kategorija predloška | Primijenjeni predložak. |
| PDP Status · PDP Pokušaji | Ishod i broj krugova. |
| PDP Verifikacija (2. agent) | Presuda kontrolora činjenica. |
| PDP Nepotkrijepljene tvrdnje | Tvrdnje bez potpore u izvorima. |
| PDP Ekstrahiranih polja | Broj potvrđenih polja u inventaru. |
| PDP Coverage check | „prolazi“ ili popis izgubljenih podataka. |
| PDP Konflikt izvora | Polja s različitim vrijednostima među izvorima. |
| PDP Broj izvora · PDP Izvori | Koliko je izvora korišteno i njihovi URL-ovi. |
| PDP MD datoteka · PDP DOCX datoteka | Putanje do generiranih opisa. |
| PDP Napomene | Ostale bilješke. |
| Ukupni status | Zbirni ishod; OK samo ako su oba alata prošla. |
| Model | Model koji je generirao redak. |

### 6.3. Statusi

| Status | Značenje | Postupak |
| --- | --- | --- |
| OK | Struktura, činjenice i potpunost prolaze. | Spremno za uredničku provjeru. |
| OK (skraćeno) | SEO prošao nakon determinističkog skraćivanja. | Provjeriti je li skraćeni title i dalje jasan. |
| TREBA PROVJERA | Pravilo nije zadovoljeno ni nakon svih krugova. | Vidjeti stupac Napomene. |
| NEDOSTAJE PODATAK IZ IZVORA | Coverage check našao izgubljen podatak. | Dopuniti ili pokrenuti ponovno. |
| CONFLICT / REVIEW | Izvori daju različite konkretne vrijednosti. | Ručno odlučiti koja je točna. |
| GREŠKA EKSTRAKCIJE | Nije moguće pouzdano izvući strukturirana polja. | Provjeriti dostupnost i sadržaj izvora. |
| GREŠKA | Nema stranice proizvoda (izvor prioriteta 1). | Ispraviti URL u ulaznoj tablici. |

![Slika 5. Kako se određuje status pojedinog proizvoda.](diagrams/statusi.png)

*Slika 5. Kako se određuje status pojedinog proizvoda.*

> **Što znači OK**  
> Status OK znači da je struktura ispravna, da su napisane tvrdnje potkrijepljene izvorima, da relevantni podaci iz izvora nisu izgubljeni i da nema neriješenog konflikta. OK nije zamjena za uredničku provjeru prije objave, nego preduvjet za nju.

## 7. Rad sa sustavom

### 7.1. Naredbe

```
python generate_all.py -i proizvodi.xlsx --dry-run    # izvori i promptovi, bez tokena
python generate_all.py -i proizvodi.xlsx --limit 2    # test na dva proizvoda
python generate_all.py -i proizvodi.xlsx              # puni posao
python generate_all.py -i proizvodi.xlsx --retry-review   # samo retci koji nisu OK
```

### 7.2. Odabir opsega

| Opcija | Učinak |
| --- | --- |
| --only seo | pdp | both | Koji dio sadržaja generirati. |
| --limit N · --sku | Ograničenje na dio asortimana. |
| --max-attempts | Broj krugova ispravaka po proizvodu. |
| --search-results · --no-secondary · --no-web-search | Opseg izvora. |
| --no-verify · --no-extract · --no-coverage | Isključivanje pojedinih kontrola (dijagnostika). |
| --refresh-cache · --force | Ponovno dohvaćanje izvora, odnosno ponovna obrada. |
| --prompts-dir · --show-prompts | Vanjski promptovi i njihov ispis. |

### 7.3. Podešavanje promptova

Napomene se dodaju na kraj ugrađenih promptova i uređuju kao datoteke: `seo_napomene.md`, `pdp_napomene.md` te po kategoriji (`pdp_napomene_cosmetics.md` i slično) i `verify_napomene.md`. Potpuna zamjena prompta moguća je kroz `seo_system.md`, `pdp_system.md` i `verify_system.md`, uz podržane placeholdere. Mapa se stvara naredbom `python prompts_cfg.py --init`.

> **Pravila i validator idu zajedno**  
> Ton, formulacije i zabranjene riječi rade odmah preko napomena. Ako izmjena dira tvrda pravila (pikselske limite, nazive tabova, obvezne rečenice, broj FAQ pitanja), treba uskladiti i deterministički validator — inače model piše jedno, a kontrola traži drugo.

### 7.4. Tipični scenariji

| Situacija | Postupak |
| --- | --- |
| Prvi put na novom asortimanu | `--dry-run` za provjeru izvora, pa `--limit 2`, pa puni posao. |
| Posao je prekinut | Ponovno pokretanje iste naredbe; obrađeni proizvodi se preskaču. |
| Klijent je promijenio pravilo teksta | Dopuniti datoteku s napomenama, provjeriti s `--show-prompts`, pa `--retry-review`. |
| Puno redaka „TREBA PROVJERA“ | Pogledati stupce Napomene i Coverage check; obično znači siromašnu stranicu proizvoda. |
| Pojedini proizvod treba ponoviti | `--sku <SKU> --force`. |
| Izvori su se promijenili | `--refresh-cache` za ponovno dohvaćanje. |

## 8. Nefunkcionalna svojstva

### 8.1. Pouzdanost

- Svaki proizvod zapisuje se odmah po obradi; prekinuti posao nastavlja se bez gubitka i bez ponovnog trošenja tokena.
- Na throttling i privremene greške poziva čeka se s eksponencijalnim odmakom.
- Nedostupan izvor ne ruši obradu: redak se označava i nastavlja se dalje.
- Dohvaćene stranice keširaju se, pa ponovni prolaz ne opterećuje izvore.

### 8.2. Testiranje

Offline testovi pokrivaju klijentova pravila, hijerarhiju izvora, coverage check, pikselsko mjerenje, skraćivanje koje čuva količinu, vanjske promptove i pretvorbu u DOCX. Testovi koriste mock klijente, ne zovu Bedrock ni mrežu i ne stvaraju trošak.

### 8.3. Trošak i kapacitet

Trošak je izravno razmjeran broju poziva modelu, a on ovisi o broju krugova ispravaka. Najveći dio troška otpada na PDP dio, i to na ulazne tokene (kostur, primjer kategorije i izvori). Praktične poluge za smanjenje: manji model za kontrolora činjenica, manji broj web izvora po proizvodu i grupna obrada za poslove bez vremenskog pritiska. Procjene za konkretan opseg isporučene su u zasebnim dokumentima.

### 8.6. Sigurnost podataka

- Pristupni podaci drže se u `.env` koji se ne unosi u repozitorij.
- Sustav ne šalje podatke nikamo osim na Bedrock i na javno dostupne izvore koje sam dohvaća.
- Izlaz ne sadrži cijene, zalihe ni druge podatke koji se mijenjaju u sustavu.

### 8.4. Mjerila kvalitete

Izlaz se ocjenjuje s četiri mjerila, redom po važnosti: **točnost** (nijedna tvrdnja bez potpore u izvorima), **potpunost** (nijedan pronađen podatak nije izgubljen), **usklađenost s pravilima** (pikseli, struktura, zabranjeni izrazi) i **čitljivost**. Sustav prva tri mjerila provjerava automatski; četvrto ostaje na uredničkoj provjeri.

### 8.5. Ograničenja

- Kvaliteta izlaza ovisi o sadržaju izvora: siromašna stranica proizvoda daje siromašniji opis i više redaka za provjeru.
- Pikselsko mjerenje je približak stvarnog prikaza u tražilici; prikaz može ovisiti o upitu i uređaju.
- Retci označeni statusom različitim od OK zahtijevaju ljudsku odluku i ne objavljuju se automatski.
- Prijevodi nisu dio ovog opsega.

## 9. Dodaci

### 9.1. Popis automatskih provjera

| Područje | Provjera |
| --- | --- |
| Title | Širina u pikselima · početak kanonskim nazivom · prisutnost količine · zarez ispred količine · kratice jedinica · razmak broj–jedinica · velika slova · jedinstvenost |
| Meta opis | Širina u pikselima · prisutnost naziva · obvezna namjena · potpuna zadnja rečenica · jedinstvenost |
| Oba | Zabranjeni izrazi (cijene, dostava, CTA, superlativi, definitivne tvrdnje) · brojevi s jedinicom potvrđeni u izvorima |
| PDP struktura | Naslov i redoslijed sekcija · šest tabova s točnim nazivima · brza traka i 3–4 prednosti · duljina Tab 1 · obvezni redci Tab 5 · fiksni blokovi · 3–5 FAQ pitanja |
| PDP sadržaj | Obvezne rečenice kategorije · EAN potvrđen u izvorima · brojevi s jedinicom potvrđeni · ograde u tekstu |
| PDP potpunost | Coverage check hard fieldova · placeholder umjesto postojeće vrijednosti · označenost konflikta |

### 9.2. Struktura repozitorija

```
Liberiq-descriptioner/
├── generate_all.py          objedinjeni runner
├── seo_meta_generator.py    title i meta
├── pdp_generator.py         PDP opisi
├── pdp_extract.py           ekstrakcija i coverage check
├── pdp_templates.py         predlošci po kategorijama
├── prompts_cfg.py           vanjski promptovi
├── test_*.py                offline testovi
├── requirements.txt         ovisnosti
├── Makefile                 česte naredbe
├── .env.example             predložak konfiguracije
└── README.md                upute za pokretanje
```

### 9.3. Povezani dokumenti

| Dokument | Sadržaj |
| --- | --- |
| README.md | Upute za instalaciju, pokretanje i rješavanje problema. |
| README_KLIJENT_PRAVILA.md | Popis klijentovih pravila i mjesto provedbe u kodu. |
| README_PROMPTOVI.md | Uređivanje promptova i napomena. |
| README_OBJEDINJENO.md | Objedinjeni runner i zajednički izlaz. |
