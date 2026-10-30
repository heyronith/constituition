# TMLR anonymous submission + named preprint
export PATH := $(HOME)/Library/TinyTeX/bin/universal-darwin:/opt/homebrew/bin:$(PATH)

.PHONY: pdf preprint check clean write-preprint-identity

pdf:
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

write-preprint-identity:
	cd .. && python3 scripts/write_tmlr_preprint_identity.py

preprint: write-preprint-identity
	latexmk -pdf -interaction=nonstopmode -halt-on-error \
	  -jobname=preprint \
	  -pdflatex='pdflatex -interaction=nonstopmode -halt-on-error %O "\def\TMLRpreprintflag{}\input{%S}"' \
	  main.tex

check: pdf
	cd .. && python3 scripts/tmlr_checks.py

clean:
	latexmk -C || true
	latexmk -C -jobname=preprint || true
	rm -f preprint.pdf preprint.aux preprint.bbl preprint.blg preprint.log preprint.fls preprint.fdb_latexmk preprint.out preprint_identity.tex
