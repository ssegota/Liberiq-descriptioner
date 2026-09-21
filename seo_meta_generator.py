#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generator title tagova i meta opisa za eljekarna24 (Claude Opus na AWS Bedrock).

Za svaki proizvod iz ulazne tablice (XLSX/CSV sa stupcima: Sekcija, Brend, SKU,
Naziv, URL):

  1. dohvaća stranicu proizvoda i vadi opis + specifikacije (JSON-LD, og:description,
     WooCommerce blokovi, tablica atributa),
  2. šalje upit Claude Opusu (Bedrock Converse API, isti .env kao bedrock-test.py),
  3. STROGO validira rezultat prema pravilima iz dokumenta
     "Pravila meta opis i title tag":
        - Title tag: max 550 px (Arial 20 px), naziv proizvoda na početku,
          " │ eljekarna24" se dodaje automatski SAMO ako ukupno stane u 550 px,
          bez ALL-CAPS riječi, bez akcija/cijena/dostave/superlativa.
        - Meta opis: max 960 px (Arial 14 px), naziv + namjena + 1-2 provjerljive
          specifikacije, bez cijene/zalihe/dostave, bez CTA-a, potpuna zadnja
          rečenica, jedinstven po URL-u.
        - Anti-halucinacija: svaki broj+jedinica (npr. "75 ml", "SPF50", "500 mg")
          u meta opisu mora postojati u nazivu ili sadržaju stranice.
  4. Greške vraća modelu na ispravak (do --max-attempts pokušaja). Ako i dalje ne
     prolazi, primjenjuje pravilo skraćivanja iz dokumenta (prvo CTA/opći pridjevi/
     sporedne značajke tj. zadnje rečenice/riječi; nikad naziv, tip, volumen).
  5. Zapisuje XLSX + CSV s izmjerenim pikselima, statusom i napomenama.
     Međurezultati idu u results.jsonl pa se prekinuti run nastavlja (resume).

Pokretanje:
    pip install -r requirements.txt
    cp .env.example .env   # upisati ključeve i model ID
    python seo_meta_generator.py --input eljekarna24_proizvodi_75_kom.xlsx

Korisne opcije:
    --limit 5            samo prvih 5 proizvoda (test)
    --sku C002167        samo jedan SKU
    --dry-run            bez poziva Bedrocku: dohvat stranica + prikaz prompta
    --no-fetch           bez dohvaćanja stranica (koristi samo Naziv/Brend)
    --force              ignoriraj postojeće rezultate i generiraj ponovno
    --retry-review       ponovno generiraj samo retke koji nisu OK
    --workers 3          paralelni pozivi (oprez s throttlingom)
"""

from __future__ import annotations

import argparse
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
from concurrent.futures import ThreadPoolExecutor, as_completed

import pravila as R
import prompts_cfg

# ---------------------------------------------------------------------------
# Limiti i konstante (iz dokumenta s pravilima)
# ---------------------------------------------------------------------------

TITLE_MAX_PX = 550.0          # tvrdi limit za cijeli title (s dodatkom)
META_MAX_PX = 960.0           # tvrdi limit za meta opis
TITLE_FONT_PX = 20.0          # Google SERP: title ~ Arial 20 px (desktop)
META_FONT_PX = 14.0           # Google SERP: opis ~ Arial 14 px (desktop)
BRAND_SUFFIX = " | eljekarna24"   # U+007C (klijent: NE koristiti │ U+2502)

META_TARGET_CHARS = "120–150"  # samo smjernica modelu; mjerodavni su pikseli

SYSTEM_PROMPT_HEADER = (
    'Ti si SEO specijalist za hrvatsku internetsku ljekarnu "eljekarna24". '
    "Za zadani proizvod pišeš TITLE TAG i META OPIS na hrvatskom jeziku, "
    "strogo prema pravilima u nastavku. Odgovaraš ISKLJUČIVO validnim JSON-om."
)

MAX_TOKENS = 700
TEMPERATURE = 0.2
PAGE_CONTENT_CAP = 4500       # znakova sadržaja stranice u promptu
BEDROCK_RETRIES = 5           # retry na throttling/5xx

# ---------------------------------------------------------------------------
# Mjerenje širine u pikselima (Arial, standardne AFM širine, jedinice /1000 em)
# ---------------------------------------------------------------------------

ARIAL_WIDTHS = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667,
    "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
    ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556,
    "7": 556, "8": 556, "9": 556,
    ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722,
    "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722,
    "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611,
    "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556,
    "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556,
    "o": 556, "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556,
    "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
    "{": 334, "|": 260, "}": 334, "~": 584,
}
SPECIAL_WIDTHS = {
    "đ": 556, "Đ": 722, "│": 260, "–": 556, "—": 1000, "\u2019": 191,
    "\u2018": 191, "\u201c": 333, "\u201d": 333, "…": 1000, "®": 737,
    "™": 1000, "°": 400, "×": 584, "µ": 556, "\u00a0": 278, "€": 556,
}
DEFAULT_WIDTH = 556


def _char_width_units(ch: str) -> int:
    if ch in ARIAL_WIDTHS:
        return ARIAL_WIDTHS[ch]
    if ch in SPECIAL_WIDTHS:
        return SPECIAL_WIDTHS[ch]
    # dijakritike (č, ć, ž, š, é, ...) -> širina osnovnog slova
    decomposed = unicodedata.normalize("NFD", ch)
    if decomposed and decomposed[0] in ARIAL_WIDTHS:
        return ARIAL_WIDTHS[decomposed[0]]
    return DEFAULT_WIDTH


def text_width_px(text: str, font_px: float) -> float:
    """Aproksimacija širine teksta u SERP-u (Arial, bez keminga)."""
    return sum(_char_width_units(ch) for ch in text) * font_px / 1000.0


SUFFIX_PX = text_width_px(BRAND_SUFFIX, TITLE_FONT_PX)
TITLE_CORE_TARGET_PX = TITLE_MAX_PX - SUFFIX_PX  # cilj za osnovni title


# ---------------------------------------------------------------------------
# Normalizacija teksta (za usporedbe)
# ---------------------------------------------------------------------------

def strip_diacritics(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)
    )


def norm_compact(s: str) -> str:
    """malaslova, bez dijakritika, samo [a-z0-9] — za substring provjere."""
    return re.sub(r"[^a-z0-9]", "", strip_diacritics(s or "").lower())


def norm_spaced(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", strip_diacritics(s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


CRO_STOPWORDS = {
    "za", "sa", "od", "do", "na", "u", "i", "ili", "te", "bez", "koji",
    "koja", "koje", "the", "of", "with", "uz", "iz", "kod",
}


def significant_name_tokens(naziv: str, max_tokens: int = 6) -> list[str]:
    """Prvih nekoliko 'pravih' riječi naziva (bez brojeva, jedinica, veznika)."""
    out = []
    for tok in norm_spaced(naziv).split():
        if len(tok) < 3 or tok.isdigit() or tok in CRO_STOPWORDS:
            continue
        if re.fullmatch(r"\d+(ml|mg|g|kg|l)", tok):
            continue
        out.append(tok)
        if len(out) >= max_tokens:
            break
    return out


# ---------------------------------------------------------------------------
# Zabranjeni izrazi (provjera na normaliziranom tekstu bez dijakritika)
# ---------------------------------------------------------------------------

EXEMPT_PATTERNS = [
    re.compile(r"dojenje je najbolji nacin prehrane dojenceta"),
    re.compile(r"\bnajvise\b"), re.compile(r"\bnajmanje\b"),
    re.compile(r"\bnajkasnije\b"), re.compile(r"\bnajranije\b"),
]

FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(p), label) for p, label in [
        (r"\bcijen\w*", "cijena"),
        (r"\b\d+[.,]?\d*\s*(kn|eur)\b", "cijena/valuta"),
        (r"\bakcij\w*", "akcija/promo"),
        (r"\bpopust\w*", "popust"),
        (r"\bsnizen\w*", "sniženje"),
        (r"\brasprodaj\w*", "rasprodaja"),
        (r"\bgratis\b", "gratis/promo"),
        (r"\bzalih\w*", "zaliha"),
        (r"\bdostupn\w*\s+odmah\b", "dostupnost"),
        (r"\bdostav\w*", "dostava"),
        (r"\bisporuk\w*", "isporuka"),
        (r"\bpostarin\w*", "poštarina"),
        (r"\bnaruc\w*", "CTA: naruči"),
        (r"\bkupi(te)?\b", "CTA: kupi"),
        (r"\bkupuj\w*", "CTA: kupujte"),
        (r"\bkliknite\b", "CTA"),
        (r"\bsaznajte\b", "CTA: saznajte više"),
        (r"\bposjetite\b", "CTA"),
        (r"\botkrijte\b", "CTA"),
        (r"\bpogledajte\b", "CTA"),
        (r"\bisprobajte\b", "CTA"),
        (r"\bnajbolj\w*", "superlativ"),
        (r"\bnajkvalitetnij\w*", "superlativ"),
        (r"\bvrhunsk\w*", "neprovjereni superlativ"),
        (r"\bsavrsen\w*", "superlativ"),
        (r"\bcudesn\w*", "superlativ"),
        (r"\bidealn?\w*", "neprovjeren superlativ (idealan/idealno)"),
        (r"\bnajucinkovitij\w*", "definitivna tvrdnja (najučinkovitiji)"),
        (r"\bnajdjelotvornij\w*", "definitivna tvrdnja"),
        (r"\bnajjac\w*", "definitivna tvrdnja (najjači)"),
        (r"\bnajsigurnij\w*", "definitivna tvrdnja (najsigurniji)"),
        (r"\bnajnjeznij\w*", "definitivna tvrdnja (najnježniji)"),
        (r"\bnajpopularnij\w*", "neprovjerena tvrdnja (najpopularniji)"),
        (r"\bnajprodavanij\w*", "neprovjerena tvrdnja (najprodavaniji)"),
        (r"\bnajbrz\w*", "definitivna tvrdnja (najbrži)"),
        (r"\bnaj\w{3,}(iji|ija|ije|ijeg|ijem)\b", "superlativ"),
        (r"\bjedini\w*\b", "isključiva tvrdnja (jedini)"),
        (r"\bnema premca\b", "definitivna tvrdnja"),
        (r"\bzlatni standard\b", "definitivna tvrdnja"),
        (r"\bprvi izbor\b", "definitivna tvrdnja"),
        (r"\bapsolutno\b", "apsolutna tvrdnja"),
        (r"\buvijek djeluje\b", "apsolutna tvrdnja"),
        (r"\bsvima odgovara\b", "apsolutna tvrdnja"),
        (r"\bbez iznimke\b", "apsolutna tvrdnja"),
        (r"\bsigurno ce\b", "obećanje rezultata"),
        (r"\btrenutn\w* rezultat\w*", "obećanje rezultata"),
        (r"\bodmah uklanja\b", "obećanje rezultata"),
        (r"\bpotpuno bezopasan\w*", "apsolutna tvrdnja"),
        (r"\bbez ikakvih nuspojava\b", "apsolutna tvrdnja"),
        (r"\bnenadmasn\w*", "superlativ"),
        (r"\bjedinstven\w* na trzistu", "neprovjerena tvrdnja"),
        (r"\brevolucionar\w*", "superlativ"),
        (r"\b100\s?%", "neprovjerena tvrdnja (100%)"),
        (r"\bbr(oj)?\.?\s?1\b", "superlativ (br. 1)"),
        (r"\bjamci\w*", "jamstvo/tvrdnja"),
        (r"\bgarantir\w*", "jamstvo/tvrdnja"),
        (r"\bgarancij\w*", "jamstvo/tvrdnja"),
        (r"\blijeci\b", "medicinska tvrdnja (liječi)"),
        (r"\bizlijec\w*", "medicinska tvrdnja (izliječi)"),
    ]
]
FORBIDDEN_RAW_CHARS = [("€", "cijena/valuta"), ("%", None)]  # % rješava spec-provjera

CAPS_ALLOWLIST = {"AFIB", "UVA1"}  # kratice koje smiju ostati velikim slovima

# --- klijentova pravila o zapisu količine (uputa nakon testiranja) ---
# zarez neposredno ispred količine: "..., 100 tableta"
COMMA_BEFORE_QTY_RE = re.compile(
    r",\s*\d+(?:[.,]\d+)?\s*"
    r"(?:ml|g|kg|l|mg|mcg|µg|IU|tablet\w*|kapsul\w*|vrećic\w*|vrecic\w*|komad\w*|"
    r"tab|tbl|kap|kaps|kom)\b",
    re.IGNORECASE)
# kratica jedinice umjesto pune riječi: 60 tab, 30 kap, 60 kom, 20 tbl
UNIT_ABBREV_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(tab|tbl|kap|kaps|kom|kpl|vreć|vrec)\b\.?",
    re.IGNORECASE)
# broj i jedinica bez razmaka: 75ml, 100mg
NO_SPACE_UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?(ml|mg|mcg|kg|g|l|IU)\b")
# oznake namjene u meta opisu (klijent: namjena je OBVEZNA)
# Količina PAKIRANJA (mg, mcg, µg i IU su jačina, ne količina pakiranja).
KOLICINA_U_META_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:ml|l|kg|g|tablet\w*|kapsul\w*|vrećic\w*|"
    r"vrecic\w*|komad\w*|bombon\w*|šumeć\w*)\b", re.IGNORECASE)

PURPOSE_RE = re.compile(
    r"\b(za |kod |protiv |namijenjen\w*|namjena|pomaže|pomaze|doprinosi|"
    r"koristi se|primjenjuje se|u njezi|za njegu|za zaštitu|za zastitu|"
    r"za hidrataciju|za čišćenje|za ciscenje|za mjerenje|za prehranu)",
    re.IGNORECASE)
CAPS_WORD_RE = re.compile(r"\b[A-ZČĆŽŠĐ]{4,}\b")

SPEC_TOKEN_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*"
    r"(ml|mg|g|kg|l|mcg|iu|ie|kom|kapsul\w*|tablet\w*|vrecic\w*|%)\b"
)
SPF_RE = re.compile(r"\bspf\s*(\d+\+?)\b")
UNIT_MAP = {"kapsul": "kapsul", "tablet": "tablet", "vrecic": "vrecic"}


def quantity_tokens(text: str) -> set[str]:
    """Količine (broj + jedinica) — moraju preživjeti skraćivanje."""
    return spec_tokens(text)


def find_forbidden(text: str) -> list[str]:
    hits = []
    normed = norm_spaced(text)
    for pat in EXEMPT_PATTERNS:
        normed = pat.sub(" ", normed)
    for pat, label in FORBIDDEN_PATTERNS:
        m = pat.search(normed)
        if m:
            hits.append(f"'{m.group(0)}' ({label})")
    for ch, label in FORBIDDEN_RAW_CHARS:
        if label and ch in text:
            hits.append(f"'{ch}' ({label})")
    return hits


def spec_tokens(text: str) -> set[str]:
    """Izvuci normalizirane tokene broj+jedinica i SPF vrijednosti."""
    normed = norm_spaced(text)
    out = set()
    for num, unit in SPEC_TOKEN_RE.findall(normed):
        unit_key = next((v for k, v in UNIT_MAP.items() if unit.startswith(k)), unit)
        out.add(num.replace(",", ".") + unit_key)
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
class PageData:
    fetched: bool = False
    from_cache: bool = False
    content: str = ""            # očišćeni tekst za prompt
    existing_title: str = ""     # trenutni <title> (samo za QA usporedbu)
    existing_meta: str = ""      # trenutni meta description (samo za QA)
    note: str = ""


@dataclass
class BrandSource:
    """Izvor 2 — službena stranica brenda (samo za podatke kojih nema na S1)."""
    url: str = ""
    text: str = ""


@dataclass
class Candidate:
    title_core: str = ""
    meta: str = ""
    specs_used: list = field(default_factory=list)
    namjena: str = ""
    namjena_potvrdjena: bool = True
    brand_data: list = field(default_factory=list)
    raw: str = ""


@dataclass
class RowResult:
    product: Product
    title: str = ""
    meta: str = ""
    title_px: float = 0.0
    meta_px: float = 0.0
    status: str = "TREBA PROVJERA"
    attempts: int = 0
    notes: list = field(default_factory=list)
    specs_used: list = field(default_factory=list)
    namjena: str = ""
    brand_url: str = ""
    brand_data: list = field(default_factory=list)
    page: PageData = field(default_factory=PageData)
    model_id: str = ""

    def to_record(self) -> dict:
        return {
            "Sekcija": self.product.sekcija,
            "Brend": self.product.brend,
            "SKU": self.product.sku,
            "Naziv": self.product.naziv,
            "URL": self.product.url,
            "Title tag": self.title,
            "Title px": round(self.title_px, 1),
            "Title znakova": len(self.title),
            "Meta opis": self.meta,
            "Meta px": round(self.meta_px, 1),
            "Meta znakova": len(self.meta),
            "Status": self.status,
            "Pokušaji": self.attempts,
            "Napomene": " | ".join(self.notes),
            "Korištene specifikacije": "; ".join(map(str, self.specs_used)),
            "Namjena": self.namjena,
            "Izvor – eljekarna24": self.product.url if self.page.fetched else "",
            "Izvor – brend": self.brand_url if self.brand_data else "",
            "Preuzeto s brend stranice": ", ".join(self.brand_data),
            "Napomena za provjeru": ("TREBA PROVJERA – podatak nije s eljekarna24"
                                     if self.brand_data else ""),
            "Stranica dohvaćena": "da" if self.page.fetched else "ne",
            "Postojeći title (QA)": self.page.existing_title,
            "Postojeći meta (QA)": self.page.existing_meta,
            "Model": self.model_id,
        }


# ---------------------------------------------------------------------------
# Dohvat i ekstrakcija sadržaja stranice proizvoda
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 eljekarna24-interni-seo-alat"
)

CONTENT_SELECTORS = [
    ".woocommerce-product-details__short-description",
    ".woocommerce-Tabs-panel--description",
    "#tab-description",
    "[itemprop='description']",
    ".product-short-description",
    ".product_description",
    ".product-description",
    "#description",
    ".entry-summary",
]
ATTR_TABLE_SELECTORS = "table.woocommerce-product-attributes, table.shop_attributes"
DROP_LINE_RE = re.compile(
    r"(€|\bkn\b|\bcijena\b|\bdostav\w*|\bdostupnost\b|\bna zalihi\b|"
    r"\bkosaric\w*|\bkošaric\w*|\bpopust\w*|\bakcij\w*)",
    re.IGNORECASE,
)


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


def extract_page_data(html: str) -> PageData:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    data = PageData(fetched=True)

    if soup.title and soup.title.string:
        data.existing_title = " ".join(soup.title.string.split())
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        data.existing_meta = " ".join(md["content"].split())

    parts: list[str] = []

    for prod in _jsonld_products(soup):
        desc = prod.get("description") or ""
        if desc:
            desc_text = BeautifulSoup(str(desc), "html.parser").get_text(" ", strip=True)
            parts.append("OPIS (schema): " + desc_text)
        brand = prod.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if brand:
            parts.append(f"BREND (schema): {brand}")

    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        parts.append("OPIS (og): " + " ".join(og["content"].split()))

    for sel in CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 40:
                parts.append("OPIS (stranica): " + txt)

    for table in soup.select(ATTR_TABLE_SELECTORS):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 2 and cells[0] and cells[1]:
                parts.append(f"ATRIBUT: {cells[0]}: {cells[1]}")

    if not parts:  # zadnja opcija: glavni sadržaj stranice
        main = soup.find("main") or soup.find("article") or soup.body
        if main:
            parts.append(main.get_text(" ", strip=True))
        data.note = "sadržaj izvučen generički (nije prepoznat blok opisa)"

    # dedup + čišćenje redaka s cijenom/zalihom/dostavom
    seen, lines = set(), []
    for part in parts:
        for line in re.split(r"(?<=[.!?])\s+|\n", part):
            line = " ".join(line.split())
            if len(line) < 3 or DROP_LINE_RE.search(line):
                continue
            key = norm_compact(line)[:80]
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)

    data.content = "\n".join(lines)[:PAGE_CONTENT_CAP]
    return data


def fetch_page(url: str, cache_dir: Path, refresh: bool, timeout: int = 20) -> PageData:
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    html, from_cache = None, False
    if cache_file.exists() and not refresh:
        html = cache_file.read_text(encoding="utf-8", errors="ignore")
        from_cache = True
    else:
        try:
            resp = requests.get(
                url, headers={"User-Agent": USER_AGENT, "Accept-Language": "hr"},
                timeout=timeout,
            )
            resp.raise_for_status()
            html = resp.text
            cache_file.write_text(html, encoding="utf-8", errors="ignore")
        except Exception as err:  # noqa: BLE001 — svaki problem = radi bez stranice
            data = PageData(fetched=False, note=f"dohvat nije uspio: {err}")
            return data

    data = extract_page_data(html)
    data.from_cache = from_cache
    if not data.content:
        data.fetched = False
        data.note = data.note or "stranica dohvaćena, ali bez upotrebljivog sadržaja"
    return data


# ---------------------------------------------------------------------------
# Bedrock klijent (isti .env i Converse API kao u bedrock-test.py)
# ---------------------------------------------------------------------------

def load_bedrock_config() -> dict:
    from dotenv import load_dotenv

    load_dotenv()
    required = [
        "BEDROCK_AWS_ACCESS_KEY_ID",
        "BEDROCK_AWS_SECRET_ACCESS_KEY",
        "BEDROCK_TEXT_MODEL_ID",
        "BEDROCK_AWS_REGION",
    ]
    config = {key: os.getenv(key) for key in required}
    missing = [key for key, value in config.items() if not value]
    if missing:
        sys.exit(f"Nedostaje u .env: {', '.join(missing)}")
    return config


class BedrockClient:
    def __init__(self, config: dict):
        import boto3
        from botocore.config import Config

        self.model_id = config["BEDROCK_TEXT_MODEL_ID"]
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=config["BEDROCK_AWS_REGION"],
            aws_access_key_id=config["BEDROCK_AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=config["BEDROCK_AWS_SECRET_ACCESS_KEY"],
            config=Config(
                read_timeout=120,
                connect_timeout=10,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def generate(self, system_prompt: str, user_message: str) -> str:
        from botocore.exceptions import ClientError

        last_err = None
        for attempt in range(BEDROCK_RETRIES):
            try:
                resp = self._client.converse(
                    modelId=self.model_id,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_message}]}],
                    inferenceConfig={
                        "maxTokens": MAX_TOKENS,
                        "temperature": TEMPERATURE,
                    },
                )
                blocks = resp["output"]["message"]["content"]
                return "".join(b.get("text", "") for b in blocks).strip()
            except ClientError as err:
                code = err.response["Error"]["Code"]
                if code in {
                    "ThrottlingException",
                    "ServiceUnavailableException",
                    "InternalServerException",
                    "ModelNotReadyException",
                } and attempt < BEDROCK_RETRIES - 1:
                    wait = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(wait)
                    last_err = err
                    continue
                raise
        raise last_err  # type: ignore[misc]


def explain_client_error(err, config: dict) -> str:
    code = err.response["Error"]["Code"]
    message = err.response["Error"]["Message"]
    hints = {
        "AccessDeniedException": (
            "IAM korisniku nedostaje bedrock:InvokeModel ili pristup modelu "
            f"{config['BEDROCK_TEXT_MODEL_ID']} nije odobren u Bedrock konzoli."
        ),
        "ValidationException": (
            "Najčešće pogrešan model ID. Prefiks 'eu.'/'global.' znači inference "
            f"profil koji mora postojati u regiji {config['BEDROCK_AWS_REGION']}. "
            "Provjeri: aws bedrock list-inference-profiles --region "
            f"{config['BEDROCK_AWS_REGION']}"
        ),
        "ResourceNotFoundException": (
            f"Model/profil ne postoji u regiji {config['BEDROCK_AWS_REGION']}."
        ),
        "UnrecognizedClientException": "Pogrešan access key ili secret key.",
        "ThrottlingException": "Rate limit; smanji --workers ili pričekaj.",
    }
    detail = hints.get(code, "")
    return f"[{code}] {message}" + (f"\n  -> {detail}" if detail else "")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_system_prompt() -> str:
    default = f"""{SYSTEM_PROMPT_HEADER}

PRAVILA ZA TITLE TAG
1. Piši SAMO osnovni title, BEZ dodatka "{BRAND_SUFFIX.strip()}" — sustav ga dodaje
   automatski na kraj ako ukupna širina ostaje unutar {TITLE_MAX_PX:.0f} px.
2. Naziv proizvoda mora biti na POČETKU; najvažniji pojam ide prvi.
3. Dodaj volumen, veličinu, model, materijal ili bitnu funkciju SAMO kada time
   proizvod postaje preciznije identificiran.
4. Ciljna duljina osnovnog titlea: do ~45 znakova (interni tvrdi limit je
   {TITLE_CORE_TARGET_PX:.0f} px za osnovni dio; sustav mjeri piksele, ne znakove).
5. ZABRANJENO: nizovi ključnih riječi, akcije, cijene, dostava, RIJEČI PISANE
   VELIKIM SLOVIMA (osim standardnih kratica poput SPF), neprovjereni superlativi
   (uključujući "idealan", "idealno", "savršen", "najbolji").
5f. TITLE SE GRADI IZ PDP NAZIVA: koristi SAMO riječi iz kanonskog naziva,
   istim redoslijedom. Ne preformuliraj i ne dodaj riječi kojih ondje nema.
5g. Uvijek zadrži brend, naziv linije, tip proizvoda, varijantu (nijansa, SPF,
   Riche, Légère, jakost) i količinu s jedinicom.
5h. Ako treba skratiti, ukloni CIJELI segment ovim redom: namjena iza crtice
   ili zareza, zatim opći pridjevi, zatim sporedne značajke. Nikad ne reži
   frazu na pola.
5i. Title ne završava prijedlogom, veznikom ni znakom (za, i, s, od, protiv, &)
   ni brojem bez jedinice.
5j. BEZ CRTICA (– i —) u titlu i meta opisu. Umjesto njih zarez ili točka.
5k. NIKAD DEFINITIVNI IZRAZI koji nisu specifično dokazani u izvorima:
   "najbolji", "najučinkovitiji", "najsigurniji", "jedini", "zlatni standard",
   "prvi izbor", "apsolutno", "uvijek djeluje", "svima odgovara", "bez
   iznimke", "trenutni rezultati", "bez ikakvih nuspojava". Umjesto tvrdnje o
   nadmoći navedi konkretan, provjerljiv podatak iz izvora.
5a. KOLIČINA SE PIŠE NA KRAJU, BEZ ZAREZA ISPRED: "Solgar Vitamin K1 100 mcg
   100 tableta", NE "..., 100 tableta".
5b. JEDINICA SE PIŠE PUNOM RIJEČJU: "100 tableta", "30 kapsula", "60 komada" —
   nikad "100 tab", "30 kap", "60 kom".
5c. IZMEĐU BROJA I JEDINICE IDE RAZMAK: "75 ml", nikad "75ml".
5d. KOLIČINA (volumen, dimenzija, broj jedinica) SE NIKAD NE UKLANJA pri
   skraćivanju. Prvo se uklanjaju CTA, opći pridjevi i sporedne značajke;
   naziv proizvoda, tip proizvoda, količina i glavna namjena ostaju.
6. Ulazni naziv iz baze često je pisan velikim slovima — normaliziraj ga u
   normalno pisanje (velika samo početna slova imena i početak).
7. Svaki proizvod mora dobiti jedinstven title koji opisuje baš taj proizvod.

PRAVILA ZA META OPIS
1. Struktura: naziv proizvoda + NAMJENA + 1–2 PROVJERLJIVE specifikacije iz
   priloženog sadržaja stranice (ili iz naziva ako sadržaja nema).
1a. NAMJENA JE OBVEZNA, ne opcionalna: mora biti jasno KOME ili ČEMU proizvod
   služi (npr. "za masnu kožu sklonu nepravilnostima", "za odrasle koji žele
   nadopuniti unos vitamina D", "za kućno mjerenje krvnog tlaka"). Ako se
   namjena NE MOŽE potvrditi iz izvora, NE izmišljaj je — u polje
   "namjena_potvrdjena" upiši false i napiši meta opis bez izmišljene namjene.
1b. PRVA REČENICA: naziv bez količine, zatim namjena, zatim količina.
   Primjer: „Solgar Vitamin K1 100 mcg za odrasle, 100 tableta.“
   DRUGA REČENICA: jedna ili dvije specifikacije iz izvora.
1c. Namjena mora biti unutar prvih 100 znakova.
1d. Količina se piše SAMO JEDNOM, u prvoj rečenici. Bez „Pakiranje od“,
   „Volumen“, „Dostupno u“.
1e. Meta opis sadrži brend i naziv linije iz titla.
1f. TVRDNJE PO KATEGORIJI: dodaci prehrani samo odobrene zdravstvene tvrdnje
   doslovno iz izvora; hrana za dojenčad samo namjena i dob, bez zdravstvenih
   tvrdnji; medicinski proizvodi samo tvrdnje iz upute; kozmetika tvrdnja o
   učinku samo doslovno iz izvora. Ne pojačavaj tvrdnju iz izvora
   („podnošljivost ispitana na atopičnoj koži“ nije „pogodno za atopičnu kožu“).
2. Duljina: {META_TARGET_CHARS} znakova; tvrdi limit {META_MAX_PX:.0f} px. Kratko,
   čitljivo, bez nepotrebnih uvoda.
3. Tekst mora biti smislen i završen: potpuna zadnja rečenica koja završava
   točkom, bez poziva na akciju (CTA).
4. ZABRANJENO: cijena, zaliha, dostava, keyword stuffing, generičke fraze,
   promotivne poruke, spominjanje konkurenata, superlativi te medicinske ili
   tvrdnje o učinkovitosti koje nisu potvrđene u priloženom izvoru.
5. Meta opis mora biti jedinstven i vezan uz sadržaj baš ove stranice.

IZVOR PODATAKA
Koristi ISKLJUČIVO podatke iz zadanog naziva, brenda i priloženog sadržaja
stranice. Ne izmišljaj specifikacije, sastojke ni tvrdnje. Svaki broj s
jedinicom (npr. "75 ml", "500 mg", "SPF50") smiješ upotrijebiti samo ako
postoji u izvoru. Ako sadržaj stranice nije dostupan, osloni se samo na naziv.

FORMAT ODGOVORA
Vrati ISKLJUČIVO validan JSON, bez ikakvog teksta prije ili poslije:
{{"title": "...", "meta_description": "...", "specs_used": ["..."],
  "namjena": "...", "namjena_potvrdjena": true/false,
  "podaci_s_brend_stranice": ["..."]}}
U "specs_used" navedi doslovne fraze iz izvora na kojima temeljiš specifikacije.
U "namjena" navedi namjenu onako kako je stoji u izvoru.
U "podaci_s_brend_stranice" navedi SAMO podatke preuzete s označenog izvora
[BREND]; ako ništa nije preuzeto s njega, vrati praznu listu."""
    prompt = prompts_cfg.render(
        "seo_system", default,
        TITLE_MAX_PX=f"{TITLE_MAX_PX:.0f}",
        TITLE_CORE_TARGET_PX=f"{TITLE_CORE_TARGET_PX:.0f}",
        META_MAX_PX=f"{META_MAX_PX:.0f}",
        META_TARGET_CHARS=META_TARGET_CHARS,
        BRAND_SUFFIX=BRAND_SUFFIX.strip(),
    )
    return prompts_cfg.with_notes(prompt, "seo_napomene")


def build_user_message(product: Product, page: PageData,
                       feedback: str | None = None,
                       canonical_name: str = "",
                       brand_source: "BrandSource | None" = None) -> str:
    content = page.content if page.fetched and page.content else (
        "SADRŽAJ STRANICE NIJE DOSTUPAN — koristi samo podatke iz naziva "
        "i ne navodi specifikacije kojih nema u nazivu."
    )
    name_block = f"Naziv (iz baze; normaliziraj velika slova): {product.naziv}"
    if canonical_name:
        name_block += (f"\nKANONSKI NAZIV (iz PDP-a — title MORA počinjati ovim "
                       f"nazivom): {canonical_name}")
    brand_block = ""
    if brand_source and brand_source.text:
        brand_block = (f"\n\n[BREND] SLUŽBENA STRANICA BRENDA — {brand_source.url}\n"
                       "Koristi je SAMO za podatak kojeg nema na stranici proizvoda "
                       "i svaki takav podatak navedi u 'podaci_s_brend_stranice'.\n"
                       f"{brand_source.text}")
    msg = f"""PROIZVOD
{name_block}
Brend: {product.brend or "-"}
Sekcija: {product.sekcija or "-"}
SKU: {product.sku}
URL: {product.url}

SADRŽAJ STRANICE PROIZVODA — eljekarna24 (primarni izvor):
<<<
{content}
>>>{brand_block}

Generiraj title (bez dodatka webshopa) i meta opis prema pravilima.
Vrati samo JSON."""
    if feedback:
        msg += f"""

PRETHODNI POKUŠAJ NIJE PROŠAO AUTOMATSKU KONTROLU.
{feedback}
Ispravi SVE navedene greške. Ako treba skratiti: prvo ukloni CTA, opće pridjeve
i sporedne značajke; NE uklanjaj naziv proizvoda, tip proizvoda, volumen ili
dimenziju kada su relevantni, ni glavnu namjenu. Vrati samo JSON."""
    return msg


def parse_model_json(text: str) -> Candidate | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    for chunk in (cleaned, *re.findall(r"\{.*\}", cleaned, flags=re.S)):
        try:
            data = json.loads(chunk)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and "title" in data and "meta_description" in data:
            specs = data.get("specs_used") or []
            if not isinstance(specs, list):
                specs = [str(specs)]
            brand = data.get("podaci_s_brend_stranice") or []
            if not isinstance(brand, list):
                brand = [str(brand)]
            return Candidate(
                title_core=str(data["title"]).strip(),
                meta=str(data["meta_description"]).strip(),
                specs_used=[str(s) for s in specs],
                namjena=str(data.get("namjena", "") or "").strip(),
                namjena_potvrdjena=bool(data.get("namjena_potvrdjena", True)),
                brand_data=[str(b) for b in brand if str(b).strip()],
                raw=text,
            )
    return None


# ---------------------------------------------------------------------------
# Sanitizacija i validacija
# ---------------------------------------------------------------------------

TRAILING_SUFFIX_RE = re.compile(r"\s*[|│\-–]\s*eljekarna24\s*$", re.IGNORECASE)


def sanitize_title_core(title: str) -> str:
    title = " ".join((title or "").split())
    title = TRAILING_SUFFIX_RE.sub("", title)
    return title.strip(" .,;:|│-–")


def sanitize_meta(meta: str) -> str:
    return " ".join((meta or "").split())


def validate_candidate(cand: Candidate, product: Product, page: PageData,
                       seen_titles: set[str], seen_metas: set[str],
                       canonical_name: str = "") -> list[str]:
    """Vraća listu grešaka (prazna lista = prolaz). Poruke idu i modelu i u QA."""
    errors: list[str] = []
    title, meta = cand.title_core, cand.meta

    # --- Title ---
    if not title:
        errors.append("Title je prazan.")
    else:
        px = text_width_px(title, TITLE_FONT_PX)
        if px > TITLE_MAX_PX:
            errors.append(
                f"Title predug i bez dodatka webshopa: {px:.0f} px, tvrdi limit "
                f"{TITLE_MAX_PX:.0f} px. Skrati ga."
            )
        elif px > TITLE_CORE_TARGET_PX:
            errors.append(
                f"Osnovni title je {px:.0f} px; da bi stao dodatak "
                f"'{BRAND_SUFFIX.strip()}', mora biti ≤ {TITLE_CORE_TARGET_PX:.0f} px "
                "(~45 znakova). Skrati uklanjanjem sporednih značajki."
            )
        name_ref = canonical_name or product.naziv
        first_tok = (significant_name_tokens(name_ref, 1) or [""])[0]
        nt = norm_compact(title)
        if first_tok and not (
            nt.startswith(first_tok) or nt.startswith(norm_compact(product.brend))
        ):
            errors.append(
                f"Title ne počinje nazivom proizvoda — mora početi nazivom "
                f"'{' '.join(name_ref.split()[:3])}...' (naziv/brend na početku)."
            )
        for word in CAPS_WORD_RE.findall(title):
            if word not in CAPS_ALLOWLIST:
                errors.append(
                    f"Title sadrži riječ velikim slovima: '{word}'. "
                    "Piši normalnim pisanjem (npr. 'Sun', a ne 'SUN')."
                )
        if COMMA_BEFORE_QTY_RE.search(title):
            errors.append("Zarez ispred količine nije dopušten — količina se piše "
                          "na kraju bez zareza (npr. 'Vitamin K1 100 mcg 100 tableta').")
        m_abbr = UNIT_ABBREV_RE.search(title)
        if m_abbr:
            errors.append(f"Kratica jedinice '{m_abbr.group(0).strip()}' — jedinicu "
                          "piši punom riječju (tableta, kapsula, komada, vrećica).")
        m_nospace = NO_SPACE_UNIT_RE.search(title)
        if m_nospace:
            errors.append(f"'{m_nospace.group(0)}' — između broja i jedinice mora "
                          "biti razmak (npr. '75 ml').")
        src_qty = quantity_tokens(canonical_name or product.naziv)
        if src_qty and not (quantity_tokens(title) & src_qty):
            errors.append(
                f"Title je izgubio količinu ({sorted(src_qty)[0]}). Količina se "
                "NIKAD ne uklanja — skrati uklanjanjem sporednih značajki.")
        if R.zavrsava_lose(title):
            errors.append("Title završava prijedlogom, veznikom, znakom ili brojem "
                          "bez jedinice. Ukloni cijeli segment, ne dio fraze.")
        if R.nadi_crtice(title):
            errors.append("Title sadrži crticu (– ili —). Ukloni je; crtica ostaje "
                          "samo u rasponu brojeva.")
        for hit in R.nadi_zabranjene_rijeci(title):
            errors.append(f"Zabranjena riječ u titlu: {hit}.")
        if canonical_name:
            rijeci_naziva = {w for w in norm_spaced(canonical_name).split()}
            visak = [w for w in norm_spaced(title).split()
                     if w not in rijeci_naziva and w not in {"eljekarna24"}
                     and len(w) > 2]
            if visak:
                errors.append(f"Title sadrži riječi kojih nema u PDP nazivu: "
                              f"{', '.join(visak[:4])}. Koristi samo riječi iz PDP "
                              "naziva, istim redoslijedom.")
        for hit in find_forbidden(title):
            errors.append(f"Zabranjeni izraz u titlu: {hit}.")

    # --- Meta opis ---
    if not meta:
        errors.append("Meta opis je prazan.")
    else:
        px = text_width_px(meta, META_FONT_PX)
        if px > META_MAX_PX:
            errors.append(
                f"Meta opis predug: {px:.0f} px, limit {META_MAX_PX:.0f} px. "
                f"Skrati na ~{META_TARGET_CHARS} znakova."
            )
        tokens = significant_name_tokens(product.naziv)
        if tokens:
            nm = norm_compact(meta)
            present = sum(1 for t in tokens if t in nm)
            if present / len(tokens) < 0.5:
                errors.append(
                    "Meta opis ne sadrži naziv proizvoda — uključi ključne riječi "
                    f"naziva ({', '.join(tokens[:4])})."
                )
        if not PURPOSE_RE.search(meta):
            errors.append(
                "Meta opis ne sadrži namjenu proizvoda. Namjena je OBVEZNA: "
                "napiši kome ili čemu proizvod služi (npr. 'za masnu kožu sklonu "
                "nepravilnostima'). Ako se ne može potvrditi iz izvora, ne "
                "izmišljaj je nego postavi namjena_potvrdjena = false.")
        if not re.search(r"[.!]$", meta) or meta.endswith(("…", "...")):
            errors.append(
                "Meta opis mora završiti potpunom rečenicom i točkom "
                "(bez trotočja i bez CTA-a)."
            )
        if not PURPOSE_RE.search(meta[:100]):
            errors.append("Namjena mora biti unutar prvih 100 znakova meta opisa.")
        for fraza in ("pakiranje od", "volumen", "dostupno u", "dostupna u",
                      "paket od"):
            if fraza in meta.lower():
                errors.append(f"Meta opis sadrži zabranjenu formulaciju količine "
                              f"„{fraza}“. Količina se piše samo jednom, u prvoj "
                              "rečenici.")
        if len(KOLICINA_U_META_RE.findall(meta)) > 1:
            errors.append("Količina se u meta opisu spominje više puta. Napiši je "
                          "samo jednom, u prvoj rečenici.")
        if R.nadi_crtice(meta):
            errors.append("Meta opis sadrži crticu (– ili —). Umjesto nje zarez "
                          "ili točka.")
        for hit in R.nadi_zabranjene_rijeci(meta):
            errors.append(f"Zabranjena riječ u meta opisu: {hit}.")
        if canonical_name:
            brend_rijec = (canonical_name.split() or [""])[0]
            if brend_rijec and norm_compact(brend_rijec) not in norm_compact(meta):
                errors.append(f"Meta opis ne sadrži brend „{brend_rijec}“ iz titla.")
        if title:
            kol_title = R.kolicina_iz(title)
            kol_meta = R.kolicina_iz(meta)
            if kol_title and kol_meta and norm_compact(kol_title) != norm_compact(kol_meta):
                errors.append(f"Količina se razlikuje: title „{kol_title}“, meta "
                              f"„{kol_meta}“. Mora biti ista u PDP nazivu, titlu i "
                              "meta opisu.")
        for hit in find_forbidden(meta):
            errors.append(f"Zabranjeni izraz u meta opisu: {hit}.")
        for word in CAPS_WORD_RE.findall(meta):
            if word not in CAPS_ALLOWLIST:
                errors.append(f"Meta opis sadrži riječ velikim slovima: '{word}'.")

        # anti-halucinacija: broj+jedinica mora postojati u izvoru
        source_norm = norm_spaced(product.naziv + " " + (page.content or ""))
        source_specs = spec_tokens(source_norm)
        for tok in spec_tokens(meta):
            if tok not in source_specs:
                errors.append(
                    f"Podatak '{tok}' u meta opisu nije potvrđen u nazivu ni na "
                    "stranici — koristi samo provjerljive specifikacije."
                )

    # specs_used moraju postojati u izvoru
    source_compact = norm_compact(product.naziv + " " + (page.content or ""))
    for spec in cand.specs_used:
        sc = norm_compact(str(spec))
        if len(sc) >= 4 and sc not in source_compact:
            errors.append(
                f"Navedena specifikacija '{spec}' nije pronađena u izvoru — "
                "navedi doslovnu frazu iz izvora ili je izostavi."
            )

    # jedinstvenost
    if title and norm_compact(title) in seen_titles:
        errors.append(
            "Title nije jedinstven (već korišten za drugi proizvod) — dodaj "
            "diferencijator (volumen, model, varijantu)."
        )
    if meta and norm_compact(meta) in seen_metas:
        errors.append("Meta opis nije jedinstven — preformuliraj za ovaj proizvod.")

    return errors


# ---------------------------------------------------------------------------
# Determinističko skraćivanje (fallback nakon max pokušaja)
# ---------------------------------------------------------------------------

VARIJANTE = ("riche", "légère", "legere", "light", "medium", "extra", "forte",
             "plus", "intense", "spf", "pigment correct", "uvmune", "optipro",
             "comfortis", "supremepro", "bisglycinate", "citrate")


def obavezni_pojmovi(naziv: str) -> list[str]:
    """Pojmovi koji se pri skraćivanju nikad ne uklanjaju: brend, linija,
    varijanta (nijansa, SPF, Riche, jakost) i količina s jedinicom."""
    pojmovi = []
    nisko = (naziv or "").lower()
    for oznaka in VARIJANTE:
        if oznaka in nisko:
            i = nisko.index(oznaka)
            pojmovi.append(naziv[i:i + len(oznaka)])
    kolicina = R.kolicina_iz(naziv)
    if kolicina:
        pojmovi.append(kolicina)
    prve = (naziv or "").split()[:3]           # brend + početak linije
    if prve:
        pojmovi.append(" ".join(prve[:2]))
    return pojmovi


def trim_title_to_px(title: str, limit_px: float, keep_qty: set[str] | None = None) -> str:
    """Skraćuje s kraja, ali NIKAD ne uklanja količinu (klijentovo pravilo).

    Ako uklanjanje zadnjih riječi odnosi količinu, ona se vraća na kraj, a
    skraćuje se iz sredine (sporedne značajke) sve dok se ne stane u limit.
    """
    keep_qty = keep_qty or quantity_tokens(title)
    words = title.split()

    # 1) pokušaj klasično skraćivanje s kraja dok količina ostaje prisutna
    while len(words) > 1 and text_width_px(" ".join(words), TITLE_FONT_PX) > limit_px:
        candidate = words[:-1]
        if keep_qty and not (quantity_tokens(" ".join(candidate)) & keep_qty):
            break
        words = candidate

    out = " ".join(words).strip(" ,;:-–")
    if text_width_px(out, TITLE_FONT_PX) <= limit_px:
        return out

    # 2) količina bi ispala: izdvoji rep s količinom i skraćuj sredinu
    all_words = title.split()
    qty_in_title = quantity_tokens(title) & keep_qty
    candidates = [i for i in range(len(all_words))
                  if qty_in_title <= quantity_tokens(" ".join(all_words[i:]))]
    start = max(candidates) if candidates else len(all_words)
    head, tail = all_words[:start], all_words[start:]
    while len(head) > 1 and text_width_px(" ".join(head + tail), TITLE_FONT_PX) > limit_px:
        head.pop()
    return " ".join(head + tail).strip(" ,;:-–")


def trim_meta_to_px(meta: str, limit_px: float) -> str:
    sentences = re.split(r"(?<=[.!])\s+", meta.strip())
    while len(sentences) > 1 and text_width_px(" ".join(sentences), META_FONT_PX) > limit_px:
        sentences.pop()
    out = " ".join(sentences).strip()
    if text_width_px(out, META_FONT_PX) > limit_px:
        words = out.rstrip(".!").split()
        while len(words) > 3 and text_width_px(" ".join(words) + ".", META_FONT_PX) > limit_px:
            words.pop()
        out = " ".join(words).rstrip(" ,;:-–") + "."
    return out


def finalize_title(core: str) -> tuple[str, float, str]:
    """Dodaje ' | eljekarna24' samo ako ukupno stane u 550 px (pravilo klijenta)."""
    full = core + BRAND_SUFFIX
    px = text_width_px(full, TITLE_FONT_PX)
    if px <= TITLE_MAX_PX:
        return full, px, ""
    px_core = text_width_px(core, TITLE_FONT_PX)
    return core, px_core, "dodatak webshopa izostavljen (ne stane u 550 px)"


# ---------------------------------------------------------------------------
# Obrada jednog proizvoda
# ---------------------------------------------------------------------------

def process_product(product: Product, page: PageData, client: BedrockClient,
                    seen_titles: set[str], seen_metas: set[str], lock: threading.Lock,
                    max_attempts: int, canonical_name: str = "",
                    brand_source: "BrandSource | None" = None) -> RowResult:
    """canonical_name: naziv iz PDP-a (klijent: title mora početi TIM nazivom).
    brand_source: izvor 2 (službena stranica brenda) — koristi se samo za
    podatke kojih nema na eljekarna24 i svaki takav podatak se označava."""
    result = RowResult(product=product, page=page,
                       model_id=getattr(client, "model_id", ""))
    result.brand_url = brand_source.url if brand_source else ""
    system_prompt = build_system_prompt()

    # klijent: ako nema stranice proizvoda na eljekarna24, redak je GREŠKA
    if not page.fetched:
        result.status = "GREŠKA"
        result.notes = ["Stranica proizvoda na eljekarna24 nije dostupna — "
                        "klijentovo pravilo: bez izvora 1 redak je greška."]
        return result

    feedback = None
    best: Candidate | None = None
    best_errors: list[str] = ["model nije vratio valjan odgovor"]

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        raw = client.generate(system_prompt,
                              build_user_message(product, page, feedback,
                                                 canonical_name, brand_source))
        cand = parse_model_json(raw)
        if cand is None:
            feedback = ("Odgovor nije bio valjan JSON s poljima 'title' i "
                        "'meta_description'. Vrati isključivo JSON.")
            continue

        cand.title_core = sanitize_title_core(cand.title_core)
        cand.meta = sanitize_meta(cand.meta)

        with lock:
            errors = validate_candidate(cand, product, page, seen_titles,
                                        seen_metas, canonical_name)
        if not cand.namjena_potvrdjena:
            errors = list(errors) + [
                "Namjena nije potvrđena u izvorima (namjena_potvrdjena = false) — "
                "klijentovo pravilo: redak ide u TREBA PROVJERA, namjena se ne "
                "izmišlja."]

        if best is None or len(errors) < len(best_errors):
            best, best_errors = cand, errors

        if not errors:
            break

        feedback = (
            f'Prethodni title: "{cand.title_core}" '
            f"({text_width_px(cand.title_core, TITLE_FONT_PX):.0f} px)\n"
            f'Prethodni meta opis: "{cand.meta}" '
            f"({text_width_px(cand.meta, META_FONT_PX):.0f} px)\n"
            "Greške:\n" + "\n".join(f"- {e}" for e in errors)
        )

    if best is None:
        result.status = "GREŠKA"
        result.notes = best_errors
        return result

    title_core, meta = best.title_core, best.meta
    result.specs_used = best.specs_used
    result.namjena = best.namjena
    result.brand_data = best.brand_data
    remaining = list(best_errors)

    # fallback: determinističko skraćivanje ako je jedini problem duljina
    length_only = remaining and all(("px" in e and "predug" in e) or "mora biti ≤" in e
                                    for e in remaining)
    if remaining and length_only:
        izvor_naziv = canonical_name or product.naziv
        title_core = R.skrati_po_segmentima(
            title_core or izvor_naziv,
            stane=lambda t: text_width_px(t, TITLE_FONT_PX) <= TITLE_CORE_TARGET_PX,
            obavezno=obavezni_pojmovi(izvor_naziv))
        meta = trim_meta_to_px(meta, META_MAX_PX)
        with lock:
            recheck = validate_candidate(
                Candidate(title_core=title_core, meta=meta,
                          specs_used=best.specs_used, namjena=best.namjena),
                product, page, seen_titles, seen_metas, canonical_name,
            )
        if not recheck:
            remaining = []
            result.notes.append("automatski skraćeno na limit")
        else:
            remaining = recheck

    result.title, result.title_px, suffix_note = finalize_title(title_core)
    result.meta = meta
    result.meta_px = text_width_px(meta, META_FONT_PX)
    if suffix_note:
        result.notes.append(suffix_note)

    if result.brand_data:
        result.notes.append("podatak s brend stranice — obvezna ljudska provjera: "
                            + ", ".join(result.brand_data))
    if not remaining:
        # status OK samo kad validator nema nijednu napomenu (upute, točka 6)
        result.status = "TREBA PROVJERA" if result.brand_data else "OK"
        with lock:
            seen_titles.add(norm_compact(title_core))
            seen_metas.add(norm_compact(meta))
    else:
        result.status = "TREBA PROVJERA"
        result.notes.extend(remaining)
    if page.note:
        result.notes.append(f"stranica: {page.note}")
    return result


# ---------------------------------------------------------------------------
# Ulaz / izlaz
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {
    "sekcija": "sekcija", "brend": "brend", "brand": "brend", "sku": "sku",
    "šifra": "sku", "sifra": "sku", "naziv": "naziv", "name": "naziv",
    "url": "url", "link": "url",
}


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
            sys.exit(f"Ulazna tablica nema stupac '{required}'. Nađeni stupci: "
                     f"{list(df.columns)}")

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
            naziv=naziv,
            url=url,
        ))
    return products


def write_outputs(results: list[RowResult], out_dir: Path) -> tuple[Path, Path]:
    import pandas as pd

    records = [r.to_record() for r in results]
    df = pd.DataFrame(records)

    xlsx_path = out_dir / "generirani_meta_title.xlsx"
    csv_path = out_dir / "generirani_meta_title.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Meta i title")
        ws = writer.sheets["Meta i title"]
        widths = {"A": 16, "B": 14, "C": 10, "D": 42, "E": 46, "F": 52, "G": 9,
                  "H": 9, "I": 70, "J": 9, "K": 9, "L": 16, "M": 9, "N": 50,
                  "O": 34, "P": 10, "Q": 46, "R": 60, "S": 30}
        for col, width in widths.items():
            ws.column_dimensions[col].width = width
    return xlsx_path, csv_path


def append_jsonl(path: Path, result: RowResult) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result.to_record(), ensure_ascii=False) + "\n")


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


def record_to_result(rec: dict) -> RowResult:
    product = Product(rec.get("Sekcija", ""), rec.get("Brend", ""), rec.get("SKU", ""),
                      rec.get("Naziv", ""), rec.get("URL", ""))
    res = RowResult(product=product)
    res.title = rec.get("Title tag", "")
    res.meta = rec.get("Meta opis", "")
    res.title_px = float(rec.get("Title px", 0) or 0)
    res.meta_px = float(rec.get("Meta px", 0) or 0)
    res.status = rec.get("Status", "TREBA PROVJERA")
    res.attempts = int(rec.get("Pokušaji", 0) or 0)
    res.notes = [n for n in rec.get("Napomene", "").split(" | ") if n]
    res.specs_used = [s for s in rec.get("Korištene specifikacije", "").split("; ") if s]
    res.page = PageData(fetched=rec.get("Stranica dohvaćena") == "da",
                        existing_title=rec.get("Postojeći title (QA)", ""),
                        existing_meta=rec.get("Postojeći meta (QA)", ""))
    res.model_id = rec.get("Model", "")
    return res


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Generator title/meta tagova (Bedrock).")
    ap.add_argument("--input", "-i", required=True, help="XLSX ili CSV s proizvodima")
    ap.add_argument("--output", "-o", default="out", help="izlazna mapa (default: out)")
    ap.add_argument("--limit", type=int, default=0, help="obradi samo prvih N")
    ap.add_argument("--sku", action="append", default=[], help="obradi samo ovaj SKU (može više puta)")
    ap.add_argument("--workers", type=int, default=1, help="paralelni Bedrock pozivi")
    ap.add_argument("--max-attempts", type=int, default=3, help="pokušaja po proizvodu")
    ap.add_argument("--no-fetch", action="store_true", help="ne dohvaćaj stranice")
    ap.add_argument("--refresh-cache", action="store_true", help="ponovno dohvati HTML")
    ap.add_argument("--force", action="store_true", help="ignoriraj postojeće rezultate")
    ap.add_argument("--retry-review", action="store_true",
                    help="ponovno generiraj samo retke koji nisu OK")
    ap.add_argument("--dry-run", action="store_true",
                    help="bez Bedrocka: dohvat + ispis prompta za prvi proizvod")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    in_path = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".cache" / "html"
    jsonl_path = out_dir / "results.jsonl"

    products = load_products(in_path)
    if args.sku:
        wanted = {s.strip() for s in args.sku}
        products = [p for p in products if p.sku in wanted]
    if args.limit:
        products = products[: args.limit]
    if not products:
        sys.exit("Nema proizvoda za obradu.")
    print(f"Proizvoda za obradu: {len(products)}")

    done = {} if args.force else load_done(jsonl_path)
    if args.retry_review:
        done = {k: v for k, v in done.items() if v.get("Status", "").startswith("OK")}

    def get_page(p: Product) -> PageData:
        if args.no_fetch:
            return PageData(fetched=False, note="dohvat isključen (--no-fetch)")
        return fetch_page(p.url, cache_dir, refresh=args.refresh_cache)

    if args.dry_run:
        p = products[0]
        page = get_page(p)
        print(f"\n--- SYSTEM PROMPT ---\n{build_system_prompt()}")
        print(f"\n--- USER MESSAGE ({p.sku}) ---\n{build_user_message(p, page)}")
        print(f"\n(stranica dohvaćena: {page.fetched}; iz cachea: {page.from_cache})")
        return

    config = load_bedrock_config()
    client = BedrockClient(config)
    print(f"Model:  {client.model_id}")
    print(f"Regija: {config['BEDROCK_AWS_REGION']}")
    print(f"Limiti: title {TITLE_MAX_PX:.0f} px (osnovni dio ≤ "
          f"{TITLE_CORE_TARGET_PX:.0f} px + '{BRAND_SUFFIX.strip()}'), "
          f"meta {META_MAX_PX:.0f} px\n")

    lock = threading.Lock()
    seen_titles: set[str] = set()
    seen_metas: set[str] = set()
    results: dict[str, RowResult] = {}

    for sku, rec in done.items():
        res = record_to_result(rec)
        results[sku] = res
        if res.status.startswith("OK"):
            core = TRAILING_SUFFIX_RE.sub("", res.title)
            seen_titles.add(norm_compact(core))
            seen_metas.add(norm_compact(res.meta))

    todo = [p for p in products if p.sku not in results]
    if len(products) - len(todo):
        print(f"Preskačem {len(products) - len(todo)} već obrađenih (results.jsonl; "
              "--force za ponovno).")

    from botocore.exceptions import ClientError  # noqa: PLC0415

    def worker(p: Product) -> RowResult:
        page = get_page(p)
        return process_product(p, page, client, seen_titles, seen_metas, lock,
                               args.max_attempts)

    processed = 0
    try:
        if args.workers <= 1:
            iterator = ((p, worker(p)) for p in todo)
            for p, res in iterator:
                results[p.sku] = res
                append_jsonl(jsonl_path, res)
                processed += 1
                print(f"[{processed}/{len(todo)}] {p.sku} {p.naziv[:48]:<48} -> "
                      f"{res.status} (pokušaja: {res.attempts}, "
                      f"title {res.title_px:.0f}px, meta {res.meta_px:.0f}px)")
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(worker, p): p for p in todo}
                for fut in as_completed(futures):
                    p = futures[fut]
                    res = fut.result()
                    results[p.sku] = res
                    append_jsonl(jsonl_path, res)
                    processed += 1
                    print(f"[{processed}/{len(todo)}] {p.sku} {p.naziv[:48]:<48} -> "
                          f"{res.status} (pokušaja: {res.attempts}, "
                          f"title {res.title_px:.0f}px, meta {res.meta_px:.0f}px)")
    except ClientError as err:
        print("\nBedrock greška:\n  " + explain_client_error(err, config))
        print("Dosad obrađeno je spremljeno u results.jsonl — ponovno pokretanje "
              "nastavlja gdje je stalo.")
        sys.exit(1)

    # završna kontrola jedinstvenosti preko cijelog skupa
    by_title: dict[str, list[RowResult]] = {}
    for res in results.values():
        core = TRAILING_SUFFIX_RE.sub("", res.title)
        by_title.setdefault(norm_compact(core), []).append(res)
    for dupes in by_title.values():
        if len(dupes) > 1:
            for res in dupes[1:]:
                if "duplikat titlea" not in " ".join(res.notes):
                    res.notes.append("duplikat titlea u skupu — ručno razlikovati")
                    res.status = "TREBA PROVJERA"

    ordered = [results[p.sku] for p in products if p.sku in results]
    xlsx_path, csv_path = write_outputs(ordered, out_dir)

    ok = sum(1 for r in ordered if r.status.startswith("OK"))
    review = len(ordered) - ok
    print(f"\nGotovo: {ok} OK, {review} za provjeru.")
    print(f"XLSX: {xlsx_path}\nCSV:  {csv_path}")
    if review:
        print("Retke sa statusom 'TREBA PROVJERA' možeš regenerirati s: "
              "--retry-review (ili --sku <SKU>).")


if __name__ == "__main__":
    main()
