# Phase 8 manuscript build
export PATH := $(HOME)/Library/TinyTeX/bin/universal-darwin:/opt/homebrew/bin:$(PATH)

.PHONY: paper numbers assets overleaf clean anon-check test-macros

numbers:
	uv run python scripts/paper_numbers.py

assets: numbers
	uv run python scripts/paper_assets.py

paper: assets
	cd paper && \
	  perl -i.bak -pe 's/^\\anon(?:true|false)$$/\\anontrue/' main.tex && \
	  latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex && \
	  cp main.pdf main_anon.pdf && \
	  perl -i.bak -pe 's/^\\anon(?:true|false)$$/\\anonfalse/' main.tex && \
	  latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex && \
	  cp main.pdf main_preprint.pdf && \
	  perl -i.bak -pe 's/^\\anon(?:true|false)$$/\\anontrue/' main.tex && \
	  rm -f main.tex.bak
	@echo "Built paper/main_anon.pdf and paper/main_preprint.pdf"

overleaf: paper
	cd paper && rm -f overleaf.zip && zip -r overleaf.zip \
	  main.tex numbers.tex math_commands.tex refs.bib tmlr.sty tmlr.bst fancyhdr.sty \
	  sections tables figs appendix TMLR_STYLE_COMMIT.txt MACROS.md \
	  -x '*.aux' '*.log' '*.out' '*.bbl' '*.blg' '*.fdb_latexmk' '*.fls' '*.synctex.gz' \
	     'figs/_make_figs.R' 'main.pdf' 'main_anon.pdf' 'main_preprint.pdf' '*.bak'
	@echo "Wrote paper/overleaf.zip"

test-macros:
	uv run pytest tests/test_paper_numbers.py -q

anon-check:
	@python3 scripts/paper_anon_check.py paper/main_anon.pdf

clean:
	cd paper && latexmk -C || true
	rm -f paper/main_anon.pdf paper/main_preprint.pdf paper/overleaf.zip
