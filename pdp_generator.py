#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generator PDP opisa za eLjekarna24 prema PDP templateima verzije 11
(Claude na AWS Bedrocku).

Za svaki proizvod iz ulazne tablice (Sekcija, Brend, SKU, Naziv, URL):

  1. IZVORI po razinama iz općih pravila templatea:
       razina 1  HR ambalaža / deklaracija / PIM (lokalne datoteke, --pim-dir)
       razina 2  eLjekarna24 (URL iz tablice) i službena stranica brenda
       razina 3  Vaše zdravlje, Prima Pharme; za kozmetiku i parfeme i
                 Notino, MAKEUP, Douglas — samo za usporedbu, tekst se ne kopira
  2. KLASIFIKACIJA: koji template (A–K) i koja podvrsta (npr. početna formula,
     biljni dodatak prehrani) — prema uputi „Koji template se koristi” iz
     dokumenta kategorije i deklaraciji proizvoda.
  3. EKSTRAKCIJA činjenica (inventar) + provjera je li svaki izvor isti
     proizvod i pakiranje.
  4. REGULATIVA u kodu (regulativa.py): % PU, dopuštene tvrdnje iz Uredbe
     432/2012 s provjerenim uvjetom, najveće doze (NN 160/2013), zabranjene
     biljke, obrazac prve rečenice prema EAN-u.
  5. PISAC: dobiva doslovno opća pravila, template, checklistu kategorije i
     odobreni primjer, uz izračune iz koraka 4.
  6. DETERMINISTIČKA KONTROLA: struktura, tabovi, tablica podataka, obvezne
     napomene, blok tvrdnji (svaka tvrdnja mora biti iz dokumenta tvrdnji),
     zabranjene fraze, navođenje izvora, kopiranje s drugih webshopova,
     šablonski počeci, kontrola serije.
  7. STRUČNA PROVJERA (drugi agent): činjenice prema izvorima i regulatorna
     pravila kategorije; greške se vraćaju piscu.
  8. IZLAZ: PDP_<SKU>_<naziv>.md i .docx (neprovjereni podaci crvenom bojom,
     u MD-u kao [PROVJERITI: …]) + tablica izvora na kraju dokumenta.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import pdp_extract as X
import pdp_templates as T
import pravila as R
import prompts_cfg
import regulativa as G

# ---------------------------------------------------------------------------
# Konstante
# ---------------------------------------------------------------------------

GEN_MAX_TOKENS = 8000
GEN_TEMPERATURE = 0.3
VERIFY_MAX_TOKENS = 3000
EXTRACT_MAX_TOKENS = 8000
VERIFY_TEMPERATURE = 0.0
THINKING_HEADROOM = 16000     # modeli koji uvijek razmišljaju (Opus 5.5)
# modeli koji ne primaju temperature i uvijek razmišljaju
NOVI_MODEL_RE = re.compile(r"opus-(4-[78]|5)|sonnet-5|fable|mythos")

# USD po milijunu tokena: ulaz, izlaz, čitanje iz cachea, upis u cache.
# Cjenik Anthropica (listopad 2026.); Bedrock je partnerski cjenik, provjeriti
# na aws.amazon.com/bedrock/pricing prije ponude klijentu.
CIJENE = {
    "opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "opus-5": (5.00, 25.00, 0.50, 6.25),
    "opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "sonnet-5": (2.00, 10.00, 0.20, 2.50),
    "sonnet-4-6": (3.00, 15.00, 0.30, 3.75),
    "haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def trosak_usd(usage: dict[str, dict[str, int]]) -> float:
    """Trošak u USD za {model: {input, output, cache_read, cache_write}}."""
    ukupno = 0.0
    for model, u in usage.items():
        cijena = next((v for k, v in sorted(CIJENE.items(), key=lambda x: -len(x[0]))
                       if k in model), None)
        if cijena is None:
            continue
        ukupno += (u.get("input", 0) * cijena[0] + u.get("output", 0) * cijena[1]
                   + u.get("cache_read", 0) * cijena[2]
                   + u.get("cache_write", 0) * cijena[3]) / 1e6
    return ukupno
BEDROCK_RETRIES = 6

# Strogi način (--strogo): svaki crveno označeni podatak daje TREBA PROVJERA.
STROGI_NACIN = False


def postavi_strogi_nacin(vrijednost: bool) -> None:
    global STROGI_NACIN
    STROGI_NACIN = bool(vrijednost)


PAGE_CONTENT_CAP = 16000      # znakova sa stranice proizvoda (eLjekarna24)
WEB_SOURCE_CAP = 9000         # znakova po ostalom izvoru
LOCAL_SOURCE_CAP = 30000      # PIM / deklaracija

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 eljekarna24-interni-pdp-alat"
)

KIND_PIM = "ambalaža / deklaracija / PIM"
KIND_PRIMARY = "stranica proizvoda"           # eLjekarna24 (zadržan naziv)
KIND_BRAND = "službena stranica brenda"
KIND_COMPARE = "usporedni izvor"

# zadržano zbog kompatibilnosti sa starim zapisima
SECONDARY_LABEL = KIND_BRAND
TERTIARY_LABEL = KIND_COMPARE

STATUS_OK = "OK"
STATUS_PROVJERITI = "OK, PROVJERITI CRVENO"
STATUS_REVIEW = "TREBA PROVJERA"
STATUS_STOP = "ZAUSTAVLJENO"

# ---------------------------------------------------------------------------
# Normalizacija
# ---------------------------------------------------------------------------

def strip_diacritics(s: str) -> str:
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)
    )


def norm_compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_diacritics(s).lower())


def norm_spaced(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", strip_diacritics(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def slugify(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", strip_diacritics(s).lower()).strip("-")
    return s[:max_len].rstrip("-") or "proizvod"


def danas_hr() -> str:
    d = dt.date.today()
    return f"{d.day}. {d.month}. {d.year}."


# ---------------------------------------------------------------------------
# Zabranjeni izrazi (trgovina, superlativi, apsolutne tvrdnje)
# ---------------------------------------------------------------------------

EXEMPT_PATTERNS = [
    re.compile(r"dojenje je najbolji nacin prehrane\w*"),
    re.compile(r"majcino mlijeko najbolja je hrana\w*"),
    re.compile(r"\bnajvise\b"), re.compile(r"\bnajmanje\b"),
    re.compile(r"\bnajkasnije\b"), re.compile(r"\bnajranije\b"),
    re.compile(r"lijecnik\w*|lijecnick\w*"),
]

FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(p), label) for p, label in [
        (r"\bcijen\w*", "cijena"),
        (r"\b\d+[.,]?\d*\s*(kn|eur)\b", "cijena/valuta"),
        (r"\bakcij\w*", "akcija/promo"),
        (r"\bpopust\w*", "popust"),
        (r"\bsnizen\w*", "sniženje"),
        (r"\bgratis\b", "gratis/promo"),
        (r"\bdostav\w*", "dostava"),
        (r"\bna zalihi\b", "zaliha"),
        (r"\bkosaric\w*", "košarica"),
        (r"\bnaruc\w*", "CTA: naruči"),
        (r"\bkupi(te)?\b", "CTA: kupi"),
        (r"\bkliknite\b", "CTA"),
        (r"\bsaznajte\b", "CTA"),
        (r"\bnajbolj\w*", "superlativ"),
        (r"\bnajkvalitetnij\w*", "superlativ"),
        (r"\bvrhunsk\w*", "superlativ"),
        (r"\bsavrsen\w*", "superlativ"),
        (r"\bidealn?\w*", "idealan"),
        (r"\bnajucinkovitij\w*", "definitivna tvrdnja"),
        (r"\bnajsigurnij\w*", "definitivna tvrdnja"),
        (r"\bnaj\w{3,}(iji|ija|ije|ijeg|ijem)\b", "superlativ"),
        (r"\bnema premca\b", "definitivna tvrdnja"),
        (r"\bzlatni standard\b", "definitivna tvrdnja"),
        (r"\buvijek djeluje\b", "apsolutna tvrdnja"),
        (r"\bprvi izbor\b", "definitivna tvrdnja"),
        (r"\bapsolutno\b", "apsolutna tvrdnja"),
        (r"\bsvima odgovara\b", "apsolutna tvrdnja"),
        (r"\btrenutn\w* rezultat\w*", "obećanje rezultata"),
        (r"\bpotpuna zastita\b|\bblokira sunce\b|\b100 ?% zastit\w*",
         "zabranjena tvrdnja o zaštiti od sunca"),
        (r"\bdokazano djeluje\b", "tvrdnja bez metode"),
        (r"\bjamci\w*", "jamstvo/tvrdnja"),
        (r"\bgarantira\w*", "jamstvo/tvrdnja"),
        (r"\bpatentiran\w*|\bnajnoviji\w*|\bnajnapredniji\w*", "pridjev koji hvali proizvod"),
    ]
]

# Skraćeni zdravstveni slogani (SEO, H1, podnaslovi, brza traka).
SLOGAN_RE = re.compile(r"\b(za|protiv) (imunitet\w*|srce|energij\w*|razvoj\w*|kosti|"
                       r"probav\w*|umor\w*|san|spavanje|mozak|pamcenj\w*)\b")


def find_forbidden(text: str) -> list[str]:
    normed = norm_spaced(text)
    for pat in EXEMPT_PATTERNS:
        normed = pat.sub(" ", normed)
    hits = []
    for pat, label in FORBIDDEN_PATTERNS:
        m = pat.search(normed)
        if m:
            hits.append(f"'{m.group(0)}' ({label})")
    if "€" in text:
        hits.append("'€' (cijena/valuta)")
    return hits


SPEC_TOKEN_RE = re.compile(
    r"\b(\d+(?:d\d+)?)\s*"
    r"(ml|mg|g|kg|l|mcg|µg|iu|ie|kom|cm|kapsul\w*|tablet\w*|vrecic\w*)\b"
)
SPF_RE = re.compile(r"\bspf\s*(\d+\+?)\b")
UNIT_STEMS = ("kapsul", "tablet", "vrecic")


def spec_tokens(text: str) -> set[str]:
    text = re.sub(r"(?m)^\s*\d+\.\s+", " ", text or "")       # „2. Kapsulu uzmite…”
    text = re.sub(r"(\d)[.,](\d)", r"\1d\2", text)             # 2,5 -> 2d5 (decimale)
    normed = norm_spaced(text.replace("µg", " mcg").replace("μg", " mcg"))
    out = set()
    for num, unit in SPEC_TOKEN_RE.findall(normed):
        for stem in UNIT_STEMS:
            if unit.startswith(stem):
                unit = stem
                break
        if "d" in num:                                         # 2d50 -> 2.5
            num = num.replace("d", ".").rstrip("0").rstrip(".")
        out.add(num + unit)
    for val in SPF_RE.findall(normed):
        out.add("spf" + val)
    return out


# ---------------------------------------------------------------------------
# Podatkovni modeli
# ---------------------------------------------------------------------------

@dataclass
class Product:
    sekcija: str
    brend: str
    sku: str
    naziv: str
    url: str


@dataclass
class Source:
    sid: str
    kind: str
    url: str
    title: str = ""
    text: str = ""
    razina: int = 2
    datum: str = field(default_factory=danas_hr)

    @property
    def usporedni(self) -> bool:
        return self.kind == KIND_COMPARE


@dataclass
class RowResult:
    product: Product
    category: str = ""
    podvrsta: str = ""
    klasifikacija: str = ""
    status: str = STATUS_REVIEW
    attempts: int = 0
    verified: str = "-"
    unsupported: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    md_path: str = ""
    docx_path: str = ""
    model_id: str = ""
    inventory: object = None
    coverage: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    nedostaje: list = field(default_factory=list)
    provjeriti: list = field(default_factory=list)
    regulatorno: list = field(default_factory=list)
    info: list = field(default_factory=list)
    prva_recenica: str = ""
    obrazac: str = ""

    def to_record(self) -> dict:
        return {
            "Sekcija": self.product.sekcija,
            "Brend": self.product.brend,
            "SKU": self.product.sku,
            "Naziv": self.product.naziv,
            "URL": self.product.url,
            "Kategorija predloška": T.CATEGORY_LABELS.get(self.category, self.category),
            "Podvrsta": self.podvrsta,
            "Klasifikacija": self.klasifikacija,
            "Status": self.status,
            "Pokušaji": self.attempts,
            "Verifikacija (2. agent)": self.verified,
            "Nepotkrijepljene tvrdnje": " | ".join(self.unsupported),
            "Ekstrahiranih polja": (len(self.inventory.found())
                                    if self.inventory else 0),
            "Coverage check": ("prolazi" if not self.coverage else
                               " | ".join(self.coverage[:4])),
            "Konflikt izvora": " | ".join(self.conflicts),
            "Nedostaje": " | ".join(self.nedostaje),
            "Za provjeru (crveno)": " | ".join(self.provjeriti),
            "Regulatorno": " | ".join(self.regulatorno),
            "Obrazac prve rečenice": self.obrazac,
            "Informativno": " | ".join(self.info),
            "Broj izvora": len(self.sources),
            "Izvori": " | ".join(f"{s.sid} {s.kind}: {s.url}" for s in self.sources),
            "MD datoteka": self.md_path,
            "DOCX datoteka": self.docx_path,
            "Napomene": " | ".join(self.notes),
            "Model": self.model_id,
        }


# ---------------------------------------------------------------------------
# Dohvat izvora
# ---------------------------------------------------------------------------

def _cache_get_or_fetch(url: str, cache_dir: Path, refresh: bool,
                        timeout: int = 25) -> str | None:
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if cache_file.exists() and not refresh:
        return cache_file.read_text(encoding="utf-8", errors="ignore")
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT,
                                          "Accept-Language": "hr,en;q=0.8"},
                            timeout=timeout)
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("Content-Type", "text/html"):
            return None
        cache_file.write_text(resp.text, encoding="utf-8", errors="ignore")
        return resp.text
    except Exception:  # noqa: BLE001 — izvor koji ne radi preskačemo
        return None


def _jsonld_products(soup) -> list[dict]:
    found = []

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if "Product" in [str(x) for x in types]:
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(tag.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def _structured_text(el) -> str:
    """Tekst elementa sa sačuvanim odlomcima, natuknicama i tablicama."""
    from bs4 import NavigableString

    out: list[str] = []

    def walk(node):
        if isinstance(node, NavigableString):
            out.append(str(node))
            return
        name = getattr(node, "name", "")
        if name in ("script", "style", "noscript", "svg", "button", "form"):
            return
        if name == "tr":
            cells = [c.get_text(" ", strip=True) for c in node.find_all(["th", "td"])]
            out.append("\n| " + " | ".join(cells) + " |")
            return
        if name == "br":
            out.append("\n")
            return
        if name == "li":
            out.append("\n- ")
        if name in ("p", "div", "ul", "ol", "table", "h1", "h2", "h3", "h4",
                    "h5", "section", "dl"):
            out.append("\n")
        for child in node.children:
            walk(child)
        if name in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "dt", "dd"):
            out.append("\n")

    walk(el)
    text = "".join(out).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"(?m)^-\n+", "- ", text)          # <li><p>…</p></li>
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# eLjekarna24 je BigCommerce: cijeli opis je u .pv-desc-source (tabovi se
# slažu JavaScriptom), kratki opis u .pv-desc-short, EAN u polju UPC.
ELJ_SELECTORS = [".pv-desc-short", ".pv-desc-source"]
LEGACY_SELECTORS = [
    ".woocommerce-product-details__short-description",
    ".woocommerce-Tabs-panel--description", "#tab-description",
    "[itemprop='description']", ".product-description", "#description",
    ".productView-description",
]


def extract_product_page(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []

    title = soup.select_one(".productView-title, h1")
    if title:
        parts.append("NAZIV NA STRANICI: " + title.get_text(" ", strip=True))
    brand = soup.select_one(".productView-brand, .product-brand")
    if brand:
        parts.append("BREND: " + brand.get_text(" ", strip=True))
    info = soup.select_one(".productView-info")
    if info:
        names = [n.get_text(" ", strip=True).rstrip(":")
                 for n in info.select(".productView-info-name")]
        values = [v.get_text(" ", strip=True)
                  for v in info.select(".productView-info-value")]
        for n, v in zip(names, values):
            if n.upper() == "UPC" and v:
                parts.append(f"EAN (UPC na stranici): {v}")
    for sel in ELJ_SELECTORS + LEGACY_SELECTORS:
        for el in soup.select(sel):
            txt = _structured_text(el)
            if len(txt) > 40:
                parts.append(txt)
    if len(" ".join(parts)) < 400:
        for prod in _jsonld_products(soup):
            desc = prod.get("description") or ""
            if desc:
                parts.append(BeautifulSoup(str(desc), "html.parser")
                             .get_text("\n", strip=True))
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            parts.append(" ".join(og["content"].split()))
    for table in soup.select("table.woocommerce-product-attributes, "
                             "table.shop_attributes, .productView-specs table"):
        parts.append(_structured_text(table))
    if not parts:
        main = soup.find("main") or soup.find("article") or soup.body
        if main:
            parts.append(_structured_text(main))

    seen, blocks = set(), []
    for part in parts:
        key = norm_compact(part)[:200]
        if key in seen:
            continue
        seen.add(key)
        blocks.append(part)
    return "\n\n".join(blocks)[:PAGE_CONTENT_CAP]


def ean_sa_stranice(text: str) -> str:
    m = re.search(r"EAN \(UPC na stranici\):\s*(\d{8,14})", text or "")
    return m.group(1) if m else ""


def extract_generic_page(html: str) -> tuple[str, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = " ".join(soup.title.get_text().split()) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                     "form", "iframe", "aside"]):
        tag.decompose()
    main = (soup.select_one("[itemtype*='Product']") or soup.find("main")
            or soup.find("article") or soup.body)
    text = _structured_text(main) if main else ""
    return title, text[:WEB_SOURCE_CAP]


def _ddgs():
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        return DDGS
    except ImportError:
        return None


def site_search_url(product: Product, domain: str) -> str | None:
    """Stranica ovog proizvoda na zadanoj domeni (site: pretraga)."""
    DDGS = _ddgs()
    if DDGS is None:
        return None
    query = f"site:{domain} {product.naziv}".strip()
    if product.brend and norm_compact(product.brend) not in norm_compact(product.naziv):
        query = f"site:{domain} {product.brend} {product.naziv}"
    try:
        with DDGS() as ddgs:
            for hit in ddgs.text(query, region="hr-hr", max_results=6) or []:
                href = hit.get("href") or hit.get("url") or ""
                if href.startswith("http") and domain in urlparse(href).netloc.lower():
                    return href
    except Exception:  # noqa: BLE001 — pretraga je neobavezna
        return None
    return None


def brand_site_urls(product: Product, max_urls: int = 1) -> list[str]:
    """Stranica proizvoda na službenoj stranici brenda: prvo poznate HR domene
    (pravila.BREND_DOMENE), zatim opća pretraga ograničena na domene brenda."""
    domene = [d for d in R.BREND_DOMENE.get(R._norm_brend(product.brend), ())]
    nadjeno: list[str] = []
    for domena in domene:
        url = site_search_url(product, domena)
        if url and R.je_stranica_brenda(url, product.brend):
            nadjeno.append(url)
        if len(nadjeno) >= max_urls:
            return nadjeno
    DDGS = _ddgs()
    if DDGS is None or nadjeno:
        return nadjeno
    naziv = product.naziv
    if product.brend and norm_compact(product.brend) not in norm_compact(naziv):
        naziv = f"{product.brend} {naziv}"
    try:
        with DDGS() as ddgs:
            for hit in ddgs.text(naziv, region="hr-hr", max_results=10) or []:
                href = hit.get("href") or hit.get("url") or ""
                if href.startswith("http") and R.je_stranica_brenda(href, product.brend):
                    nadjeno.append(href)
                    break
    except Exception:  # noqa: BLE001 — pretraga je neobavezna
        pass
    return nadjeno[:max_urls]


def load_local_sources(product: Product, pim_dir: Path | None,
                       ean: str = "") -> list[Source]:
    """Razina 1: HR ambalaža, deklaracija, PIM ili uputa iz lokalne mape.
    Datoteka se prepoznaje po SKU-u ili EAN-u u nazivu (npr. C002167_*.pdf)."""
    if not pim_dir or not pim_dir.exists():
        return []
    keys = [k for k in (product.sku, ean) if k]
    out = []
    for path in sorted(pim_dir.rglob("*")):
        if not path.is_file() or not any(k in path.name for k in keys):
            continue
        text = ""
        suf = path.suffix.lower()
        try:
            if suf in (".txt", ".md", ".csv", ".json"):
                text = path.read_text(encoding="utf-8", errors="ignore")
            elif suf == ".pdf":
                from pypdf import PdfReader
                text = "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
            elif suf == ".docx":
                from docx import Document
                text = "\n".join(p.text for p in Document(str(path)).paragraphs)
            elif suf in (".html", ".htm"):
                text = extract_generic_page(path.read_text(errors="ignore"))[1]
        except Exception as err:  # noqa: BLE001
            text = ""
            print(f"  [PIM] {path.name} nije pročitan: {err}")
        if text.strip():
            out.append(Source(sid="", kind=KIND_PIM, url=str(path),
                              title=path.name, text=text[:LOCAL_SOURCE_CAP], razina=1))
    return out


def gather_sources(product: Product, category: str, cache_dir: Path,
                   refresh: bool, web_search: bool, max_web: int = 3,
                   secondary: bool = True, pim_dir: Path | None = None) -> list[Source]:
    """Izvori po razinama iz općih pravila. S1 je uvijek eLjekarna24."""
    sources: list[Source] = []
    if not R.je_primarni(product.url):
        return sources
    html = _cache_get_or_fetch(product.url, cache_dir, refresh)
    if html:
        text = extract_product_page(html)
        if text:
            sources.append(Source(sid="S1", kind=KIND_PRIMARY, url=product.url,
                                  title="eLjekarna24", text=text, razina=2))
    if not sources:
        return sources

    sources += load_local_sources(product, pim_dir, ean_sa_stranice(sources[0].text))

    if secondary and web_search:
        kozmetika = category in ("B", "E", "I")
        kandidati: list[tuple[str, str, int]] = [
            (u, KIND_BRAND, 2) for u in brand_site_urls(product)]
        domene = list(R.USPOREDNE_DOMENE)
        if kozmetika:
            domene += list(R.USPOREDNE_DOMENE_KOZMETIKA)
        for domena in domene[:max(2, max_web + (2 if kozmetika else 0))]:
            url = site_search_url(product, domena)
            if url:
                kandidati.append((url, KIND_COMPARE, 3))
        for url, kind, razina in kandidati:
            if not R.je_dopusten(url, product.brend, kozmetika=True)[0]:
                continue
            page = _cache_get_or_fetch(url, cache_dir, refresh)
            if not page:
                continue
            title, text = extract_generic_page(page)
            if len(text) < 150:
                continue
            sources.append(Source(sid="", kind=kind, url=url,
                                  title=title or kind, text=text, razina=razina))
            time.sleep(0.3)

    for i, src in enumerate(sources, start=1):
        src.sid = f"S{i}"
    return sources


def _naziv_izvora(s: Source) -> str:
    if s.kind == KIND_PRIMARY:
        return "eLjekarna24"
    if s.kind == KIND_PIM:
        return f"Ambalaža / PIM ({s.title})"
    host = urlparse(s.url).netloc.removeprefix("www.")
    nazivi = {"webljekarna.vasezdravlje.com": "Vaše zdravlje",
              "primapharme.hr": "Prima Pharme", "notino.hr": "Notino",
              "makeup.hr": "MAKEUP", "douglas.hr": "Douglas"}
    return nazivi.get(host, host or s.title)


def sources_block(sources: list[Source]) -> str:
    if not sources:
        return "NEMA DOSTUPNIH IZVORA."
    opis = {
        KIND_PIM: "RAZINA 1 — HR AMBALAŽA / DEKLARACIJA / PIM (najviša razina)",
        KIND_PRIMARY: "RAZINA 2 — eLjekarna24, stranica proizvoda",
        KIND_BRAND: "RAZINA 2 — službena stranica brenda / HR distributera",
        KIND_COMPARE: ("RAZINA 3 — USPOREDNI IZVOR (samo za usporedbu podataka; "
                       "tekst se NE kopira ni doslovno ni uz sitne izmjene)"),
    }
    return "\n\n".join(f"[{s.sid}] {opis.get(s.kind, s.kind)} — {_naziv_izvora(s)} — "
                       f"{s.url}\n{s.text}" for s in sources)


def sources_norm_text(product: Product, sources: list[Source]) -> str:
    return norm_spaced(product.naziv + " " + product.brend + " " +
                       " ".join(s.text for s in sources))


# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------

def load_bedrock_config() -> dict:
    from dotenv import load_dotenv

    load_dotenv()
    required = ["BEDROCK_AWS_ACCESS_KEY_ID", "BEDROCK_AWS_SECRET_ACCESS_KEY",
                "BEDROCK_TEXT_MODEL_ID", "BEDROCK_AWS_REGION"]
    config = {key: os.getenv(key) for key in required}
    missing = [key for key, value in config.items() if not value]
    if missing:
        sys.exit(f"Nedostaje u .env: {', '.join(missing)}")
    # model za dodatne pokušaje kad osnovni model ne prođe kontrolu (npr. Opus)
    config["BEDROCK_RESCUE_MODEL_ID"] = os.getenv("BEDROCK_RESCUE_MODEL_ID", "")
    config["BEDROCK_VERIFY_MODEL_ID"] = (os.getenv("BEDROCK_VERIFY_MODEL_ID")
                                         or config["BEDROCK_TEXT_MODEL_ID"])
    return config


class BedrockClient:
    def __init__(self, config: dict):
        import boto3
        from botocore.config import Config

        self.model_id = config["BEDROCK_TEXT_MODEL_ID"]
        self.verify_model_id = config["BEDROCK_VERIFY_MODEL_ID"]
        self.rescue_model_id = config.get("BEDROCK_RESCUE_MODEL_ID") or ""
        self._cache_ok = True
        self._bez_temperature: set[str] = set()
        self._uvijek_razmislja: set[str] = set()
        self._usage_lock = threading.Lock()
        self.usage: dict[str, dict[str, int]] = {}            # model -> zbroj
        self._usage_dretve: dict[int, dict[str, dict[str, int]]] = {}
        for m in (self.model_id, self.verify_model_id,
                  config.get("BEDROCK_RESCUE_MODEL_ID") or ""):
            if NOVI_MODEL_RE.search(m or ""):
                self._bez_temperature.add(m)
                self._uvijek_razmislja.add(m)
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=config["BEDROCK_AWS_REGION"],
            aws_access_key_id=config["BEDROCK_AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=config["BEDROCK_AWS_SECRET_ACCESS_KEY"],
            config=Config(read_timeout=600, connect_timeout=10,
                          retries={"max_attempts": 3, "mode": "standard"}),
        )

    def _converse(self, model_id: str, system_prompt: str, user_message: str,
                  max_tokens: int, temperature: float) -> str:
        from botocore.exceptions import ClientError

        last_err = None
        for attempt in range(BEDROCK_RETRIES):
            system = [{"text": system_prompt}]
            if self._cache_ok:
                # dugi system prompt (pravila, template, checklista) je isti za
                # sve proizvode iste kategorije: prompt caching
                system.append({"cachePoint": {"type": "default"}})
            cfg = {"maxTokens": max_tokens}
            if model_id not in self._bez_temperature:
                cfg["temperature"] = temperature
            if model_id in self._uvijek_razmislja:
                # thinking se naplaćuje kao izlaz i troši maxTokens
                cfg["maxTokens"] = max_tokens + THINKING_HEADROOM
            try:
                resp = self._client.converse(
                    modelId=model_id, system=system,
                    messages=[{"role": "user", "content": [{"text": user_message}]}],
                    inferenceConfig=cfg,
                )
                self._zabiljezi(model_id, resp.get("usage") or {})
                blocks = resp["output"]["message"]["content"]
                if any("reasoningContent" in b for b in blocks):
                    self._uvijek_razmislja.add(model_id)
                return "".join(b.get("text", "") for b in blocks).strip()
            except ClientError as err:
                code = err.response["Error"]["Code"]
                msg = err.response["Error"].get("Message", "")
                if code == "ValidationException" and self._cache_ok and \
                        "cach" in msg.lower():
                    self._cache_ok = False
                    continue
                # noviji modeli (npr. Opus 5.5) ne primaju temperature
                if code == "ValidationException" and "temperature" in msg.lower() \
                        and model_id not in self._bez_temperature:
                    self._bez_temperature.add(model_id)
                    continue
                if code in {"ThrottlingException", "ServiceUnavailableException",
                            "InternalServerException", "ModelNotReadyException",
                            "ModelErrorException"} and attempt < BEDROCK_RETRIES - 1:
                    time.sleep(min(60, 2 ** attempt * 3) + random.uniform(0, 2))
                    last_err = err
                    continue
                raise
        raise last_err  # type: ignore[misc]

    def _zabiljezi(self, model_id: str, usage: dict) -> None:
        polja = {"inputTokens": "input", "outputTokens": "output",
                 "cacheReadInputTokens": "cache_read",
                 "cacheWriteInputTokens": "cache_write"}
        with self._usage_lock:
            for cilj in (self.usage,
                         self._usage_dretve.setdefault(threading.get_ident(), {})):
                z = cilj.setdefault(model_id, {v: 0 for v in polja.values()} | {"poziva": 0})
                z["poziva"] += 1
                for k, v in polja.items():
                    z[v] += int(usage.get(k) or 0)

    def usage_dretve(self) -> dict[str, dict[str, int]]:
        """Potrošnja tokena trenutne dretve (za trošak po proizvodu)."""
        with self._usage_lock:
            return json.loads(json.dumps(self._usage_dretve.get(threading.get_ident(), {})))

    def generate(self, system_prompt: str, user_message: str,
                 model_id: str | None = None) -> str:
        return self._converse(model_id or self.model_id, system_prompt, user_message,
                              GEN_MAX_TOKENS, GEN_TEMPERATURE)

    def verify(self, system_prompt: str, user_message: str) -> str:
        return self._converse(self.verify_model_id, system_prompt, user_message,
                              VERIFY_MAX_TOKENS, VERIFY_TEMPERATURE)

    def extract(self, system_prompt: str, user_message: str) -> str:
        return self._converse(self.model_id, system_prompt, user_message,
                              EXTRACT_MAX_TOKENS, 0.0)


def explain_client_error(err, config: dict) -> str:
    code = err.response["Error"]["Code"]
    message = err.response["Error"]["Message"]
    hints = {
        "AccessDeniedException": ("IAM korisniku nedostaje bedrock:InvokeModel ili "
                                  "pristup modelu nije odobren u Bedrock konzoli."),
        "ValidationException": ("Najčešće pogrešan model ID; provjeri: aws bedrock "
                                "list-inference-profiles --region "
                                f"{config['BEDROCK_AWS_REGION']}"),
        "ResourceNotFoundException": ("Model/profil ne postoji u regiji "
                                      f"{config['BEDROCK_AWS_REGION']}."),
        "UnrecognizedClientException": "Pogrešan access key ili secret key.",
        "ThrottlingException": "Rate limit; pričekaj pa nastavi (resume radi).",
    }
    detail = hints.get(code, "")
    return f"[{code}] {message}" + (f"\n  -> {detail}" if detail else "")


# ---------------------------------------------------------------------------
# Promptovi
# ---------------------------------------------------------------------------

FORMAT_PRAVILA = """IZLAZNI FORMAT (Markdown, obavezan — po njemu sustav provjerava i
pretvara dokument u DOCX)
- Prvi redak: "# " + naziv proizvoda (isti kao H1).
- Odjeljci razine 2, točno ovim nazivima i redom: "## SEO elementi",
  "## Prvi ekran", "## Tab N: <naziv taba točno iz templatea>" za svaki tab,
  "## Česta pitanja" (samo ako FAQ ima smisla i dopušten je).
- SEO elementi: tablica "| Element | Tekst |" s redcima Meta title, Meta
  description, H1, Alt tekst. Meta title završava s " │ eLjekarna24" (znak │).
- Prvi ekran: "**Naziv proizvoda:** …" i "**Kratki opis:** …", svaki u svom retku.
- Brza traka: jedan redak "**Brza traka:** oznaka · oznaka · oznaka" na vrhu
  Taba 1 (kod Templatea C odmah ispod "**VAŽNA NAPOMENA:** …"). Ako nema barem
  3 provjerena podatka, redak se izostavlja.
- Podnaslovi unutar taba: "### …". Natuknice: "- ". Koraci: "1. ", "2. ".
- Blok tvrdnji (gdje je dopušten): natuknice "- Sadrži …" na kraju Taba 1.
- Tablica podataka: "| Podatak | Vrijednost |" s redcima točno iz templatea.
- FAQ: pitanje u retku "**Pitanje?**", odgovor u sljedećem odlomku.
- NEPROVJEREN PODATAK (u templateu „crvena boja teksta”) piši kao
  [PROVJERITI: podatak]. Oznaka obuhvaća SAMO konkretan podatak (vrijednost,
  naziv, broj, popis sastojaka), NIKAD cijelu rečenicu ni opisni tekst.
  Crveno se označava:
    * podatak koji je SAMO kod usporedne ljekarne ili webshopa (razina 3);
    * neslaganje izvora ISTE razine (npr. eLjekarna24 i stranica brenda):
      [PROVJERITI: vrijednost A] / [PROVJERITI: vrijednost B];
    * obvezni podatak koji nije pronađen: ćelija prazna, naziv retka
      [PROVJERITI: Naziv retka];
    * podatak u koji postoji opravdana sumnja (npr. pravopisna greška u izvoru
      prenesena doslovno, dnevna doza iznad najveće dopuštene).
  Podatak s eLjekarne24 ili stranice brenda (razina 2) koji se ne kosi s drugim
  izvorom razine 1–2 piše se NORMALNO, bez oznake. Ako se razina 2 i usporedni
  izvor (razina 3) ne slažu, vrijedi razina 2, bez oznake. Opisni podatak koji
  nije potvrđen izostavi (ne označavaj ga). Označen podatak ne ide u brzu traku.
  Nigdje drugdje ne piši „provjeriti”, „potvrditi” ni slično.
- Tablicu izvora NE piši: sustav je dodaje sam iz JSON-a na kraju odgovora.
- Bez ``` ograda oko dokumenta, bez teksta prije ili poslije dokumenta.

AUTOMATSKA KONTROLA (sustav ove točke provjerava doslovno; dokument koji ih
krši vraća se na ispravak):
- točni nazivi i redoslijed odjeljaka i tabova iz templatea, bez dodatnih tabova;
- tablica podataka s redcima točno iz templatea, istim redom;
- broj rečenica kratkog opisa iz templatea; prva rečenica prema zadanom obrascu,
  ne počinje s „Ovaj proizvod”, „Riječ je o”, „Predstavljamo”, „U ponudi je”,
  „Dolazi u obliku”; naziv proizvoda u tekstu Taba 1 najviše jednom;
- brza traka: 3–6 kratkih oznaka odvojenih „·”, bez tvrdnji, % PU, uputa i
  oznaka [PROVJERITI];
- podnaslovi s podatkom o ovom proizvodu, nikad općeniti;
- dodaci prehrani i hrana za djecu: „doprinosi” samo u bloku tvrdnji; tvrdnje
  samo iz priloženog popisa odobrenih; bez tvrdnji o apsorpciji, iskoristivosti,
  podnošljivosti, nadraživanju želuca ili sluznice; uz tvrdnje bez količina;
- obvezne rečenice kategorije doslovno; SKU nigdje;
- FAQ: na pitanje da/ne odgovor počinje s „Da” ili „Ne”; najviše 2–3 rečenice;
- bez crtica (– —) osim u rasponu brojeva, bez uskličnika, bez navođenja izvora
  („prema proizvođaču”, „prema deklaraciji”, „navodi se”), bez fraza i praznih
  glagola s popisa u općim pravilima (pruža, omogućuje, osigurava, podržava, nudi);
- svaki broj s jedinicom mora postojati u izvorima (preračunavanja poput trajanja
  pakiranja piši bez novih jedinica);
- tekst usporednih ljekarni se ne kopira (8 i više istih riječi zaredom).

NA KRAJU ODGOVORA, nakon dokumenta, zaseban blok:
```json
{"izvori": {"S1": "što taj izvor potvrđuje u opisu", "S2": "..."},
 "nedostaje": ["obvezni podaci kojih nema ni u jednom izvoru"],
 "konflikti": ["podatak: vrijednost A [Sx] / vrijednost B [Sy]"],
 "provjeriti": ["svaki podatak koji si označio [PROVJERITI: …] i zašto"],
 "kut": "kut proizvoda koji si odabrao",
 "namjena": "namjena proizvoda za odabir tvrdnji (samo A i C)"}
```"""


def _system_parts(letter: str, podvrsta: str) -> list[str]:
    dijelovi = [
        "OPĆA PRAVILA ZA SVE PDP OPISE (klijent, PDP template ver.11):\n\n"
        + T.opca_pravila(),
        f"TEMPLATE ZA OVAJ PROIZVOD ({T.label(letter)}):\n\n" + T.template_tekst(letter),
    ]
    for naziv, tekst in T.checkliste_za(letter, podvrsta):
        dijelovi.append(f"{naziv.upper()} (ima prednost pred templateom ako se "
                        f"razlikuju):\n\n{tekst}")
    return dijelovi


def build_gen_system(letter: str, podvrsta: str = "") -> str:
    podvrsta = podvrsta or T.podvrsta_heuristika(letter)
    default = (
        "Ti si iskusna magistra farmacije i copywriterica hrvatske internetske "
        "ljekarne eLjekarna24. Pišeš PDP opis proizvoda na hrvatskom jeziku, "
        "točno prema klijentovim pravilima, templateu i checklisti niže. "
        "Pravila su obvezna; checklista ima prednost pred templateom.\n\n"
        "Postupak prije pisanja (ne upisuje se u dokument): provjeri je li svaki "
        "izvor isti proizvod i pakiranje; odredi kut proizvoda; odaberi "
        "relevantne odobrene tvrdnje iz priloženog popisa; prođi završnu "
        "provjeru iz checkliste prije predaje.\n\n"
        + FORMAT_PRAVILA + "\n\n" + "\n\n".join(_system_parts(letter, podvrsta))
    )
    prompt = prompts_cfg.render("pdp_system", default, kategorija=T.label(letter))
    return prompts_cfg.with_notes(prompt, "pdp_napomene", f"pdp_napomene_{letter}")


@dataclass
class Upute:
    """Izračuni iz koda koji idu piscu i kontroli."""
    obrazac: str = ""
    obrazac_opis: str = ""
    regulativa: str = ""
    prilog_ii: str = ""
    zauzeti_poceci: list = field(default_factory=list)
    dodatno: list = field(default_factory=list)


def build_gen_user(product: Product, letter: str, podvrsta: str,
                   sources: list[Source], feedback: str | None = None,
                   inventory=None, upute: Upute | None = None) -> str:
    upute = upute or Upute()
    primjer = T.primjer_za(letter)
    primjer_blok = (f"\n\nODOBRENI PRIMJER GOTOVOG OPISA (drugi proizvod; samo za "
                    f"format, ton i razinu detalja — nijedna činjenica iz primjera "
                    f"ne ide u ovaj opis):\n<<<PRIMJER\n{primjer}PRIMJER>>>"
                    if primjer else "")
    inv_blok = ""
    if inventory is not None and inventory.facts:
        inv_blok = ("\n\nINVENTAR ČINJENICA (izvučen iz izvora prije pisanja; "
                    "OBVEZNO PRENIJETI = mora biti u opisu):\n<<<INVENTAR\n"
                    + inventory.as_prompt_block() + "\nINVENTAR>>>")
    tabovi = "\n".join(f"  Tab {n}: {t}" + (" (neobvezan)" if o else "")
                       for n, t, o in T.tabs_for(letter, podvrsta))
    smjernice = [
        f"Template: {T.label(letter)}; podvrsta: {podvrsta or '-'}.",
        f"Tabovi (točni nazivi):\n{tabovi}",
        f"Obrazac prve rečenice kratkog opisa ({upute.obrazac}): prva rečenica "
        f"počinje {upute.obrazac_opis}.",
        "FAQ: " + ("dopušten, neobvezan, najviše "
                   f"{T.TEMPLATE_META[letter]['faq_max']} pitanja."
                   if T.faq_dopusten(letter, podvrsta) else "NE stavlja se."),
        f"Datum pristupa izvorima: {danas_hr()}",
    ]
    if upute.zauzeti_poceci:
        smjernice.append("KONTROLA SERIJE: ovi su počeci prve rečenice već iskorišteni "
                         "u opisima iste kategorije; tvoja prva rečenica NE smije "
                         "počinjati istim riječima: "
                         + "; ".join(f"„{p}…”" for p in upute.zauzeti_poceci[-25:]))
    smjernice += upute.dodatno
    reg = ""
    if upute.regulativa:
        reg = f"\n\nREGULATIVA (izračunao sustav):\n{upute.regulativa}"
    if upute.prilog_ii:
        reg += ("\n\nIZVADAK IZ PRILOGA II. PRAVILNIKA NN 160/2013 za sastojke "
                f"proizvoda (najveće doze i posebna upozorenja):\n{upute.prilog_ii}")

    msg = f"""PROIZVOD
Naziv u bazi (normaliziraj velika slova; promotivne oznake poput „2+1 GRATIS” ne
idu u naziv): {product.naziv}
Brend: {product.brend or "-"}
Sekcija webshopa: {product.sekcija or "-"}
URL: {product.url}

SMJERNICE ZA OVAJ PROIZVOD
- {chr(10).join('- ' + s for s in smjernice)[2:]}

KOSTUR IZLAZNOG FORMATA:
<<<KOSTUR
{T.build_skeleton(letter, podvrsta)}KOSTUR>>>{primjer_blok}

IZVORI ZA OVAJ PROIZVOD:
<<<IZVORI
{sources_block(sources)}
IZVORI>>>{inv_blok}{reg}

Napiši potpuni PDP opis za ovaj proizvod u izlaznom formatu, zatim JSON blok."""
    if feedback:
        msg += f"""

PRETHODNI POKUŠAJ NIJE PROŠAO KONTROLU. Ispravi SVE navedeno i vrati cijeli
ispravljeni dokument (i JSON blok); dijelove koji nisu navedeni ne mijenjaj
bez potrebe:
{feedback}"""
    return msg


VERIFY_SYSTEM_DEFAULT = """Ti si stručna provjera PDP opisa za eLjekarna24: magistra farmacije
sa znanjem regulative hrane, dodataka prehrani, kozmetike i medicinskih
proizvoda u RH/EU. Dobit ćeš IZVORE, regulatorne izračune sustava, pravila
(opća pravila, template i checklistu) i gotov PDP opis.

Provjeri i prijavi SAMO stvarne greške:
1. ČINJENICE: svaki podatak o proizvodu (sastojci, količine, doze, dob, upute,
   upozorenja, EAN, proizvođač, specifikacije, okus, oblik) mora biti u izvorima.
   Podatak koji je samo u jednom izvoru ili samo kod usporedne ljekarne mora biti
   označen [PROVJERITI: …]. Izmišljen ili promijenjen podatak je greška.
2. REGULATIVA: zdravstvene tvrdnje samo iz popisa odobrenih tvrdnji koje je
   izračunao sustav (uvjet ispunjen) i samo relevantne za namjenu; nikakvi
   drugi učinci (ni u podnaslovima, brzoj traci, FAQ-u, SEO-u); obvezne
   napomene kategorije doslovno i na pravom mjestu; za početnu formulu bez
   ikakvih tvrdnji, bez FAQ-a i bez isticanja pojedinih sastojaka; kozmetika
   samo učinci koje navodi brend, bez liječenja; medicinski proizvod samo
   namjena iz upute; „bio/eko” samo uz certifikat.
3. PRAVILA PISANJA: navođenje izvora u javnom tekstu („prema proizvođaču”…),
   šablonski uvodi, prazni glagoli, zabranjene fraze, ponavljanje istog podatka
   u više tabova, odgovor u FAQ-u bez jednoznačnog podatka, kopiran tekst
   usporedne ljekarne, prva rečenica kratkog opisa koja ne slijedi zadani
   obrazac ili ne prolazi test različitosti.

NE prijavljuj: stil koji je u skladu s pravilima, očite izvedenice iz naziva i
oblika proizvoda (npr. „krema za lice” → područje primjene lice), prijevod
podatka s izvora na hrvatski, oznake [PROVJERITI: …] same po sebi, % PU koji je
izračunao sustav.

Odgovori ISKLJUČIVO validnim JSON-om:
{"prolazi": true/false,
 "greske": [{"mjesto": "Tab 1 / Kratki opis / …", "problem": "…",
             "ispravak": "kako ispraviti", "vrsta": "činjenica|regulativa|pisanje"}],
 "napomena": "…"}
"prolazi" je false čim postoji ijedna greška vrste činjenica ili regulativa,
ili više od dvije greške vrste pisanje."""


def build_verify_system(letter: str = "A", podvrsta: str = "") -> str:
    default = VERIFY_SYSTEM_DEFAULT + "\n\nPRAVILA KLIJENTA:\n\n" + \
        "\n\n".join(_system_parts(letter, podvrsta or T.podvrsta_heuristika(letter)))
    return prompts_cfg.with_notes(
        prompts_cfg.render("verify_system", default), "verify_napomene")


def build_verify_user(product: Product, sources: list[Source], md: str,
                      upute: Upute | None = None) -> str:
    upute = upute or Upute()
    return f"""PROIZVOD: {product.naziv} (brend: {product.brend})

IZVORI:
<<<IZVORI
{sources_block(sources)}
IZVORI>>>

REGULATORNI IZRAČUNI SUSTAVA:
{upute.regulativa or "(nema)"}
Zadani obrazac prve rečenice: {upute.obrazac_opis or "-"}

PDP OPIS ZA PROVJERU:
<<<PDP
{md}
PDP>>>

Vrati samo JSON."""


def parse_verifier_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S)
    for chunk in (cleaned, *re.findall(r"\{.*\}", cleaned, flags=re.S)):
        try:
            data = json.loads(chunk)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and "prolazi" in data:
            greske = data.get("greske")
            if greske is None:   # stari format
                greske = [{"problem": c.get("tvrdnja", ""), "ispravak": c.get("razlog", ""),
                           "vrsta": "činjenica"}
                          for c in data.get("nepotkrijepljene_tvrdnje") or []
                          if isinstance(c, dict)]
            data["greske"] = [g for g in greske if isinstance(g, dict) and g.get("problem")]
            return data
    return None


# ---------------------------------------------------------------------------
# Obrada odgovora
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*?)\s*$")
JSON_BLOK_RE = re.compile(r"```json\s*(\{.*?\})\s*```\s*$", re.S)


def odvoji_json_blok(raw: str) -> tuple[str, dict]:
    """Izdvoji završni JSON iz odgovora; dokument ostaje bez njega."""
    m = JSON_BLOK_RE.search(raw or "")
    podaci: dict = {}
    if m:
        try:
            ucitano = json.loads(m.group(1))
            if isinstance(ucitano, dict):
                podaci = ucitano
        except json.JSONDecodeError:
            podaci = {}
        raw = raw[:m.start()].rstrip()
    else:
        m2 = re.search(r"\n(\{\s*\"(?:izvori|nedostaje|konflikti|provjeriti)\".*\})\s*$",
                       raw or "", re.S)
        if m2:
            try:
                podaci = json.loads(m2.group(1))
            except json.JSONDecodeError:
                podaci = {}
            raw = raw[:m2.start()].rstrip()
    return raw, podaci


def clean_markdown(raw: str) -> str:
    text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", (raw or "").strip(), flags=re.S)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            text = "\n".join(lines[i:])
            break
    # model ponekad sam doda tablicu izvora: nju piše sustav
    text = re.split(r"\n## Izvori\b", text)[0]
    return text.strip() + "\n"


def upisi_ean(md: str, ean: str) -> tuple[str, bool]:
    """Potvrđen EAN upiši u prazan redak EAN tablice podataka."""
    if not ean or ean in md:
        return md, False
    novi, upisano = [], False
    for redak in md.splitlines():
        if (not upisano and redak.strip().startswith("|")
                and re.match(r"\|\s*(\[PROVJERITI:\s*)?EAN\]?\s*\|", redak.strip())):
            celije = redak.strip().strip("|").split("|")
            if len(celije) >= 2 and not re.search(r"\d{8,14}", celije[1]):
                redak = f"| EAN | {ean} |"
                upisano = True
        novi.append(redak)
    return "\n".join(novi), upisano


def dodaj_tablicu_izvora(md: str, sources: list[Source], potvrde: dict) -> str:
    redovi = ["", "## Izvori (ne objavljuje se)", "",
              "| ID | Naziv i URL | Datum pristupa | Što potvrđuje |",
              "| --- | --- | --- | --- |"]
    for s in sources:
        sto = str(potvrde.get(s.sid) or potvrde.get(f"[{s.sid}]") or "").strip()
        if not sto and s.usporedni:
            sto = "usporedba podataka"
        sto = sto.replace("|", "/") or "-"
        redovi.append(f"| {s.sid} | {_naziv_izvora(s)}, {s.url} | {s.datum} | {sto} |")
    return md.rstrip() + "\n" + "\n".join(redovi) + "\n"


def parse_headings(md: str) -> list[dict]:
    out = []
    for idx, line in enumerate(md.splitlines()):
        m = HEADING_RE.match(line)
        if m:
            out.append({"level": len(m.group(1)), "title": m.group(2), "line": idx})
    return out


def sekcije(md: str) -> dict[str, str]:
    """Odjeljci razine 2: naslov -> tekst do sljedećeg naslova razine ≤ 2."""
    lines = md.splitlines()
    heads = [h for h in parse_headings(md) if h["level"] <= 2]
    out = {}
    for i, h in enumerate(heads):
        if h["level"] != 2:
            continue
        end = heads[i + 1]["line"] if i + 1 < len(heads) else len(lines)
        out[h["title"]] = "\n".join(lines[h["line"] + 1:end])
    return out


def tablica(block: str) -> list[list[str]]:
    rows = []
    for ln in block.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def recenice(tekst: str) -> list[str]:
    t = re.sub(r"\s+", " ", (tekst or "").strip())
    if not t:
        return []
    # ne dijeli na brojevima („1. vrećica”, „2,5 µg”) ni kraticama
    dijelovi = re.split(r"(?<=[a-zčćžšđ0-9%)”\]])[.!?]\s+(?=[A-ZČĆŽŠĐ„\"])", t)
    return [d.strip() for d in dijelovi if d.strip()]


def kratki_opis(md: str) -> str:
    m = re.search(r"\*\*Kratki opis:\*\*\s*(.+)", md)
    return m.group(1).strip() if m else ""


def naziv_iz_md(md: str) -> str:
    m = re.search(r"\*\*Naziv proizvoda:\*\*\s*(.+)", md)
    if m:
        return m.group(1).strip()
    m = re.match(r"#\s+(.+)", md.strip())
    return m.group(1).strip() if m else ""


def pocetak(recenica: str, n: int = 4) -> str:
    return " ".join(re.sub(r"\[PROVJERITI:\s*|\]", "", recenica).split()[:n])


def oznake_za_provjeru(md: str) -> list[str]:
    return [m.group(1).strip() or "(bez teksta)"
            for m in re.finditer(r"\[PROVJERITI(?::\s*([^\]]*))?\]", md)]


# ---------------------------------------------------------------------------
# Deterministička kontrola
# ---------------------------------------------------------------------------

# Checklista dodaci prehrani, pogl. 5: „Ne smije se napisati što taj oblik radi
# u tijelu: bolja apsorpcija ili iskoristivost, blaže za želudac, ne iritira
# sluznicu, bolje se podnosi, bez nuspojava.”
UCINAK_OBLIKA_RE = re.compile(
    r"\b(apsorpcij\w*|apsorbira\w*|iskoristiv\w*|bioraspoloživ\w*|podnošljiv\w*|"
    r"bolje se podnosi|nadražuj\w*|ne iritira\w*|iritacij\w* (želuca|sluznice)|"
    r"blaž\w* za želud\w*|osjetljiv\w* želu\w*|nježn\w* (za|prema) želu\w*|"
    r"bez (probavnih )?nuspojava|bez zatvora)\b", re.IGNORECASE)

YES_NO_RE = re.compile(r"^(je li|jesu li|smije li|smiju li|može li|mogu li|sadrži li|"
                       r"ima li|treba li|trebam li|smijem li|koristi li|odgovara li)\b",
                       re.IGNORECASE)


def validate_pdp(md: str, product: Product, letter: str, podvrsta: str,
                 sources: list[Source], inventory=None,
                 procjena: G.Procjena | None = None, upute: Upute | None = None,
                 meta_inv: dict | None = None) -> list[str]:
    """Deterministička kontrola. [] = prolaz."""
    upute = upute or Upute()
    meta = T.TEMPLATE_META[letter]
    errors: list[str] = []
    sek = sekcije(md)
    naslovi = list(sek)

    # --- H1 i redoslijed odjeljaka ---
    h1 = [h for h in parse_headings(md) if h["level"] == 1]
    if len(h1) != 1:
        errors.append("Dokument mora početi s točno jednim naslovom '# <naziv proizvoda>'.")
    ocekivani = ["SEO elementi", "Prvi ekran"] + \
        [f"Tab {n}: {t}" for n, t, _ in T.tabs_for(letter, podvrsta)]
    neobvezni = {f"Tab {n}: {t}" for n, t, o in T.tabs_for(letter, podvrsta) if o}
    dopusteni = set(ocekivani) | {"Česta pitanja"}
    for nas in naslovi:
        if nas not in dopusteni:
            errors.append(f"Odjeljak '## {nas}' nije u templateu. Dopušteni su: "
                          + ", ".join(ocekivani) + " i 'Česta pitanja'.")
    prisutni = [n for n in ocekivani if n in sek]
    for n in ocekivani:
        if n not in sek and n not in neobvezni:
            errors.append(f"Nedostaje odjeljak '## {n}' (naziv točno iz templatea).")
    if [n for n in naslovi if n in ocekivani] != prisutni:
        errors.append("Odjeljci nisu redoslijedom iz templatea.")
    if sum(1 for n in naslovi if n.startswith("Tab ")) > 6:
        errors.append("Najviše 6 tabova.")

    # --- SEO elementi ---
    seo = {r[0].lower(): (r[1] if len(r) > 1 else "")
           for r in tablica(sek.get("SEO elementi", ""))}
    for kljuc in ("meta title", "meta description", "h1", "alt tekst"):
        if not seo.get(kljuc, "").strip():
            errors.append(f"SEO elementi: nedostaje redak '{kljuc}'.")
    title = seo.get("meta title", "")
    if title and not title.rstrip().endswith("│ eLjekarna24"):
        errors.append("Meta title mora završavati s ' │ eLjekarna24' (znak │).")
    desc = seo.get("meta description", "")
    if len(desc) > 165:
        errors.append(f"Meta description ima {len(desc)} znakova (najviše ~155).")
    if h1 and seo.get("h1") and norm_compact(seo["h1"]) != norm_compact(h1[0]["title"]):
        errors.append("H1 u SEO elementima mora biti jednak naslovu dokumenta.")
    for k in ("meta title", "meta description", "h1"):
        m = SLOGAN_RE.search(norm_spaced(seo.get(k, "")))
        if m:
            errors.append(f"{k}: skraćeni zdravstveni slogan '{m.group(0)}' nije dopušten.")

    # --- Prvi ekran ---
    naziv = naziv_iz_md(md)
    ko = kratki_opis(md)
    if "**Naziv proizvoda:**" not in sek.get("Prvi ekran", ""):
        errors.append("Prvi ekran: nedostaje '**Naziv proizvoda:** …'.")
    if not ko:
        errors.append("Prvi ekran: nedostaje '**Kratki opis:** …'.")
    else:
        rec = recenice(ko)
        lo, hi = meta["kratki_opis"]
        if not lo <= len(rec) <= hi:
            errors.append(f"Kratki opis ima {len(rec)} rečenica; template traži {lo}–{hi}.")
        prva = rec[0] if rec else ""
        zab = R.pocinje_zabranjeno(prva)
        if zab:
            errors.append(f"Prva rečenica kratkog opisa ne smije počinjati s „{zab}”.")
        naziv_pocetak = norm_compact(" ".join(naziv.split()[:2]))
        pocinje_nazivom = bool(naziv_pocetak) and norm_compact(prva).startswith(naziv_pocetak)
        if pocinje_nazivom and upute.obrazac_opis and \
                not G.obrazac_je_naziv(upute.obrazac_opis):
            errors.append("Prva rečenica kratkog opisa počinje nazivom proizvoda, a "
                          f"zadani obrazac ({upute.obrazac}) je: {upute.obrazac_opis}.")
        if letter == "A" and podvrsta != "biljni čaj (nije dodatak prehrani)":
            if "dodatak prehrani" not in prva.lower():
                errors.append("Kategorija „dodatak prehrani” mora biti u prvoj rečenici "
                              "kratkog opisa.")
            oznaka = str((meta_inv or {}).get("oznaka_uz_naziv") or "").strip().lower()
            if oznaka and oznaka not in prva.lower():
                errors.append(f"Uz kategoriju u prvoj rečenici mora stajati „{oznaka}” "
                              "(tako piše uz naziv na deklaraciji).")
        if letter == "C" and podvrsta == T.POCETNA_FORMULA and \
                "rođenj" not in ko.lower():
            errors.append("Kod početne formule kratki opis navodi da je prikladna od "
                          "rođenja kada dojenje nije moguće.")
        poc = pocetak(prva)
        if poc and any(norm_compact(poc) == norm_compact(z) for z in upute.zauzeti_poceci):
            errors.append(f"Kontrola serije: prva rečenica počinje istim riječima "
                          f"(„{poc}…”) kao opis drugog proizvoda iste kategorije.")

    # --- Tab 1 ---
    tab1_naslov = next((n for n in naslovi if n.startswith("Tab 1:")), None)
    tab1 = sek.get(tab1_naslov, "") if tab1_naslov else ""
    linije1 = [l.strip() for l in tab1.splitlines() if l.strip()]
    if letter == "C":
        if not linije1 or not linije1[0].upper().startswith("**VAŽNA NAPOMENA"):
            errors.append("Tab 1 mora počinjati napomenom o dojenju "
                          "('**VAŽNA NAPOMENA:** …').")
        elif not re.search(r"majčino mlijeko|dojenj", linije1[0], re.IGNORECASE):
            errors.append("Napomena o dojenju mora govoriti o majčinom mlijeku / dojenju.")
    traka = next((l for l in linije1 if l.startswith("**Brza traka:**")), "")
    if traka:
        oznake = [o.strip() for o in traka.split(":**", 1)[1].split("·") if o.strip()]
        if not 3 <= len(oznake) <= 6:
            errors.append(f"Brza traka ima {len(oznake)} oznaka; dopušteno 3–6 "
                          "(ili je izostavi ako nema 3 provjerena podatka).")
        if "[PROVJERITI" in traka:
            errors.append("Podatak označen za provjeru ne ide u brzu traku.")
        if re.search(r"%\s*PU|\bPU\b|doprinos", traka):
            errors.append("Brza traka ne smije sadržavati % PU ni tvrdnje.")
        m = SLOGAN_RE.search(norm_spaced(traka))
        if m:
            errors.append(f"Brza traka sadrži skraćenu tvrdnju „{m.group(0)}”.")
        if letter == "C" and podvrsta == T.POCETNA_FORMULA and re.search(
                r"DHA|ARA|oligosahar|HMO|bifido|nukleotid|bez glutena|°C",
                traka, re.IGNORECASE):
            errors.append("Brza traka početne formule smije imati samo vrstu, dob, oblik, "
                          "pakiranje i alergen (bez pojedinih sastojaka i pripreme).")
        if len(oznake) and any(len(o.split()) > 10 for o in oznake):
            errors.append("Oznaka u brzoj traci je kratka činjenica od nekoliko riječi.")
    for h in re.findall(r"^###\s+(.+)$", tab1, re.M):
        if R.je_genericki_podnaslov(h):
            errors.append(f"Podnaslov „{h}” je općenit; podnaslov mora sadržavati "
                          "podatak koji vrijedi samo za ovaj proizvod.")
        m = SLOGAN_RE.search(norm_spaced(h))
        if m:
            errors.append(f"Podnaslov „{h}” sadrži skraćenu tvrdnju „{m.group(0)}”.")
    proza1 = [l for l in linije1 if not l.startswith(("**Brza", "**VAŽNA", "|", "#", "- Sadrži"))]
    naziv_kratko = norm_spaced(" ".join([w for w in naziv.split() if len(w) > 2][:2]))
    if naziv_kratko:
        broj = sum(norm_spaced(l).count(naziv_kratko) for l in proza1)
        if broj > 1:
            errors.append(f"Naziv proizvoda u tekstu Taba 1 stoji {broj} puta (najviše jednom).")
    for l in proza1:
        zab = R.pocinje_zabranjeno(l.lstrip("-* "))
        if zab:
            errors.append(f"Odlomak u Tabu 1 počinje s „{zab}”.")
            break

    # --- Tvrdnje ---
    tvrdnje_stavke = [l[2:].strip() for l in tab1.splitlines()
                      if l.strip().startswith("- Sadrži")]
    if tvrdnje_stavke and not T.tvrdnje_dopustene(letter, podvrsta):
        errors.append("Za ovaj proizvod zdravstvene i prehrambene tvrdnje nisu dopuštene; "
                      "ukloni blok „Sadrži … doprinosi …”.")
    elif tvrdnje_stavke and procjena is not None:
        for g in G.neodobrene_tvrdnje(tvrdnje_stavke, procjena):
            errors.append(f"Tvrdnja nije iz dokumenta tvrdnji (432/2012) ili uvjet nije "
                          f"ispunjen: {g}")
        for st in tvrdnje_stavke:
            bez_uvjeta = re.sub(r"Koristan učinak postiže se[^.]*\.", "", st)
            if re.search(r"\d+\s*(mg|µg|mcg|g|IU|%)", bez_uvjeta):
                errors.append(f"Uz tvrdnju se ne pišu doza, količina ni % PU: „{st[:80]}”.")
    if letter in ("A", "C"):
        bez_tvrdnji = "\n".join(l for l in md.splitlines()
                                if not l.strip().startswith("- Sadrži")
                                and not l.strip().startswith("|"))
        if re.search(r"\bdoprinos[ie]\b", bez_tvrdnji, re.IGNORECASE):
            errors.append("Glagol „doprinosi” smije se koristiti samo u bloku tvrdnji.")
        m = UCINAK_OBLIKA_RE.search(bez_tvrdnji)
        if m:
            errors.append(f"Tvrdnja o djelovanju oblika u tijelu („{m.group(0)}”) nije u "
                          "dokumentu tvrdnji: oblik se objašnjava samo kao „što je to”, "
                          "bez apsorpcije, podnošljivosti i učinka na želudac ili sluznicu.")

    # --- [PROVJERITI] samo za podatak, ne za rečenicu ---
    if re.search(r"\[PROVJERITI:[^\]\n]*\n", md):
        errors.append("Oznaka [PROVJERITI: …] ne smije prelaziti u novi redak ni "
                      "obuhvaćati tablicu; označi pojedinačne vrijednosti.")
    for m in R.PROVJERITI_RE.finditer(md):
        sadrzaj = (m.group(1) or "").strip()
        if len(sadrzaj.split()) > 14 and sadrzaj.count(",") < 4:
            errors.append(f"[PROVJERITI: …] obuhvaća cijelu rečenicu („{sadrzaj[:60]}…”); "
                          "oznaka je samo za konkretan podatak. Podatak s eLjekarne24 ili "
                          "stranice brenda piše se normalno, a nepotvrđen opis se izostavlja.")
            break

    # --- Tablica podataka ---
    if meta.get("data_tab") and meta.get("data_rows"):
        tabn = next((n for n in naslovi if n.startswith(f"Tab {meta['data_tab']}:")), None)
        redovi = tablica(sek.get(tabn, "")) if tabn else []
        podaci = [r for r in redovi if r and r[0].lower() != "podatak"]
        oznake_red = [R.PROVJERITI_RE.sub(lambda m: m.group(1) or "", r[0]).strip()
                      for r in podaci]
        if not podaci:
            errors.append(f"Tab {meta['data_tab']} mora imati tablicu "
                          "'| Podatak | Vrijednost |'.")
        else:
            if [norm_compact(o) for o in oznake_red] != \
                    [norm_compact(o) for o in meta["data_rows"]]:
                errors.append("Tablica podataka mora imati točno ove retke, ovim "
                              f"redom: {', '.join(meta['data_rows'])}.")
            for r, oz in zip(podaci, oznake_red):
                vr = r[1].strip() if len(r) > 1 else ""
                if not vr and "[PROVJERITI" not in r[0]:
                    errors.append(f"Prazan redak '{oz}' u tablici podataka mora imati "
                                  f"naziv retka označen kao [PROVJERITI: {oz}].")
                if norm_compact(oz) == "ean" and vr:
                    znam = re.sub(r"\D", "", vr)
                    ean_izvor = inventory.ean if inventory is not None else ""
                    if ean_izvor and znam and znam != ean_izvor and "[PROVJERITI" not in vr:
                        errors.append(f"EAN {znam} se ne slaže s EAN-om iz izvora ({ean_izvor}).")
    if product.sku and re.search(rf"\b{re.escape(product.sku)}\b", md):
        errors.append("Šifra proizvoda / SKU ne upisuje se nigdje u opisu.")

    # --- Obvezne rečenice ---
    for rec in meta.get("obvezne_recenice", []):
        if letter == "A" and podvrsta == "biljni čaj (nije dodatak prehrani)":
            break
        if norm_spaced(rec) not in norm_spaced(md):
            errors.append(f"Nedostaje obvezna rečenica (doslovno): „{rec}”")

    # --- FAQ ---
    faq = sek.get("Česta pitanja", "")
    if faq.strip():
        if not T.faq_dopusten(letter, podvrsta):
            errors.append("FAQ se za ovaj proizvod ne stavlja; ukloni odjeljak.")
        pitanja = re.findall(r"^\*\*(.+?\?)\*\*\s*$", faq, re.M)
        if len(pitanja) > meta["faq_max"]:
            errors.append(f"FAQ ima {len(pitanja)} pitanja (najviše {meta['faq_max']}).")
        dijelovi = re.split(r"^\*\*.+?\?\*\*\s*$", faq, flags=re.M)[1:]
        for q, odg in zip(pitanja, dijelovi):
            odg = odg.strip()
            if not odg:
                errors.append(f"FAQ pitanje „{q}” nema odgovor.")
                continue
            if len(recenice(odg)) > 3:
                errors.append(f"Odgovor na „{q}” ima više od 3 rečenice.")
            if YES_NO_RE.match(q) and not re.match(r"(Da|Ne)\b", odg):
                errors.append(f"Na da/ne pitanje „{q}” odgovor počinje s „Da” ili „Ne”.")
            if re.search(r"posavjetujte se|provjerite kod|obratite se", odg, re.IGNORECASE) \
                    and len(recenice(odg)) <= 1:
                errors.append(f"Odgovor na „{q}” nema konkretan podatak.")

    # --- Zabranjeni izrazi, interne napomene, crtice, stil ---
    javni = "\n".join(l for l in md.splitlines()
                      if not l.lower().startswith(("| meta", "| alt")))
    for hit in find_forbidden(javni):
        errors.append(f"Zabranjen izraz: {hit}.")
    # namjena medicinskog proizvoda prenosi se iz upute (Template D), lijeka iz
    # Upute o lijeku (K); ostalima je medicinski rječnik zabranjen
    for hit in R.nadi_zabranjene_rijeci(javni, lijek=(letter in ("K", "D", "H"))):
        if not any(hit.split("“")[0] in e for e in errors):
            errors.append(f"Zabranjena riječ ili fraza: {hit}.")
    for hit in R.nadi_interne_napomene(md):
        errors.append(f"Ne smije biti u javnom tekstu: {hit}.")
    crtice = R.nadi_crtice(md)
    if crtice:
        errors.append(f"Dokument sadrži {len(crtice)} crtica (– ili —); umjesto njih "
                      "zarez ili točka (crtica smije biti samo u rasponu brojeva).")
    if R.ima_usklicnik_ili_emoji(md):
        errors.append("Bez uskličnika i emojija.")
    for hit in R.nadi_tvrdnje_bez_objasnjenja(md):
        errors.append(f"Tvrdnja bez objašnjenja: {hit}.")

    # --- Brojevi s jedinicom moraju postojati u izvorima ---
    izvor_specs = spec_tokens(product.naziv + " " + " ".join(s.text for s in sources))
    izvor_specs |= spec_tokens(upute.regulativa + " " + upute.prilog_ii)
    if inventory is not None:
        izvor_specs |= spec_tokens(" ".join(f.vrijednost for f in inventory.facts))
        izvor_specs |= spec_tokens(json.dumps(inventory.meta, ensure_ascii=False))
    for tok in sorted(spec_tokens(md) - izvor_specs):
        errors.append(f"Podatak '{tok}' ne postoji u izvorima ni u nazivu.")

    # --- Kopiranje s usporednih izvora ---
    usporedni = [s.text for s in sources if s.usporedni]
    dopusteni = [s.text for s in sources if not s.usporedni] + \
        list(meta.get("obvezne_recenice", [])) + [upute.regulativa]
    for frag in R.preuzeti_odlomci(md, usporedni, dopusteni_tekstovi=dopusteni)[:3]:
        errors.append(f"Tekst preuzet s usporedne ljekarne/webshopa („{frag}…”); "
                      "napiši vlastitim riječima.")
    return errors


# ---------------------------------------------------------------------------
# Markdown -> DOCX (neprovjereni podaci crvenom bojom)
# ---------------------------------------------------------------------------

RUN_RE = re.compile(r"\*\*(.+?)\*\*|\[PROVJERITI(?::\s*([^\]]*))?\]|\*(.+?)\*")


def _add_runs(paragraph, text: str, bold: bool = False) -> None:
    from docx.shared import RGBColor

    red = RGBColor(0xC0, 0x00, 0x00)
    pos = 0
    for m in RUN_RE.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()]).bold = bold or None
        if m.group(1) is not None:
            _add_runs(paragraph, m.group(1), bold=True)
        elif m.group(0).startswith("[PROVJERITI"):
            run = paragraph.add_run(m.group(2) if m.group(2) else "[PROVJERITI]")
            run.font.color.rgb = red
            run.bold = bold or None
        else:
            run = paragraph.add_run(m.group(3))
            run.italic = True
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:]).bold = bold or None


def md_to_docx(md: str, out_path: Path) -> None:
    from docx import Document

    doc = Document()
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        m = HEADING_RE.match(line)
        if m:
            doc.add_heading(m.group(2), level=len(m.group(1)) - 1 if len(m.group(1)) > 1 else 0)
            i += 1
            continue
        if line.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                n_cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=n_cols)
                table.style = "Table Grid"
                for r, row in enumerate(rows):
                    for c in range(n_cols):
                        cell = table.cell(r, c)
                        cell.text = ""
                        _add_runs(cell.paragraphs[0], row[c] if c < len(row) else "",
                                  bold=(r == 0))
                doc.add_paragraph("")
            continue
        s = line.strip()
        if s.startswith(("- ", "* ")):
            _add_runs(doc.add_paragraph(style="List Bullet"), s[2:])
        elif re.match(r"\d+\.\s", s):
            _add_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\d+\.\s+", "", s))
        else:
            _add_runs(doc.add_paragraph(), s)
        i += 1
    doc.save(str(out_path))


# ---------------------------------------------------------------------------
# Klasifikacija i priprema uputa
# ---------------------------------------------------------------------------

def klasificiraj(product: Product, sources: list[Source], client) -> tuple[str, str, str]:
    """(template, podvrsta, razlog). Bez modela: heuristika."""
    kat = T.kategorija_za(product.sekcija)
    dopusteni = list(T.dopusteni_templateovi(kat))
    letter = T.category_for(product.sekcija, product.naziv)
    podvrsta = T.podvrsta_heuristika(letter, product.naziv)
    if client is None:
        return letter, podvrsta, "heuristika (bez modela)"
    treba = len(dopusteni) > 1 or any(d in T.PODVRSTE for d in dopusteni)
    if not treba:
        return letter, podvrsta, "jedini template u kategoriji"
    s1 = sources[0].text if sources else ""
    raw = client.extract(
        X.build_classify_system(T.odabir_tekst(kat), dopusteni, T.PODVRSTE),
        X.build_classify_user(product, s1))
    data = X.parse_classification(raw)
    l2 = str(data.get("template", "")).strip().upper()[:1]
    if l2 in dopusteni:
        letter = l2
        pv = str(data.get("podvrsta", "")).strip()
        opcije = T.PODVRSTE.get(letter, [])
        podvrsta = next((o for o in opcije if o.lower() == pv.lower()), None) or \
            next((o for o in opcije if pv.lower() and pv.lower() in o.lower()), None) or \
            T.podvrsta_heuristika(letter, product.naziv)
        return letter, podvrsta, str(data.get("razlog", ""))[:200]
    return letter, podvrsta, "heuristika (klasifikator nije vratio dopušten template)"


def pripremi_upute(letter: str, podvrsta: str, inventory, sources: list[Source],
                   zauzeti: list[str]) -> tuple[Upute, G.Procjena | None, list[str]]:
    upute = Upute(zauzeti_poceci=list(zauzeti))
    regulatorno: list[str] = []
    ean = (inventory.ean if inventory is not None else "") or \
        (ean_sa_stranice(sources[0].text) if sources else "")
    upute.obrazac, upute.obrazac_opis = G.obrazac_prve_recenice(
        ean, pocetna_formula=(letter == "C" and podvrsta == T.POCETNA_FORMULA))
    if letter == "K":
        upute.obrazac_opis = ("terapijskim indikacijama iz Upute o lijeku (Template K "
                              "ne koristi obrasce)")
    procjena = None
    if letter in ("A", "C") and inventory is not None:
        procjena = G.procijeni(inventory.aktivne_tvari, dodatak_prehrani=(letter == "A"))
        upute.regulativa = G.blok_za_prompt(procjena, T.tvrdnje_dopustene(letter, podvrsta))
        regulatorno += procjena.upozorenja
        if letter == "A":
            nazivi = [t.tvar for t in procjena.tvari] + \
                [str(b.get("hr", "")) + " " + str(b.get("lat", ""))
                 for b in inventory.meta.get("biljne_vrste") or [] if isinstance(b, dict)]
            upute.prilog_ii = G.izvadak_priloga_ii(nazivi)
    if letter == "C" and podvrsta == T.POCETNA_FORMULA and inventory is not None and \
            str(inventory.meta.get("promocija_na_stranici", "")).lower() == "da":
        regulatorno.append("Početna formula: na stranici eLjekarne24 vidljiv je popust/akcija, "
                           "što Delegirana uredba (EU) 2016/127 ne dopušta — javiti.")
    oznaka = str((inventory.meta if inventory is not None else {}).get("oznaka_uz_naziv") or "")
    if letter == "A" and oznaka:
        upute.dodatno.append(f"Na deklaraciji uz naziv piše „{oznaka}”: prva rečenica "
                             f"kratkog opisa sadrži „dodatak prehrani {oznaka}”.")
    return upute, procjena, regulatorno


# ---------------------------------------------------------------------------
# Obrada jednog proizvoda
# ---------------------------------------------------------------------------

def process_product(product: Product, category: str, sources: list[Source],
                    client, max_attempts: int, do_verify: bool = True,
                    do_extract: bool = True, do_coverage: bool = True,
                    podvrsta: str = "", zauzeti_poceci: list[str] | None = None,
                    rescue_attempts: int = 2,
                    ) -> tuple[RowResult, str]:
    letter = category
    podvrsta = podvrsta or T.podvrsta_heuristika(letter, product.naziv)
    result = RowResult(product=product, category=letter, podvrsta=podvrsta,
                       sources=list(sources), model_id=client.model_id)

    # --- 1. ekstrakcija ---
    inventory = None
    if do_extract and sources:
        for pokusaj in range(2):
            raw_inv = client.extract(
                X.build_extract_system(letter),
                X.build_extract_user(product, sources_block(sources))
                + ("\n\nPRETHODNI ODGOVOR NIJE BIO VALJAN JSON. Vrati "
                   "ISKLJUČIVO JSON, bez teksta okolo." if pokusaj else ""))
            inventory = X.parse_inventory(raw_inv, letter)
            if inventory.ok:
                break
        result.inventory = inventory
        if not inventory.ok:
            result.status = "GREŠKA EKSTRAKCIJE"
            result.notes.append(inventory.error)
            return result, ""
        result.conflicts = [f"{f.polje}: {f.konflikt or f.vrijednost}"
                            for f in inventory.conflicts()]
        # izvori koji nisu isti proizvod i pakiranje ne idu piscu
        isti = inventory.isti_proizvod()
        odbaceni = [s for s in sources if s.sid != "S1" and isti.get(s.sid) is False]
        if odbaceni:
            sources = [s for s in sources if s not in odbaceni]
            result.info.append("odbačeni izvori (drugi proizvod ili pakiranje): "
                               + ", ".join(f"{s.sid} {s.url}" for s in odbaceni))
            for i, s in enumerate(sources, start=1):
                s.sid = f"S{i}"
            result.sources = list(sources)
            # inventar je izvučen i iz odbačenih izvora: izvuci ga ponovno samo
            # iz izvora koji su isti proizvod, da njihovi podaci ne uđu u opis
            ponovno = X.parse_inventory(client.extract(
                X.build_extract_system(letter),
                X.build_extract_user(product, sources_block(sources))), letter)
            if ponovno.ok:
                inventory = result.inventory = ponovno
                result.conflicts = [f"{f.polje}: {f.konflikt or f.vrijednost}"
                                    for f in inventory.conflicts()]

    # --- 2. regulativa ---
    if letter == "A" and inventory is not None:
        tekst = json.dumps(inventory.meta.get("biljne_vrste") or [], ensure_ascii=False) + \
            " ".join(f.vrijednost for f in inventory.found())
        zabranjene = G.zabranjene_biljke(tekst)
        if zabranjene:
            result.status = STATUS_STOP
            result.regulatorno.append("Proizvod sadrži biljnu vrstu s Priloga III. "
                                      "Pravilnika NN 160/2013: " + ", ".join(zabranjene)
                                      + ". Opis se ne piše (checklista).")
            return result, ""
    upute, procjena, regulatorno = pripremi_upute(letter, podvrsta, inventory, sources,
                                                  zauzeti_poceci or [])
    result.regulatorno += regulatorno
    result.obrazac = f"{upute.obrazac}: {upute.obrazac_opis}"

    system_prompt = build_gen_system(letter, podvrsta)
    verify_system = build_verify_system(letter, podvrsta) if do_verify else ""
    ean = (inventory.ean if inventory is not None else "") or \
        (ean_sa_stranice(sources[0].text) if sources else "")

    feedback: str | None = None
    stil_krug = False
    best_md, best_issues, best_json = "", None, {}
    best_score = (-1, -10 ** 6)

    def consider(md_text: str, issues: list[str], stage: int, js: dict) -> None:
        nonlocal best_md, best_issues, best_score, best_json
        score = (stage, -len(issues))
        if score > best_score:
            best_md, best_issues, best_score, best_json = md_text, list(issues), score, js

    # plan pokušaja: osnovni model, zatim dodatni pokušaji modelom za
    # spašavanje (npr. Opus), koji dobiva najbolju dosadašnju verziju i sve
    # dosad nađene greške te svaku ispravlja uz provjeru u izvorima
    rescue = getattr(client, "rescue_model_id", "") or ""
    plan = [None] * max_attempts + ([rescue] * rescue_attempts if rescue else [])
    ukupno = len(plan)
    svi_problemi: list[str] = []
    for attempt, model in enumerate(plan, start=1):
        result.attempts = attempt
        if model and best_md:
            if attempt == max_attempts + 1:
                result.info.append(f"dodatni pokušaj modelom {model}")
            fb = ("Ovo je dodatni pokušaj. Ispod je NAJBOLJA DOSADAŠNJA VERZIJA opisa i "
                  "popis SVIH grešaka koje su automatska kontrola i stručna provjera "
                  "dosad našle. Za svaku grešku pronađi odgovarajući podatak u izvorima "
                  "([Sx]) i ispravi ga; ako podatka nema u izvorima, izostavi tvrdnju "
                  "(ili, ako je obvezan, ostavi prazno uz [PROVJERITI: naziv]). Ne uvodi "
                  "nove podatke. Vrati cijeli ispravljeni dokument i JSON blok.\n\n"
                  "SVE DOSAD NAĐENE GREŠKE:\n"
                  + "\n".join(f"- {i}" for i in dict.fromkeys(svi_problemi))
                  + (f"\n\nZADNJA PROVJERA:\n{feedback}" if feedback else "")
                  + f"\n\nNAJBOLJA DOSADAŠNJA VERZIJA:\n<<<PDP\n{best_md}PDP>>>")
        else:
            fb = feedback
        raw = client.generate(system_prompt,
                              build_gen_user(product, letter, podvrsta, sources,
                                             fb, inventory, upute),
                              **({"model_id": model} if model else {}))
        raw, interni = odvoji_json_blok(raw)
        md = clean_markdown(raw)
        md = R.ukloni_crtice(md)
        md = R.normaliziraj_multipak(md)
        md, ean_upisan = upisi_ean(md, ean)
        if ean_upisan:
            result.info.append("EAN iz izvora automatski upisan u tablicu podataka")
        md = R.primijeni_rjecnik(md)

        errors = validate_pdp(md, product, letter, podvrsta, sources, inventory,
                              procjena, upute,
                              inventory.meta if inventory is not None else {})
        if errors:
            svi_problemi.extend(errors)
            consider(md, errors, 0, interni)
            feedback = ("Greške automatske kontrole (pravila templatea i checkliste):\n"
                        + "\n".join(f"- {e}" for e in errors))
            continue

        if do_coverage and inventory is not None:
            gaps = X.coverage_check(inventory, md)
            if gaps:
                svi_problemi.extend(gaps)
                result.coverage = gaps
                consider(md, gaps, 1, interni)
                feedback = ("Podaci koji POSTOJE u izvorima nisu preneseni u opis. "
                            "Dopuni opis tim podacima u odgovarajućem tabu:\n"
                            + "\n".join(f"- {g}" for g in gaps))
                continue
            result.coverage = []

        if do_verify:
            verdict = parse_verifier_json(client.verify(
                verify_system, build_verify_user(product, sources, md, upute)))
            if verdict is None:
                result.verified = "neuspjelo parsiranje odgovora stručne provjere"
                result.notes.append("stručna provjera nije vratila valjan JSON")
            elif not verdict.get("prolazi") and verdict["greske"]:
                issues = [f"[{g.get('vrsta', '')}] {g.get('mjesto', '')}: {g['problem']}"
                          + (f" → {g['ispravak']}" if g.get("ispravak") else "")
                          for g in verdict["greske"]]
                # činjenične i regulatorne greške blokiraju; stilske se šalju
                # piscu jednom, a zatim bilježe kao napomena
                blokira = [i for i, g in zip(issues, verdict["greske"])
                           if "pisanje" not in str(g.get("vrsta", "")).lower()]
                if blokira or (not stil_krug and attempt < ukupno):
                    stil_krug = stil_krug or not blokira
                    svi_problemi.extend(issues)
                    consider(md, issues, 2, interni)
                    result.verified = "ne prolazi"
                    feedback = ("Stručna provjera (drugi agent) našla je greške. "
                                "Ispravi ih:\n" + "\n".join(f"- {i}" for i in issues))
                    continue
                result.verified = "prolazi (stilske napomene)"
                result.info.extend(f"stručna provjera (stil): {i}" for i in issues)
            else:
                result.verified = "prolazi"
                if verdict.get("napomena"):
                    result.info.append(f"stručna provjera: {verdict['napomena']}")
        else:
            result.verified = "preskočeno"

        return _zavrsi(result, md, interni, sources, ok=True), \
            dodaj_tablicu_izvora(md, sources, interni.get("izvori") or {})

    issues = best_issues or ["model nije vratio upotrebljiv dokument"]
    result.unsupported = [i for i in issues if i.startswith(("[činjenica]", "[regulativa]"))
                          or "dokumenta tvrdnji" in i]
    result.notes.extend(issues)
    _zavrsi(result, best_md, best_json, sources, ok=False)
    md_out = dodaj_tablicu_izvora(best_md, sources, best_json.get("izvori") or {}) \
        if best_md.strip() else ""
    return result, md_out


def _zavrsi(result: RowResult, md: str, interni: dict, sources: list[Source],
            ok: bool) -> RowResult:
    result.nedostaje = [str(x) for x in (interni.get("nedostaje") or [])]
    if interni.get("konflikti"):
        result.conflicts = [str(x) for x in interni["konflikti"]]
    result.provjeriti = oznake_za_provjeru(md)
    result.prva_recenica = (recenice(kratki_opis(md)) or [""])[0]
    # Status „TREBA PROVJERA” je ukinut (klijent, 31. 10. 2026.): isporučuje se
    # najbolja verzija, a status kaže samo ima li podataka za provjeru na
    # ambalaži (crvene oznake, obvezni podatak koji nedostaje, regulatorna
    # napomena). Preostale napomene kontrole ostaju samo u results.jsonl.
    if result.provjeriti or result.nedostaje or result.regulatorno:
        result.status = STATUS_PROVJERITI
    else:
        result.status = STATUS_OK
    return result


# ---------------------------------------------------------------------------
# Ulaz / izlaz
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {"sekcija": "sekcija", "brend": "brend", "brand": "brend",
                  "sku": "sku", "šifra": "sku", "sifra": "sku", "naziv": "naziv",
                  "name": "naziv", "url": "url", "link": "url"}


def load_products(path: Path) -> list[Product]:
    import pandas as pd

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(path, dtype=str, keep_default_na=False)
    mapping = {}
    for col in df.columns:
        key = COLUMN_ALIASES.get(str(col).strip().lower())
        if key:
            mapping[key] = col
    for required in ("naziv", "url"):
        if required not in mapping:
            sys.exit(f"Ulazna tablica nema stupac '{required}'. "
                     f"Nađeni stupci: {list(df.columns)}")
    products = []
    for _, row in df.iterrows():
        naziv = str(row[mapping["naziv"]]).strip()
        url = str(row[mapping["url"]]).strip()
        if not naziv or not url:
            continue
        products.append(Product(
            sekcija=str(row[mapping["sekcija"]]).strip() if "sekcija" in mapping else "",
            brend=str(row[mapping["brend"]]).strip() if "brend" in mapping else "",
            sku=str(row[mapping["sku"]]).strip() if "sku" in mapping else url,
            naziv=naziv, url=url,
        ))
    return products


def write_index(records: list[dict], out_dir: Path) -> tuple[Path, Path]:
    import pandas as pd

    df = pd.DataFrame(records)
    xlsx_path = out_dir / "pdp_indeks.xlsx"
    csv_path = out_dir / "pdp_indeks.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="PDP indeks")
    return xlsx_path, csv_path


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


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
# Main (samostalno pokretanje, samo PDP)
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Generator PDP opisa (template ver.11).")
    ap.add_argument("--input", "-i", required=True, help="XLSX ili CSV s proizvodima")
    ap.add_argument("--output", "-o", default="out_pdp", help="izlazna mapa")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sku", action="append", default=[])
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--search-results", type=int, default=3)
    ap.add_argument("--pim-dir", default="", help="mapa s ambalažom / PIM-om (razina 1)")
    ap.add_argument("--no-web-search", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--retry-review", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    pdp_dir = out_dir / "pdp"
    pdp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".cache" / "html"
    jsonl_path = out_dir / "results.jsonl"
    pim_dir = Path(args.pim_dir) if args.pim_dir else None

    products = load_products(Path(args.input))
    if args.sku:
        wanted = {s.strip() for s in args.sku}
        products = [p for p in products if p.sku in wanted]
    if args.limit:
        products = products[: args.limit]
    if not products:
        sys.exit("Nema proizvoda za obradu.")

    def get_sources(p: Product, letter: str) -> list[Source]:
        if args.no_fetch:
            return []
        return gather_sources(p, letter, cache_dir, refresh=args.refresh_cache,
                              web_search=not args.no_web_search,
                              max_web=args.search_results, pim_dir=pim_dir)

    if args.dry_run:
        p = products[0]
        letter = T.category_for(p.sekcija, p.naziv)
        sources = get_sources(p, letter)
        print(f"\n--- {T.label(letter)} | IZVORA: {len(sources)} ---")
        for s in sources:
            print(f"  [{s.sid}] {s.kind}: {s.url} ({len(s.text)} znakova)")
        print(f"\n--- USER MESSAGE ---\n{build_gen_user(p, letter, '', sources)[:5000]}")
        return

    config = load_bedrock_config()
    client = BedrockClient(config)
    done = {} if args.force else load_done(jsonl_path)
    if args.retry_review:
        done = {k: v for k, v in done.items() if str(v.get("Status", "")).startswith("OK")}
    records: dict[str, dict] = dict(done)
    todo = [p for p in products if p.sku not in records]
    zauzeti: dict[str, list[str]] = {}

    from botocore.exceptions import ClientError  # noqa: PLC0415
    try:
        for idx, p in enumerate(todo, start=1):
            letter0 = T.category_for(p.sekcija, p.naziv)
            sources = get_sources(p, letter0)
            letter, podvrsta, razlog = klasificiraj(p, sources, client)
            result, md = process_product(p, letter, sources, client, args.max_attempts,
                                         do_verify=not args.no_verify, podvrsta=podvrsta,
                                         zauzeti_poceci=zauzeti.get(letter, []))
            result.klasifikacija = razlog
            if result.prva_recenica:
                zauzeti.setdefault(letter, []).append(pocetak(result.prva_recenica))
            if md.strip():
                stem = f"PDP_{p.sku}_{slugify(p.naziv)}"
                (pdp_dir / f"{stem}.md").write_text(md, encoding="utf-8")
                result.md_path = str(pdp_dir / f"{stem}.md")
                try:
                    md_to_docx(md, pdp_dir / f"{stem}.docx")
                    result.docx_path = str(pdp_dir / f"{stem}.docx")
                except Exception as err:  # noqa: BLE001
                    result.notes.append(f"DOCX nije zapisan: {err}")
            record = result.to_record()
            records[p.sku] = record
            append_jsonl(jsonl_path, record)
            print(f"[{idx}/{len(todo)}] {p.sku} {p.naziv[:44]:<44} -> "
                  f"{letter} {result.status} (pokušaja: {result.attempts})")
    except ClientError as err:
        print("\nBedrock greška:\n  " + explain_client_error(err, config))
        sys.exit(1)

    ordered = [records[p.sku] for p in products if p.sku in records]
    xlsx_path, _ = write_index(ordered, out_dir)
    print(f"\nIndeks: {xlsx_path}")


if __name__ == "__main__":
    main()
