#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Uvoz klijentovih dokumenata u predlosci/ i regulativa/.

    python alati/uvezi_predloske.py \
        --templateovi "Template - kategorije ver.11/" \
        --checkliste "Dodaci prehrani, ... cheklista/" \
        --primjeri PDP_opis_NAN_SUPREMEpro_1_800g.docx PDP_opis_Ferozomal_....docx

Potrebno: pandoc (docx/odt -> Markdown), pdftotext (poppler) i pdfplumber
(samo za dokument tvrdnji: pip install pdfplumber).

Što radi:
  - PDP_template_NN_*.docx -> predlosci/kategorije/NN.md (odabir templatea),
    predlosci/opca_pravila.md (iz 01) i predlosci/templateovi/<A–K>.md
    (provjerava da je isti template jednak u svim datotekama),
  - Checklista_*.odt -> predlosci/checkliste/*.md,
  - odobreni primjeri -> predlosci/primjeri/*.md (izvorni tekst; verzija u
    izlaznom formatu u predlosci/primjeri/format/ uređuje se ručno),
  - EFSA- tvrdnje.pdf -> regulativa/tvrdnje_432_2012.json,
  - Pravilnik ... .pdf -> regulativa/nn160_prilog_II.txt i _III.txt.

Nakon uvoza: make test (test_v4.py provjerava da se nazivi tabova i redci
tablice u pdp_templates.TEMPLATE_META slažu s novim templateima).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
P = REPO / "predlosci"
G = REPO / "regulativa"

CHECKLISTE = {
    "dodaci_prehrani": "dodaci_prehrani.md",
    "biljni_dodaci_prehrani": "biljni_dodaci_prehrani.md",
    "djecja_hrana": "djecja_hrana.md",
}


def gfm(path: Path) -> str:
    out = subprocess.run(["pandoc", str(path), "-t", "gfm", "--wrap=none"],
                         check=True, capture_output=True, text=True).stdout
    for a, b in (("\\[", "["), ("\\]", "]"), ("\\*", "*"), ('\\"', '"'),
                 ("\\'", "'"), ("\\|", "|")):
        out = out.replace(a, b)
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


def uvezi_templateove(mapa: Path) -> None:
    templates: dict[str, str] = {}
    for f in sorted(mapa.glob("PDP_template_*.docx")):
        t = gfm(f)
        i = t.index("## Opća pravila")
        j = i + re.search(r"\n## Template ", t[i:]).start()
        nn = f.stem.split("_")[2]
        (P / "kategorije").mkdir(parents=True, exist_ok=True)
        (P / "kategorije" / f"{nn}.md").write_text(t[:i].strip() + "\n", encoding="utf-8")
        if nn == "01":
            (P / "opca_pravila.md").write_text(t[i:j].strip() + "\n", encoding="utf-8")
        for dio in re.split(r"\n(?=## Template )", t[j:]):
            dio = dio.strip()
            if not dio:
                continue
            slovo = re.match(r"## Template (\w)", dio).group(1)
            if slovo in templates and templates[slovo] != dio:
                sys.exit(f"Template {slovo} se razlikuje između datoteka ({f.name}).")
            templates[slovo] = dio
    (P / "templateovi").mkdir(parents=True, exist_ok=True)
    for slovo, tekst in templates.items():
        (P / "templateovi" / f"{slovo}.md").write_text(tekst + "\n", encoding="utf-8")
    print(f"templateovi: {', '.join(sorted(templates))}")


def uvezi_checkliste(mapa: Path) -> None:
    (P / "checkliste").mkdir(parents=True, exist_ok=True)
    for f in sorted(mapa.glob("Checklista_*.odt")):
        kljuc = re.sub(r"^Checklista_za_izradu_PDP_opisa_-_", "", f.stem)
        cilj = CHECKLISTE.get(kljuc, kljuc + ".md")
        t = gfm(f).replace("\\#", "#").replace("\\-", "-").replace("\\_", "_")
        t = re.sub(r"(\|[^\n]*)\n\n(?=\|)", r"\1\n", t)
        (P / "checkliste" / cilj).write_text(t, encoding="utf-8")
        print(f"checklista: {cilj}")
    for f in mapa.glob("*.pdf"):
        if "tvrdnj" in f.name.lower():
            uvezi_tvrdnje(f)
        elif "pravilnik" in f.name.lower():
            uvezi_pravilnik(f)


def uvezi_tvrdnje(pdf: Path) -> None:
    import pdfplumber

    rows = []
    with pdfplumber.open(str(pdf)) as doc:
        for pg in doc.pages:
            for t in pg.extract_tables():
                for r in t:
                    r = [re.sub(r"\s+", " ", (c or "")).strip() for c in r]
                    if any(r) and not (r[0].startswith("Tvrdnja") and "Uvjeti" in " ".join(r)):
                        rows.append((r + ["", "", "", ""])[:4])
    tvrdnje: list[dict] = []
    for r in rows:
        if r[0]:
            tvrdnje.append({"tvrdnja": r[0], "uvjet": r[1], "ogranicenja": r[2]})
        elif tvrdnje:          # nastavak retka s prethodne stranice
            for k, v in zip(("tvrdnja", "uvjet", "ogranicenja"), r[:3]):
                if v:
                    tvrdnje[-1][k] = (tvrdnje[-1][k] + " " + v).strip()
    cisto = []
    for c in tvrdnje:
        c = {k: re.sub(r"[►◄▼]\s*[A-Z]?\d*", "", re.sub(r"\s*\xad\s*", "", v)).strip()
             for k, v in c.items()}
        if len(c["tvrdnja"]) < 15 or c["tvrdnja"].startswith("("):
            continue
        c["uvjet"] = c["uvjet"].split(" Pregled potreba")[0].strip()
        if re.fullmatch(r"[\d,\s]*", c["ogranicenja"]):
            c["ogranicenja"] = ""
        cisto.append(c)
    G.mkdir(exist_ok=True)
    (G / "tvrdnje_432_2012.json").write_text(
        json.dumps(cisto, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"tvrdnje: {len(cisto)}")


def uvezi_pravilnik(pdf: Path) -> None:
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True,
                         capture_output=True, text=True).stdout.splitlines()
    i2 = next(n for n, l in enumerate(txt) if l.strip() == "PRILOG II.")
    i3 = next(n for n, l in enumerate(txt) if l.strip() == "PRILOG III.")
    G.mkdir(exist_ok=True)
    (G / "nn160_prilog_II.txt").write_text("\n".join(txt[i2:i3]) + "\n", encoding="utf-8")
    (G / "nn160_prilog_III.txt").write_text("\n".join(txt[i3:]) + "\n", encoding="utf-8")
    print("pravilnik NN 160/2013: prilozi II. i III.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--templateovi", type=Path)
    ap.add_argument("--checkliste", type=Path)
    ap.add_argument("--primjeri", type=Path, nargs="*", default=[])
    a = ap.parse_args()
    if a.templateovi:
        uvezi_templateove(a.templateovi)
    if a.checkliste:
        uvezi_checkliste(a.checkliste)
    for f in a.primjeri:
        (P / "primjeri").mkdir(parents=True, exist_ok=True)
        (P / "primjeri" / (f.stem + ".md")).write_text(gfm(f), encoding="utf-8")
        print(f"primjer: {f.name}")


if __name__ == "__main__":
    main()
