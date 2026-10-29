.PHONY: test lint confirmatory aie-exploratory aie aie-submission aie-titlepage

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

aie:
	$(MAKE) -C paper_aie pdf check

aie-submission:
	$(MAKE) -C paper_aie submission

aie-titlepage:
	$(MAKE) -C paper_aie titlepage

-include paper.mk
