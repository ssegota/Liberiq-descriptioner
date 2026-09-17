# Podešavanje promptova (bez diranja koda)

Svi promptovi oba generatora idu kroz `prompts_cfg.py` i mogu se uređivati kao
obične `.md` datoteke. Bez te mape alati rade s ugrađenim promptovima.

```bash
python prompts_cfg.py --init          # stvori mapu prompts/
python generate_all.py -i ulaz.xlsx --show-prompts   # vidi konačne promptove
```

## Dvije razine

**1. Napomene (za komentare klijenta — preporučeno).** Sadržaj se DODAJE na kraj
ugrađenog prompta kao odjeljak „dodatne upute“; ugrađena pravila ostaju.

| Datoteka | Utječe na |
| --- | --- |
| `seo_napomene.md` | SEO title i meta |
| `pdp_napomene.md` | sve PDP proizvode |
| `pdp_napomene_cosmetics.md` | samo kozmetiku |
| `pdp_napomene_supplement.md` | samo dodatke prehrani |
| `pdp_napomene_device.md` | samo uređaje |
| `pdp_napomene_formula.md` | samo mliječne formule |
| `verify_napomene.md` | kontrolora činjenica |

**2. Override (potpuna zamjena prompta).** `seo_system.md`, `pdp_system.md`,
`verify_system.md`. Uz `--init` se zapisuju `*.primjer.md` s aktualnim ugrađenim
promptom — preimenuj bez `.primjer` da ga aktiviraš i uredi.

Podržani placeholderi: SEO `{TITLE_MAX_PX} {TITLE_CORE_TARGET_PX} {META_MAX_PX}
{META_TARGET_CHARS} {BRAND_SUFFIX}`; PDP `{kategorija} {tabovi} {brza_traka}
{extra} {PLACEHOLDER_UNKNOWN} {PLACEHOLDER_ORIGIN}`.

## Važno

Ton, formulacije, zabranjene riječi i upute po brendu idu u napomene i rade
odmah. Ali tvrda pravila provjerava i **deterministički validator**, pa ako
klijent traži izmjenu koja dira:

- pikselske limite, redoslijed naziva, zabranjene izraze u SEO-u →
  `seo_meta_generator.py` (`validate_candidate`, konstante na vrhu),
- nazive tabova, obvezne rečenice, strukturu, broj FAQ pitanja →
  `pdp_templates.py` (`TEMPLATES`, `mandatory_phrases`) i `validate_pdp`,

tada treba uskladiti i njih — inače model piše jedno, a kontrola traži drugo i
redak ostaje na „TREBA PROVJERA“. Format odgovora kontrolora (JSON) ne mijenjati.

Nakon izmjena provjeri s `--show-prompts`, pa pokreni `--limit 2` prije punog runa.
