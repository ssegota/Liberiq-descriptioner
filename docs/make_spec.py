#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Specifikacija Liberiq Descriptionera — jedan izvor sadržaja, dva izlaza
(Markdown + dizajnirani PDF). Stil inspiriran liberiq.com."""

from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)
from PIL import Image as PILImage
from pathlib import Path

DIAG = Path(__file__).resolve().parent / "diagrams"

VERZIJA = "1.0"
DATUM = f"{date.today():%d.%m.%Y.}"

# ---------------------------------------------------------------------------
# Paleta (liberiq.com: meke organske forme, plum + rose na toploj bijeloj)
# ---------------------------------------------------------------------------
INK = colors.HexColor("#0A0A0A")        # crna tipografija s naslovnice
PLUM = colors.HexColor("#0A0A0A")        # zaglavlja tablica: crna
PLUM_DARK = colors.HexColor("#0A0A0A")
ROSE = colors.HexColor("#FF5C39")        # koral — akcent
AMBER = colors.HexColor("#FFB020")
YELLOW = colors.HexColor("#FFD54A")
ORANGE = colors.HexColor("#FF7A1A")
PINK = colors.HexColor("#FF6F91")
ROSE_SOFT = colors.HexColor("#FFF1EA")   # topla podloga za napomene
LILAC_SOFT = colors.HexColor("#FDF7F0")  # izmjenični redci
CREAM = colors.HexColor("#FDF8F2")
MUTED = colors.HexColor("#6B6B6B")
BORDER = colors.HexColor("#E6E6E6")

# ---------------------------------------------------------------------------
# SADRŽAJ — blokovi: h1 h2 h3 p bullets numbers table code note kv
# ---------------------------------------------------------------------------

C = [
("h1", "1. Uvod"),
("h2", "1.1. Svrha dokumenta"),
("p", "Ovaj dokument opisuje rad softvera **Liberiq Descriptioner** — sustava za "
      "automatsko generiranje SEO title i meta tagova te PDP opisa proizvoda za "
      "webshop eljekarna24. Namijenjen je razvojnom timu, uredničkom timu koji "
      "provjerava izlaz prije objave te naručitelju kao opis isporučenog rješenja."),
("h2", "1.2. Opseg"),
("p", "Sustav pokriva cjelokupan put od ulazne tablice proizvoda do gotovog, "
      "provjerenog sadržaja spremnog za uredničku provjeru i objavu. Ne pokriva "
      "objavu na webshop, upravljanje PIM sustavom niti prijevode (prijevodi su "
      "predviđeni kao zasebna faza)."),
("h2", "1.3. Ključna svojstva"),
("bullets", [
    "**Dvostruka kontrola**: sve što model napiše provjerava se determinističkim "
    "validatorom (pravila, pikseli, struktura) i drugim modelom (činjenice).",
    "**Nema izmišljanja**: svaki broj s jedinicom, identifikator i specifikacija "
    "mora postojati u izvorima; što se ne može potvrditi, ne objavljuje se.",
    "**Nema gubitka podataka**: coverage check hvata podatke koji su postojali u "
    "izvorima, ali nisu završili u finalnom opisu.",
    "**Prekid i nastavak**: svaki obrađeni proizvod odmah se zapisuje, pa se "
    "prekinuti posao nastavlja bez ponovnog trošenja tokena.",
    "**Podesivi promptovi**: pravila i napomene uređuju se kao tekstualne "
    "datoteke, bez diranja koda.",
]),

("h2", "1.4. Pojmovnik"),
("table", ["Pojam", "Značenje"], [
    ["PDP", "Product Detail Page — stranica proizvoda; ovdje označava strukturirani "
     "opis proizvoda s tabovima."],
    ["Title tag / meta opis", "Naslov i opis stranice koje tražilica prikazuje u "
     "rezultatima pretrage."],
    ["Inventar činjenica", "Strukturirani popis podataka izvučenih iz izvora prije "
     "pisanja teksta."],
    ["Hard field", "Podatak koji ne smije nestati iz opisa: doza, puni sastav, "
     "koncentracije, upozorenja, identifikatori."],
    ["Coverage check", "Provjera je li podatak koji postoji u izvorima završio u "
     "gotovom opisu."],
    ["Kanonski naziv", "Naziv proizvoda generiran u PDP-u; obvezni početak title taga."],
    ["Krug ispravaka", "Ponovni poziv modelu s popisom prekršenih pravila."],
], [40, 124]),

("h1", "2. Arhitektura i tok rada"),
("h2", "2.1. Pregled"),
("p", "Sustav se sastoji od objedinjenog runnera i dvaju generatora koji dijele "
      "prikupljene izvore i isti Bedrock klijent. PDP generator izvršava se prvi "
      "jer iz njega proizlazi kanonski naziv proizvoda koji SEO generator koristi "
      "kao obvezni početak title taga."),
("figure", "tok_pregled", "Slika 1. Pregled toka: od ulazne tablice do isporučenog sadržaja."),
("p", "PDP generator izvršava se prvi jer iz njega proizlazi kanonski naziv "
      "proizvoda koji SEO generator koristi kao obvezni početak title taga. Oba "
      "generatora dijele isti dohvat izvora i isti Bedrock klijent."),
("h2", "2.2. Moduli"),
("table", ["Modul", "Odgovornost"], [
    ["generate_all.py", "Objedinjeni runner: redoslijed izvršavanja, dijeljenje "
     "izvora, zbirni indeks, resume, CLI."],
    ["seo_meta_generator.py", "Title i meta: prompt, pikselsko mjerenje, "
     "validacija pravila, skraćivanje, krugovi ispravaka."],
    ["pdp_generator.py", "PDP: prikupljanje izvora, prompt pisca, kontrola "
     "formata, kontrolor činjenica, MD→DOCX."],
    ["pdp_extract.py", "Strukturirana ekstrakcija činjenica prije pisanja i "
     "coverage check nakon pisanja."],
    ["pdp_templates.py", "Predlošci i referentni primjeri po kategorijama, "
     "obvezne fraze, fiksni blokovi."],
    ["prompts_cfg.py", "Vanjski promptovi i napomene (override i dopune)."],
], [46, 118]),
("h2", "2.3. Model i izvršavanje"),
("p", "Pozivi idu na Claude modele preko AWS Bedrock Converse API-ja. Model za "
      "generiranje i model za kontrolu činjenica mogu biti različiti "
      "(`BEDROCK_TEXT_MODEL_ID` i `BEDROCK_VERIFY_MODEL_ID`). Obrada je "
      "sekvencijalna radi kontrole rate limita; na throttling se čeka s "
      "eksponencijalnim odmakom, a prekinuti posao nastavlja se iz zapisa."),

("h2", "2.4. Slijed poziva"),
("figure", "pozivi", "Slika 6. Redoslijed poziva prema izvorima i modelima za jedan proizvod."),
("p", "Po proizvodu se izvodi najmanje četiri poziva modelu (ekstrakcija, pisanje "
      "PDP-a, provjera činjenica, generiranje title i meta taga), a svaki neuspjeli "
      "krug dodaje jedan poziv pisca uz ponovljenu kontrolu."),

("h1", "3. Ulaz"),
("h2", "3.1. Ulazna tablica"),
("p", "XLSX ili CSV. Nazivi stupaca prepoznaju se i u varijantama (brand → Brend, "
      "šifra → SKU, link → URL). Vrijednosti se čitaju kao tekst, pa brendovi "
      "poput „NAN“ ostaju sačuvani."),
("table", ["Stupac", "Obavezan", "Opis i uloga u obradi"], [
    ["Sekcija", "ne", "Kategorija iz webshopa. Određuje PDP predložak: Kozmetika → "
     "kozmetika; Vitamini, minerali i kolageni te Beta glukani → dodatak prehrani; "
     "Mliječne formule → mliječna formula; Cijeli webshop → uređaj. Ako je prazna, "
     "kategorija se pogađa iz naziva."],
    ["Brend", "ne", "Marka proizvoda. Provjerava se da naziv i title počinju "
     "brendom; ulazi u upite pretrage i rangiranje izvora."],
    ["SKU", "ne", "Interna šifra. Ključ za nastavak rada, filtriranje i nazive "
     "izlaznih datoteka. Ako nedostaje, koristi se URL."],
    ["Naziv", "**da**", "Naziv iz baze, često velikim slovima. Referenca za "
     "normalizaciju, količinu i ključne riječi."],
    ["URL", "**da**", "Stranica proizvoda — izvor prioriteta 1. Bez nje SEO redak "
     "dobiva status GREŠKA."],
], [26, 24, 114]),
("h2", "3.2. Hijerarhija izvora"),
("table", ["Prioritet", "Izvor", "Pravilo korištenja"], [
    ["1", "Stranica proizvoda s linka iz tablice", "Uvijek prvo. Kad podatak "
     "postoji ondje, koristi se ta vrijednost."],
    ["2", "webljekarna.vasezdravlje.com", "Zadani sekundarni izvor; traži se "
     "site: pretragom po brendu i nazivu. Samo za podatke kojih nema na "
     "prioritetu 1."],
    ["3", "Ostali web izvori", "Službena stranica brenda i drugi izvori; tek kad "
     "podatka nema na 1 ni 2. Za SEO se koristi isključivo službena stranica "
     "brenda — forumi, konkurentski webshopovi i tražilice ne."],
], [24, 52, 88]),
("figure", "hijerarhija_izvora", "Slika 2. Hijerarhija izvora i postupanje s konfliktom."),
("note", "Prioritet i konflikt",
 "Prioritet određuje koja se vrijednost koristi. Ako izvori daju različitu "
 "konkretnu vrijednost, konflikt se svejedno vidljivo označava statusom "
 "CONFLICT / REVIEW i ne rješava se samovoljnim odabirom ni spajanjem."),
("h2", "3.3. Ekstrakcija sadržaja stranice"),
("p", "Sa stranice proizvoda čitaju se: JSON-LD (schema.org Product), "
      "og:description, standardni blokovi opisa i tablica atributa. Redci s "
      "cijenom, zalihom i dostavom uklanjaju se prije slanja modelu. Dohvaćeni "
      "HTML kešira se po URL-u, pa ponovni prolaz ne opterećuje izvore."),
("h2", "3.4. Konfiguracija"),
("kv", [
    ["BEDROCK_AWS_ACCESS_KEY_ID", "AWS pristupni ključ"],
    ["BEDROCK_AWS_SECRET_ACCESS_KEY", "AWS tajni ključ"],
    ["BEDROCK_AWS_REGION", "regija, npr. eu-central-1"],
    ["BEDROCK_TEXT_MODEL_ID", "model za generiranje (inference profil)"],
    ["BEDROCK_VERIFY_MODEL_ID", "neobavezno: model za kontrolora činjenica"],
]),

("h1", "4. Obrada: SEO title i meta"),
("h2", "4.1. Mjerenje duljine"),
("p", "Duljina se mjeri u pikselima, ne u znakovima: title u Arialu 20 px "
      "(limit **550 px**), meta opis u Arialu 14 px (limit **960 px**). Mjerenje "
      "koristi ugrađenu tablicu širina glifova, uz podršku za dijakritike. Broj "
      "znakova prikazuje se samo kao pomoćni podatak."),
("h2", "4.2. Pravila title taga"),
("bullets", [
    "Počinje **kanonskim nazivom** proizvoda iz PDP-a, ne starim nazivom s weba.",
    "Nastavak ` | eljekarna24` (znak U+007C) dodaje se samo ako ukupno stane u "
    "550 px; inače se izostavlja.",
    "Količina se piše na kraju, **bez zareza** ispred.",
    "Jedinica se piše punom riječju: „100 tableta“, ne „100 tab“.",
    "Između broja i jedinice ide razmak: „75 ml“.",
    "Pri skraćivanju uklanjaju se CTA, opći pridjevi i sporedne značajke; naziv, "
    "tip proizvoda, **količina** i glavna namjena nikada.",
    "Bez riječi pisanih velikim slovima (osim brenda i standardnih kratica), bez "
    "akcija, cijena, dostave i definitivnih izraza.",
    "Jedinstven po URL-u; kod istog proizvoda u dva pakiranja razlikuje ga količina.",
]),
("h2", "4.3. Pravila meta opisa"),
("bullets", [
    "Struktura: naziv + **namjena** + jedna do dvije provjerljive specifikacije.",
    "Namjena je obvezna. Ako se ne može potvrditi iz izvora, ne izmišlja se — "
    "redak dobiva status TREBA PROVJERA.",
    "Najviše 960 px; završava potpunom rečenicom, bez poziva na akciju.",
    "Bez cijene, zalihe i dostave (ti se podaci iskazuju kroz schemu).",
    "Jedinstven i vezan uz sadržaj točno te stranice.",
]),
("h2", "4.4. Zabranjeni izrazi"),
("p", "Deterministički se odbijaju promotivne poruke, cijene, dostava, pozivi na "
      "akciju te definitivni i apsolutni izrazi koji nisu specifično dokazani u "
      "izvorima: *najbolji, najučinkovitiji, najsigurniji, jedini, zlatni "
      "standard, prvi izbor, apsolutno, uvijek djeluje, svima odgovara, bez "
      "iznimke, idealan, savršen, vrhunski* i slično, uključujući opći uzorak "
      "„naj…iji“. Iznimke su obvezne zakonske rečenice (primjerice „Dojenje je "
      "najbolji način prehrane dojenčeta.“) i mjerni izrazi (*najviše, najmanje, "
      "najkasnije*)."),
("h2", "4.5. Tok ispravaka"),
("figure", "seo_tok", "Slika 4. Tok generiranja i kontrole title taga i meta opisa."),
("p", "Model vraća JSON s title tagom, meta opisom, korištenim specifikacijama, "
      "namjenom i oznakom je li namjena potvrđena. Validator vraća popis "
      "prekršenih pravila, koji se šalje natrag modelu na ispravak (zadano do tri "
      "kruga). Ako preostane samo problem duljine, primjenjuje se determinističko "
      "skraćivanje koje čuva količinu: prvo se skraćuje s kraja, a ako bi time "
      "ispala količina, skraćuje se sredina i rep s količinom ostaje."),

("h2", "4.6. Primjer"),
("table", ["", "Prije", "Poslije"], [
    ["Title", "Solgar Vitamin K1 100 mcg, 100 tab │ eljekarna24", 
     "Solgar Vitamin K1 100 mcg 100 tableta | eljekarna24"],
    ["Što je ispravljeno", "zarez ispred količine, kratica jedinice, pogrešan "
     "znak separatora", "467 px, unutar limita 550 px"],
    ["Meta", "Solgar Vitamin K1 100 mcg dodatak je prehrani. Pakiranje sadrži "
     "100 tableta.", "Solgar Vitamin K1 100 mcg za odrasle, 100 tableta. Vitamin K "
     "doprinosi normalnom zgrušavanju krvi."],
    ["Što je ispravljeno", "nema namjene, količina tek u zadnjoj rečenici",
     "naziv, namjena i količina u prvoj rečenici"],
], [30, 62, 72]),

("h1", "5. Obrada: PDP opisi"),
("h2", "5.1. Tok"),
("figure", "pdp_tok", "Slika 3. Tok PDP generatora: ekstrakcija, pisanje i tri kontrole."),
("p", "Pisac ne bira podatke i ne piše tekst istodobno. Prvo se gradi inventar "
      "činjenica, zatim se piše dokument, pa se provjerava i točnost i potpunost."),
("numbers", [
    "**Strukturirana ekstrakcija** — zaseban poziv modelu gradi inventar: polje, "
    "vrijednost doslovno iz izvora, oznaka izvora i status (FOUND, NOT FOUND, "
    "DERIVED, CONFLICT).",
    "**Pisac** — dobiva inventar s označenim hard fieldovima i piše PDP prema "
    "predlošku kategorije.",
    "**Kontrola formata** — deterministička provjera strukture, naslova, "
    "obveznih fraza i zabranjenih izraza.",
    "**Kontrolor činjenica** — drugi model provjerava je li svaka tvrdnja "
    "potkrijepljena izvorima i vraća popis nepotkrijepljenih.",
    "**Coverage check** — usporedba inventara s gotovim dokumentom: je li išta "
    "pronađeno izgubljeno ili zamijenjeno placeholderom.",
]),
("h2", "5.2. Hard fields"),
("p", "Podaci koji ne smiju nestati ni biti skraćeni: doza i način uporabe, puni "
      "sastav odnosno INCI, aktivne tvari i koncentracije, upozorenja, "
      "identifikatori (EAN, UPC, SKU), tehničke specifikacije i dobna faza. Puni "
      "sastav prenosi se doslovno i u cijelosti; propisani placeholder koristi se "
      "isključivo kada podatak stvarno nije pronađen."),
("h2", "5.3. Struktura dokumenta"),
("bullets", [
    "**Prvi ekran** — naziv proizvoda (brend + naziv + glavna karakteristika + "
    "količina), kratki opis u jednoj rečenici, brza traka s 3–4 ključne prednosti.",
    "**Istaknuti blok** — tablica prilagođena kategoriji.",
    "**Šest tabova** — nazivi točno prema kategoriji; Tab 1 ima 80–150 riječi, "
    "Tab 5 nosi tablicu podataka, Tab 6 je fiksni savjet ljekarnika.",
    "**Kliničke studije** — samo kozmetika i samo uz potvrđene rezultate s "
    "metodom mjerenja.",
    "**Ocjene i recenzije** — fiksni blok; recenzije dolaze iz sustava.",
    "**FAQ** — 3 do 5 pitanja utemeljenih na izvorima.",
]),
("h2", "5.4. Tabovi po kategoriji"),
("table", ["Kategorija", "Tabovi 1–5 (Tab 6 je uvijek „Savjet ljekarnika“)"], [
    ["kozmetika", "Opis i prednosti · Je li za moju kožu? · Kako se koristi? · "
     "Sastojci · Podatci i upozorenja"],
    ["dodatak prehrani", "Opis i prednosti · Doza i kome je namijenjen · Kako se "
     "uzima? · Sastojci i sastav · Upozorenja i podatci"],
    ["uređaj", "Opis i prednosti · Upute za korištenje? · Funkcije i "
     "specifikacije · Validacija i dokumentacija · Podaci i upute"],
    ["mliječna formula", "Opis i ključne informacije · Priprema i hranjenje · "
     "Sastav, alergeni i nutritivne vrijednosti · Čuvanje i sigurnost · Pakiranje "
     "i proizvođač"],
], [40, 124]),
("h2", "5.5. Obvezne rečenice po kategoriji"),
("p", "Dodaci prehrani moraju sadržavati napomenu da dodatak nije zamjena za "
      "uravnoteženu prehranu i upozorenje o nepremašivanju preporučene dnevne "
      "doze. Mliječne formule moraju sadržavati rečenicu „Dojenje je najbolji "
      "način prehrane dojenčeta.“ i upućivanje na tablicu hranjenja s deklaracije. "
      "Uređaji moraju upućivati na hrvatsku uputu za uporabu i navesti da uređaj "
      "ne postavlja dijagnozu."),

("h2", "5.6. Inventar činjenica"),
("p", "Inventar je međukorak koji se ne objavljuje, ali određuje sve što slijedi. "
      "Za svako polje bilježi se vrijednost doslovno iz izvora, oznaka izvora i "
      "status."),
("table", ["Status", "Značenje", "Posljedica"], [
    ["FOUND", "Podatak je pronađen u izvorima.", "Mora završiti u opisu; ako je "
     "hard field, ne smije biti skraćen."],
    ["NOT FOUND", "Podatka nema ni u jednom izvoru.", "Koristi se propisani "
     "placeholder ili se izostavlja."],
    ["DERIVED", "Izračunato iz potvrđenih polja.", "Dopušteno uz oslonac na "
     "potvrđene vrijednosti."],
    ["CONFLICT", "Izvori daju različitu konkretnu vrijednost.", "Označava se za "
     "provjeru; vrijednosti se ne spajaju."],
], [28, 66, 70]),

("h1", "6. Izlaz"),
("h2", "6.1. Struktura izlazne mape"),
("code", """out_all/
├── sadrzaj_indeks.xlsx        jedna tablica sa svim rezultatima
├── sadrzaj_indeks.csv         isti sadržaj u CSV-u
├── pdp/
│   ├── PDP_<SKU>_<naziv>.md   PDP opis u Markdownu
│   └── PDP_<SKU>_<naziv>.docx isti opis u Word formatu
├── results.jsonl              zapis za nastavak prekinutog rada
└── .cache/html/               keširane dohvaćene stranice"""),
("h2", "6.2. Stupci zbirne tablice"),
("p", "Jedan redak po proizvodu. Ulazni stupci prenose se nepromijenjeni radi "
      "sparivanja, SEO stupci nose prefiks „SEO“, PDP stupci prefiks „PDP“."),
("table", ["Stupac", "Sadržaj"], [
    ["Sekcija · Brend · SKU · Naziv · URL", "Prijepis ulazne tablice."],
    ["Stranica dohvaćena", "Je li izvor prioriteta 1 uspješno pročitan."],
    ["SEO Title tag", "Konačni title s nastavkom webshopa ako stane u limit."],
    ["SEO Title px · SEO Title znakova", "Izmjerena širina (Arial 20 px) i broj "
     "znakova."],
    ["SEO Meta opis", "Konačni meta opis."],
    ["SEO Meta px · SEO Meta znakova", "Izmjerena širina (Arial 14 px) i broj "
     "znakova."],
    ["SEO Namjena", "Namjena proizvoda kako je potvrđena u izvorima."],
    ["SEO Status · SEO Pokušaji", "Ishod i broj krugova generiranja."],
    ["SEO Napomene", "Preostale greške i bilješke."],
    ["SEO Korištene specifikacije", "Doslovne fraze iz izvora — revizijski trag."],
    ["SEO Izvor – eljekarna24", "URL izvora prioriteta 1."],
    ["SEO Izvor – brend", "URL sekundarnog izvora ako je korišten."],
    ["SEO Preuzeto s brend stranice", "Koji su točno podaci preuzeti izvan "
     "prioriteta 1."],
    ["SEO Napomena za provjeru", "Oznaka obvezne ljudske provjere za takav redak."],
    ["SEO Postojeći title / meta (QA)", "Zatečene vrijednosti sa stranice za "
     "usporedbu staro/novo."],
    ["PDP Kategorija predloška", "Primijenjeni predložak."],
    ["PDP Status · PDP Pokušaji", "Ishod i broj krugova."],
    ["PDP Verifikacija (2. agent)", "Presuda kontrolora činjenica."],
    ["PDP Nepotkrijepljene tvrdnje", "Tvrdnje bez potpore u izvorima."],
    ["PDP Ekstrahiranih polja", "Broj potvrđenih polja u inventaru."],
    ["PDP Coverage check", "„prolazi“ ili popis izgubljenih podataka."],
    ["PDP Konflikt izvora", "Polja s različitim vrijednostima među izvorima."],
    ["PDP Broj izvora · PDP Izvori", "Koliko je izvora korišteno i njihovi URL-ovi."],
    ["PDP MD datoteka · PDP DOCX datoteka", "Putanje do generiranih opisa."],
    ["PDP Napomene", "Ostale bilješke."],
    ["Ukupni status", "Zbirni ishod; OK samo ako su oba alata prošla."],
    ["Model", "Model koji je generirao redak."],
], [58, 106]),
("h2", "6.3. Statusi"),
("table", ["Status", "Značenje", "Postupak"], [
    ["OK", "Struktura, činjenice i potpunost prolaze.", "Spremno za uredničku "
     "provjeru."],
    ["OK (skraćeno)", "SEO prošao nakon determinističkog skraćivanja.", "Provjeriti "
     "je li skraćeni title i dalje jasan."],
    ["TREBA PROVJERA", "Pravilo nije zadovoljeno ni nakon svih krugova.", "Vidjeti "
     "stupac Napomene."],
    ["NEDOSTAJE PODATAK IZ IZVORA", "Coverage check našao izgubljen podatak.",
     "Dopuniti ili pokrenuti ponovno."],
    ["CONFLICT / REVIEW", "Izvori daju različite konkretne vrijednosti.", "Ručno "
     "odlučiti koja je točna."],
    ["GREŠKA EKSTRAKCIJE", "Nije moguće pouzdano izvući strukturirana polja.",
     "Provjeriti dostupnost i sadržaj izvora."],
    ["GREŠKA", "Nema stranice proizvoda (izvor prioriteta 1).", "Ispraviti URL u "
     "ulaznoj tablici."],
], [46, 66, 52]),
("figure", "statusi", "Slika 5. Kako se određuje status pojedinog proizvoda."),
("note", "Što znači OK",
 "Status OK znači da je struktura ispravna, da su napisane tvrdnje "
 "potkrijepljene izvorima, da relevantni podaci iz izvora nisu izgubljeni i da "
 "nema neriješenog konflikta. OK nije zamjena za uredničku provjeru prije "
 "objave, nego preduvjet za nju."),

("h1", "7. Rad sa sustavom"),
("h2", "7.1. Naredbe"),
("code", """python generate_all.py -i proizvodi.xlsx --dry-run    # izvori i promptovi, bez tokena
python generate_all.py -i proizvodi.xlsx --limit 2    # test na dva proizvoda
python generate_all.py -i proizvodi.xlsx              # puni posao
python generate_all.py -i proizvodi.xlsx --retry-review   # samo retci koji nisu OK"""),
("h2", "7.2. Odabir opsega"),
("table", ["Opcija", "Učinak"], [
    ["--only seo | pdp | both", "Koji dio sadržaja generirati."],
    ["--limit N · --sku", "Ograničenje na dio asortimana."],
    ["--max-attempts", "Broj krugova ispravaka po proizvodu."],
    ["--search-results · --no-secondary · --no-web-search", "Opseg izvora."],
    ["--no-verify · --no-extract · --no-coverage", "Isključivanje pojedinih "
     "kontrola (dijagnostika)."],
    ["--refresh-cache · --force", "Ponovno dohvaćanje izvora, odnosno ponovna obrada."],
    ["--prompts-dir · --show-prompts", "Vanjski promptovi i njihov ispis."],
], [64, 100]),
("h2", "7.3. Podešavanje promptova"),
("p", "Napomene se dodaju na kraj ugrađenih promptova i uređuju kao datoteke: "
      "`seo_napomene.md`, `pdp_napomene.md` te po kategoriji "
      "(`pdp_napomene_cosmetics.md` i slično) i `verify_napomene.md`. Potpuna "
      "zamjena prompta moguća je kroz `seo_system.md`, `pdp_system.md` i "
      "`verify_system.md`, uz podržane placeholdere. Mapa se stvara naredbom "
      "`python prompts_cfg.py --init`."),
("note", "Pravila i validator idu zajedno",
 "Ton, formulacije i zabranjene riječi rade odmah preko napomena. Ako izmjena "
 "dira tvrda pravila (pikselske limite, nazive tabova, obvezne rečenice, broj "
 "FAQ pitanja), treba uskladiti i deterministički validator — inače model piše "
 "jedno, a kontrola traži drugo."),

("h2", "7.4. Tipični scenariji"),
("table", ["Situacija", "Postupak"], [
    ["Prvi put na novom asortimanu", "`--dry-run` za provjeru izvora, pa `--limit 2`, "
     "pa puni posao."],
    ["Posao je prekinut", "Ponovno pokretanje iste naredbe; obrađeni proizvodi se "
     "preskaču."],
    ["Klijent je promijenio pravilo teksta", "Dopuniti datoteku s napomenama, "
     "provjeriti s `--show-prompts`, pa `--retry-review`."],
    ["Puno redaka „TREBA PROVJERA“", "Pogledati stupce Napomene i Coverage check; "
     "obično znači siromašnu stranicu proizvoda."],
    ["Pojedini proizvod treba ponoviti", "`--sku <SKU> --force`."],
    ["Izvori su se promijenili", "`--refresh-cache` za ponovno dohvaćanje."],
], [52, 112]),

("h1", "8. Nefunkcionalna svojstva"),
("h2", "8.1. Pouzdanost"),
("bullets", [
    "Svaki proizvod zapisuje se odmah po obradi; prekinuti posao nastavlja se bez "
    "gubitka i bez ponovnog trošenja tokena.",
    "Na throttling i privremene greške poziva čeka se s eksponencijalnim odmakom.",
    "Nedostupan izvor ne ruši obradu: redak se označava i nastavlja se dalje.",
    "Dohvaćene stranice keširaju se, pa ponovni prolaz ne opterećuje izvore.",
]),
("h2", "8.2. Testiranje"),
("p", "Offline testovi pokrivaju klijentova pravila, hijerarhiju izvora, coverage "
      "check, pikselsko mjerenje, skraćivanje koje čuva količinu, vanjske "
      "promptove i pretvorbu u DOCX. Testovi koriste mock klijente, ne zovu "
      "Bedrock ni mrežu i ne stvaraju trošak."),
("h2", "8.3. Trošak i kapacitet"),
("p", "Trošak je izravno razmjeran broju poziva modelu, a on ovisi o broju krugova "
      "ispravaka. Najveći dio troška otpada na PDP dio, i to na ulazne tokene "
      "(kostur, primjer kategorije i izvori). Praktične poluge za smanjenje: manji "
      "model za kontrolora činjenica, manji broj web izvora po proizvodu i "
      "grupna obrada za poslove bez vremenskog pritiska. Procjene za konkretan "
      "opseg isporučene su u zasebnim dokumentima."),
("h2", "8.6. Sigurnost podataka"),
("bullets", [
    "Pristupni podaci drže se u `.env` koji se ne unosi u repozitorij.",
    "Sustav ne šalje podatke nikamo osim na Bedrock i na javno dostupne izvore "
    "koje sam dohvaća.",
    "Izlaz ne sadrži cijene, zalihe ni druge podatke koji se mijenjaju u sustavu.",
]),
("h2", "8.4. Mjerila kvalitete"),
("p", "Izlaz se ocjenjuje s četiri mjerila, redom po važnosti: **točnost** (nijedna "
      "tvrdnja bez potpore u izvorima), **potpunost** (nijedan pronađen podatak nije "
      "izgubljen), **usklađenost s pravilima** (pikseli, struktura, zabranjeni "
      "izrazi) i **čitljivost**. Sustav prva tri mjerila provjerava automatski; "
      "četvrto ostaje na uredničkoj provjeri."),
("h2", "8.5. Ograničenja"),
("bullets", [
    "Kvaliteta izlaza ovisi o sadržaju izvora: siromašna stranica proizvoda daje "
    "siromašniji opis i više redaka za provjeru.",
    "Pikselsko mjerenje je približak stvarnog prikaza u tražilici; prikaz može "
    "ovisiti o upitu i uređaju.",
    "Retci označeni statusom različitim od OK zahtijevaju ljudsku odluku i ne "
    "objavljuju se automatski.",
    "Prijevodi nisu dio ovog opsega.",
]),
]

# ---------------------------------------------------------------------------
# Markdown izlaz
# ---------------------------------------------------------------------------

def to_markdown() -> str:
    out = [f"# Liberiq Descriptioner — specifikacija softvera", "",
           f"**Verzija {VERZIJA} · {DATUM}**", "",
           "Sustav za automatsko generiranje SEO title i meta tagova te PDP opisa "
           "proizvoda za webshop eljekarna24, na Claude modelima preko AWS "
           "Bedrocka.", "", "---", ""]
    for block in C:
        kind = block[0]
        if kind == "h1":
            out += [f"## {block[1]}", ""]
        elif kind == "h2":
            out += [f"### {block[1]}", ""]
        elif kind == "h3":
            out += [f"#### {block[1]}", ""]
        elif kind == "p":
            out += [block[1], ""]
        elif kind == "bullets":
            out += [f"- {b}" for b in block[1]] + [""]
        elif kind == "numbers":
            out += [f"{i}. {b}" for i, b in enumerate(block[1], 1)] + [""]
        elif kind == "code":
            out += ["```", block[1], "```", ""]
        elif kind == "note":
            out += [f"> **{block[1]}**  ", f"> {block[2]}", ""]
        elif kind == "kv":
            out += ["| Varijabla | Opis |", "| --- | --- |"]
            out += [f"| `{k}` | {v} |" for k, v in block[1]] + [""]
        elif kind == "figure":
            out += [f"![{block[2]}](diagrams/{block[1]}.png)", "",
                    f"*{block[2]}*", ""]
        elif kind == "table":
            header, rows = block[1], block[2]
            out += ["| " + " | ".join(header) + " |",
                    "| " + " | ".join("---" for _ in header) + " |"]
            out += ["| " + " | ".join(r) + " |" for r in rows] + [""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# PDF izlaz
# ---------------------------------------------------------------------------

pdfmetrics.registerFont(TTFont("DJ", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DJ-B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJ-I", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFontFamily("DJ", normal="DJ", bold="DJ-B", italic="DJ-I")
pdfmetrics.registerFont(TTFont("DJM", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"))
MONO = "DJM"

ST = {
    "h1": ParagraphStyle("h1", fontName="DJ-B", fontSize=15, leading=19,
                         textColor=PLUM_DARK, spaceBefore=4, spaceAfter=7),
    "h2": ParagraphStyle("h2", fontName="DJ-B", fontSize=10.8, leading=14,
                         textColor=PLUM, spaceBefore=11, spaceAfter=4),
    "p": ParagraphStyle("p", fontName="DJ", fontSize=9.2, leading=13.2,
                        textColor=INK, spaceAfter=6),
    "li": ParagraphStyle("li", fontName="DJ", fontSize=9.2, leading=13.2,
                         textColor=INK, leftIndent=11, spaceAfter=3.5),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=7.6, leading=10.4,
                           textColor=PLUM_DARK),
    "note_t": ParagraphStyle("nt", fontName="DJ-B", fontSize=9.2, leading=12.5,
                             textColor=PLUM_DARK, spaceAfter=2),
    "note_b": ParagraphStyle("nb", fontName="DJ", fontSize=9, leading=12.5,
                             textColor=INK),
    "cell": ParagraphStyle("c", fontName="DJ", fontSize=8.3, leading=11,
                           textColor=INK),
    "cellb": ParagraphStyle("cb", fontName="DJ-B", fontSize=8.3, leading=11,
                            textColor=PLUM_DARK),
    "chead": ParagraphStyle("ch", fontName="DJ-B", fontSize=8.3, leading=10.8,
                            textColor=colors.white),
    "caption": ParagraphStyle("cap", fontName="DJ", fontSize=8.2, leading=11,
                              textColor=MUTED, alignment=TA_CENTER),
    "cover_kicker": ParagraphStyle("ck", fontName="DJ-B", fontSize=10, leading=13,
                                   textColor=INK, alignment=0),
    "cover_title": ParagraphStyle("ct", fontName="DJ-B", fontSize=31, leading=37,
                                  textColor=INK, alignment=0),
    "cover_sub": ParagraphStyle("cs", fontName="DJ", fontSize=11.5, leading=16.5,
                                textColor=MUTED, alignment=0),
    "cover_meta": ParagraphStyle("cm", fontName="DJ", fontSize=9.5, leading=14,
                                 textColor=MUTED, alignment=0),
}


def md_inline(text: str) -> str:
    """**bold**, *italic*, `code` → reportlab markup."""
    import re
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", rf'<font face="{MONO}" size="8.4" color="#0A0A0A">\1</font>',
                  text)
    return text


def blob(canvas, x, y, r, color, alpha=0.18):
    canvas.saveState()
    canvas.setFillColor(color)
    canvas.setFillAlpha(alpha)
    canvas.circle(x, y, r, stroke=0, fill=1)
    canvas.restoreState()


def gradient_band(canvas, x, y, w, h, stops, alpha=1.0, steps=220):
    """Vodoravni gradijent kroz zadane boje."""
    canvas.saveState()
    canvas.setFillAlpha(alpha)
    seg = len(stops) - 1
    for i in range(steps):
        t = i / (steps - 1)
        k = min(int(t * seg), seg - 1)
        local = t * seg - k
        c1, c2 = stops[k], stops[k + 1]
        canvas.setFillColorRGB(c1.red + (c2.red - c1.red) * local,
                               c1.green + (c2.green - c1.green) * local,
                               c1.blue + (c2.blue - c1.blue) * local)
        canvas.rect(x + w * i / steps, y, w / steps + 0.7, h, stroke=0, fill=1)
    canvas.restoreState()


def soft_blob(canvas, cx, cy, r, stops, rings=70, peak=0.5):
    """Mekana gradijentna mrlja koja se gubi u bijelo, kao na naslovnici weba."""
    canvas.saveState()
    for i in range(rings, 0, -1):
        t = i / rings                      # 1 = rub, 0 = sredina
        k = min(int((1 - t) * (len(stops) - 1)), len(stops) - 2)
        local = (1 - t) * (len(stops) - 1) - k
        c1, c2 = stops[k], stops[k + 1]
        canvas.setFillColorRGB(c1.red + (c2.red - c1.red) * local,
                               c1.green + (c2.green - c1.green) * local,
                               c1.blue + (c2.blue - c1.blue) * local)
        canvas.setFillAlpha(peak * (1 - t) ** 2 / rings * 6)
        canvas.circle(cx, cy, r * t, stroke=0, fill=1)
    canvas.restoreState()


def cover_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
    # velika mekana mrlja u gornjem lijevom kutu, izlazi izvan stranice
    soft_blob(canvas, -10 * mm, A4[1] + 6 * mm, 135 * mm,
              [YELLOW, AMBER, ORANGE, ROSE, PINK], peak=0.62)
    # manji odsjaj dolje desno
    soft_blob(canvas, A4[0] + 14 * mm, 26 * mm, 78 * mm,
              [PINK, ROSE, ORANGE], peak=0.40)
    gradient_band(canvas, 0, A4[1] - 6 * mm, A4[0], 6 * mm,
                  [YELLOW, AMBER, ORANGE, ROSE, PINK])
    canvas.restoreState()


def body_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
    gradient_band(canvas, 0, A4[1] - 3.4 * mm, A4[0], 3.4 * mm,
                  [YELLOW, AMBER, ORANGE, ROSE, PINK])
    canvas.setFont("DJ", 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 11 * mm,
                      f"Liberiq Descriptioner — specifikacija softvera · v{VERZIJA}")
    canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, str(canvas.getPageNumber()))
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
    canvas.restoreState()


def make_table(header, rows, widths_mm):
    widths = [w * mm for w in widths_mm]
    data = [[Paragraph(md_inline(h), ST["chead"]) for h in header]]
    for r in rows:
        data.append([Paragraph(md_inline(c), ST["cellb"] if i == 0 else ST["cell"])
                     for i, c in enumerate(r)])
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), PLUM),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
             ("LINEBEFORE", (0, 0), (0, -1), 0, colors.white),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 6),
             ("RIGHTPADDING", (0, 0), (-1, -1), 6),
             ("TOPPADDING", (0, 0), (-1, -1), 4.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5)]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), LILAC_SOFT))
    t.setStyle(TableStyle(style))
    return t


def note_box(title, body):
    inner = Table([[Paragraph(md_inline(title), ST["note_t"])],
                   [Paragraph(md_inline(body), ST["note_b"])]],
                  colWidths=[158 * mm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ROSE_SOFT),
        ("LINEBEFORE", (0, 0), (0, -1), 2.6, ROSE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (0, 0), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
    ]))
    return inner


def code_box(text):
    rows = [[Paragraph(line.replace(" ", "&nbsp;").replace("<", "&lt;") or "&nbsp;",
                       ST["code"])] for line in text.splitlines()]
    t = Table(rows, colWidths=[158 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CREAM),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, PLUM),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def figure(name, caption, max_w_mm=158, max_h_mm=185):
    path = DIAG / f"{name}.png"
    with PILImage.open(path) as im:
        iw, ih = im.size
    w = max_w_mm * mm
    h = w * ih / iw
    if h > max_h_mm * mm:
        h = max_h_mm * mm
        w = h * iw / ih
    img = Image(str(path), width=w, height=h)
    cap = Paragraph(md_inline(caption), ST["caption"])
    return KeepTogether([img, Spacer(1, 4), cap, Spacer(1, 10)])


def h1_block(text):
    num, _, title = text.partition(". ")
    row = Table([[Paragraph(f'<font color="#FF5C39">{num}</font>  {title}', ST["h1"])]],
                colWidths=[158 * mm])
    row.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.6, ROSE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    return row


def build_pdf(path):
    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=16 * mm, bottomMargin=18 * mm,
                          title="Liberiq Descriptioner — specifikacija softvera",
                          author="Liberiq")
    frame_cover = Frame(18 * mm, 18 * mm, A4[0] - 36 * mm, A4[1] - 40 * mm, id="cover")
    frame_body = Frame(18 * mm, 18 * mm, A4[0] - 36 * mm, A4[1] - 36 * mm, id="body")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=cover_page),
        PageTemplate(id="body", frames=[frame_body], onPage=body_page),
    ])

    rule = Table([[""]], colWidths=[46 * mm], rowHeights=[2.4])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ROSE)]))
    story = [Spacer(1, 96 * mm),
             Paragraph("SPECIFIKACIJA SOFTVERA", ST["cover_kicker"]),
             Spacer(1, 9),
             Paragraph("Liberiq<br/>Descriptioner", ST["cover_title"]),
             Spacer(1, 13), rule, Spacer(1, 13),
             Paragraph("Automatsko generiranje SEO title i meta tagova te PDP "
                       "opisa proizvoda<br/>za webshop eljekarna24", ST["cover_sub"]),
             Spacer(1, 34),
             Paragraph(f"Verzija {VERZIJA} · {DATUM}", ST["cover_meta"]),
             NextPageTemplate("body"), PageBreak()]

    for block in C:
        kind = block[0]
        if kind == "h1":
            story.append(Spacer(1, 6))
            story.append(h1_block(block[1]))
            story.append(Spacer(1, 4))
        elif kind == "h2":
            story.append(Paragraph(md_inline(block[1]), ST["h2"]))
        elif kind == "p":
            story.append(Paragraph(md_inline(block[1]), ST["p"]))
        elif kind == "bullets":
            for b in block[1]:
                story.append(Paragraph(
                    f'<font color="#FF5C39">•</font>  {md_inline(b)}', ST["li"]))
            story.append(Spacer(1, 4))
        elif kind == "numbers":
            for i, b in enumerate(block[1], 1):
                story.append(Paragraph(
                    f'<font color="#FF5C39"><b>{i}.</b></font>  {md_inline(b)}',
                    ST["li"]))
            story.append(Spacer(1, 4))
        elif kind == "code":
            story.append(KeepTogether(code_box(block[1])))
            story.append(Spacer(1, 8))
        elif kind == "note":
            story.append(KeepTogether(note_box(block[1], block[2])))
            story.append(Spacer(1, 9))
        elif kind == "kv":
            story.append(make_table(["Varijabla", "Opis"],
                                    [[f"`{k}`", v] for k, v in block[1]], [62, 96]))
            story.append(Spacer(1, 8))
        elif kind == "figure":
            story.append(figure(block[1], block[2]))
        elif kind == "table":
            story.append(make_table(block[1], block[2], block[3]))
            story.append(Spacer(1, 8))

    doc.build(story)


C += [
("h1", "9. Dodaci"),
("h2", "9.1. Popis automatskih provjera"),
("table", ["Područje", "Provjera"], [
    ["Title", "Širina u pikselima · početak kanonskim nazivom · prisutnost količine · "
     "zarez ispred količine · kratice jedinica · razmak broj–jedinica · velika "
     "slova · jedinstvenost"],
    ["Meta opis", "Širina u pikselima · prisutnost naziva · obvezna namjena · "
     "potpuna zadnja rečenica · jedinstvenost"],
    ["Oba", "Zabranjeni izrazi (cijene, dostava, CTA, superlativi, definitivne "
     "tvrdnje) · brojevi s jedinicom potvrđeni u izvorima"],
    ["PDP struktura", "Naslov i redoslijed sekcija · šest tabova s točnim nazivima · "
     "brza traka i 3–4 prednosti · duljina Tab 1 · obvezni redci Tab 5 · fiksni "
     "blokovi · 3–5 FAQ pitanja"],
    ["PDP sadržaj", "Obvezne rečenice kategorije · EAN potvrđen u izvorima · "
     "brojevi s jedinicom potvrđeni · ograde u tekstu"],
    ["PDP potpunost", "Coverage check hard fieldova · placeholder umjesto "
     "postojeće vrijednosti · označenost konflikta"],
], [34, 130]),
("h2", "9.2. Struktura repozitorija"),
("code", """Liberiq-descriptioner/
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
└── README.md                upute za pokretanje"""),
("h2", "9.3. Povezani dokumenti"),
("table", ["Dokument", "Sadržaj"], [
    ["README.md", "Upute za instalaciju, pokretanje i rješavanje problema."],
    ["README_KLIJENT_PRAVILA.md", "Popis klijentovih pravila i mjesto provedbe u kodu."],
    ["README_PROMPTOVI.md", "Uređivanje promptova i napomena."],
    ["README_OBJEDINJENO.md", "Objedinjeni runner i zajednički izlaz."],
], [56, 108]),
]


if __name__ == "__main__":
    md = to_markdown()
    open("/mnt/user-data/outputs/SPECIFIKACIJA.md", "w", encoding="utf-8").write(md)
    build_pdf("/mnt/user-data/outputs/Liberiq_Descriptioner_specifikacija.pdf")
    print(f"MD: {len(md.splitlines())} redaka; PDF zapisan.")
