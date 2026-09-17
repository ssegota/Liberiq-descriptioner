#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testovi vanjskih promptova: default bez mape, napomene, override,
po-kategorijske napomene, placeholderi, otpornost na greške."""
import shutil
import sys
from pathlib import Path

import prompts_cfg
import pdp_generator as P
import seo_meta_generator as S

FAILURES = []


def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


DIR = Path("/home/claude/build/test_prompts")
shutil.rmtree(DIR, ignore_errors=True)

# 1. Bez mape -> ugrađeni promptovi
prompts_cfg.set_dir(DIR)
seo_base = S.build_system_prompt()
pdp_base = P.build_gen_system("cosmetics")
ver_base = P.build_verify_system()
check("bez mape: SEO ugrađeni prompt", "PRAVILA ZA TITLE TAG" in seo_base)
check("bez mape: PDP ugrađeni prompt", "PRAVILA FORMATA (apsolutna)" in pdp_base)
check("bez mape: kontrolor ugrađeni", "prolazi" in ver_base)
check("bez mape: nema odjeljka s napomenama",
      prompts_cfg.NOTE_HEADER not in seo_base + pdp_base)

# 2. --init stvara datoteke
target = prompts_cfg.init(DIR)
files = {p.name for p in target.glob("*.md")}
check("init: napomene stvorene",
      {"seo_napomene.md", "pdp_napomene.md", "pdp_napomene_formula.md",
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
(DIR / "pdp_napomene_formula.md").write_text("- Nikad ne spominjati okus.\n",
                                             encoding="utf-8")
prompts_cfg.set_dir(DIR)   # očisti cache

seo_p = S.build_system_prompt()
check("napomene: SEO dodane", "Brend uvijek s dijakriticima." in seo_p and
      prompts_cfg.NOTE_HEADER in seo_p)
check("napomene: ugrađena pravila ostala", "PRAVILA ZA TITLE TAG" in seo_p)
check("napomene: HTML komentar uklonjen", "<!-- komentar -->" not in seo_p)

cos = P.build_gen_system("cosmetics")
form = P.build_gen_system("formula")
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
    "PDP OVERRIDE za {kategorija}.\nTabovi:\n{tabovi}\nTraka: {brza_traka}\n",
    encoding="utf-8")
prompts_cfg.set_dir(DIR)

seo_o = S.build_system_prompt()
check("override: zamjena SEO prompta",
      seo_o.startswith("NOVA PRAVILA.") and "PRAVILA ZA TITLE TAG" not in seo_o)
check("override: placeholderi popunjeni",
      "550 px" in seo_o and "960 px" in seo_o and "| eljekarna24" in seo_o)
check("override: nepoznat placeholder ne ruši", "{nepostojeci}" in seo_o)
check("override: napomene i dalje dodane", "Brend uvijek s dijakriticima." in seo_o)

pdp_o = P.build_gen_system("device")
check("override: PDP zamjena + placeholderi",
      pdp_o.startswith("PDP OVERRIDE za medicinski proizvod / uređaj") and
      "Tab 3: Funkcije i specifikacije" in pdp_o)

# 5. Prazna datoteka = bez učinka
(DIR / "seo_system.md").write_text("<!-- samo komentar -->\n", encoding="utf-8")
prompts_cfg.set_dir(DIR)
check("prazan override -> vraća se ugrađeni prompt",
      "PRAVILA ZA TITLE TAG" in S.build_system_prompt())

# 6. Kontrolor: napomene + očuvan JSON format
(DIR / "verify_napomene.md").write_text("- Prijavi i nejasne dobne granice.\n",
                                        encoding="utf-8")
prompts_cfg.set_dir(DIR)
v = P.build_verify_system()
check("kontrolor: napomene dodane", "nejasne dobne granice" in v)
check("kontrolor: JSON format očuvan",
      '"nepotkrijepljene_tvrdnje"' in v and '"prolazi"' in v)

# 7. Popis aktivnih datoteka
check("active(): popis datoteka", len(prompts_cfg.active()) >= 7,
      f"({len(prompts_cfg.active())})")

# 8. Generiranje i dalje radi s izmijenjenim promptom (validator netaknut)
import json, threading
prod = P.Product("Kozmetika", "La Roche-Posay", "T1",
                 "LA ROCHE POSAY EFFACLAR DUO+M KREMA 40 ML", "https://x/")
src = [P.Source("S1", "stranica proizvoda", "u", "t",
                "Effaclar Duo+M krema 40 ml, niacinamid, glicerin, Zinc PCA, "
                "salicilna kiselina, EAN 3337875863377, 66 % manje mitesera "
                "nakon 4 tjedna na 45 ispitanika, 44 % na 45, 45 % na 42, "
                "24 sata hidratacije na 24 ispitanika, La Roche-Posay "
                "Laboratoire Dermatologique CAI, 86270 La Roche-Posay, Francuska, "
                "adolescente od 10 godina")]
import pdp_templates as T
import json as _json


class Mock:
    def extract(self, system, user):
        return _json.dumps({"cinjenice": [
            {"polje": "namjena", "vrijednost": "", "izvor": "",
             "status": "NOT FOUND"}]}, ensure_ascii=False)

    model_id = verify_model_id = "mock"

    def generate(self, system, user):
        assert "Obraćanje na vi." in system      # napomena stvarno stiže modelu
        return T.EXAMPLES["cosmetics"]

    def verify(self, system, user):
        return json.dumps({"prolazi": True, "nepotkrijepljene_tvrdnje": [],
                           "napomena": ""}, ensure_ascii=False)


res, md = P.process_product(prod, "cosmetics", src, Mock(), 2, True)
check("pipeline: radi s vanjskim napomenama", res.status == "OK", f"({res.status})")

shutil.rmtree(DIR, ignore_errors=True)
prompts_cfg.set_dir(Path("prompts"))

print()
if FAILURES:
    print("PALO:", FAILURES)
    sys.exit(1)
print("Sve OK.")
