#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi vanjskih promptova: default bez mape, napomene, override,
po-kategorijske napomene, placeholderi, otpornost na greške."""
import shutil
import sys
import tempfile
from pathlib import Path

import prompts_cfg
import pdp_generator as P
import seo_meta_generator as S

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


TMP = Path(tempfile.mkdtemp(prefix="liberiq_test_prompts_"))
DIR = TMP / "prompts"
shutil.rmtree(DIR, ignore_errors=True)

# 1. Bez mape -> ugrađeni promptovi
prompts_cfg.set_dir(DIR)
seo_base = S.build_system_prompt()
pdp_base = P.build_gen_system("B")
ver_base = P.build_verify_system()
check("bez mape: SEO ugrađeni prompt", "PRAVILA ZA TITLE TAG" in seo_base)
check("bez mape: PDP ugrađeni prompt (pravila klijenta doslovno)",
      "IZLAZNI FORMAT" in pdp_base and "Kako opis ne postaje šablona" in pdp_base
      and "Template B: Kozmetika" in pdp_base)
check("bez mape: kontrolor ugrađeni", "prolazi" in ver_base)
check("bez mape: nema odjeljka s napomenama",
      prompts_cfg.NOTE_HEADER not in seo_base + pdp_base)

# 2. --init stvara datoteke
target = prompts_cfg.init(DIR)
files = {p.name for p in target.glob("*.md")}
check("init: napomene stvorene",
      {"seo_napomene.md", "pdp_napomene.md", "pdp_napomene_C.md",
       "verify_napomene.md"} <= files, f"({len(files)} datoteka)")
check("init: primjeri overridea stvoreni",
      {"seo_system.primjer.md", "pdp_system.primjer.md",
       "verify_system.primjer.md"} <= files)
check("init: primjer sadrži aktualni prompt",
      "PRAVILA ZA TITLE TAG" in (target / "seo_system.primjer.md").read_text(encoding="utf-8"))
check("init: primjeri se ne aktiviraju sami",
      "PRAVILA ZA TITLE TAG" in S.build_system_prompt() and
      S.build_system_prompt().count("PRAVILA ZA TITLE TAG") == 1)

# 3. Napomene se dodaju
(DIR / "seo_napomene.md").write_text(
    "<!-- komentar -->\n\n- Brend uvijek s dijakriticima.\n", encoding="utf-8")
(DIR / "pdp_napomene.md").write_text("- Obraćanje na vi.\n", encoding="utf-8")
(DIR / "pdp_napomene_C.md").write_text("- Nikad ne spominjati okus.\n",
                                             encoding="utf-8")
prompts_cfg.set_dir(DIR)   # očisti cache

seo_p = S.build_system_prompt()
check("napomene: SEO dodane", "Brend uvijek s dijakriticima." in seo_p and
      prompts_cfg.NOTE_HEADER in seo_p)
check("napomene: ugrađena pravila ostala", "PRAVILA ZA TITLE TAG" in seo_p)
check("napomene: HTML komentar uklonjen", "<!-- komentar -->" not in seo_p)

cos = P.build_gen_system("B")
form = P.build_gen_system("C")
check("napomene: opće PDP u svim kategorijama",
      "Obraćanje na vi." in cos and "Obraćanje na vi." in form)
check("napomene: po kategoriji samo gdje treba",
      "Nikad ne spominjati okus." in form and
      "Nikad ne spominjati okus." not in cos)

# 4. Override s placeholderima
(DIR / "seo_system.md").write_text(
    "NOVA PRAVILA. Title do {TITLE_MAX_PX} px, meta do {META_MAX_PX} px, "
    "dodatak {BRAND_SUFFIX}. Nepoznat {nepostojeci} ostaje.\n", encoding="utf-8")
(DIR / "pdp_system.md").write_text(
    "PDP OVERRIDE za {kategorija}.\n", encoding="utf-8")
prompts_cfg.set_dir(DIR)

seo_o = S.build_system_prompt()
check("override: zamjena SEO prompta",
      seo_o.startswith("NOVA PRAVILA.") and "PRAVILA ZA TITLE TAG" not in seo_o)
check("override: placeholderi popunjeni",
      "550 px" in seo_o and "960 px" in seo_o and "│ eLjekarna24" in seo_o)
check("override: nepoznat placeholder ne ruši", "{nepostojeci}" in seo_o)
check("override: napomene i dalje dodane", "Brend uvijek s dijakriticima." in seo_o)

pdp_o = P.build_gen_system("D")
check("override: PDP zamjena + placeholderi",
      pdp_o.startswith("PDP OVERRIDE za D: Medicinski uređaji"))

# 5. Prazna datoteka = bez učinka
(DIR / "seo_system.md").write_text("<!-- samo komentar -->\n", encoding="utf-8")
prompts_cfg.set_dir(DIR)
check("prazan override -> vraća se ugrađeni prompt",
      "PRAVILA ZA TITLE TAG" in S.build_system_prompt())

# 6. Kontrolor: napomene + očuvan JSON format
(DIR / "verify_napomene.md").write_text("- Prijavi i nejasne dobne granice.\n",
                                        encoding="utf-8")
prompts_cfg.set_dir(DIR)
v = P.build_verify_system("A")
check("kontrolor: napomene dodane", "nejasne dobne granice" in v)
check("kontrolor: JSON format očuvan",
      '"greske"' in v and '"prolazi"' in v)

# 7. Popis aktivnih datoteka
check("active(): popis datoteka", len(prompts_cfg.active()) >= 7,
      f"({len(prompts_cfg.active())})")

# 8. Napomena stvarno stiže piscu
import pdp_templates as T  # noqa: E402

(DIR / "pdp_system.md").unlink()           # bez overridea
prompts_cfg.set_dir(DIR)
check("napomena stiže u prompt pisca", "Obraćanje na vi." in P.build_gen_system("A"))
check("checklista je u promptu Templatea A",
      "Checklista za izradu PDP opisa" in P.build_gen_system("A"))
check("biljna checklista za biljni dodatak",
      "biljni dodaci prehrani" in P.build_gen_system("A", "biljni dodatak prehrani").lower())
check("Template K bez checkliste", "Checklista za izradu" not in P.build_gen_system("K"))

shutil.rmtree(TMP, ignore_errors=True)
prompts_cfg.set_dir(Path("prompts"))

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
