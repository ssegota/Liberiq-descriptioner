#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mermaid dijagrami za specifikaciju — render u PNG s Liberiq paletom."""

import json
import subprocess
from pathlib import Path

OUT = Path("/home/claude/build/diagrams")
CHROME = "/home/claude/.cache/puppeteer/chrome/linux-131.0.6778.204/chrome-linux64/chrome"

# Liberiq paleta (sa stranice: topli gradijent + crna tipografija na bijeloj)
INK = "#0A0A0A"
AMBER = "#FFB020"
ORANGE = "#FF7A1A"
CORAL = "#FF5C39"
PINK = "#FF6F91"
YELLOW = "#FFD54A"
SOFT_Y = "#FFF3D6"
SOFT_O = "#FFE6D5"
SOFT_P = "#FFE1E7"
GREY = "#6B6B6B"
LINE = "#E2E2E2"

THEME = {
    "theme": "base",
    "themeVariables": {
        "fontFamily": "DejaVu Sans, Helvetica, Arial, sans-serif",
        "fontSize": "15px",
        "primaryColor": SOFT_Y,
        "primaryTextColor": INK,
        "primaryBorderColor": AMBER,
        "lineColor": CORAL,
        "secondaryColor": SOFT_O,
        "tertiaryColor": SOFT_P,
        "clusterBkg": "#FFFFFF",
        "clusterBorder": LINE,
        "edgeLabelBackground": "#FFFFFF",
        "textColor": INK,
    },
    "flowchart": {"curve": "basis", "padding": 14, "nodeSpacing": 42,
                  "rankSpacing": 46, "useMaxWidth": False},
    "sequence": {"useMaxWidth": False, "actorFontSize": 14, "noteFontSize": 13,
                 "messageFontSize": 13},
}

CLASSES = f"""
classDef ulaz fill:{SOFT_Y},stroke:{AMBER},stroke-width:2px,color:{INK};
classDef izvor fill:{SOFT_O},stroke:{ORANGE},stroke-width:2px,color:{INK};
classDef obrada fill:#FFFFFF,stroke:{CORAL},stroke-width:2px,color:{INK};
classDef kontrola fill:{SOFT_P},stroke:{PINK},stroke-width:2px,color:{INK};
classDef izlaz fill:{INK},stroke:{INK},stroke-width:2px,color:#FFFFFF;
classDef status fill:#FFFFFF,stroke:{GREY},stroke-width:1.5px,color:{INK};
"""

DIAGRAMS = {
# --------------------------------------------------------------- 1. pregled
"tok_pregled": f"""flowchart TB
    IN["Ulazna tablica<br/><b>XLSX / CSV</b>"]:::ulaz
    SRC["Prikupljanje izvora<br/><i>jedan dohvat, dijeljeni cache</i>"]:::izvor
    PDP["<b>PDP generator</b><br/>ekstrakcija → pisac → kontrole"]:::obrada
    SEO["<b>SEO generator</b><br/>title + meta → pikselska kontrola"]:::obrada
    XLSX["sadrzaj_indeks.xlsx"]:::izlaz
    DOCS["PDP opisi<br/>.md + .docx"]:::izlaz

    IN --> SRC
    SRC --> PDP
    SRC --> SEO
    PDP -- "kanonski naziv proizvoda" --> SEO
    PDP --> DOCS
    PDP --> XLSX
    SEO --> XLSX
{CLASSES}""",

# ------------------------------------------------------------- 2. izvori
"hijerarhija_izvora": f"""flowchart LR
    P["<b>Prioritet 1</b><br/>stranica proizvoda<br/>s linka iz tablice"]:::ulaz
    S["<b>Prioritet 2</b><br/>webljekarna<br/>.vasezdravlje.com"]:::izvor
    T["<b>Prioritet 3</b><br/>ostali web izvori<br/><i>SEO: samo brend</i>"]:::kontrola
    Q{{"Podatak<br/>pronađen?"}}:::status
    U["Koristi vrijednost<br/>višeg prioriteta"]:::obrada
    C["<b>CONFLICT / REVIEW</b><br/>konflikt se označava,<br/>ne spaja se"]:::izlaz

    P -->|"nema podatka"| S
    S -->|"nema podatka"| T
    P --> Q
    S --> Q
    T --> Q
    Q -->|"da"| U
    U -->|"vrijednosti se razlikuju"| C
{CLASSES}""",

# ---------------------------------------------------------------- 3. PDP tok
"pdp_tok": f"""flowchart TB
    SRC["Izvori S1…Sn"]:::izvor
    EX["<b>1. Strukturirana ekstrakcija</b><br/>inventar činjenica<br/><i>vrijednost · izvor · status</i>"]:::obrada
    W["<b>2. Pisac</b><br/>PDP prema predlošku kategorije"]:::obrada
    F["<b>3. Kontrola formata</b><br/>struktura, tabovi, obvezne fraze"]:::kontrola
    FC["<b>4. Kontrolor činjenica</b><br/>je li sve potkrijepljeno?"]:::kontrola
    CC["<b>5. Coverage check</b><br/>je li išta izgubljeno?"]:::kontrola
    OK["<b>OK</b><br/>.md + .docx"]:::izlaz
    R["Popis grešaka<br/>natrag pisci"]:::status

    SRC --> EX --> W --> F
    F -->|"prolazi"| FC
    FC -->|"prolazi"| CC
    CC -->|"prolazi"| OK
    F -->|"greška"| R
    FC -->|"nepotkrijepljena tvrdnja"| R
    CC -->|"izgubljen podatak"| R
    R -.->|"do 3 kruga"| W
{CLASSES}""",

# ---------------------------------------------------------------- 4. SEO tok
"seo_tok": f"""flowchart TB
    IN["Kanonski naziv iz PDP-a<br/>+ stranica proizvoda"]:::ulaz
    G["<b>Generiranje</b><br/>title · meta · namjena"]:::obrada
    V["<b>Kontrola pravila</b><br/>pikseli, količina, namjena,<br/>zabranjeni izrazi"]:::kontrola
    D{{"Samo problem<br/>duljine?"}}:::status
    TR["<b>Skraćivanje</b><br/>uklanja sporedno,<br/><b>čuva količinu</b>"]:::obrada
    OK["<b>OK</b><br/>title ≤ 550 px<br/>meta ≤ 960 px"]:::izlaz
    R["Popis prekršenih pravila"]:::status

    IN --> G --> V
    V -->|"prolazi"| OK
    V -->|"ne prolazi"| D
    D -->|"da"| TR --> OK
    D -->|"ne"| R
    R -.->|"do 3 kruga"| G
{CLASSES}""",

# ------------------------------------------------------------- 5. statusi
"statusi": f"""flowchart LR
    START["Obrađen proizvod"]:::ulaz
    Q1{{"Struktura i<br/>pravila?"}}:::status
    Q2{{"Tvrdnje<br/>potkrijepljene?"}}:::status
    Q3{{"Podaci<br/>sačuvani?"}}:::status
    Q4{{"Konflikt<br/>izvora?"}}:::status
    OK["<b>OK</b>"]:::izlaz
    E1["TREBA PROVJERA"]:::kontrola
    E2["NEDOSTAJE PODATAK<br/>IZ IZVORA"]:::kontrola
    E3["CONFLICT / REVIEW"]:::kontrola

    START --> Q1
    Q1 -->|"ne"| E1
    Q1 -->|"da"| Q2
    Q2 -->|"ne"| E1
    Q2 -->|"da"| Q3
    Q3 -->|"ne"| E2
    Q3 -->|"da"| Q4
    Q4 -->|"da"| E3
    Q4 -->|"ne"| OK
{CLASSES}""",

# --------------------------------------------------- 6. slijed poziva modelu
"pozivi": f"""sequenceDiagram
    autonumber
    participant R as Runner
    participant W as Web izvori
    participant B as Claude (pisac)
    participant V as Claude (kontrolor)

    R->>W: dohvat izvora po prioritetu
    W-->>R: sadržaj S1…Sn
    R->>B: ekstrakcija činjenica
    B-->>R: inventar (FOUND / CONFLICT / NOT FOUND)
    R->>B: pisanje PDP-a uz inventar
    B-->>R: PDP dokument
    R->>R: kontrola formata
    R->>V: provjera činjenica
    V-->>R: presuda + nepotkrijepljene tvrdnje
    R->>R: coverage check
    R->>B: title i meta uz kanonski naziv
    B-->>R: title · meta · namjena
    R->>R: pikselska kontrola i skraćivanje
""",
}


def render():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = OUT / "_theme.json"
    cfg.write_text(json.dumps(THEME), encoding="utf-8")
    pcfg = OUT / "_puppeteer.json"
    pcfg.write_text(json.dumps({"executablePath": CHROME,
                                "args": ["--no-sandbox", "--disable-dev-shm-usage",
                                         "--disable-gpu"]}), encoding="utf-8")
    made = []
    for name, src in DIAGRAMS.items():
        mmd = OUT / f"{name}.mmd"
        png = OUT / f"{name}.png"
        mmd.write_text(src, encoding="utf-8")
        cmd = ["mmdc", "-i", str(mmd), "-o", str(png), "-c", str(cfg),
               "-p", str(pcfg), "-b", "transparent", "-s", "3"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if png.exists():
            made.append((name, png.stat().st_size))
        else:
            print(f"GREŠKA {name}: {res.stderr[-400:]}")
    return made


if __name__ == "__main__":
    for name, size in render():
        print(f"{name:22s} {size/1024:7.1f} kB")
