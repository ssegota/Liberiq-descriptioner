#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generator PDP sadržaja (opisa proizvoda s tabovima) za eljekarna24
— Claude Opus na AWS Bedrock, dva agenta: pisac + kontrolor činjenica.

Za svaki proizvod iz ulazne tablice (Sekcija, Brend, SKU, Naziv, URL):

  1. IZVORI: dohvaća stranicu proizvoda (eljekarna24) i dodatne izvore s
     interneta (DuckDuckGo pretraga, prednost službenim stranicama brenda).
     Svaki izvor dobiva oznaku [S1], [S2] ... i sprema se u cache.
  2. PISAC (Claude Opus): generira PDP u Markdownu, STROGO prema predlošku
     kategorije iz PDP_struktura.docx i četiri primjera (kozmetika, dodatak
     prehrani, uređaj, mliječna formula). Predlošci žive u pdp_templates.py.
  3. AUTOMATSKA KONTROLA FORMATA (deterministička): točni naslovi sekcija i
     tabova, "Brza traka" polja, 3–4 ključne prednosti, Tab 1 od 80 do 150
     riječi, obvezni redci Tab 5 (Pakiranje/Brend/Proizvođač/Zemlja
     podrijetla/EAN/Obvezna provjera), fiksni Tab 6 i blok recenzija, FAQ s
     3–5 pitanja, obvezne rečenice po kategoriji (npr. "Dojenje je najbolji
     način prehrane dojenčeta." za formule), zabranjeni izrazi (cijene,
     akcije, dostava, CTA, superlativi, "klinički dokazano", liječi/jamči),
     EAN samo ako postoji u izvorima, svaki broj s jedinicom mora postojati
     u izvorima.
  4. KONTROLOR (drugi agent, Claude na Bedrocku): provjerava svaku činjeničnu
     tvrdnju prema izvorima; nepotkrijepljene tvrdnje vraćaju se piscu.
  5. Greške se vraćaju modelu na ispravak do --max-attempts puta.
  6. IZLAZ po proizvodu: PDP_<SKU>_<naziv>.md i .docx + zbirni indeks
     (XLSX/CSV) sa statusima. results.jsonl omogućuje nastavak prekinutog rada.

Pokretanje:
    pip install -r requirements.txt
    cp .env.example .env   # isti .env kao za bedrock-test.py / seo_meta_generator.py
    python pdp_generator.py --input eljekarna24_proizvodi_75_kom.xlsx

Korisne opcije:
    --limit 2            samo prva 2 proizvoda (test)
    --sku C002167        samo jedan SKU (može više puta)
    --dry-run            bez Bedrocka: skupi izvore i ispiši prompt
    --no-web-search      bez internetske pretrage (samo stranica proizvoda)
    --no-verify          preskoči drugog agenta (ne preporučuje se)
    --search-results 3   koliko web izvora po proizvodu
    --force              ignoriraj postojeće rezultate
    --retry-review       ponovno generiraj samo retke koji nisu OK
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import pdp_extract as X
import pravila as R
import pdp_templates as T
import prompts_cfg

# ---------------------------------------------------------------------------
# Konstante
# ---------------------------------------------------------------------------

GEN_MAX_TOKENS = 3500
GEN_TEMPERATURE = 0.2
VERIFY_MAX_TOKENS = 1200
EXTRACT_MAX_TOKENS = 4000
VERIFY_TEMPERATURE = 0.0
BEDROCK_RETRIES = 5

PAGE_CONTENT_CAP = 6000       # znakova sa stranice proizvoda
WEB_SOURCE_CAP = 2500         # znakova po web izvoru
TAB1_MIN_WORDS, TAB1_MAX_WORDS = 80, 150
FAQ_MIN, FAQ_MAX = 3, 5

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 eljekarna24-interni-pdp-alat"
)

# Hijerarhija izvora (klijent):
#   prioritet 1 — stranica proizvoda s linka iz ulazne tablice (eljekarna24)
#   prioritet 2 — zadani sekundarni izvor (webljekarna.vasezdravlje.com)
#   prioritet 3 — svi ostali web izvori
PRIMARY_DOMAIN = "eljekarna24"
SECONDARY_LABEL = "službena stranica brenda"

CATEGORY_QUERY_EXTRA = {
    "cosmetics": "sastav INCI",
    "supplement": "deklaracija sastav doziranje",
    "device": "upute specifikacije",
    "formula": "priprema sastav deklaracija",
}

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


# ---------------------------------------------------------------------------
# Zabranjeni izrazi (na normaliziranom tekstu) + izuzete obvezne rečenice
# ---------------------------------------------------------------------------

EXEMPT_PATTERNS = [
    # obvezna zakonska rečenica za mliječne formule sadrži "najbolji"
    re.compile(r"dojenje je najbolji nacin prehrane dojenceta"),
    # mjerni izrazi, nisu tvrdnje o kvaliteti
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
        (r"\bdostav\w*", "dostava"),
        (r"\bisporuka\b", "isporuka"),
        (r"\bdostupnost\b", "dostupnost (podatak iz sustava, ne iz teksta)"),
        (r"\bna zalihi\b", "zaliha"),
        (r"\bkosaric\w*", "košarica (element trgovine, ne PDP teksta)"),
        (r"\bnaruc\w*", "CTA: naruči"),
        (r"\bkupi(te)?\b", "CTA: kupi"),
        (r"\bkupuj\w*", "CTA: kupujte"),
        (r"\bkliknite\b", "CTA"),
        (r"\bsaznajte\b", "CTA: saznajte više"),
        (r"\bposjetite\b", "CTA"),
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
        (r"\brevolucionar\w*", "superlativ"),
        (r"\bbr(oj)?\.?\s?1\b", "superlativ (br. 1)"),
        (r"\b100\s?%\s?(prirodn|ucinkovit|siguran)\w*", "neprovjerena tvrdnja"),
        (r"\bklinicki dokazano\b", "gola tvrdnja 'klinički dokazano' bez metode"),
        (r"\bdokazano djeluje\b", "gola tvrdnja bez metode"),
        (r"\bjamci\w*", "jamstvo/tvrdnja"),
        (r"\bgarantira\w*", "jamstvo/tvrdnja"),
        (r"\blijeci\b", "medicinska tvrdnja (liječi)"),
        (r"\bizlijec\w*", "medicinska tvrdnja (izliječi)"),
    ]
]

HEDGE_PHRASES = ["prema deklaraciji", "prema podacima proizvoda", "prema uputi",
                 "prema opisu proizvoda", "prema dostupnoj dokumentaciji"]


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
    r"\b(\d+(?:[.,]\d+)?)\s*"
    r"(ml|mg|g|kg|l|mcg|iu|ie|kom|cm|kapsul\w*|tablet\w*|vrecic\w*|%)\b"
)
SPF_RE = re.compile(r"\bspf\s*(\d+\+?)\b")
UNIT_STEMS = ("kapsul", "tablet", "vrecic")


def spec_tokens(text: str) -> set[str]:
    normed = norm_spaced(text)
    out = set()
    for num, unit in SPEC_TOKEN_RE.findall(normed):
        for stem in UNIT_STEMS:
            if unit.startswith(stem):
                unit = stem
                break
        out.add(num.replace(",", ".") + unit)
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
    sid: str            # "S1", "S2", ...
    kind: str           # "stranica proizvoda" | "web"
    url: str
    title: str = ""
    text: str = ""


@dataclass
class RowResult:
    product: Product
    category: str = ""
    status: str = "TREBA PROVJERA"
    attempts: int = 0
    verified: str = "-"
    unsupported: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    sources: list = field(default_factory=list)   # list[Source]
    md_path: str = ""
    docx_path: str = ""
    model_id: str = ""
    inventory: object = None
    coverage: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    nedostaje: list = field(default_factory=list)

    def to_record(self) -> dict:
        return {
            "Sekcija": self.product.sekcija,
            "Brend": self.product.brend,
            "SKU": self.product.sku,
            "Naziv": self.product.naziv,
            "URL": self.product.url,
            "Kategorija predloška": T.CATEGORY_LABELS.get(self.category, self.category),
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
            "Broj izvora": len(self.sources),
            "Izvori": " | ".join(s.url for s in self.sources),
            "MD datoteka": self.md_path,
            "DOCX datoteka": self.docx_path,
            "Napomene": " | ".join(self.notes),
            "Model": self.model_id,
        }


# ---------------------------------------------------------------------------
# Dohvat izvora
# ---------------------------------------------------------------------------

def _cache_get_or_fetch(url: str, cache_dir: Path, refresh: bool,
                        timeout: int = 20) -> str | None:
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
    except Exception:  # noqa: BLE001 — izvor koji ne radi jednostavno preskačemo
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


PRODUCT_SELECTORS = [
    ".woocommerce-product-details__short-description",
    ".woocommerce-Tabs-panel--description", "#tab-description",
    "[itemprop='description']", ".product-short-description",
    ".product_description", ".product-description", "#description",
    ".entry-summary",
]


def extract_product_page(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []

    for prod in _jsonld_products(soup):
        desc = prod.get("description") or ""
        if desc:
            parts.append(BeautifulSoup(str(desc), "html.parser")
                         .get_text(" ", strip=True))
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        parts.append(" ".join(og["content"].split()))
    for sel in PRODUCT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 40:
                parts.append(txt)
    for table in soup.select("table.woocommerce-product-attributes, "
                             "table.shop_attributes"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 2 and cells[0] and cells[1]:
                parts.append(f"{cells[0]}: {cells[1]}")
    if not parts:
        main = soup.find("main") or soup.find("article") or soup.body
        if main:
            parts.append(main.get_text(" ", strip=True))

    seen, lines = set(), []
    for part in parts:
        for line in re.split(r"(?<=[.!?])\s+|\n", part):
            line = " ".join(line.split())
            if len(line) < 3:
                continue
            key = norm_compact(line)[:80]
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)
    return "\n".join(lines)[:PAGE_CONTENT_CAP]


def extract_generic_page(html: str) -> tuple[str, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = " ".join(soup.title.get_text().split()) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                     "form", "iframe"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body
    text = main.get_text(" ", strip=True) if main else ""
    text = re.sub(r"\s+", " ", text)
    return title, text[:WEB_SOURCE_CAP]


def web_search_urls(product: Product, category: str, max_urls: int) -> list[dict]:
    """DuckDuckGo pretraga; vraća [{'href':..., 'title':...}] rangirano."""
    try:
        try:
            from ddgs import DDGS  # novije ime paketa
        except ImportError:
            from duckduckgo_search import DDGS  # starije ime
    except ImportError:
        return []

    queries = [
        f"{product.brend} {product.naziv}".strip(),
        f"{product.brend} {product.naziv} {CATEGORY_QUERY_EXTRA[category]}".strip(),
    ]
    brand_tokens = [t for t in norm_spaced(product.brend).split() if len(t) >= 4]

    results: dict[str, dict] = {}
    for query in queries:
        try:
            with DDGS() as ddgs:
                for hit in ddgs.text(query, region="hr-hr", max_results=8) or []:
                    href = hit.get("href") or hit.get("url") or ""
                    if not href.startswith("http"):
                        continue
                    host = urlparse(href).netloc.lower()
                    if (PRIMARY_DOMAIN in host
                            or href.lower().endswith(".pdf")):
                        continue
                    score = 1 + sum(2 for tok in brand_tokens if tok in
                                    norm_compact(host))
                    prev = results.get(href)
                    if not prev or score > prev["score"]:
                        results[href] = {"href": href,
                                         "title": hit.get("title", ""),
                                         "score": score}
        except Exception:  # noqa: BLE001 — pretraga je opcionalna
            continue
        time.sleep(0.4)

    ranked = sorted(results.values(), key=lambda r: -r["score"])
    return ranked[:max_urls]


def brand_site_urls(product: Product, max_urls: int = 2) -> list[str]:
    """Stranice proizvoda na SLUŽBENIM hrvatskim domenama brenda (allowlist)."""
    domene = [d for d in R.dopustene_domene(product.brend) if d != R.PRIMARNA_DOMENA]
    nadjeno: list[str] = []
    for domena in domene:
        url = site_search_url(product, domena)
        if url and R.je_dopusten(url, product.brend)[0]:
            nadjeno.append(url)
        if len(nadjeno) >= max_urls:
            break
    return nadjeno


def site_search_url(product: Product, domain: str) -> str | None:
    """Nađi stranicu ovog proizvoda na zadanoj domeni (site: pretraga)."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except ImportError:
        return None

    query = f"site:{domain} {product.brend} {product.naziv}".strip()
    try:
        with DDGS() as ddgs:
            for hit in ddgs.text(query, region="hr-hr", max_results=5) or []:
                href = hit.get("href") or hit.get("url") or ""
                if href.startswith("http") and domain in urlparse(href).netloc.lower():
                    return href
    except Exception:  # noqa: BLE001 — sekundarni izvor je neobavezan
        return None
    return None


def gather_sources(product: Product, category: str, cache_dir: Path,
                   refresh: bool, web_search: bool, max_web: int,
                   secondary: bool = True) -> list[Source]:
    """Izvori prema hijerarhiji iz uputa, provedenoj u kodu (allowlist domena):
       1. stranica proizvoda na eljekarna24 (URL iz ulazne tablice),
       2. službena hrvatska stranica brenda, samo za podatke kojih nema na 1.
    Sve ostalo se odbacuje prije slanja modelu."""
    sources: list[Source] = []

    # --- izvor 1 ---
    if not R.je_primarni(product.url):
        return sources
    html = _cache_get_or_fetch(product.url, cache_dir, refresh)
    if html:
        text = extract_product_page(html)
        if text:
            sources.append(Source(sid="S1", kind="stranica proizvoda",
                                  url=product.url, title="eljekarna24", text=text))
    if not sources:
        return sources

    # --- izvor 2: samo službena hrvatska stranica brenda ---
    if secondary and web_search:
        for url in brand_site_urls(product):
            dopusteno, _razlog = R.je_dopusten(url, product.brend)
            if not dopusteno:
                continue
            brand_html = _cache_get_or_fetch(url, cache_dir, refresh)
            if not brand_html:
                continue
            title, text = extract_generic_page(brand_html)
            if len(text) < 150:
                continue
            sources.append(Source(sid=f"S{len(sources) + 1}", kind=SECONDARY_LABEL,
                                  url=url, title=title or "stranica brenda",
                                  text=text))
            time.sleep(0.3)

    for i, src in enumerate(sources, start=1):
        src.sid = f"S{i}"
    return sources


def sources_block(sources: list[Source]) -> str:
    if not sources:
        return ("NEMA DOSTUPNIH IZVORA — koristi samo podatke iz naziva proizvoda; "
                "za sve ostalo upotrijebi propisane placeholdere i ne izmišljaj "
                "nikakve specifikacije.")
    parts = []
    for s in sources:
        if s.kind == "stranica proizvoda":
            head = (f"[{s.sid}] PRIORITET 1 — STRANICA PROIZVODA (eljekarna24) "
                    f"— {s.url}")
        else:
            head = (f"[{s.sid}] PRIORITET 2 — SLUŽBENA STRANICA BRENDA "
                    f"— {s.url}")
        parts.append(f"{head}\n{s.text}")
    return "\n\n".join(parts)


def sources_norm_text(product: Product, sources: list[Source]) -> str:
    return norm_spaced(product.naziv + " " + product.brend + " " +
                       " ".join(s.text for s in sources))


# ---------------------------------------------------------------------------
# Bedrock (isti .env kao bedrock-test.py)
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
    config["BEDROCK_VERIFY_MODEL_ID"] = (os.getenv("BEDROCK_VERIFY_MODEL_ID")
                                         or config["BEDROCK_TEXT_MODEL_ID"])
    return config


class BedrockClient:
    def __init__(self, config: dict):
        import boto3
        from botocore.config import Config

        self.model_id = config["BEDROCK_TEXT_MODEL_ID"]
        self.verify_model_id = config["BEDROCK_VERIFY_MODEL_ID"]
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=config["BEDROCK_AWS_REGION"],
            aws_access_key_id=config["BEDROCK_AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=config["BEDROCK_AWS_SECRET_ACCESS_KEY"],
            config=Config(read_timeout=180, connect_timeout=10,
                          retries={"max_attempts": 3, "mode": "standard"}),
        )

    def _converse(self, model_id: str, system_prompt: str, user_message: str,
                  max_tokens: int, temperature: float) -> str:
        from botocore.exceptions import ClientError

        last_err = None
        for attempt in range(BEDROCK_RETRIES):
            try:
                resp = self._client.converse(
                    modelId=model_id,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user",
                               "content": [{"text": user_message}]}],
                    inferenceConfig={"maxTokens": max_tokens,
                                     "temperature": temperature},
                )
                blocks = resp["output"]["message"]["content"]
                return "".join(b.get("text", "") for b in blocks).strip()
            except ClientError as err:
                code = err.response["Error"]["Code"]
                if code in {"ThrottlingException", "ServiceUnavailableException",
                            "InternalServerException",
                            "ModelNotReadyException"} and attempt < BEDROCK_RETRIES - 1:
                    time.sleep(2 ** attempt + random.uniform(0, 1))
                    last_err = err
                    continue
                raise
        raise last_err  # type: ignore[misc]

    def generate(self, system_prompt: str, user_message: str) -> str:
        return self._converse(self.model_id, system_prompt, user_message,
                              GEN_MAX_TOKENS, GEN_TEMPERATURE)

    def verify(self, system_prompt: str, user_message: str) -> str:
        return self._converse(self.verify_model_id, system_prompt, user_message,
                              VERIFY_MAX_TOKENS, VERIFY_TEMPERATURE)

    def extract(self, system_prompt: str, user_message: str) -> str:
        """Strukturirana ekstrakcija prije pisanja (temperatura 0)."""
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

def build_gen_system(category: str) -> str:
    t = T.TEMPLATES[category]
    tabs = "\n".join(f"  Tab {i}: {label}" for i, label in enumerate(t["tabs"], 1))
    extra = ""
    if category == "formula":
        extra = ("\nPOSEBNO ZA MLIJEČNE FORMULE: strogo deklarativno, bez "
                 "idealiziranja formule; obvezna je rečenica 'Dojenje je najbolji "
                 "način prehrane dojenčeta.' i upućivanje na tablicu hranjenja s "
                 "deklaracije.")
    if category == "supplement":
        extra = ("\nPOSEBNO ZA DODATKE PREHRANI: zdravstvene tvrdnje samo u obliku "
                 "'X doprinosi ...' i samo ako su navedene u izvorima; obvezne su "
                 "rečenice da dodatak prehrani nije zamjena za uravnoteženu i "
                 "raznovrsnu prehranu i da se ne prekoračuje preporučena dnevna "
                 "doza.")
    if category == "device":
        extra = ("\nPOSEBNO ZA UREĐAJE: uređaj ne postavlja dijagnozu i nije "
                 "zamjena za liječnički savjet; uputiti na (hrvatsku) uputu za "
                 "uporabu; značajke navoditi samo potvrđene u izvorima.")
    default = f"""Ti si stručni copywriter hrvatske internetske ljekarne "eljekarna24".
Pišeš PDP (stranicu proizvoda) s tabovima na hrvatskom jeziku, u Markdownu,
STROGO prema zadanom kosturu i primjeru. Kategorija proizvoda: {T.CATEGORY_LABELS[category]}.

MODEL MORA
- Koristiti priloženi INVENTAR ČINJENICA kao polazište: svaki podatak sa
  statusom FOUND mora završiti u finalnom PDP-u, u najlogičnijem dijelu
  strukture. Podatak označen kao HARD FIELD (doza, puni sastav/INCI, aktivne
  tvari i koncentracije, način uporabe, upozorenja, identifikatori,
  specifikacije) NE SMIJE nestati ni biti skraćen.
- Prenijeti puni sastav / INCI U CIJELOSTI kada je pronađen, doslovno, bez
  skraćivanja, prepričavanja i bez "i ostali sastojci". Popis uvedi riječju
  "INCI:" (kozmetika), odnosno "Sastav:" (ostale kategorije). Propisani
  placeholder koristi SAMO ako puni sastav nije pronađen.
- Sačuvati konkretne brojke, količine, mjerne jedinice, koncentracije i
  identifikatore točno onako kako stoje u inventaru.
- Placeholder koristiti SAMO kada podatak stvarno nije pronađen (NOT FOUND).
- Ako inventar sadrži KONFLIKT, vidljivo ga označiti za provjeru.
- Stil, strukturu i objašnjenje smiješ poboljšati — činjenice ne.

ZABRANA DEFINITIVNIH IZRAZA
Ne koristi izraze nadmoći ni apsolutne tvrdnje ("najbolji", "najučinkovitiji",
"najsigurniji", "jedini", "zlatni standard", "prvi izbor", "apsolutno",
"uvijek djeluje", "svima odgovara", "bez iznimke", "bez ikakvih nuspojava",
"trenutni rezultati") osim ako je točno takva tvrdnja doslovno potvrđena u
izvorima uz navedenu metodu ili mjerenje. Umjesto toga navedi konkretan
provjerljiv podatak. Iznimka su obvezne zakonske rečenice (npr. "Dojenje je
najbolji način prehrane dojenčeta.") i mjerni izrazi ("najviše", "najmanje",
"najkasnije").

PRAVILA IZLAZA (spremno za copy/paste)
- U tekst za kupca NE piši oznake izvora ([S1], [S2]), riječi „KONFLIKT“,
  „potvrditi“, „provjeriti koji je ispravan“, „Prije lokalne objave“, „prema
  dostupnoj dokumentaciji“, nazive drugih trgovina ni njihove šifre.
  Neslaganja i nedostatke vrati ISKLJUČIVO u završnom JSON-u.
- Ne koristi crtice (– ili —). Umjesto njih zarez ili točka. Crtica ostaje samo
  u rasponu brojeva (22–42 cm, 6–12 mjeseci) i unutar naziva (La Roche-Posay).
- Šifre drugih trgovina se ne preuzimaju i ne uspoređuju; to nije konflikt.
- Brza traka: popuni svih šest polja konkretnim podacima (Tip proizvoda,
  Namjena, Ciljana skupina, Područje primjene, Tekstura / oblik, Pakiranje).
  Uputa iz predloška nikad ne ostaje u izlazu.
- Istaknuti sastojci: točno 3 ili 4, svaki s potvrđenom ulogom. Puni sastav ili
  INCI ide doslovno ispod njih. Nutritivna tablica ide zasebno.
- Kliničke studije: redak samo ako izvor navodi rezultat, vrijeme, broj
  ispitanika, metodu i izvor. Inače IZOSTAVI cijeli blok.
- Ne koristi „klinički dokazano“, „testirano“ ni „dermatološki testirano“ bez
  objašnjenja što je i kako testirano.
- Naziv proizvoda: Brend + naziv + glavna karakteristika + količina na kraju.
  Bez crtice, bez znaka |, bez namjene u nazivu, bez zareza ispred količine.
- Hrana za dojenčad: obvezna rečenica „Dojenje je najbolji način prehrane
  dojenčeta.“ Početna hrana za dojenčad (0 do 6 mjeseci) bez prehrambenih i
  zdravstvenih tvrdnji.

NA KRAJU ODGOVORA, nakon dokumenta, u zasebnom bloku vrati JSON:
```json
{{"nedostaje": ["EAN", "..."], "konflikti": ["..."], "koristeni_izvori": ["..."]}}
```

MODEL NE SMIJE
- Izbaciti pronađeni podatak zato što ga smatra manje važnim.
- Zamijeniti postojeću vrijednost rečenicom tipa "provjeriti na pakiranju" ili
  "provjeriti na deklaraciji".
- Promijeniti broj, jedinicu, koncentraciju ili identifikator bez izvora.
- Spojiti konfliktne vrijednosti iz različitih izvora u jednu novu činjenicu.
- Opće znanje modela predstaviti kao činjenicu o ovom proizvodu.
- Puniti PDP generičkim tekstom na štetu konkretnih podataka proizvoda.
- Koristiti činjenice iz formatnog primjera kategorije.

HIJERARHIJA IZVORA (provodi se u kodu)
- PRIORITET 1: stranica proizvoda na eljekarna24 (URL iz ulazne tablice).
- PRIORITET 2: službena hrvatska stranica brenda, samo za podatak kojeg nema
  na prioritetu 1.
- Drugih izvora nema. Ako podatka nema ni u jednom od ta dva izvora, NE
  izmišljaj ga: ostavi tekst iz predloška i navedi polje u listi "nedostaje".
- Ako se konkretne vrijednosti razlikuju, NE spajaj ih i NE biraj sam:
  neslaganje vrati isključivo u JSON polju "konflikti", nikad u tekstu.

PRAVILA SADRŽAJA (apsolutna)
1. ISKLJUČIVO ČINJENICE IZ IZVORA [S1..Sn], iz INVENTARA ili iz naziva
   proizvoda. Ništa se ne izmišlja: ni sastojci, ni brojke, ni tvrdnje, ni EAN,
   ni proizvođač.
2. Svaki broj s jedinicom (ml, g, mg, µg, IU, kapsula, cm, %...) smije se
   upotrijebiti samo ako postoji u izvorima ili nazivu.
3. Podatak kojeg nema u izvorima: upotrijebi točan placeholder
   "{T.PLACEHOLDER_UNKNOWN}" (Proizvođač, EAN i sl.), odnosno
   "{T.PLACEHOLDER_ORIGIN}" (Zemlja podrijetla), ili ga izostavi.
4. Oprezan, provjerljiv jezik s ogradama: "prema deklaraciji", "prema podacima
   proizvoda", "prema uputi". Bez obećanja rezultata.
5. ZABRANJENO: cijene i valute, akcije/popusti/gratis, dostava, dostupnost,
   zalihe, košarica, pozivi na akciju (naruči, kupi, kliknite, saznajte...),
   superlativi (najbolji, vrhunski, savršen...), "klinički dokazano" bez metode,
   liječi/izliječi/jamči/garantira, spominjanje konkurenata i drugih trgovina.
6. Kliničke brojke samo ako u izvorima postoje s metodom (vrijeme, broj
   ispitanika, način mjerenja); inače se sekcija Kliničke studije izostavlja.
7. FAQ: 3–5 stvarnih pitanja kupaca, odgovori isključivo iz izvora.{extra}

PRAVILA FORMATA (apsolutna)
1. Odgovor je ISKLJUČIVO Markdown dokument, bez ikakvog teksta prije ili
   poslije, bez ``` ograda.
2. Kostur, redoslijed sekcija, numeracija i naslovi moraju biti TOČNO kao u
   zadanom kosturu; primjer pokazuje gotov dokument iste kategorije.
3. Nazivi tabova moraju biti doslovno:
{tabs}
4. "Brza traka ispod opisa" sadrži točno ovu liniju polja: "{t['brza_traka']}"
   i nakon nje 3–4 natuknice ključnih prednosti.
5. Tab 1 ima 80–150 riječi i počinje situacijom kupca.
6. Tab 5 obvezno sadrži tablicu s redcima: Pakiranje, Brend, Proizvođač,
   Zemlja podrijetla, EAN i "Obvezna provjera prije objave", plus upozorenja
   iz deklaracije kao zasebne rečenice.
7. Tab 6 i blok "Ocjene i recenzije kupaca" prepisuju se DOSLOVNO iz kostura.
8. Primjer služi ISKLJUČIVO za format: nijedna činjenica iz primjera ne smije
   završiti u tvom dokumentu ako ne postoji i u izvorima za OVAJ proizvod."""
    prompt = prompts_cfg.render(
        "pdp_system", default,
        kategorija=T.CATEGORY_LABELS[category],
        tabovi=tabs,
        brza_traka=t["brza_traka"],
        extra=extra.strip(),
        PLACEHOLDER_UNKNOWN=T.PLACEHOLDER_UNKNOWN,
        PLACEHOLDER_ORIGIN=T.PLACEHOLDER_ORIGIN,
    )
    return prompts_cfg.with_notes(prompt, "pdp_napomene",
                                  f"pdp_napomene_{category}")


def build_gen_user(product: Product, category: str, sources: list[Source],
                   feedback: str | None = None, inventory=None) -> str:
    inv_block = ""
    if inventory is not None and inventory.facts:
        inv_block = f"""

INVENTAR ČINJENICA (strukturirano izvučen iz izvora PRIJE pisanja — sve što je
FOUND mora završiti u PDP-u; HARD FIELD se ne smije izgubiti ni skratiti):
<<<INVENTAR
{inventory.as_prompt_block()}
INVENTAR>>>"""
    msg = f"""PROIZVOD
Naziv (iz baze; normaliziraj velika slova): {product.naziv}
Brend: {product.brend or "-"}
Sekcija: {product.sekcija or "-"}
SKU: {product.sku}
URL: {product.url}

KOSTUR (obavezan format):
<<<KOSTUR
{T.build_skeleton(category)}
KOSTUR>>>

PRIMJER GOTOVOG DOKUMENTA ISTE KATEGORIJE (drugi proizvod; SAMO za format):
<<<PRIMJER
{T.EXAMPLES[category]}
PRIMJER>>>

IZVORI ZA OVAJ PROIZVOD:
<<<IZVORI
{sources_block(sources)}
IZVORI>>>{inv_block}

Napiši potpuni PDP dokument za ovaj proizvod. Vrati samo Markdown."""
    if feedback:
        msg += f"""

PRETHODNI POKUŠAJ NIJE PROŠAO KONTROLU. Ispravi SVE navedeno i vrati cijeli
ispravljeni dokument:
{feedback}"""
    return msg


VERIFY_SYSTEM_DEFAULT = """Ti si stroga kontrola činjenica za sadržaj internetske ljekarne.
Dobit ćeš IZVORE [S1..Sn] i PDP dokument. Provjeri svaku ČINJENIČNU tvrdnju o
proizvodu (sastojci, brojke, doze, namjena, dobne granice, sadržaj pakiranja,
tehnologije, EAN, proizvođač, rezultati ispitivanja): je li potkrijepljena
izvorima ili nazivom proizvoda?

NE prijavljuj: opće upute sigurnog korištenja, standardna upozorenja kategorije,
placeholder rečenice ("Unijeti točno prema aktualnoj deklaraciji ili PIM-u.",
"Navesti samo ako je potvrđena..."), fiksne blokove (Tab 6, recenzije) ni
formulacije s ogradom koje ne unose novu činjenicu.

Odgovori ISKLJUČIVO validnim JSON-om, bez ikakvog drugog teksta:
{"prolazi": true/false,
 "nepotkrijepljene_tvrdnje": [{"tvrdnja": "...", "razlog": "..."}],
 "napomena": "..."}
"prolazi" je false čim postoji ijedna nepotkrijepljena činjenična tvrdnja."""


def build_verify_system() -> str:
    return prompts_cfg.with_notes(
        prompts_cfg.render("verify_system", VERIFY_SYSTEM_DEFAULT),
        "verify_napomene")


def build_verify_user(product: Product, sources: list[Source], md: str) -> str:
    return f"""PROIZVOD: {product.naziv} (brend: {product.brend}, SKU: {product.sku})

IZVORI:
<<<IZVORI
{sources_block(sources)}
IZVORI>>>

PDP DOKUMENT ZA PROVJERU:
<<<PDP
{md}
PDP>>>

Vrati samo JSON."""


def parse_verifier_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    for chunk in (cleaned, *re.findall(r"\{.*\}", cleaned, flags=re.S)):
        try:
            data = json.loads(chunk)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and "prolazi" in data:
            claims = data.get("nepotkrijepljene_tvrdnje") or []
            if not isinstance(claims, list):
                claims = []
            data["nepotkrijepljene_tvrdnje"] = [
                c for c in claims if isinstance(c, dict) and c.get("tvrdnja")
            ]
            return data
    return None


# ---------------------------------------------------------------------------
# Parsiranje Markdowna i validacija strukture
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*?)\s*$")


JSON_BLOK_RE = re.compile(r"```json\s*(\{.*?\})\s*```\s*$", re.S)


def odvoji_json_blok(raw: str) -> tuple[str, dict]:
    """Izdvoji završni JSON (nedostaje / konflikti / koristeni_izvori) iz odgovora.
    Dokument koji ide klijentu ostaje bez njega."""
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
        # model je vratio goli JSON na kraju, bez ograda
        m2 = re.search(r"\n(\{\s*\"(?:nedostaje|konflikti|koristeni_izvori)\".*\})\s*$",
                       raw or "", re.S)
        if m2:
            try:
                podaci = json.loads(m2.group(1))
            except json.JSONDecodeError:
                podaci = {}
            raw = raw[:m2.start()].rstrip()
    return raw, podaci


def clean_markdown(raw: str) -> str:
    text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[i:]).strip() + "\n"
    return text.strip() + "\n"


def parse_headings(md: str) -> list[dict]:
    out = []
    for idx, line in enumerate(md.splitlines()):
        m = HEADING_RE.match(line)
        if m:
            out.append({"level": len(m.group(1)), "title": m.group(2),
                        "line": idx})
    return out


def block_of(md: str, headings: list[dict], pos: int) -> str:
    """Tekst nakon headinga `pos` do sljedećeg headinga iste ili više razine."""
    lines = md.splitlines()
    start = headings[pos]["line"] + 1
    level = headings[pos]["level"]
    end = len(lines)
    for h in headings[pos + 1:]:
        if h["level"] <= level:
            end = h["line"]
            break
    return "\n".join(lines[start:end])


def prose_words(block: str) -> int:
    words = 0
    for line in block.splitlines():
        s = line.strip()
        if not s or s.startswith(("|", "#", "-", "*")):
            continue
        words += len(s.split())
    return words


def has_table(block: str) -> bool:
    lines = [ln.strip() for ln in block.splitlines()]
    return any(ln.startswith("|") and "---" in ln for ln in lines)


def validate_pdp(md: str, product: Product, category: str,
                 sources: list[Source]) -> list[str]:
    """Deterministička kontrola formata i sadržajnih pravila. [] = prolaz."""
    t = T.TEMPLATES[category]
    errors: list[str] = []
    headings = parse_headings(md)

    h1 = [h for h in headings if h["level"] == 1]
    if len(h1) != 1 or not h1[0]["title"].startswith("PDP struktura s tabovima:"):
        errors.append("Dokument mora početi s točno jednim naslovom "
                      "'# PDP struktura s tabovima: <naziv>'.")

    # --- H2 sekcije redom, s točnom numeracijom ---
    h2 = [h for h in headings if h["level"] == 2]
    h2_titles = [h["title"] for h in h2]

    def h2_index(prefix: str) -> int:
        for i, title in enumerate(h2_titles):
            if title.startswith(prefix):
                return i
        return -1

    expected_fixed = ["1. Prvi ekran: Naziv, opis i brzi podatci",
                      "2. Istaknuti blok iznad tabova",
                      "3. Struktura tabova (Max 6 tabova)"]
    for i, expected in enumerate(expected_fixed):
        if i >= len(h2_titles) or h2_titles[i] != expected:
            got = h2_titles[i] if i < len(h2_titles) else "(nedostaje)"
            errors.append(f"Sekcija {i + 1} mora biti točno '## {expected}' "
                          f"(nađeno: '{got}').")

    studies_idx = h2_index("4. Kliničke studije")
    has_studies = studies_idx != -1
    if has_studies and not t["allow_studies"]:
        errors.append("Sekcija 'Kliničke studije' nije dopuštena za ovu "
                      "kategoriju — izostavi je.")
    n_reviews = 5 if has_studies else 4
    reviews_expected = f"{n_reviews}. Ocjene i recenzije kupaca"
    faq_expected = f"{n_reviews + 1}. Često postavljana pitanja (FAQ)"
    if reviews_expected not in h2_titles:
        errors.append(f"Nedostaje ili je pogrešno numerirana sekcija "
                      f"'## {reviews_expected}'.")
    if faq_expected not in h2_titles:
        errors.append(f"Nedostaje ili je pogrešno numerirana sekcija "
                      f"'## {faq_expected}'.")

    # --- Sekcija 1: naziv, kratki opis, brza traka ---
    sec1_pos = next((i for i, h in enumerate(headings)
                     if h["level"] == 2 and h["title"].startswith("1. Prvi ekran")),
                    None)
    if sec1_pos is not None:
        sec1_end = next((h["line"] for h in headings[sec1_pos + 1:]
                         if h["level"] <= 2), len(md.splitlines()))
        sub = [h for h in headings
               if h["level"] == 3 and headings[sec1_pos]["line"] < h["line"] < sec1_end]
        sub_titles = [h["title"] for h in sub]
        for expected in ["Naziv proizvoda", "Kratki opis", "Brza traka ispod opisa"]:
            if expected not in sub_titles:
                errors.append(f"U sekciji 1 nedostaje podnaslov '### {expected}'.")

        for i, h in enumerate(sub):
            if h["title"] == "Naziv proizvoda":
                body = block_of(md, headings, headings.index(h))
                name_line = next((ln.strip() for ln in body.splitlines()
                                  if ln.strip()), "")
                if not name_line:
                    errors.append("Naziv proizvoda je prazan.")
                else:
                    brand_tok = norm_compact(product.brend)
                    first_tok = (norm_spaced(product.naziv).split() or [""])[0]
                    nn = norm_compact(name_line)
                    if brand_tok and not nn.startswith(brand_tok) \
                            and not nn.startswith(norm_compact(first_tok)):
                        errors.append("Naziv proizvoda mora početi brendom "
                                      f"('{product.brend}').")
                    src_specs = spec_tokens(product.naziv)
                    if src_specs and not (spec_tokens(name_line) & src_specs):
                        errors.append("Naziv proizvoda mora sadržavati količinu iz "
                                      f"naziva u bazi (npr. {sorted(src_specs)[0]}).")
            if h["title"] == "Kratki opis":
                body = block_of(md, headings, headings.index(h)).strip()
                if not body:
                    errors.append("Kratki opis je prazan.")
                elif body.count(".") > 2:
                    errors.append("Kratki opis mora biti jedna rečenica.")
            if h["title"] == "Brza traka ispod opisa":
                body = block_of(md, headings, headings.index(h))
                lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
                bullets = [ln for ln in lines if ln.startswith("- ")]
                if not 3 <= len(bullets) <= 4:
                    errors.append("Brza traka mora imati 3–4 natuknice ključnih "
                                  f"prednosti (nađeno: {len(bullets)}).")

    # --- Sekcija 2: istaknuti blok ---
    sec2_pos = next((i for i, h in enumerate(headings)
                     if h["level"] == 2 and
                     h["title"].startswith("2. Istaknuti blok")), None)
    if sec2_pos is not None:
        body = block_of(md, headings, sec2_pos)
        if not has_table(body):
            errors.append("Istaknuti blok iznad tabova mora sadržavati tablicu.")

    # --- Tabovi ---
    tab_heads = [h for h in headings
                 if h["level"] == 3 and h["title"].startswith("Tab ")]
    if len(tab_heads) != 6:
        errors.append(f"Mora postojati točno 6 tabova (nađeno: {len(tab_heads)}).")
    for i, expected_label in enumerate(t["tabs"], start=1):
        expected = f"Tab {i}: {expected_label}"
        found = next((h for h in tab_heads if h["title"] == expected), None)
        if not found:
            got = tab_heads[i - 1]["title"] if i - 1 < len(tab_heads) else "(nedostaje)"
            errors.append(f"Tab {i} mora se zvati točno '### {expected}' "
                          f"(nađeno: '{got}').")

    tab_blocks: dict[int, str] = {}
    for h in tab_heads:
        m = re.match(r"Tab (\d)", h["title"])
        if m:
            tab_blocks[int(m.group(1))] = block_of(md, headings, headings.index(h))

    if 1 in tab_blocks:
        n_words = prose_words(tab_blocks[1])
        if not TAB1_MIN_WORDS <= n_words <= TAB1_MAX_WORDS:
            errors.append(f"Tab 1 mora imati {TAB1_MIN_WORDS}–{TAB1_MAX_WORDS} "
                          f"riječi opisa (nađeno: {n_words}).")

    if 5 in tab_blocks:
        for row in T.TAB5_REQUIRED_ROWS:
            if row.lower() not in tab_blocks[5].lower():
                errors.append(f"Tab 5 mora sadržavati redak '{row}'.")
        if not has_table(tab_blocks[5]):
            errors.append("Tab 5 mora sadržavati tablicu podataka.")

    if 6 in tab_blocks:
        if "Stručni savjet ljekarnika" not in tab_blocks[6] or \
                "izravnog kontakta s ljekarnikom" not in tab_blocks[6]:
            errors.append("Tab 6 mora doslovno sadržavati fiksne natuknice iz "
                          "kostura (savjet ljekarnika + izravan kontakt).")

    # --- Kliničke studije (ako postoje) ---
    if has_studies:
        pos = next(i for i, h in enumerate(headings)
                   if h["level"] == 2 and h["title"].startswith("4. Kliničke"))
        if not has_table(block_of(md, headings, pos)):
            errors.append("Sekcija Kliničke studije mora sadržavati tablicu "
                          "'Rezultat | Metoda mjerenja i izvor'.")

    # --- Recenzije (fiksni tekst) ---
    rev_pos = next((i for i, h in enumerate(headings)
                    if h["level"] == 2 and "Ocjene i recenzije" in h["title"]), None)
    if rev_pos is not None:
        body = block_of(md, headings, rev_pos)
        if "eLjekarna24" not in body or "recenzij" not in body.lower():
            errors.append("Blok recenzija mora se doslovno prepisati iz kostura "
                          "(stvarne recenzije iz sustava eLjekarna24).")

    # --- FAQ ---
    faq_pos = next((i for i, h in enumerate(headings)
                    if h["level"] == 2 and "(FAQ)" in h["title"]), None)
    if faq_pos is not None:
        faq_block = block_of(md, headings, faq_pos)
        questions = [h for h in headings
                     if h["level"] == 3 and h["line"] > headings[faq_pos]["line"]]
        q_ok = [q for q in questions if q["title"].endswith("?")]
        if not FAQ_MIN <= len(q_ok) <= FAQ_MAX:
            errors.append(f"FAQ mora imati {FAQ_MIN}–{FAQ_MAX} pitanja koja "
                          f"završavaju upitnikom (nađeno: {len(q_ok)}).")
        if len(q_ok) != len(questions):
            errors.append("Svaki FAQ podnaslov mora biti pitanje (završava s '?').")
        for q in q_ok:
            ans = block_of(md, headings, headings.index(q)).strip()
            if len(ans) < 20:
                errors.append(f"FAQ pitanje '{q['title']}' nema sadržajan odgovor.")
        del faq_block

    # --- Obvezne fraze kategorije ---
    for phrase, message in t["mandatory_phrases"]:
        options = phrase if isinstance(phrase, (tuple, list)) else (phrase,)
        if not any(o.lower() in md.lower() for o in options):
            errors.append(f"Nedostaje obvezni element: {message}.")

    # --- Ograde ("prema deklaraciji" i sl.) ---
    low = md.lower()
    if not any(h in low for h in HEDGE_PHRASES):
        errors.append("Dokument mora sadržavati ograde poput 'prema deklaraciji' "
                      "ili 'prema podacima proizvoda'.")

    # --- Zabranjeni izrazi ---
    for hit in find_forbidden(md):
        errors.append(f"Zabranjeni izraz u dokumentu: {hit}.")
    for hit in R.nadi_zabranjene_rijeci(md):
        errors.append(f"Zabranjena riječ: {hit}.")

    # --- Z2: interne napomene ne smiju u tekst za kupca ---
    for hit in R.nadi_interne_napomene(md):
        errors.append(f"Interna napomena u tekstu za kupca: {hit}. Takve podatke "
                      "vrati samo u JSON poljima, nikad u dokumentu.")

    # --- Z4: crtice ---
    crtice = R.nadi_crtice(md)
    if crtice:
        errors.append(f"Dokument sadrži {len(crtice)} crtica (– ili —). Umjesto "
                      "njih koristi zarez ili točku; crtica smije ostati samo u "
                      "rasponu brojeva (22–42 cm).")

    # --- tvrdnje „testirano“ bez objašnjenja ---
    for hit in R.nadi_tvrdnje_bez_objasnjenja(md):
        errors.append(f"Tvrdnja bez objašnjenja: {hit}.")

    # --- brzi podaci: šest popunjenih polja ---
    if sec1_pos is not None:
        for h in headings:
            if h["level"] == 3 and h["title"] == "Brza traka ispod opisa":
                body = block_of(md, headings, headings.index(h))
                for polje in T.BRZA_TRAKA_POLJA:
                    red = re.search(rf"\|\s*{re.escape(polje)}\s*\|([^|]*)\|", body)
                    if not red:
                        errors.append(f"Brza traka nema polje „{polje}“. Obvezno je "
                                      "svih šest polja.")
                    elif len(red.group(1).strip()) < 2 or "{" in red.group(1):
                        errors.append(f"Polje „{polje}“ u brzoj traci nije popunjeno "
                                      "konkretnim podatkom iz izvora.")
                break

    # --- istaknuti sastojci: točno 3 ili 4 ---
    sastojci_tab = {"cosmetics": 4, "supplement": 4, "formula": 3}.get(category)
    if sastojci_tab and sastojci_tab in tab_blocks:
        redovi = [ln for ln in tab_blocks[sastojci_tab].splitlines()
                  if ln.strip().startswith("|") and "---" not in ln]
        broj = max(0, len(redovi) - 1)          # bez zaglavlja
        if redovi and not 3 <= broj <= 4:
            errors.append(f"Istaknutih sastojaka mora biti 3 ili 4 (nađeno: {broj}). "
                          "Nutritivna tablica i puni sastav idu odvojeno, ispod.")

    # --- kliničke studije: svaki redak s vremenom, brojem ispitanika i metodom ---
    if has_studies:
        pos = next(i for i, h in enumerate(headings)
                   if h["level"] == 2 and h["title"].startswith("4. Kliničke"))
        blok = block_of(md, headings, pos)
        for ln in blok.splitlines():
            if not ln.strip().startswith("|") or "---" in ln or "Rezultat |" in ln:
                continue
            ima_broj = re.search(r"\d+\s*ispitanik", ln, re.IGNORECASE)
            ima_vrijeme = re.search(r"\d+\s*(tjedan|tjedn|dan|dana|sat|sati|mjesec)",
                                    ln, re.IGNORECASE)
            ima_metodu = re.search(r"(procjen|mjerenj|metod|instrumental|ispitivanj)",
                                   ln, re.IGNORECASE)
            if not (ima_broj and ima_vrijeme and ima_metodu):
                errors.append("Redak kliničkih studija nema sve obvezno (rezultat, "
                              "vrijeme, broj ispitanika, metoda, izvor). Ako podaci "
                              "nisu potpuni, IZOSTAVI cijeli blok Kliničke studije.")
                break

    # --- obvezni podaci u Tab 5 ---
    if 5 in tab_blocks:
        for polje, naziv in (("EAN", "EAN"), ("Proizvođač", "proizvođač"),
                             ("Pakiranje", "pakiranje")):
            red = re.search(rf"\|\s*{polje}[^|]*\|([^|]*)\|", tab_blocks[5],
                            re.IGNORECASE)
            if red and not red.group(1).strip():
                errors.append(f"Obvezan podatak „{naziv}“ u Tabu 5 je prazan.")

    # --- EAN ---
    src_compact = norm_compact(product.naziv + " " +
                               " ".join(s.text for s in sources))
    for m in re.finditer(r"^\|\s*EAN[^|]*\|\s*([^|]+)\|", md,
                         flags=re.MULTILINE | re.IGNORECASE):
        cell = m.group(1).strip()
        digits = re.sub(r"\D", "", cell)
        if digits:
            if len(digits) not in (8, 12, 13, 14):
                errors.append(f"EAN '{cell}' nema valjan broj znamenki.")
            elif digits not in src_compact:
                errors.append(f"EAN '{digits}' ne postoji u izvorima — upotrijebi "
                              f"placeholder: '{T.PLACEHOLDER_UNKNOWN}'.")
        elif T.PLACEHOLDER_UNKNOWN not in cell:
            errors.append("EAN bez vrijednosti mora sadržavati placeholder: "
                          f"'{T.PLACEHOLDER_UNKNOWN}'.")

    # --- Brojevi s jedinicama moraju postojati u izvorima ---
    source_specs = spec_tokens(product.naziv + " " +
                               " ".join(s.text for s in sources))
    for tok in sorted(spec_tokens(md)):
        if tok not in source_specs:
            errors.append(f"Podatak '{tok}' ne postoji u izvorima ni u nazivu — "
                          "ukloni ga ili zamijeni potvrđenim podatkom.")

    return errors


# ---------------------------------------------------------------------------
# Markdown -> DOCX (python-docx)
# ---------------------------------------------------------------------------

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _add_runs(paragraph, text: str) -> None:
    pos = 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        paragraph.add_run(m.group(1)).bold = True
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


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
            doc.add_heading(m.group(2), level=len(m.group(1)))
            i += 1
            continue

        if line.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
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
                        para = cell.paragraphs[0]
                        _add_runs(para, row[c] if c < len(row) else "")
                        if r == 0:
                            for run in para.runs:
                                run.bold = True
                doc.add_paragraph("")
            continue

        if line.strip().startswith(("- ", "* ")):
            para = doc.add_paragraph(style="List Bullet")
            _add_runs(para, line.strip()[2:])
            i += 1
            continue

        para = doc.add_paragraph()
        _add_runs(para, line.strip())
        i += 1

    doc.save(str(out_path))


# ---------------------------------------------------------------------------
# Obrada jednog proizvoda
# ---------------------------------------------------------------------------

def process_product(product: Product, category: str, sources: list[Source],
                    client: BedrockClient, max_attempts: int,
                    do_verify: bool, do_extract: bool = True,
                    do_coverage: bool = True) -> tuple[RowResult, str]:
    result = RowResult(product=product, category=category, sources=sources,
                       model_id=client.model_id)
    system_prompt = build_gen_system(category)

    # --- 1. STRUKTURIRANA EKSTRAKCIJA PRIJE PISANJA ---
    inventory = None
    if do_extract and sources:
        raw_inv = client.extract(X.build_extract_system(category),
                                 X.build_extract_user(product,
                                                      sources_block(sources)))
        inventory = X.parse_inventory(raw_inv, category)
        result.inventory = inventory
        if not inventory.ok:
            result.status = "GREŠKA EKSTRAKCIJE"
            result.notes.append(inventory.error)
            return result, ""
        result.conflicts = [f"{f.polje}: {f.konflikt or f.vrijednost}"
                            for f in inventory.conflicts()]

    feedback: str | None = None
    best_md, best_issues = "", None
    best_score = (-1, -10 ** 6)  # (struktura prošla?, -broj problema)

    def consider(md_text: str, issues: list[str], structure_ok: bool) -> None:
        nonlocal best_md, best_issues, best_score
        score = (1 if structure_ok else 0, -len(issues))
        if score > best_score:
            best_md, best_issues, best_score = md_text, list(issues), score

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        raw = client.generate(system_prompt,
                              build_gen_user(product, category, sources, feedback,
                                             inventory))
        raw, interni_json = odvoji_json_blok(raw)
        md = clean_markdown(raw)
        md = R.ukloni_crtice(md)                    # Z4, sigurnosna mreža
        md = R.primijeni_rjecnik(md)                # ujednačen zapis brendova
        result.nedostaje = [str(x) for x in (interni_json.get("nedostaje") or [])]
        if interni_json.get("konflikti"):
            result.conflicts = [str(x) for x in interni_json["konflikti"]]

        errors = validate_pdp(md, product, category, sources)
        if errors:
            consider(md, errors, structure_ok=False)
            feedback = ("Greške automatske kontrole formata i sadržaja:\n"
                        + "\n".join(f"- {e}" for e in errors))
            continue

        if not do_verify:
            result.status = "OK (bez verifikacije)"
            result.verified = "preskočeno"
            return result, md

        verdict_raw = client.verify(build_verify_system(),
                                    build_verify_user(product, sources, md))
        verdict = parse_verifier_json(verdict_raw)
        if verdict is None:
            result.status = "OK"
            result.verified = "neuspjelo parsiranje odgovora kontrolora"
            result.notes.append("kontrolor nije vratio valjan JSON — ručno provjeriti")
            return result, md

        claims = [c["tvrdnja"] for c in verdict["nepotkrijepljene_tvrdnje"]]
        if verdict.get("prolazi") and not claims:
            result.verified = "prolazi"
            if verdict.get("napomena"):
                result.notes.append(f"kontrolor: {verdict['napomena']}")

            # --- COVERAGE CHECK: je li išta izgubljeno iz izvora? ---
            gaps = []
            if do_coverage and inventory is not None:
                gaps = X.coverage_check(inventory, md) + \
                    X.placeholder_instead_of_value(inventory, md)
            if not gaps:
                razlozi = []
                obvezni = [n for n in result.nedostaje
                           if re.search(r"ean|proizvo|pakiranj|sastav",
                                        str(n), re.IGNORECASE)]
                if obvezni:
                    razlozi.append("nedostaje obvezan podatak: "
                                   + ", ".join(obvezni))
                if any(s.kind == SECONDARY_LABEL for s in sources):
                    razlozi.append("korišten je izvor 2 (stranica brenda)")
                if result.conflicts:
                    razlozi.append("neslaganje izvora zabilježeno interno")
                if razlozi:
                    result.status = "TREBA PROVJERA"
                    result.notes.extend(razlozi)
                else:
                    result.status = "OK"
                return result, md

            result.coverage = gaps
            consider(md, gaps, structure_ok=True)
            feedback = ("COVERAGE CHECK: podatci koji POSTOJE u izvorima nisu "
                        "završili u PDP-u ili su zamijenjeni općom napomenom. "
                        "Dopuni dokument tim podatcima (bez izmišljanja i bez "
                        "mijenjanja formata):\n"
                        + "\n".join(f"- {g}" for g in gaps))
            continue

        issues = [f"Nepotkrijepljena tvrdnja: \"{c['tvrdnja']}\" "
                  f"({c.get('razlog', 'nema izvora')})"
                  for c in verdict["nepotkrijepljene_tvrdnje"]] or \
                 ["Kontrolor je odbio dokument bez navedenih tvrdnji."]
        consider(md, issues, structure_ok=True)
        feedback = ("Kontrolor činjenica (drugi agent) pronašao je "
                    "nepotkrijepljene tvrdnje. Ukloni ih, zamijeni potvrđenim "
                    "podacima iz izvora ili propisanim placeholderom:\n"
                    + "\n".join(f"- {i}" for i in issues))

    issues = best_issues or ["model nije vratio upotrebljiv dokument"]
    coverage_issues = [i for i in issues
                       if "nije prenesen u PDP" in i or "zamijenjen" in i
                       or "Konflikt izvora" in i]
    result.unsupported = [i for i in issues if "tvrdnja" in i.lower()]
    result.coverage = coverage_issues
    if coverage_issues and not result.unsupported:
        result.status = "NEDOSTAJE PODATAK IZ IZVORA"
        result.verified = "prolazi (fact-check), coverage ne prolazi"
    else:
        result.status = "TREBA PROVJERA"
        result.verified = "ne prolazi"
    result.notes.extend(issues)
    return result, best_md


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
        ws = writer.sheets["PDP indeks"]
        widths = {"A": 16, "B": 14, "C": 10, "D": 42, "E": 44, "F": 22, "G": 18,
                  "H": 9, "I": 22, "J": 50, "K": 10, "L": 60, "M": 34, "N": 34,
                  "O": 50, "P": 28}
        for col, width in widths.items():
            ws.column_dimensions[col].width = width
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
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Generator PDP opisa (Bedrock, 2 agenta).")
    ap.add_argument("--input", "-i", required=True, help="XLSX ili CSV s proizvodima")
    ap.add_argument("--output", "-o", default="out_pdp", help="izlazna mapa")
    ap.add_argument("--limit", type=int, default=0, help="obradi samo prvih N")
    ap.add_argument("--sku", action="append", default=[],
                    help="obradi samo ovaj SKU (može više puta)")
    ap.add_argument("--max-attempts", type=int, default=3, help="pokušaja po proizvodu")
    ap.add_argument("--search-results", type=int, default=3,
                    help="broj web izvora po proizvodu (uz stranicu proizvoda)")
    ap.add_argument("--no-web-search", action="store_true", help="bez web pretrage")
    ap.add_argument("--no-fetch", action="store_true",
                    help="bez dohvaćanja stranice proizvoda i weba")
    ap.add_argument("--no-verify", action="store_true",
                    help="preskoči drugog agenta (kontrolora činjenica)")
    ap.add_argument("--refresh-cache", action="store_true", help="ponovno dohvati izvore")
    ap.add_argument("--force", action="store_true", help="ignoriraj postojeće rezultate")
    ap.add_argument("--retry-review", action="store_true",
                    help="ponovno generiraj samo retke koji nisu OK")
    ap.add_argument("--dry-run", action="store_true",
                    help="bez Bedrocka: skupi izvore i ispiši prompt za 1. proizvod")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    pdp_dir = out_dir / "pdp"
    pdp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".cache" / "html"
    jsonl_path = out_dir / "results.jsonl"

    products = load_products(Path(args.input))
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
    print(f"Proizvoda za obradu: {len(products)} "
          f"({', '.join(f'{T.CATEGORY_LABELS[k]}: {v}' for k, v in counts.items())})")

    def get_sources(p: Product) -> list[Source]:
        if args.no_fetch:
            return []
        return gather_sources(p, categories[p.sku], cache_dir,
                              refresh=args.refresh_cache,
                              web_search=not args.no_web_search,
                              max_web=args.search_results)

    if args.dry_run:
        p = products[0]
        cat = categories[p.sku]
        sources = get_sources(p)
        print(f"\n--- KATEGORIJA: {T.CATEGORY_LABELS[cat]} | IZVORA: {len(sources)} ---")
        for s in sources:
            print(f"  [{s.sid}] {s.kind}: {s.url} ({len(s.text)} znakova)")
        print(f"\n--- SYSTEM PROMPT (pisac) ---\n{build_gen_system(cat)}")
        print(f"\n--- USER MESSAGE ({p.sku}) ---\n"
              f"{build_gen_user(p, cat, sources)[:4000]}\n[... skraćeno ...]")
        return

    config = load_bedrock_config()
    client = BedrockClient(config)
    print(f"Model (pisac):     {client.model_id}")
    print(f"Model (kontrolor): {client.verify_model_id}")
    print(f"Regija:            {config['BEDROCK_AWS_REGION']}\n")

    done = {} if args.force else load_done(jsonl_path)
    if args.retry_review:
        done = {k: v for k, v in done.items() if str(v.get("Status", "")).startswith("OK")}

    records: dict[str, dict] = dict(done)
    todo = [p for p in products if p.sku not in records]
    if len(products) - len(todo):
        print(f"Preskačem {len(products) - len(todo)} već obrađenih "
              "(results.jsonl; --force za ponovno).")

    from botocore.exceptions import ClientError  # noqa: PLC0415

    try:
        for idx, p in enumerate(todo, start=1):
            cat = categories[p.sku]
            sources = get_sources(p)
            result, md = process_product(p, cat, sources, client,
                                         args.max_attempts,
                                         do_verify=not args.no_verify)

            if md.strip():
                stem = f"PDP_{p.sku}_{slugify(p.naziv)}"
                md_path = pdp_dir / f"{stem}.md"
                docx_path = pdp_dir / f"{stem}.docx"
                md_path.write_text(md, encoding="utf-8")
                try:
                    md_to_docx(md, docx_path)
                    result.docx_path = str(docx_path)
                except Exception as err:  # noqa: BLE001
                    result.notes.append(f"DOCX nije zapisan: {err}")
                result.md_path = str(md_path)

            record = result.to_record()
            records[p.sku] = record
            append_jsonl(jsonl_path, record)
            print(f"[{idx}/{len(todo)}] {p.sku} {p.naziv[:44]:<44} -> "
                  f"{result.status} (pokušaja: {result.attempts}, "
                  f"izvora: {len(sources)})")
    except ClientError as err:
        print("\nBedrock greška:\n  " + explain_client_error(err, config))
        print("Dosad obrađeno je u results.jsonl — ponovno pokretanje nastavlja "
              "gdje je stalo.")
        sys.exit(1)

    ordered = [records[p.sku] for p in products if p.sku in records]
    xlsx_path, csv_path = write_index(ordered, out_dir)

    ok = sum(1 for r in ordered if str(r.get("Status", "")).startswith("OK"))
    print(f"\nGotovo: {ok} OK, {len(ordered) - ok} za provjeru.")
    print(f"PDP datoteke: {pdp_dir}/  (MD + DOCX po proizvodu)")
    print(f"Indeks: {xlsx_path}\n        {csv_path}")
    if len(ordered) - ok:
        print("Retke koji nisu OK regeneriraj s: --retry-review (ili --sku <SKU>).")


if __name__ == "__main__":
    main()
