# MLJ (Springer Nature sn-jnl) build
export PATH := $(HOME)/Library/TinyTeX/bin/universal-darwin:/opt/homebrew/bin:$(PATH)

.PHONY: pdf assets check submission clean word

assets:
	cd .. && uv run python scripts/paper_numbers.py
	cp ../paper/numbers.tex macros_numbers.tex
	cd .. && uv run python scripts/paper_assets_mlj.py

pdf: assets
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
	latexmk -pdf -interaction=nonstopmode -halt-on-error contribution_information_sheet.tex
	latexmk -pdf -interaction=nonstopmode -halt-on-error cover_letter.tex

check: pdf
	cd .. && uv run python scripts/paper_number_audit.py --mlj
	cd .. && uv run pytest tests/test_paper_numbers.py -q
	cd .. && python3 scripts/mlj_checks.py
	cd .. && python3 scripts/check_float_citations.py

submission: check
	cd .. && python3 scripts/mlj_flatten_submission.py
	cd .. && python3 scripts/check_float_citations.py --submission

word:
	cd .. && uv run python scripts/make_mlj_word.py

clean:
	latexmk -C || true
	rm -f contribution_information_sheet.pdf cover_letter.pdf
