# AI and Ethics (Springer Nature sn-jnl, numbered) build
export PATH := $(HOME)/Library/TinyTeX/bin/universal-darwin:/opt/homebrew/bin:$(PATH)

.PHONY: pdf assets check submission titlepage clean

assets:
	# Reuse frozen MLJ numbers/macros and figures; do not regenerate analysis/results.
	@test -f macros_numbers.tex || cp ../paper_mlj/macros_numbers.tex macros_numbers.tex
	@test -f figs/Fig1.pdf || cp ../paper_mlj/figs/Fig1.pdf figs/Fig1.pdf
	@test -f figs/Fig2.pdf || cp ../paper_mlj/figs/Fig2.pdf figs/Fig2.pdf
	@test -f figs/Fig3.pdf || cp ../paper_mlj/figs/Fig3.pdf figs/Fig3.pdf
	# Printed order: Fig4 = per-item; Fig5 = forest (MLJ Fig4).
	cp -f ../results/exploratory_aie/figs/per_item_erosion.pdf figs/Fig4.pdf
	@test -f figs/Fig5.pdf || cp ../paper_mlj/figs/Fig4.pdf figs/Fig5.pdf
	@test -f figs/Fig5.eps || cp ../paper_mlj/figs/Fig4.eps figs/Fig5.eps

pdf: assets
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
	cp -f main.pdf manuscript.pdf
	latexmk -pdf -interaction=nonstopmode -halt-on-error title_page.tex

titlepage:
	latexmk -pdf -interaction=nonstopmode -halt-on-error title_page.tex

check: pdf
	@if [ -f ../scripts/paper_number_audit.py ]; then \
	  cd .. && uv run python scripts/paper_number_audit.py --aie; \
	fi
	@if [ -f ../tests/test_paper_numbers.py ]; then \
	  cd .. && uv run pytest tests/test_paper_numbers.py -q; \
	fi
	cd .. && python3 scripts/aie_checks.py

submission:
	cd .. && python3 scripts/aie_flatten_submission.py


clean:
	latexmk -C || true
	rm -f manuscript.pdf title_page.pdf
