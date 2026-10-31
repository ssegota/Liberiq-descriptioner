#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Objedinjeni generator sadržaja za eljekarna24 — SEO (title/meta) + PDP opisi
u JEDNOM prolazu, Claude na AWS Bedrocku.

Oba alata rade nad istom ulaznom tablicom, pa ovaj runner:
  1. jednom dohvaća stranicu proizvoda i DIJELI je između oba alata
     (zajednički HTML cache — nema dvostrukog dohvaćanja),
  2. jednim Bedrock klijentom pokreće SEO generiranje (title + meta, piksel
     validacija) i PDP generiranje (pisac + kontrolor činjenica),
  3. piše JEDAN zajednički indeks (XLSX + CSV) sa svim stupcima oba alata,
     jedan results.jsonl (resume za oboje) i PDP datoteke (.md + .docx).

Logika generiranja, validacije i predložaka nije duplicirana — koristi se
izravno iz seo_meta_generator.py i pdp_generator.py.

Pokretanje:
    pip install -r requirements_pdp.txt
    cp .env.example .env
    python generate_all.py --input eljekarna24_proizvodi_75_kom.xlsx

Korisne opcije:
    --only seo | pdp | both   što generirati (zadano: both)
    --limit 2 / --sku C002167 / --dry-run / --force / --retry-review
    --no-web-search / --no-fetch / --no-verify / --search-results 3
    --max-attempts 3 / --refresh-cache
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import pdp_generator as P
import pravila as R
import prompts_cfg
import pdp_templates as T
import seo_meta_generator as S

# ---------------------------------------------------------------------------
# Zajednički dohvat izvora
# ---------------------------------------------------------------------------

def gather_shared(product: P.Product, category: str, cache_dir: Path, args):
    """Vrati (PageData za SEO, list[Source] za PDP) uz jedan dohvat stranice.

    Oba modula keširaju HTML pod istim imenom (sha1 URL-a) u istoj mapi, pa
    drugi poziv čita iz cachea umjesto da ponovno ide na mrežu.
    """
    if args.no_fetch:
        return (S.PageData(fetched=False, note="dohvat isključen (--no-fetch)"), [])

    page = S.fetch_page(product.url, cache_dir, refresh=args.refresh_cache)
    sources = P.gather_sources(product, category, cache_dir,
                               refresh=False,          # HTML je već svjež
                               web_search=not args.no_web_search,
                               max_web=args.search_results,
                               secondary=not getattr(args, "no_secondary", False),
                               pim_dir=Path(args.pim_dir) if args.pim_dir else None)
    # eLjekarna24 je BigCommerce: puni opis (sastav, upute) izvlači PDP
    # ekstraktor iz .pv-desc-source; SEO dobiva isti, potpuniji tekst
    if sources and len(sources[0].text) > len(page.content or ""):
        page.content = sources[0].text[:S.PAGE_CONTENT_CAP * 2]
    return page, sources


# ---------------------------------------------------------------------------
# Objedinjeni zapis
# ---------------------------------------------------------------------------

INPUT_COLS = ["Sekcija", "Brend", "SKU", "Naziv", "URL"]

NAME_RE = __import__("re").compile(r"^###\s*Naziv proizvoda\s*$", __import__("re").M)


def canonical_name_from_md(md: str) -> str:
    """Naziv proizvoda iz generiranog PDP-a — title mora počinjati njime
    (klijentova uputa: title se ne gradi iz starog naziva s weba)."""
    return R.PROVJERITI_RE.sub(lambda m: m.group(1) or "", P.naziv_iz_md(md or "")).strip()


def ugradi_seo(md: str, title: str, meta: str) -> str:
    """Meta title i meta description iz SEO alata (pikselski provjereni)
    upisuju se u tablicu SEO elementi PDP-a, da postoji jedna verzija."""
    def zamijeni(redak: str) -> str:
        celije = redak.strip().strip("|").split("|")
        if len(celije) < 2:
            return redak
        kljuc = celije[0].strip().lower()
        if kljuc == "meta title" and title:
            return f"| Meta title | {title} |"
        if kljuc == "meta description" and meta:
            return f"| Meta description | {meta} |"
        return redak
    return "\n".join(zamijeni(l) if l.strip().startswith("|") else l
                     for l in (md or "").splitlines()) + "\n"


def seo_upute(letter: str, podvrsta: str, md: str) -> str:
    """Pravila za SEO elemente iz templatea + prijedlog iz PDP-a."""
    redovi = ["Meta title: [naziv, vrsta ili oblik, pakiranje]; bez skraćenih "
              "zdravstvenih slogana („za imunitet”, „za srce”, „za energiju”).",
              "Meta description do ~155 znakova; kreće od kuta proizvoda, a zatim "
              "sadrži podatke propisane za kategoriju."]
    if letter == "A":
        redovi.append("Dodatak prehrani: meta description sadrži „dodatak prehrani”, "
                      "glavni sastojak i količinu te pakiranje; bez učinaka.")
    if letter == "C":
        redovi.append("Hrana za dojenčad: meta description sadrži vrstu proizvoda, dob "
                      "i pakiranje; bez ikakvih tvrdnji"
                      + (" (početna formula: i da je za dojenčad od rođenja kada "
                         "dojenje nije moguće)" if podvrsta == T.POCETNA_FORMULA else "")
                      + ".")
    seo = {r[0].lower(): r[1] for r in P.tablica(P.sekcije(md).get("SEO elementi", ""))
           if len(r) > 1}
    if seo.get("meta description"):
        redovi.append("Prijedlog iz PDP opisa (smiješ ga preuzeti ako prolazi pravila): "
                      + seo["meta description"])
    return "\n".join("- " + r for r in redovi)


def brand_source_for(sources, brend: str):
    """Izvor 2 za SEO: isključivo službena hrvatska stranica brenda.
    Sve ostalo (druge ljekarne, tražilice, strana tržišta) blokira allowlist."""
    for s in sources:
        if s.kind == P.KIND_BRAND and R.prioritet_izvora(s.url, brend) == 2:
            return S.BrandSource(url=s.url, text=s.text[:3000])
    return None


SEO_COLS = ["Title tag", "Title px", "Title znakova", "Meta opis", "Meta px",
            "Meta znakova", "Namjena", "Status", "Pokušaji", "Napomene",
            "Informativno",
            "Korištene specifikacije", "Izvor – eljekarna24", "Izvor – brend",
            "Preuzeto s brend stranice", "Napomena za provjeru",
            "Postojeći title (QA)", "Postojeći meta (QA)"]

PDP_COLS = ["Kategorija predloška", "Podvrsta", "Klasifikacija", "Status",
            "Pokušaji", "Verifikacija (2. agent)", "Nepotkrijepljene tvrdnje",
            "Ekstrahiranih polja", "Coverage check", "Konflikt izvora",
            "Nedostaje", "Za provjeru (crveno)", "Regulatorno",
            "Obrazac prve rečenice", "Informativno",
            "Broj izvora", "Izvori", "MD datoteka", "DOCX datoteka",
            "Napomene"]


GRESKE = (P.STATUS_STOP, "GREŠKA")

# Stupci koji su služili samo statusu „TREBA PROVJERA” (ukinut 31. 10. 2026.);
# ostaju u results.jsonl za dijagnostiku, ali ne idu u tablice.
IZOSTAVLJENI = ("Napomene", "Nepotkrijepljene tvrdnje", "Verifikacija (2. agent)",
                "Coverage check", "Pokušaji", "Napomena za provjeru", "Informativno")


def uskladi_status(rec: dict) -> dict:
    """Bez statusa „TREBA PROVJERA”: OK ili OK, PROVJERITI CRVENO (ima crvenih
    oznaka, nedostajućih obveznih podataka ili regulatornih napomena);
    GREŠKA i ZAUSTAVLJENO ostaju."""
    crveno = any(str(rec.get(k, "")).strip() for k in
                  ("PDP Za provjeru (crveno)", "PDP Nedostaje", "PDP Regulatorno"))
    for k in ("SEO Status", "PDP Status"):
        st = str(rec.get(k, "") or "")
        if st and not st.startswith(("OK",) + GRESKE):
            rec[k] = "OK"
    statusi = [str(rec.get(k)) for k in ("SEO Status", "PDP Status") if rec.get(k)]
    greska = next((g for g in statusi if g.startswith(GRESKE)), None)
    if greska:
        rec["Ukupni status"] = greska
    else:
        rec["Ukupni status"] = P.STATUS_PROVJERITI if crveno else "OK"
        if rec.get("PDP Status") == "OK" and crveno:
            rec["PDP Status"] = P.STATUS_PROVJERITI
    return rec


def za_tablicu(rec: dict) -> dict:
    return {k: v for k, v in uskladi_status(dict(rec)).items()
            if not any(k.endswith(i) for i in IZOSTAVLJENI)}


def combined_record(product: P.Product, seo_res, pdp_res, model_id: str,
                    page_fetched: bool) -> dict:
    """Jedan redak: ulaz + SEO stupci (prefiks 'SEO ') + PDP stupci ('PDP ')."""
    rec = {c: getattr(product, c.lower() if c != "URL" else "url")
           for c in INPUT_COLS[:4]}
    rec["URL"] = product.url
    rec["Stranica dohvaćena"] = "da" if page_fetched else "ne"

    if seo_res is not None:
        s = seo_res.to_record()
        for col in SEO_COLS:
            rec[f"SEO {col}"] = s.get(col, "")
    if pdp_res is not None:
        p = pdp_res.to_record()
        for col in PDP_COLS:
            rec[f"PDP {col}"] = p.get(col, "")

    statuses = [rec.get("SEO Status"), rec.get("PDP Status")]
    statuses = [s for s in statuses if s]
    if statuses and all(str(s).startswith("OK") for s in statuses):
        rec["Ukupni status"] = (P.STATUS_PROVJERITI
                                if any(str(s) == P.STATUS_PROVJERITI for s in statuses)
                                else "OK")
    else:
        # najozbiljniji status pobjeđuje (klijentove oznake)
        prio = [P.STATUS_STOP, "GREŠKA", "GREŠKA EKSTRAKCIJE",
                "NEDOSTAJE PODATAK IZ IZVORA", "TREBA PROVJERA"]
        rec["Ukupni status"] = next(
            (s for s in prio if any(str(x).startswith(s) for x in statuses)),
            "TREBA PROVJERA")
    rec["Model"] = model_id
    return uskladi_status(rec)


KLIJENT_COLS = ["Sekcija", "Brend", "SKU", "Naziv", "URL", "Title tag",
                "Title (px)", "Meta opis", "Meta opis (px)"]

INTERNI_COLS = ["Sekcija", "Brend", "SKU", "Naziv", "URL", "Status", "Template",
                "Za provjeru (crveno)", "Regulatorno",
                "Izvor – eljekarna24", "Izvor – brend", "Preuzeto s brend stranice",
                "Nedostaje", "Konflikti",
                "PDP Status", "PDP datoteka", "Trajanje", "Model"]


def write_klijent_file(records: list[dict], out_dir: Path):
    """Datoteka za klijenta: samo title i meta, bez ijednog internog stupca."""
    import pandas as pd

    redci = []
    for r in records:
        if str(r.get("SEO Status", "")) == "GREŠKA":
            continue
        redci.append({
            "Sekcija": r.get("Sekcija", ""), "Brend": r.get("Brend", ""),
            "SKU": r.get("SKU", ""), "Naziv": r.get("Naziv", ""),
            "URL": r.get("URL", ""),
            "Title tag": r.get("SEO Title tag", ""),
            "Title (px)": r.get("SEO Title px", ""),
            "Meta opis": r.get("SEO Meta opis", ""),
            "Meta opis (px)": r.get("SEO Meta px", ""),
        })
    df = pd.DataFrame(redci, columns=KLIJENT_COLS)
    xlsx = out_dir / "title_meta_za_klijenta.xlsx"
    df.to_csv(out_dir / "title_meta_za_klijenta.csv", index=False,
              encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Title i meta")
        ws = w.sheets["Title i meta"]
        for col, width in zip("ABCDEFGHI", (16, 16, 12, 46, 46, 60, 10, 80, 12)):
            ws.column_dimensions[col].width = width
    return xlsx


def write_interni_file(records: list[dict], out_dir: Path):
    """Interna datoteka: statusi, izvori, nedostaci, konflikti, napomene."""
    import pandas as pd

    redci = []
    for r in records:
        redci.append({
            "Sekcija": r.get("Sekcija", ""), "Brend": r.get("Brend", ""),
            "SKU": r.get("SKU", ""), "Naziv": r.get("Naziv", ""),
            "URL": r.get("URL", ""),
            "Status": r.get("Ukupni status", ""),
            "Template": " / ".join(x for x in (r.get("PDP Kategorija predloška", ""),
                                               r.get("PDP Podvrsta", "")) if x),
            "Za provjeru (crveno)": r.get("PDP Za provjeru (crveno)", ""),
            "Regulatorno": r.get("PDP Regulatorno", ""),
            "Izvor – eljekarna24": r.get("SEO Izvor – eljekarna24", ""),
            "Izvor – brend": r.get("SEO Izvor – brend", ""),
            "Preuzeto s brend stranice": r.get("SEO Preuzeto s brend stranice", ""),
            "Nedostaje": " | ".join(x for x in (r.get("PDP Nedostaje", ""),
                                               r.get("SEO Nedostaje", "")) if x),
            "Konflikti": r.get("PDP Konflikt izvora", ""),
            "PDP Status": r.get("PDP Status", ""),
            "PDP datoteka": r.get("PDP DOCX datoteka", ""),
            "Trajanje": r.get("Trajanje", ""),
            "Model": r.get("Model", ""),
        })
    df = pd.DataFrame(redci, columns=INTERNI_COLS)
    xlsx = out_dir / "interno.xlsx"
    df.to_csv(out_dir / "interno.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Interno")
        ws = w.sheets["Interno"]
        for idx, col in enumerate(df.columns, start=1):
            ws.cell(row=1, column=idx).column_letter
        for col, width in zip("ABCDEFGHIJKLMNOPQRS",
                              (16, 14, 12, 40, 44, 20, 24, 60, 50, 44, 44, 34,
                               30, 34, 60, 22, 44, 12, 26)):
            ws.column_dimensions[col].width = width
    return xlsx


def write_index(records: list[dict], out_dir: Path):
    import pandas as pd

    df = pd.DataFrame(records)
    xlsx_path = out_dir / "sadrzaj_indeks.xlsx"
    csv_path = out_dir / "sadrzaj_indeks.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sadržaj")
        ws = writer.sheets["Sadržaj"]
        for idx, col in enumerate(df.columns, start=1):
            letter = ws.cell(row=1, column=idx).column_letter
            if col in ("Naziv", "URL", "SEO Meta opis", "PDP Izvori",
                       "SEO Napomene", "PDP Napomene",
                       "PDP Nepotkrijepljene tvrdnje"):
                width = 50
            elif col.endswith(("px", "znakova", "Pokušaji", "Broj izvora")):
                width = 10
            else:
                width = 24
            ws.column_dimensions[letter].width = width
        ws.freeze_panes = "F2"
    return xlsx_path, csv_path


def load_done(path: Path) -> dict[str, dict]:
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                done[rec["SKU"]] = rec
            except (json.JSONDecodeError, KeyError):
                continue
    return done


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Objedinjeni generator: SEO title/meta + PDP opisi.")
    ap.add_argument("--input", "-i", required=True, help="XLSX ili CSV s proizvodima")
    ap.add_argument("--output", "-o", default="out_all", help="izlazna mapa")
    ap.add_argument("--only", choices=["seo", "pdp", "both"], default="both",
                    help="što generirati (zadano: both)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sku", action="append", default=[])
    ap.add_argument("--max-attempts", type=int, default=4)
    ap.add_argument("--rescue-model", default=None,
                    help="model za dodatne pokušaje kad osnovni ne prođe kontrolu "
                         "(npr. eu.anthropic.claude-opus-5-5; zadano BEDROCK_RESCUE_MODEL_ID)")
    ap.add_argument("--rescue-attempts", type=int, default=2,
                    help="broj dodatnih pokušaja modelom za spašavanje (zadano 2)")
    ap.add_argument("--workers", type=int, default=1,
                    help="broj proizvoda koji se obrađuju istodobno (zadano 1)")
    ap.add_argument("--strogo", action="store_true",
                    help="doslovno po uputama: nedostatak EAN-a ili proizvođača "
                         "i korištenje izvora 2 daju TREBA PROVJERA")
    ap.add_argument("--search-results", type=int, default=3)
    ap.add_argument("--pim-dir", default="",
                    help="mapa s HR ambalažom / deklaracijom / PIM-om (razina 1); "
                         "datoteke se prepoznaju po SKU-u ili EAN-u u nazivu")
    ap.add_argument("--no-web-search", action="store_true")
    ap.add_argument("--no-secondary", action="store_true",
                    help="ne koristi izvor 2 (službenu stranicu brenda)")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--no-extract", action="store_true",
                    help="preskoči strukturiranu ekstrakciju prije pisanja")
    ap.add_argument("--no-coverage", action="store_true",
                    help="preskoči coverage check nakon pisanja")
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--retry-review", action="store_true",
                    help="ponovno obradi samo retke s greškom")
    ap.add_argument("--prompts-dir", default="prompts",
                    help="mapa s vanjskim promptovima/napomenama (zadano: prompts)")
    ap.add_argument("--show-prompts", action="store_true",
                    help="ispiši konačne promptove (s napomenama) i izađi")
    ap.add_argument("--dry-run", action="store_true",
                    help="bez Bedrocka: skupi izvore i prikaži što bi se slalo")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    pdp_dir = out_dir / "pdp"
    pdp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".cache" / "html"       # ZAJEDNIČKI cache
    jsonl_path = out_dir / "results.jsonl"

    prompts_cfg.set_dir(args.prompts_dir)
    aktivne = prompts_cfg.active()
    if aktivne:
        print(f"Promptovi iz mape {args.prompts_dir}/: {', '.join(aktivne)}")

    S.postavi_strogi_nacin(args.strogo)
    P.postavi_strogi_nacin(args.strogo)

    products = P.load_products(Path(args.input))
    if args.sku:
        wanted = {s.strip() for s in args.sku}
        products = [p for p in products if p.sku in wanted]
    if args.limit:
        products = products[: args.limit]
    if not products:
        sys.exit("Nema proizvoda za obradu.")

    categories = {p.sku: T.category_for(p.sekcija, p.naziv) for p in products}
    counts: dict[str, int] = {}
    for cat in categories.values():
        counts[cat] = counts.get(cat, 0) + 1
    print(f"Proizvoda: {len(products)} "
          f"({', '.join(f'{T.CATEGORY_LABELS[k]}: {v}' for k, v in counts.items())})")
    print(f"Generiram: {args.only}")

    if args.show_prompts:
        print("=" * 70 + "\n SEO — system prompt\n" + "=" * 70)
        print(S.build_system_prompt())
        for cat in sorted(set(categories.values())):
            print("\n" + "=" * 70 +
                  f"\n PDP — system prompt ({T.CATEGORY_LABELS[cat]})\n" + "=" * 70)
            print(P.build_gen_system(cat))
        print("\n" + "=" * 70 + "\n Stručna provjera — system prompt (A)\n" + "=" * 70)
        print(P.build_verify_system("A"))
        return

    if args.dry_run:
        p = products[0]
        cat = categories[p.sku]
        page, sources = gather_shared(p, cat, cache_dir, args)
        print(f"\n--- {p.sku} | {T.CATEGORY_LABELS[cat]} ---")
        print(f"Stranica proizvoda: {'da' if page.fetched else 'ne'} "
              f"({len(page.content)} znakova)")
        for s in sources:
            print(f"  [{s.sid}] {s.kind}: {s.url} ({len(s.text)} znakova)")
        print(f"\nSEO prompt: {len(S.build_system_prompt()) + len(S.build_user_message(p, page))} znakova")
        print(f"PDP prompt: {len(P.build_gen_system(cat)) + len(P.build_gen_user(p, cat, '', sources))} znakova")
        return

    config = P.load_bedrock_config()
    client = P.BedrockClient(config)          # isti klijent za oba alata
    if args.rescue_model is not None:
        client.rescue_model_id = args.rescue_model
    print(f"Model (pisac):     {client.model_id}")
    print(f"Model (kontrolor): {client.verify_model_id}")
    if client.rescue_model_id:
        print(f"Model (dodatni pokušaji): {client.rescue_model_id} "
              f"(+{args.rescue_attempts})")
    print(f"Regija:            {config['BEDROCK_AWS_REGION']}\n")

    done = {} if args.force else load_done(jsonl_path)
    if args.retry_review:
        # ponavljaju se samo retci s greškom (TREBA PROVJERA više ne postoji)
        done = {k: v for k, v in done.items()
                if str(uskladi_status(dict(v)).get("Ukupni status", "")).startswith("OK")}
    records: dict[str, dict] = dict(done)
    todo = [p for p in products if p.sku not in records]
    if len(products) - len(todo):
        print(f"Preskačem {len(products) - len(todo)} već obrađenih "
              "(results.jsonl; --force za ponovno).")

    lock = threading.Lock()
    seen_titles: set[str] = set()
    seen_metas: set[str] = set()
    for rec in records.values():
        if str(rec.get("SEO Status", "")).startswith("OK"):
            core = S.TRAILING_SUFFIX_RE.sub("", rec.get("SEO Title tag", ""))
            seen_titles.add(S.norm_compact(core))
            seen_metas.add(S.norm_compact(rec.get("SEO Meta opis", "")))

    # kontrola serije: počeci prve rečenice po templateu (opća pravila)
    zauzeti: dict[str, list[str]] = {}
    for rec in records.values():
        prva = rec.get("PDP Prva rečenica", "")
        if prva:
            zauzeti.setdefault(str(rec.get("PDP Template", "")), []).append(P.pocetak(prva))

    from botocore.exceptions import ClientError  # noqa: PLC0415

    zapis_lock = threading.Lock()

    def zapisi(rec: dict) -> None:
        with zapis_lock:
            records[rec["SKU"]] = rec
            with jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def obradi(idx: int, p) -> None:
        t0 = time.time()
        prije = client.usage_dretve()
        cat = categories[p.sku]
        page, sources = gather_shared(p, cat, cache_dir, args)
        podvrsta = T.podvrsta_heuristika(cat, p.naziv)
        razlog = ""
        if sources and args.only in ("pdp", "both"):
            cat, podvrsta, razlog = P.klasificiraj(p, sources, client)

        seo_res = pdp_res = None
        canonical = md = ""

        # Upute: ako stranica eljekarna24 nije dohvaćena, status je GREŠKA
        # i ne generira se ni SEO ni PDP.
        if not page.fetched or not sources:
            rec = combined_record(p, None, None, client.model_id, page.fetched)
            rec["Ukupni status"] = "GREŠKA"
            rec["SEO Status"] = "GREŠKA"
            rec["PDP Status"] = "GREŠKA"
            rec["SEO Napomene"] = ("Stranica proizvoda na eljekarna24 nije "
                                   "dohvaćena; sadržaj se ne generira.")
            zapisi(rec)
            print(f"[{idx}/{len(todo)}] {p.sku} {p.naziv[:40]:<40} -> GREŠKA "
                  "(stranica nije dohvaćena)")
            return

        # PDP ide PRVI: iz njega dolazi kanonski naziv za title
        if args.only in ("pdp", "both"):
            pdp_res, md = P.process_product(
                p, cat, sources, client, args.max_attempts,
                do_verify=not args.no_verify,
                do_extract=not args.no_extract,
                do_coverage=not args.no_coverage,
                podvrsta=podvrsta,
                zauzeti_poceci=list(zauzeti.get(cat, [])),
                rescue_attempts=args.rescue_attempts)
            pdp_res.klasifikacija = razlog
            canonical = canonical_name_from_md(md)
            if pdp_res.prva_recenica:
                with zapis_lock:
                    zauzeti.setdefault(cat, []).append(P.pocetak(pdp_res.prva_recenica))

        if args.only in ("seo", "both") and (args.only == "seo" or md.strip()):
            seo_res = S.process_product(
                p, page, client, seen_titles, seen_metas, lock,
                args.max_attempts, canonical_name=canonical,
                brand_source=brand_source_for(sources, p.brend),
                dodatne_upute=seo_upute(cat, podvrsta, md))
            if md.strip() and str(seo_res.status).startswith("OK"):
                md = ugradi_seo(md, seo_res.title, seo_res.meta)

        if pdp_res is not None and md.strip():
            stem = f"PDP_{p.sku}_{P.slugify(p.naziv)}"
            md_path = pdp_dir / f"{stem}.md"
            docx_path = pdp_dir / f"{stem}.docx"
            md_path.write_text(md, encoding="utf-8")
            try:
                P.md_to_docx(md, docx_path)
                pdp_res.docx_path = str(docx_path)
            except Exception as err:  # noqa: BLE001
                pdp_res.notes.append(f"DOCX nije zapisan: {err}")
            pdp_res.md_path = str(md_path)

        rec = combined_record(p, seo_res, pdp_res, client.model_id,
                              page.fetched)
        if pdp_res is not None:
            rec["PDP Template"] = cat
            rec["PDP Prva rečenica"] = pdp_res.prva_recenica
        rec["Trajanje"] = f"{time.time() - t0:.0f} s"
        poslije = client.usage_dretve()
        potroseno = {m: {k: v - prije.get(m, {}).get(k, 0) for k, v in u.items()}
                     for m, u in poslije.items()}
        potroseno = {m: u for m, u in potroseno.items() if u.get("poziva")}
        rec["Tokeni"] = json.dumps(potroseno, ensure_ascii=False)
        rec["Trošak USD"] = round(P.trosak_usd(potroseno), 4)
        zapisi(rec)

        bits = []
        if seo_res:
            bits.append(f"SEO {seo_res.status} "
                        f"({seo_res.title_px:.0f}px/{seo_res.meta_px:.0f}px)")
        if pdp_res:
            bits.append(f"PDP {pdp_res.status}")
        print(f"[{idx}/{len(todo)}] {p.sku} {p.naziv[:40]:<40} -> "
              f"{' | '.join(bits)}")

    try:
        if args.workers <= 1:
            for idx, p in enumerate(todo, start=1):
                obradi(idx, p)
        else:
            from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                for fut in [ex.submit(obradi, idx, p)
                            for idx, p in enumerate(todo, start=1)]:
                    fut.result()
    except ClientError as err:
        print("\nBedrock greška:\n  " + P.explain_client_error(err, config))
        print("Obrađeno je spremljeno u results.jsonl — ponovno pokretanje "
              "nastavlja gdje je stalo.")
        sys.exit(1)

    ordered = [records[p.sku] for p in products if p.sku in records]
    if todo:
        (out_dir / "token_usage.json").write_text(json.dumps(
            {"modeli": client.usage, "trosak_usd": round(P.trosak_usd(client.usage), 2),
             "proizvoda": len(todo)}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Tokeni ovog pokretanja: {P.trosak_usd(client.usage):.2f} USD "
              f"({len(todo)} proizvoda) — {out_dir / 'token_usage.json'}")
    ordered = [za_tablicu(r) for r in ordered]
    xlsx_path, csv_path = write_index(ordered, out_dir)
    klijent_path = write_klijent_file(ordered, out_dir)
    interni_path = write_interni_file(ordered, out_dir)

    from collections import Counter  # noqa: PLC0415
    brojac = Counter(str(r.get("Ukupni status", "")) for r in ordered)
    print("\nGotovo: " + ", ".join(f"{v} {k}" for k, v in brojac.most_common()))
    if args.only in ("pdp", "both"):
        print(f"PDP datoteke: {pdp_dir}/  (MD + DOCX po proizvodu)")
    print(f"Za klijenta: {klijent_path}")
    print(f"Interno:     {interni_path}")
    print(f"Puni indeks: {xlsx_path}")
    if any(k.startswith(GRESKE) for k in brojac):
        print("Retke s greškom ponovi s: --retry-review (ili --sku <SKU>).")

if __name__ == "__main__":
    main()
