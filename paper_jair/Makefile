# JAIR AI & Society submission
export PATH := $(HOME)/Library/TinyTeX/bin/universal-darwin:/opt/homebrew/bin:$(PATH)

.PHONY: pdf check sources clean

pdf: main.pdf

main.pdf: main.tex refs.bib macros_numbers.tex macros_review.tex \
		sections/*.tex appendix/*.tex tables/*.tex figs/*
	# nonstopmode without -halt-on-error: acmdatamodel.dbx emits xkeyval
	# errors (halid/swhid/…) under current TinyTeX biblatex that the
	# official kit example also emits and recovers from. pdflatex may
	# exit non-zero on those; force the full biber cycle anyway.
	pdflatex -interaction=nonstopmode main.tex || true
	biber main
	pdflatex -interaction=nonstopmode main.tex || true
	pdflatex -interaction=nonstopmode main.tex || true
	@test -s main.pdf
	@test -s main.bbl

check: pdf
	cd .. && python3 scripts/jair_checks.py

sources: pdf
	rm -f ../submission_jair_sources.zip
	cd .. && zip -r submission_jair_sources.zip paper_jair \
	  -i 'paper_jair/*.tex' 'paper_jair/*.cls' 'paper_jair/*.bbx' 'paper_jair/*.cbx' \
	     'paper_jair/*.dbx' 'paper_jair/*.bib' 'paper_jair/sections/*' \
	     'paper_jair/appendix/*' 'paper_jair/tables/*' 'paper_jair/figs/*' \
	     'paper_jair/Makefile' \
	  -x '*.aux' '*.log' '*.out' '*.bbl' '*.bcf' '*.blg' '*.run.xml' \
	     '*.fdb_latexmk' '*.fls' '*.synctex.gz' 'paper_jair/main.pdf' \
	     'paper_jair/JAIR_Example_Template.pdf'
	@echo "Wrote submission_jair_sources.zip"

clean:
	rm -f main.pdf main.aux main.log main.out main.bbl main.bcf main.blg \
	  main.run.xml main.toc main.lof main.lot main.fls main.fdb_latexmk \
	  main.synctex.gz
