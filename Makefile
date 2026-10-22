.PHONY: test lint confirmatory aie-exploratory

test:
	uv run pytest

lint:
	uv run ruff check

confirmatory:
	Rscript analysis/confirmatory/run_confirmatory.R \
	  --hazard results/hazard_table_main_v1.csv.gz \
	  --battery results/battery_b1_main_v1.csv.gz \
	  --out results/confirmatory.json

aie-exploratory:
	uv run python analysis/exploratory_aie/run_aie_exploratory.py

-include paper.mk
