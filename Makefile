.PHONY: test lint confirmatory

test:
	uv run pytest

lint:
	uv run ruff check

confirmatory:
	Rscript analysis/confirmatory/run_confirmatory.R \
	  --hazard results/hazard_table_main_v1.csv.gz \
	  --battery results/battery_b1_main_v1.csv.gz \
	  --out results/confirmatory.json

-include paper.mk
