# Liberiq Descriptioner
INPUT ?= proizvodi.xlsx
OUT   ?= out_all
PY    ?= python

.PHONY: help setup test dry-run sample run seo pdp retry prompts show-prompts clean clean-cache

help:           ## prikaži dostupne naredbe
	@grep -E '^[a-zA-Z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:          ## venv, ovisnosti i .env iz predloška
	$(PY) -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo "Gotovo. Aktiviraj: source .venv/bin/activate — pa uredi .env"

test:           ## offline testovi (bez Bedrocka i mreže)
	$(PY) test_upute.py
	$(PY) test_klijent.py
	$(PY) test_all.py
	$(PY) test_prompts.py

dry-run:        ## izvori i promptovi za prvi proizvod, bez poziva modelu
	$(PY) generate_all.py -i $(INPUT) -o $(OUT) --dry-run

sample:         ## pravi run na 2 proizvoda
	$(PY) generate_all.py -i $(INPUT) -o $(OUT) --limit 2

run:            ## puni run
	$(PY) generate_all.py -i $(INPUT) -o $(OUT)

seo:            ## samo title i meta
	$(PY) generate_all.py -i $(INPUT) -o $(OUT) --only seo

pdp:            ## samo PDP opisi
	$(PY) generate_all.py -i $(INPUT) -o $(OUT) --only pdp

retry:          ## ponovi samo retke koji nisu OK
	$(PY) generate_all.py -i $(INPUT) -o $(OUT) --retry-review

prompts:        ## stvori mapu prompts/ za uređivanje
	$(PY) prompts_cfg.py --init

show-prompts:   ## ispiši konačne promptove (s napomenama)
	$(PY) generate_all.py -i $(INPUT) --show-prompts

clean-cache:    ## obriši samo cache dohvaćenih stranica
	rm -rf $(OUT)/.cache

clean:          ## obriši cijeli izlaz
	rm -rf $(OUT) out out_pdp __pycache__
