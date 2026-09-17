# -*- coding: utf-8 -*-
"""
Predlošci PDP struktura po kategorijama — točan format iz dokumenata:
PDP_struktura.docx + četiri primjera (Effaclar, Solgar D3, Microlife BP A1, NAN 2).

Ovaj modul je jedini izvor istine za format: iz njega čitaju i prompt
(skeleton + primjer) i deterministički validator (nazivi tabova, obvezne
fraze, fiksni blokovi). Meta-napomene iz primjera ("nakon researcha",
"idealno iskomunicirati...") razriješene su u produkcijski sadržaj:
FAQ se piše iz researcha, a fiksni blokovi (Tab 6, recenzije) se prepisuju
doslovno iz predloška.
"""

# ---------------------------------------------------------------------------
# Mapiranje Sekcija -> kategorija predloška
# ---------------------------------------------------------------------------

SECTION_TO_CATEGORY = {
    "kozmetika": "cosmetics",
    "vitamini, minerali i kolageni": "supplement",
    "beta glukani": "supplement",
    "mliječne formule": "formula",
    "mlijecne formule": "formula",
    "cijeli webshop": "device",
}

CATEGORY_LABELS = {
    "cosmetics": "kozmetika",
    "supplement": "dodatak prehrani",
    "device": "medicinski proizvod / uređaj",
    "formula": "mliječna formula",
}

# ---------------------------------------------------------------------------
# Fiksni blokovi (prepisuju se doslovno; validator ih traži)
# ---------------------------------------------------------------------------

TAB6_LABEL = "Savjet ljekarnika (može voditi dodatno na kontakt prema ljekarniku nakon savjeta)"

TAB6_BODY = """- Stručni savjet ljekarnika oko upotrebe ovog proizvoda. [Dopuniti iskustvima iz prakse ljekarnika eLjekarna24 prije objave.]
- Mogućnost izravnog kontakta s ljekarnikom za dodatna pitanja."""

REVIEWS_BODY = ("Prikazati stvarne recenzije kupaca iz sustava eLjekarna24, "
                "uključujući kritične. Ne prenositi ocjene s drugih tržišta. "
                "[Blok se puni automatski iz sustava recenzija.]")

# ---------------------------------------------------------------------------
# Definicije predložaka
# ---------------------------------------------------------------------------

TEMPLATES = {
    # ------------------------------------------------------------- KOZMETIKA
    "cosmetics": {
        "tabs": [
            "Opis i prednosti",
            "Je li za moju kožu?",
            "Kako se koristi?",
            "Sastojci",
            "Podatci i upozorenja",
            TAB6_LABEL,
        ],
        "brza_traka": "tip, namjena, ciljana skupina, područje, tekstura/oblik, pakiranje",
        "istaknuti_blok_uputa": (
            'Naslov po ključnoj informaciji prije kupnje (npr. "Kako se uklapa u '
            'rutinu?") + jedna uvodna rečenica + tablica (npr. 3 koraka rutine).'
        ),
        "tab2_hint": ('Dvostupčana tablica: "Ovu kremu razmotri ako | Prije kupnje '
                      "zastani ako\" s po 3 retka."),
        "tab4_hint": ('Tablica "Istaknuti sastojak | Što to znači za kožu" (3–4 '
                      'sastojka POTVRĐENA u izvorima), zatim "Ostali:" i puni INCI '
                      "iz izvora ili propisani placeholder."),
        "mandatory_phrases": [
            ("razmotri ako", "Tab 2 mora sadržavati tablicu 'razmotri ako / zastani ako'"),
            ("zastani ako", "Tab 2 mora sadržavati stupac 'Prije kupnje zastani ako'"),
            (("INCI:", "Puni INCI"),
             "Tab 4 mora sadržavati puni INCI — doslovno prenesen popis uveden s "
             "'INCI:' kada je pronađen u izvorima, inače propisani placeholder"),
        ],
        "allow_studies": True,
    },
    # ------------------------------------------------------ DODATAK PREHRANI
    "supplement": {
        "tabs": [
            "Opis i prednosti",
            "Doza i kome je namijenjen",
            "Kako se uzima?",
            "Sastojci i sastav",
            "Upozorenja i podatci",
            TAB6_LABEL,
        ],
        "brza_traka": "tip, namjena, ciljana skupina, područje, tekstura/oblik, pakiranje",
        "istaknuti_blok_uputa": ('Naslov "Dnevna doza na prvi pogled" + tablica: '
                                 "Preporučena doza | Količina aktivne tvari | Kada se "
                                 "uzima | Trajanje pakiranja."),
        "tab2_hint": ("2–4 natuknice kome je namijenjen + preporučena doza, sve "
                      "prema deklaraciji iz izvora."),
        "tab4_hint": ('Tablica "Istaknuti sastojak | Što to znači za kupca" + puni '
                      "sastav iz izvora ili propisani placeholder."),
        "mandatory_phrases": [
            ("Dnevna doza na prvi pogled", "Istaknuti blok mora biti 'Dnevna doza na prvi pogled'"),
            ("nije zamjena za", "Obvezna rečenica: dodatak prehrani nije zamjena za "
                                "uravnoteženu i raznovrsnu prehranu"),
            ("Ne prekoračuj", "Obvezno upozorenje o nepremašivanju preporučene dnevne doze"),
        ],
        "allow_studies": False,
    },
    # ---------------------------------------------------------------- UREĐAJ
    "device": {
        "tabs": [
            "Opis i prednosti",
            "Upute za korištenje?",
            "Funkcije i specifikacije",
            "Validacija i dokumentacija",
            "Podaci i upute",
            TAB6_LABEL,
        ],
        "brza_traka": "tip, namjena, ciljana skupina, pakiranje",
        "istaknuti_blok_uputa": ("Naslov po ključnoj provjeri prije kupnje (npr. "
                                 '"Odgovara li vam manšeta?") + tablica s tom provjerom.'),
        "tab2_hint": "5–7 koraka uporabe u imperativu, prema uputi iz izvora.",
        "tab3_hint": ('Tablica "Značajka | Što znači u svakodnevnoj uporabi" sa '
                      "SAMO potvrđenim značajkama iz izvora."),
        "mandatory_phrases": [
            ("Značajka", "Tab 3 mora sadržavati tablicu 'Značajka | Što znači u svakodnevnoj uporabi'"),
            ("uputu za uporabu", "Obvezno upućivanje na (hrvatsku) uputu za uporabu"),
        ],
        "allow_studies": False,
    },
    # ------------------------------------------------------ MLIJEČNA FORMULA
    "formula": {
        "tabs": [
            "Opis i ključne informacije",
            "Priprema i hranjenje",
            "Sastav, alergeni i nutritivne vrijednosti",
            "Čuvanje i sigurnost",
            "Pakiranje i proizvođač (plus ostali obavezni podaci)",
            TAB6_LABEL,
        ],
        "brza_traka": "tip, namjena, ciljana skupina, tekstura/oblik, pakiranje",
        "istaknuti_blok_uputa": ('Naslov "Prije kupnje provjerite" + tablica: Dobna '
                                 "faza | Tip proizvoda | Alergen | Pakiranje."),
        "tab2_hint": ("Koraci pripreme prema deklaraciji + uputa na tablicu "
                      "hranjenja; bez izmišljenih omjera."),
        "mandatory_phrases": [
            ("Prije kupnje provjerite", "Istaknuti blok mora biti 'Prije kupnje provjerite'"),
            ("Dojenje je najbolji", "Obvezna rečenica: 'Dojenje je najbolji način "
                                    "prehrane dojenčeta.'"),
            ("tablici hranjenja", "Priprema se mora vezati uz tablicu hranjenja s deklaracije"),
        ],
        "allow_studies": False,
    },
}

# Redci obveznog završnog bloka podataka (Tab 5) — validator ih traži unutar Tab 5
TAB5_REQUIRED_ROWS = ["Pakiranje", "Brend", "Proizvođač", "Zemlja podrijetla",
                      "EAN", "Obvezna provjera prije objave"]

PLACEHOLDER_UNKNOWN = "Unijeti točno prema aktualnoj deklaraciji ili PIM-u."
PLACEHOLDER_ORIGIN = ("Navesti samo ako je potvrđena na deklaraciji ili u "
                      "dokumentaciji točnog proizvoda.")
PLACEHOLDER_INCI = ("Puni INCI sastav s aktualne deklaracije (umetnuti točan popis "
                    "bez prijevoda i skraćivanja).")

# ---------------------------------------------------------------------------
# Skeleton (dobiva ga model u promptu)
# ---------------------------------------------------------------------------

def build_skeleton(category: str) -> str:
    t = TEMPLATES[category]
    tabs = t["tabs"]
    lines = [
        "# PDP struktura s tabovima: {kratki naziv proizvoda}",
        "",
        "## 1. Prvi ekran: Naziv, opis i brzi podatci",
        "",
        "### Naziv proizvoda",
        "",
        "{Brend + naziv + glavna karakteristika/namjena + količina}",
        "",
        "### Kratki opis",
        "",
        "{jedna rečenica: što je proizvod, kome/čemu je namijenjen i glavna korist}",
        "",
        "### Brza traka ispod opisa",
        "",
        t["brza_traka"],
        "",
        "- {ključna prednost 1 — konkretna korist za kupca}",
        "- {ključna prednost 2}",
        "- {ključna prednost 3}",
        "- {ključna prednost 4 — 3 do 4 prednosti ukupno}",
        "",
        "## 2. Istaknuti blok iznad tabova",
        "",
        "### {naslov istaknutog bloka}",
        "",
        "{jedna uvodna rečenica}",
        "",
        "| {stupac 1} | {stupac 2} |",
        "| --- | --- |",
        "| {…} | {…} |",
        "",
        "## 3. Struktura tabova (Max 6 tabova)",
        "",
        f"### Tab 1: {tabs[0]}",
        "",
        "{80–150 riječi; počinje situacijom kupca, zatim korist i uporaba, bez CTA}",
        "",
        f"### Tab 2: {tabs[1]}",
        "",
        "{" + t.get("tab2_hint", "sadržaj taba 2") + "}",
        "",
        f"### Tab 3: {tabs[2]}",
        "",
        "{" + t.get("tab3_hint", "sadržaj taba 3 prema primjeru kategorije") + "}",
        "",
        f"### Tab 4: {tabs[3]}",
        "",
        "{" + t.get("tab4_hint", "sadržaj taba 4 prema primjeru kategorije") + "}",
        "",
        f"### Tab 5: {tabs[4]}",
        "",
        "| Pakiranje | {…} |",
        "| --- | --- |",
        "| Brend | {…} |",
        f"| Proizvođač / odgovorna osoba | {{iz izvora ili: {PLACEHOLDER_UNKNOWN}}} |",
        f"| Zemlja podrijetla | {{iz izvora ili: {PLACEHOLDER_ORIGIN}}} |",
        f"| EAN | {{iz izvora ili: {PLACEHOLDER_UNKNOWN}}} |",
        "| Obvezna provjera prije objave | {što sve mora odgovarati aktualnom pakiranju} |",
        "",
        "{upozorenja iz deklaracije, jasnim rečenicama, svako u svom retku}",
        "",
        f"### Tab 6: {TAB6_LABEL}",
        "",
        TAB6_BODY,
        "",
    ]
    n = 4
    if t["allow_studies"]:
        lines += [
            f"## {n}. Kliničke studije",
            "",
            "{SAMO ako u izvorima postoje konkretni rezultati ispitivanja za točan "
            "proizvod: uvodna rečenica + tablica 'Rezultat | Metoda mjerenja i izvor'. "
            "Svaki redak: rezultat, vrijeme, broj ispitanika, metoda. Ako podataka "
            "nema, cijelu ovu sekciju IZOSTAVI i nastavi numeraciju od "
            f"{n}.}}",
            "",
        ]
        n += 1
    lines += [
        f"## {n}. Ocjene i recenzije kupaca",
        "",
        REVIEWS_BODY,
        "",
        f"## {n + 1}. Često postavljana pitanja (FAQ)",
        "",
        "### {Pitanje 1?}",
        "",
        "{odgovor utemeljen na izvorima}",
        "",
        "{ukupno 3–5 pitanja, svako kao '### Pitanje?' + odgovor}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Kanonski primjeri (few-shot; validator ih mora sam proglasiti ispravnima)
# ---------------------------------------------------------------------------

EXAMPLE_COSMETICS = """# PDP struktura s tabovima: La Roche-Posay Effaclar Duo+M krema

## 1. Prvi ekran: Naziv, opis i brzi podatci

### Naziv proizvoda

La Roche-Posay Effaclar Duo+M krema za masnu kožu sklonu nepravilnostima 40 ml

### Kratki opis

Krema za svakodnevnu njegu masne kože sklone nepravilnostima koja pomaže smanjiti vidljivost mitesera, prištića i tragova nakon njih, uz osjećaj hidratacije.

### Brza traka ispod opisa

tip, namjena, ciljana skupina, područje, tekstura/oblik, pakiranje

- Za mitesere i nepravilnosti: pomaže smanjiti njihovu vidljivost uz redovitu uporabu.
- Za tragove nakon prištića: pomaže da izgledaju manje izraženo.
- Za masnu kožu kojoj ipak treba njega: daje osjećaj hidratacije bez preskakanja kreme.
- Za jednostavnu rutinu: nanosi se nakon čišćenja, ujutro i/ili navečer; prema podacima proizvoda može ispod šminke.

## 2. Istaknuti blok iznad tabova

### Kako se uklapa u rutinu?

Tri jednostavna koraka iznad tabova kako bi kupac odmah vidio primjenu:

| Korak | Što uključuje |
| --- | --- |
| 1. Očisti | Proizvod za čišćenje lica. |
| 2. Nanesi kremu | Mali sloj na cijelo lice. |
| 3. Zaštiti | Dnevni proizvod sa zaštitnim faktorom. |

## 3. Struktura tabova (Max 6 tabova)

### Tab 1: Opis i prednosti

Ako se lice tijekom dana brzo počne sjajiti, a uz to se pojavljuju miteseri, prištići ili tragovi nakon njih, ova krema može biti praktičan korak u svakodnevnoj rutini. La Roche-Posay Effaclar Duo+M namijenjena je masnoj koži sklonoj nepravilnostima kod odraslih i adolescenata od 10 godina, prema podacima proizvoda. Pomaže smanjiti vidljivost nepravilnosti i tragova nakon njih, a istodobno daje osjećaj hidratacije. Nanosi se nakon čišćenja na cijelo lice, ujutro i/ili navečer, bez ispiranja. Ako se šminkaš, prema podacima proizvoda može poslužiti kao podloga za šminku. Za izražene, bolne ili dugotrajne promjene na koži opis proizvoda nije zamjena za savjet dermatologa ili ljekarnika.

### Tab 2: Je li za moju kožu?

| Ovu kremu razmotri ako | Prije kupnje zastani ako |
| --- | --- |
| Imaš masnu kožu koja se sjaji, osobito na čelu, nosu i bradi. | Tražiš izrazito bogatu kremu za vrlo suhu kožu. |
| Želiš jednu kremu za svakodnevnu njegu kože na kojoj se pojavljuju miteseri i prištići. | Znaš da si osjetljiv/a na neki sastojak iz punog popisa. |
| Tražiš proizvod za jutro, večer ili ispod šminke prema uputi proizvoda. | Imaš izražene, bolne ili dugotrajne promjene na koži. |

### Tab 3: Kako se koristi?

- Očisti lice proizvodom koji ti odgovara.
- Nanesi malu količinu kreme na cijelo lice.
- Izbjegavaj područje oko očiju.
- Koristi je ujutro i/ili navečer.
- Krema se ne ispire. Prema podacima proizvoda može se koristiti i kao podloga za šminku.

### Tab 4: Sastojci

| Istaknuti sastojak | Što to znači za kožu |
| --- | --- |
| Niacinamid | Za njegu kože s tragovima nakon nepravilnosti i za ujednačeniji izgled tena. |
| Glicerin | Pomaže zadržati vlagu u formuli, što je korisno kada i masnoj koži treba dodatna hidratacija. |
| Zinc PCA | Sastojak prisutan u formuli za njegu kože sklone nepravilnostima. |
| Salicilna kiselina | Sastojak koji se često nalazi u njezi kože sklone začepljenim porama. |

Ostali:

Puni INCI sastav s aktualne deklaracije (umetnuti točan popis bez prijevoda i skraćivanja).

### Tab 5: Podatci i upozorenja

| Pakiranje | 40 ml |
| --- | --- |
| Brend | La Roche-Posay |
| Proizvođač / odgovorna osoba | La Roche-Posay Laboratoire Dermatologique CAI, 86270 La Roche-Posay, Francuska, prema dostupnoj dokumentaciji; potvrditi prema aktualnom pakiranju. |
| Zemlja podrijetla | Navesti samo ako je potvrđena na deklaraciji ili u dokumentaciji točnog proizvoda. |
| EAN | 3337875863377 |
| Obvezna provjera prije objave | Naziv, količina, INCI, upozorenja, odgovorna osoba i EAN moraju odgovarati aktualnoj ambalaži. |

Samo za vanjsku uporabu.

Izbjegavaj područje oko očiju. Ako proizvod dođe u dodir s očima, temeljito ih isperi vodom.

Prije uporabe provjeri aktualni sastav na pakiranju.

Kod izraženih, bolnih ili dugotrajnih promjena na koži potraži savjet ljekarnika ili dermatologa.

### Tab 6: Savjet ljekarnika (može voditi dodatno na kontakt prema ljekarniku nakon savjeta)

- Stručni savjet ljekarnika oko upotrebe ovog proizvoda. [Dopuniti iskustvima iz prakse ljekarnika eLjekarna24 prije objave.]
- Mogućnost izravnog kontakta s ljekarnikom za dodatna pitanja.

## 4. Kliničke studije

Ove konkretne brojke službena međunarodna stranica proizvoda navodi uz metodološke fusnote. Prije lokalne objave potvrditi da se odnose na identičnu formulu u Hrvatskoj.

| Rezultat | Metoda mjerenja i izvor |
| --- | --- |
| 66 % manje vidljivih mitesera nakon 4 tjedna | Klinička procjena na 45 ispitanika koji su proizvod koristili jednom dnevno ujutro. |
| 44 % manje vidljivih nepravilnosti nakon 4 tjedna | Klinička procjena na 45 ispitanika koji su proizvod koristili jednom dnevno ujutro. |
| 45 % manje vidljivih tragova nakon nepravilnosti nakon 4 tjedna | Klinička procjena na 42 ispitanika koji su proizvod koristili jednom dnevno ujutro. |
| 24 sata hidratacije | Instrumentalno mjerenje na 24 ispitanika. |

## 5. Ocjene i recenzije kupaca

Prikazati stvarne recenzije kupaca iz sustava eLjekarna24, uključujući kritične. Ne prenositi ocjene s drugih tržišta. [Blok se puni automatski iz sustava recenzija.]

## 6. Često postavljana pitanja (FAQ)

### Je li ova krema dovoljna za vrlo suhu kožu?

Namijenjena je masnoj koži sklonoj nepravilnostima. Ako imaš vrlo suhu kožu ili osjećaj jakog zatezanja, prije kupnje provjeri odgovara li ti tekstura i potraži bogatiju njegu ako je potrebna.

### Mogu li je koristiti ispod šminke?

Prema podacima proizvoda, može se koristiti kao podloga za šminku.

### Kada mogu očekivati promjenu?

Individualno iskustvo može se razlikovati. Ako za točan proizvod postoji klinička procjena s vremenskim okvirom, prikazuje se u bloku Kliničke studije uz uvjete ispitivanja.

### Što ako mi koža postane neugodna ili nadražena?

Prekini s uporabom ako se pojavi izražena nelagoda te se po potrebi obrati ljekarniku ili dermatologu. Provjeri i puni sastav proizvoda.
"""

EXAMPLE_SUPPLEMENT = """# PDP struktura s tabovima: Solgar Vitamin D3 400 IU

## 1. Prvi ekran: Naziv, opis i brzi podatci

### Naziv proizvoda

Solgar Vitamin D3 400 IU, 100 kapsula

### Kratki opis

Dodatak prehrani s 10 µg, odnosno 400 IU vitamina D3 po kapsuli, za odrasle koji žele praktično nadopuniti dnevni unos vitamina D uz obrok.

### Brza traka ispod opisa

tip, namjena, ciljana skupina, područje, tekstura/oblik, pakiranje

- Jedna kapsula sadržava 10 µg, odnosno 400 IU vitamina D3.
- Vitamin D doprinosi normalnoj funkciji imunološkog sustava, pod uvjetima uporabe tvrdnje.
- Vitamin D doprinosi održavanju normalnih kostiju i zuba te normalnoj funkciji mišića.
- Uzima se jedna kapsula dnevno uz obrok; pakiranje može trajati do 100 dana.

## 2. Istaknuti blok iznad tabova

### Dnevna doza na prvi pogled

Iznad tabova prikazuju se ključne informacije o dnevnoj dozi:

| Preporučena doza | Količina vitamina D | Kada se uzima | Trajanje pakiranja |
| --- | --- | --- | --- |
| 1 kapsula dnevno | 10 µg / 400 IU | Uz obrok | Do 100 dana |

## 3. Struktura tabova (Max 6 tabova)

### Tab 1: Opis i prednosti

Ako tražite jednostavan dodatak vitamina D koji se uzima jednom dnevno, Solgar Vitamin D3 400 IU sadržava 10 µg vitamina D3 u jednoj kapsuli. Namijenjen je odraslima koji žele nadopuniti dnevni unos vitamina D uz obrok. Vitamin D doprinosi normalnoj funkciji imunološkog sustava, normalnoj apsorpciji i iskorištavanju kalcija i fosfora te održavanju normalnih kostiju, zuba i funkcije mišića, kada se tvrdnje primjenjuju pod propisanim uvjetima. Pakiranje od 100 kapsula može trajati do 100 dana uz preporučenu uporabu. Dodatak prehrani nije zamjena za raznovrsnu prehranu. Ako ste trudni, dojite, uzimate lijekove ili imate zdravstvene poteškoće, prije uporabe obratite se liječniku ili ljekarniku.

### Tab 2: Doza i kome je namijenjen

- Odraslima koji žele praktično nadopuniti dnevni unos vitamina D.
- Onima koji traže manju dozu od 400 IU po kapsuli, prema deklaraciji proizvoda.
- Preporučena doza: jedna kapsula dnevno uz obrok, prema deklaraciji.

### Tab 3: Kako se uzima?

- Provjeri preporučenu dozu na aktualnom pakiranju.
- Uzmi jednu kapsulu dnevno uz obrok.
- Nemoj prekoračiti preporučenu dnevnu dozu.
- Ako uzimaš lijekove ili druge dodatke s vitaminom D, zatraži savjet liječnika ili ljekarnika.

### Tab 4: Sastojci i sastav

| Istaknuti sastojak | Što to znači za kupca |
| --- | --- |
| Vitamin D3, kolekalciferol | Aktivni oblik naveden na deklaraciji proizvoda. |
| 10 µg / 400 IU po kapsuli | Količina vitamina D u preporučenoj dnevnoj dozi od jedne kapsule. |
| Ulje riblje jetre | Na dostupnom PDP-u navedeno je kao izvor vitamina D; puni sastav treba potvrditi na aktualnom pakiranju. |

Puni sastav kapsule ostaje obvezan i mora se kopirati točno s aktualne deklaracije, bez skraćivanja ili pretpostavljanja pomoćnih tvari.

### Tab 5: Upozorenja i podatci

| Pakiranje | 100 kapsula |
| --- | --- |
| Brend | Solgar |
| Proizvođač / odgovorna osoba | Unijeti točno prema aktualnoj deklaraciji ili PIM-u. |
| Zemlja podrijetla | Navesti samo ako je potvrđena na deklaraciji ili u dokumentaciji točnog proizvoda. |
| EAN | 033984033207 |
| Obvezna provjera prije objave | Naziv dodatka, neto količina, preporučena dnevna doza, aktivne tvari po dnevnoj dozi, puni sastav, upozorenja i odgovorna osoba moraju odgovarati aktualnoj deklaraciji. |

Dodatak prehrani nije zamjena za uravnoteženu i raznovrsnu prehranu ni zdrav način života.

Ne prekoračujte preporučenu dnevnu dozu.

Ako ste trudni, dojite, uzimate lijekove ili imate zdravstvene poteškoće, prije uporabe razgovarajte s liječnikom ili ljekarnikom.

Čuvajte izvan dohvata djece i na sobnoj temperaturi, prema deklaraciji proizvoda.

### Tab 6: Savjet ljekarnika (može voditi dodatno na kontakt prema ljekarniku nakon savjeta)

- Stručni savjet ljekarnika oko upotrebe ovog proizvoda. [Dopuniti iskustvima iz prakse ljekarnika eLjekarna24 prije objave.]
- Mogućnost izravnog kontakta s ljekarnikom za dodatna pitanja.

## 4. Ocjene i recenzije kupaca

Prikazati stvarne recenzije kupaca iz sustava eLjekarna24, uključujući kritične. Ne prenositi ocjene s drugih tržišta. [Blok se puni automatski iz sustava recenzija.]

## 5. Često postavljana pitanja (FAQ)

### Koliko kapsula smijem uzeti dnevno?

Preporučena doza je jedna kapsula dnevno uz obrok, prema deklaraciji. Ne prekoračuj preporučenu dnevnu dozu.

### Mogu li ga uzimati uz druge dodatke s vitaminom D?

Ako uzimaš lijekove ili druge dodatke s vitaminom D, prije uporabe zatraži savjet liječnika ili ljekarnika.

### Koliko traje jedno pakiranje?

Pakiranje od 100 kapsula uz preporučenu dozu od jedne kapsule dnevno može trajati do 100 dana.
"""

EXAMPLE_DEVICE = """# PDP struktura s tabovima: Microlife BP A1 Easy tlakomjer

## 1. Prvi ekran: Naziv, opis i brzi podatci

### Naziv proizvoda

Microlife BP A1 Easy automatski nadlaktični tlakomjer s manšetom 22–42 cm

### Kratki opis

Automatski tlakomjer za kućno mjerenje krvnog tlaka i pulsa na nadlaktici, s upravljanjem jednom tipkom, manšetom za opseg 22–42 cm i osnovnim priborom za početak uporabe.

### Brza traka ispod opisa

tip, namjena, ciljana skupina, pakiranje

- Za jednostavno mjerenje: mjerenje se pokreće jednom tipkom.
- Za pravilan odabir veličine: priložena manšeta odgovara opsegu nadlaktice 22–42 cm.
- Za lakše uočavanje pogreške: indikatori upozoravaju na pokret i nepravilno postavljenu manšetu; PAD može označiti nepravilnost pulsa tijekom mjerenja.
- Za uporabu odmah nakon otvaranja: u kutiji su uređaj, manšeta, četiri AA baterije, torbica i dnevnik mjerenja.

## 2. Istaknuti blok iznad tabova

### Odgovara li vam manšeta?

Prije kupnje izmjerite opseg nadlaktice. Ovaj uređaj dolazi s M-L manšetom koja je prikladna za:

| Mjesto mjerenja | Opseg manšete |
| --- | --- |
| Nadlaktica | 22–42 cm |

## 3. Struktura tabova (Max 6 tabova)

### Tab 1: Opis i prednosti

Ako želite kod kuće pratiti krvni tlak bez složenog podešavanja, Microlife BP A1 Easy automatski je tlakomjer za nadlakticu kojim se upravlja jednom tipkom. Priložena M-L manšeta odgovara opsegu nadlaktice od 22 do 42 cm, pa prije kupnje izmjerite svoju nadlakticu. Uređaj prema opisu proizvoda ima Gentle+ način napuhavanja te indikatore pokreta ruke, nepravilno postavljene manšete i nepravilnosti pulsa tijekom mjerenja. U pakiranju su manšeta, torbica, četiri AA baterije i dnevnik krvnog tlaka. Za usporediva mjerenja važno je svaki put pravilno sjediti, postaviti manšetu prema uputi i ne govoriti tijekom mjerenja. Tlakomjer prikazuje rezultat mjerenja, ali ne postavlja dijagnozu i nije zamjena za liječnički savjet niti razlog za samostalnu promjenu terapije.

### Tab 2: Upute za korištenje?

- Prije kupnje izmjeri opseg nadlaktice i potvrdi da je između 22 i 42 cm.
- Prije mjerenja odmori se, sjedni oslonjenih leđa, stopala položi na pod i ne razgovaraj tijekom mjerenja.
- Postavi manšetu na golu nadlakticu prema ilustraciji u uputi i podupri ruku tako da je manšeta približno u visini srca.
- Pritisni tipku i ostani miran/na dok uređaj ne završi mjerenje.
- Ako se pojavi indikator pokreta ili nepravilno postavljene manšete, provjeri uputu i ponovi mjerenje nakon kratkog odmora.
- Zapiši rezultat u dnevnik. Za tumačenje ponavljanih ili zabrinjavajućih vrijednosti obrati se zdravstvenom djelatniku.

### Tab 3: Funkcije i specifikacije

| Značajka | Što znači u svakodnevnoj uporabi |
| --- | --- |
| M-L manšeta 22–42 cm | Prije kupnje izmjerite opseg nadlaktice. Manšeta koja ne odgovara ruci može otežati pravilno mjerenje. |
| Upravljanje jednom tipkom | Pokretanje mjerenja je jednostavno i ne zahtijeva prolazak kroz složene izbornike. |
| Gentle+ tehnologija | Microlife je opisuje kao prilagodbu napuhavanja manšete radi ugodnijeg mjerenja. |
| PAD indikator | Može označiti nepravilnost pulsa primijećenu tijekom mjerenja. To nije dijagnoza poremećaja srčanog ritma. |
| Indikator pokreta i manšete | Pomaže prepoznati mjerenje koje možda treba ponoviti nakon provjere položaja i upute. |
| Baterije | Uređaj radi na četiri AA baterije. |

### Tab 4: Validacija i dokumentacija

Tehnički list i dostupnu dokumentaciju o validaciji navesti samo prema potvrđenim izvorima za točan model; omogućiti hrvatsku uputu za uporabu.

### Tab 5: Podaci i upute

| Pakiranje | Uređaj, M-L manšeta, torbica, 4 AA baterije i dnevnik krvnog tlaka. |
| --- | --- |
| Brend | Microlife |
| Model / referentna oznaka | BP A1 Easy; tehničku oznaku potvrditi na uređaju, pakiranju i hrvatskoj uputi. |
| Proizvođač / ovlašteni predstavnik | Unijeti točno prema aktualnoj deklaraciji ili PIM-u. |
| Zemlja podrijetla | Navesti samo ako je potvrđena na deklaraciji ili u dokumentaciji točnog proizvoda. |
| EAN | 4719003310646 |
| Jamstvo | Prikazati aktualne uvjete jamstva prema dokumentaciji. |
| Obvezna provjera prije objave | Namjena, upozorenja, pribor i oznake moraju odgovarati točnoj varijanti modela i hrvatskoj uputi. |

Prije prve uporabe pročitajte cijelu hrvatsku uputu za uporabu.

Provjerite odgovara li priložena manšeta opsegu nadlaktice korisnika.

Ne mjerite preko odjeće i ne govorite niti se pomičite tijekom mjerenja.

Pojedinačan rezultat nije dijagnoza. Ne mijenjajte terapiju na temelju kućnog mjerenja bez dogovora sa zdravstvenim stručnjakom.

PAD indikator može označiti nepravilnost pulsa tijekom mjerenja, ali ne dijagnosticira poremećaj srčanog ritma.

### Tab 6: Savjet ljekarnika (može voditi dodatno na kontakt prema ljekarniku nakon savjeta)

- Stručni savjet ljekarnika oko upotrebe ovog proizvoda. [Dopuniti iskustvima iz prakse ljekarnika eLjekarna24 prije objave.]
- Mogućnost izravnog kontakta s ljekarnikom za dodatna pitanja.

## 4. Ocjene i recenzije kupaca

Prikazati stvarne recenzije kupaca iz sustava eLjekarna24, uključujući kritične. Ne prenositi ocjene s drugih tržišta. [Blok se puni automatski iz sustava recenzija.]

## 5. Često postavljana pitanja (FAQ)

### Kako znam odgovara li mi manšeta?

Prije kupnje izmjeri opseg nadlaktice. Priložena M-L manšeta prikladna je za opseg od 22 do 42 cm.

### Što znači PAD indikator?

PAD može označiti nepravilnost pulsa primijećenu tijekom mjerenja. To nije dijagnoza poremećaja srčanog ritma; za tumačenje se obrati zdravstvenom djelatniku.

### Trebam li kupiti baterije?

Ne. U pakiranju su četiri AA baterije, uz torbicu i dnevnik krvnog tlaka.
"""

EXAMPLE_FORMULA = """# PDP struktura s tabovima: NAN 2 Supremepro

## 1. Prvi ekran: Naziv, opis i brzi podatci

### Naziv proizvoda

NAN 2 Supremepro, prijelazna mliječna formula za dojenčad od 6 do 12 mjeseci, 800 g

### Kratki opis

Prijelazna mliječna formula u prahu za zdravu terminski rođenu dojenčad od 6 do 12 mjeseci, prema deklaraciji proizvoda, u pakiranju od 800 g.

### Brza traka ispod opisa

tip, namjena, ciljana skupina, tekstura/oblik, pakiranje

- Za dobnu fazu: jasno označeno 6–12 mjeseci, prema deklaraciji.
- Za transparentan odabir: puni sastav, alergeni i nutritivna tablica prije kupnje.
- Za pravilnu pripremu: tablica hranjenja, točan omjer vode i praha te priložena mjerica.
- Za praktičnu uporabu: pakiranje od 800 g s uputama o zatvaranju i čuvanju.

## 2. Istaknuti blok iznad tabova

### Prije kupnje provjerite

Iznad tabova prikazuju se sigurnosni podaci za roditelja:

| Dobna faza | Tip proizvoda | Alergen | Pakiranje |
| --- | --- | --- | --- |
| 6–12 mjeseci | Prijelazna formula | Sadržava mlijeko | 800 g |

## 3. Struktura tabova (Max 6 tabova)

### Tab 1: Opis i ključne informacije

Ako tražite prijelaznu mliječnu formulu za dijete od 6 do 12 mjeseci, NAN 2 Supremepro prema deklaraciji je namijenjen zdravoj terminski rođenoj dojenčadi u toj dobnoj fazi. Dolazi u limenci od 800 g, a obrok se priprema isključivo prema tablici hranjenja, točnom omjeru vode i praha te uz priloženu mjericu. Formula sadržava mliječni šećer, djelomično hidrolizirane bjelančevine sirutke, biljna ulja, DHA, ARA, vitamine, minerale, oligosaharide i bakterijske kulture, prema deklaraciji proizvoda. Za individualna pitanja o formuli, alergiji, posebnoj prehrani ili dobi djeteta obratite se pedijatru ili ljekarniku.

### Tab 2: Priprema i hranjenje

- Obrok pripremaj isključivo prema tablici hranjenja s aktualne deklaracije, ovisno o dobi djeteta.
- Operi ruke prije pripreme obroka.
- Operi bočicu, dudu i poklopac te pribor prokuhaj prema uputi proizvođača.
- Prokuhaj pitku vodu i ohladi je na približno 40 °C.
- U bočicu ulij točnu količinu vode prema tablici hranjenja i dodaj točan broj ravnih mjerica.
- Upotrebljavaj samo priloženu mjericu, dobro protresi i provjeri temperaturu obroka.
- Limenku nakon uporabe čvrsto zatvori i čuvaj prema uputi na pakiranju.

### Tab 3: Sastav, alergeni i nutritivne vrijednosti

| Sastojak | Objašnjenje za kupca |
| --- | --- |
| Mliječni šećer i bjelančevine sirutke | Osnovne skupine sastojaka prema deklaraciji; formula sadržava mlijeko. |
| Biljna ulja, DHA i ARA | Masnoće navedene na deklaraciji proizvoda. |
| Vitamini i minerali | Prema nutritivnoj tablici na deklaraciji. |
| Oligosaharidi i bakterijske kulture | Sastojci navedeni na deklaraciji proizvoda. |

Puni sastav ide ispod glavnih sastojaka, ali roditelj mora iznad njega odmah vidjeti alergen, glavne skupine sastojaka i upozorenje da se formula ne bira prema jednom istaknutom sastojku.

### Tab 4: Čuvanje i sigurnost

Proizvod se koristi samo prema uputi i tablici hranjenja proizvođača.

Ne mijenjajte omjer praha i vode i ne koristite drugu mjericu.

Dobna oznaka je 6–12 mjeseci, prema deklaraciji proizvoda.

Formula sadržava mlijeko; prije uporabe provjerite sve alergene na aktualnoj deklaraciji.

Dojenje je najbolji način prehrane dojenčeta. Za pitanja o primjeni formule, dobi djeteta ili posebnim potrebama obratite se pedijatru ili ljekarniku.

### Tab 5: Pakiranje i proizvođač (plus ostali obavezni podaci)

| Pakiranje | 800 g |
| --- | --- |
| Brend | NAN |
| Proizvođač / subjekt u poslovanju s hranom | Unijeti točno prema aktualnoj deklaraciji ili PIM-u. |
| Zemlja podrijetla | Navesti samo ako je potvrđena na deklaraciji ili u dokumentaciji točnog proizvoda. |
| EAN | 7613035943742 |
| Rok trajanja i LOT | Kupac ih provjerava na isporučenoj ambalaži; ne unositi statičan datum koji se može razlikovati među serijama. |
| Obvezna provjera prije objave | Točan naziv i faza, neto količina, sastav, alergeni, nutritivna tablica, priprema, čuvanje, upozorenja i odgovorni subjekt moraju odgovarati aktualnoj limenci. |

### Tab 6: Savjet ljekarnika (može voditi dodatno na kontakt prema ljekarniku nakon savjeta)

- Stručni savjet ljekarnika oko upotrebe ovog proizvoda. [Dopuniti iskustvima iz prakse ljekarnika eLjekarna24 prije objave.]
- Mogućnost izravnog kontakta s ljekarnikom za dodatna pitanja.

## 4. Ocjene i recenzije kupaca

Prikazati stvarne recenzije kupaca iz sustava eLjekarna24, uključujući kritične. Ne prenositi ocjene s drugih tržišta. [Blok se puni automatski iz sustava recenzija.]

## 5. Često postavljana pitanja (FAQ)

### Za koju je dob namijenjena ova formula?

Prema deklaraciji, namijenjena je zdravoj terminski rođenoj dojenčadi od 6 do 12 mjeseci, kao prijelazna formula.

### Sadržava li alergene?

Formula sadržava mlijeko. Prije uporabe provjerite sve alergene na aktualnoj deklaraciji.

### Kako se pravilno priprema obrok?

Isključivo prema tablici hranjenja s deklaracije: točan omjer vode i praha, priložena mjerica i provjera temperature obroka prije hranjenja.
"""

EXAMPLES = {
    "cosmetics": EXAMPLE_COSMETICS,
    "supplement": EXAMPLE_SUPPLEMENT,
    "device": EXAMPLE_DEVICE,
    "formula": EXAMPLE_FORMULA,
}


def category_for(sekcija: str, naziv: str = "") -> str:
    key = (sekcija or "").strip().lower()
    if key in SECTION_TO_CATEGORY:
        return SECTION_TO_CATEGORY[key]
    text = f"{key} {naziv}".lower()
    if any(w in text for w in ("tlakomjer", "inhalator", "vaga", "senzor", "adapter",
                               "toplomjer", "uređaj", "uredaj")):
        return "device"
    if any(w in text for w in ("formula", "mliječ", "mlijec")):
        return "formula"
    if any(w in text for w in ("vitamin", "mineral", "kolagen", "glukan", "kapsul",
                               "tablet", "dodatak prehrani")):
        return "supplement"
    return "cosmetics"
