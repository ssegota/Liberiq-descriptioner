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
                               secondary=not getattr(args, "no_secondary", False))
    return page, sources


# ---------------------------------------------------------------------------
# Objedinjeni zapis
# ---------------------------------------------------------------------------

INPUT_COLS = ["Sekcija", "Brend", "SKU", "Naziv", "URL"]

NAME_RE = __import__("re").compile(r"^###\s*Naziv proizvoda\s*$", __import__("re").M)


def canonical_name_from_md(md: str) -> str:
    """Naziv proizvoda iz generiranog PDP-a — title mora počinjati njime
    (klijentova uputa: title se ne gradi iz starog naziva s weba)."""
    m = NAME_RE.search(md or "")
    if not m:
        return ""
    for line in md[m.end():].splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def brand_source_for(sources, brend: str):
    """Izvor 2 za SEO: isključivo službena hrvatska stranica brenda.
    Sve ostalo (druge ljekarne, tražilice, strana tržišta) blokira allowlist."""
    for s in sources:
        if s.kind != P.SECONDARY_LABEL:
            continue
        dopusteno, _razlog = R.je_dopusten(s.url, brend)
        if dopusteno:
            return S.BrandSource(url=s.url, text=s.text[:2000])
    return None


SEO_COLS = ["Title tag", "Title px", "Title znakova", "Meta opis", "Meta px",
            "Meta znakova", "Namjena", "Status", "Pokušaji", "Napomene",
            "Informativno",
            "Korištene specifikacije", "Izvor – eljekarna24", "Izvor – brend",
            "Preuzeto s brend stranice", "Napomena za provjeru",
            "Postojeći title (QA)", "Postojeći meta (QA)"]

PDP_COLS = ["Kategorija predloška", "Status", "Pokušaji",
            "Verifikacija (2. agent)", "Nepotkrijepljene tvrdnje",
            "Ekstrahiranih polja", "Coverage check", "Konflikt izvora",
            "Broj izvora", "Izvori", "MD datoteka", "DOCX datoteka",
            "Napomene"]


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
        rec["Ukupni status"] = "OK"
    else:
        # najozbiljniji status pobjeđuje (klijentove oznake)
        prio = ["GREŠKA", "GREŠKA EKSTRAKCIJE", "NEDOSTAJE PODATAK IZ IZVORA",
                "TREBA PROVJERA"]
        rec["Ukupni status"] = next(
            (s for s in prio if any(str(x).startswith(s) for x in statuses)),
            "TREBA PROVJERA")
    rec["Model"] = model_id
    return rec


KLIJENT_COLS = ["Sekcija", "Brend", "SKU", "Naziv", "URL", "Title tag",
                "Title (px)", "Meta opis", "Meta opis (px)"]

INTERNI_COLS = ["Sekcija", "Brend", "SKU", "Naziv", "URL", "Status",
                "Izvor – eljekarna24", "Izvor – brend", "Preuzeto s brend stranice",
                "Nedostaje", "Konflikti", "Napomena validatora",
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
        napomene = " | ".join(
            x for x in (r.get("SEO Napomene", ""), r.get("PDP Napomene", ""),
                        r.get("PDP Coverage check", ""))
            if x and x != "prolazi" and not str(x).startswith("kontrolor:"))
        redci.append({
            "Sekcija": r.get("Sekcija", ""), "Brend": r.get("Brend", ""),
            "SKU": r.get("SKU", ""), "Naziv": r.get("Naziv", ""),
            "URL": r.get("URL", ""),
            "Status": r.get("Ukupni status", ""),
            "Izvor – eljekarna24": r.get("SEO Izvor – eljekarna24", ""),
            "Izvor – brend": r.get("SEO Izvor – brend", ""),
            "Preuzeto s brend stranice": r.get("SEO Preuzeto s brend stranice", ""),
            "Nedostaje": r.get("PDP Nedostaje", ""),
            "Konflikti": r.get("PDP Konflikt izvora", ""),
            "Napomena validatora": napomene,
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
        for col, width in zip("ABCDEFGHIJKLMNOP",
                              (16, 14, 12, 40, 44, 20, 44, 44, 34, 30, 34, 60,
                               22, 44, 12, 26)):
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
    ap.add_argument("--strogo", action="store_true",
                    help="doslovno po uputama: nedostatak EAN-a ili proizvođača "
                         "i korištenje izvora 2 daju TREBA PROVJERA")
    ap.add_argument("--search-results", type=int, default=3)
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
    ap.add_argument("--retry-review", action="store_true")
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
        for cat in ("cosmetics", "supplement", "device", "formula"):
            print("\n" + "=" * 70 +
                  f"\n PDP — system prompt ({T.CATEGORY_LABELS[cat]})\n" + "=" * 70)
            print(P.build_gen_system(cat))
        print("\n" + "=" * 70 + "\n Kontrolor činjenica — system prompt\n" + "=" * 70)
        print(P.build_verify_system())
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
        print(f"PDP prompt: {len(P.build_gen_system(cat)) + len(P.build_gen_user(p, cat, sources))} znakova")
        return

    config = P.load_bedrock_config()
    client = P.BedrockClient(config)          # isti klijent za oba alata
    print(f"Model (pisac):     {client.model_id}")
    print(f"Model (kontrolor): {client.verify_model_id}")
    print(f"Regija:            {config['BEDROCK_AWS_REGION']}\n")

    done = {} if args.force else load_done(jsonl_path)
    if args.retry_review:
        done = {k: v for k, v in done.items()
                if str(v.get("Ukupni status", "")).startswith("OK")}
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

    from botocore.exceptions import ClientError  # noqa: PLC0415

    try:
        for idx, p in enumerate(todo, start=1):
            cat = categories[p.sku]
            page, sources = gather_shared(p, cat, cache_dir, args)

            seo_res = pdp_res = None
            canonical = ""

            # Upute: ako stranica eljekarna24 nije dohvaćena, status je GREŠKA
            # i ne generira se ni SEO ni PDP.
            if not page.fetched or not sources:
                rec = combined_record(p, None, None, client.model_id, page.fetched)
                rec["Ukupni status"] = "GREŠKA"
                rec["SEO Status"] = "GREŠKA"
                rec["PDP Status"] = "GREŠKA"
                rec["SEO Napomene"] = ("Stranica proizvoda na eljekarna24 nije "
                                       "dohvaćena; sadržaj se ne generira.")
                records[p.sku] = rec
                with jsonl_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"[{idx}/{len(todo)}] {p.sku} {p.naziv[:40]:<40} -> GREŠKA "
                      "(stranica nije dohvaćena)")
                continue

            # PDP ide PRVI: iz njega dolazi kanonski naziv za title
            if args.only in ("pdp", "both"):
                pdp_res, md = P.process_product(
                    p, cat, sources, client, args.max_attempts,
                    do_verify=not args.no_verify,
                    do_extract=not args.no_extract,
                    do_coverage=not args.no_coverage)
                canonical = canonical_name_from_md(md)
                if md.strip():
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

            if args.only in ("seo", "both"):
                seo_res = S.process_product(
                    p, page, client, seen_titles, seen_metas, lock,
                    args.max_attempts, canonical_name=canonical,
                    brand_source=brand_source_for(sources, p.brend))

            rec = combined_record(p, seo_res, pdp_res, client.model_id,
                                  page.fetched)
            records[p.sku] = rec
            with jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

            bits = []
            if seo_res:
                bits.append(f"SEO {seo_res.status} "
                            f"({seo_res.title_px:.0f}px/{seo_res.meta_px:.0f}px)")
            if pdp_res:
                bits.append(f"PDP {pdp_res.status}")
            print(f"[{idx}/{len(todo)}] {p.sku} {p.naziv[:40]:<40} -> "
                  f"{' | '.join(bits)}")
    except ClientError as err:
        print("\nBedrock greška:\n  " + P.explain_client_error(err, config))
        print("Obrađeno je spremljeno u results.jsonl — ponovno pokretanje "
              "nastavlja gdje je stalo.")
        sys.exit(1)

    ordered = [records[p.sku] for p in products if p.sku in records]
    xlsx_path, csv_path = write_index(ordered, out_dir)
    klijent_path = write_klijent_file(ordered, out_dir)
    interni_path = write_interni_file(ordered, out_dir)

    ok = sum(1 for r in ordered if str(r.get("Ukupni status", "")).startswith("OK"))
    print(f"\nGotovo: {ok} OK, {len(ordered) - ok} za provjeru.")
    if args.only in ("pdp", "both"):
        print(f"PDP datoteke: {pdp_dir}/  (MD + DOCX po proizvodu)")
    print(f"Za klijenta: {klijent_path}")
    print(f"Interno:     {interni_path}")
    print(f"Puni indeks: {xlsx_path}")
    if razlozi:
        print("\nNajčešći razlozi za TREBA PROVJERA:")
        for oznaka, broj in sorted(razlozi.items(), key=lambda x: -x[1])[:8]:
            print(f"  {broj:4d}x  {oznaka}")
    if len(ordered) - ok:
        print("Retke koji nisu OK regeneriraj s: --retry-review (ili --sku <SKU>).")


if __name__ == "__main__":
    main()
