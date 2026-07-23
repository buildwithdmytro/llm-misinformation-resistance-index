# Build the LMRI paper.
#
#   make            -> lmri-paper.pdf
#   make clean      -> remove build artefacts (keeps the PDF)
#   make distclean  -> remove build artefacts and the PDF
#
# Requires: pdflatex + bibtex (TeX Live) with mathptmx, booktabs, longtable,
# graphicx, xcolor, microtype, caption, natbib, hyperref, amsmath, amssymb.
# Figures (figures/*.pdf) and table bodies (tables/*.tex) are generated from
# release_numbers.json and committed alongside the sources.

LATEX  = pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX = bibtex

PDF    = lmri-paper.pdf
SRC    = main.tex references.bib \
         tables/top10_strict.tex tables/strict_board.tex \
         tables/basic_board.tex tables/model_pins.tex \
         figures/fig_survival_ladder.pdf figures/fig_two_axes.pdf \
         figures/fig_basic_vs_strict.pdf figures/fig_domains.pdf

.PHONY: all clean distclean

all: $(PDF)

$(PDF): $(SRC)
	$(LATEX) main
	$(BIBTEX) main
	$(LATEX) main
	$(LATEX) main
	cp main.pdf $(PDF)

clean:
	rm -f main.aux main.bbl main.blg main.log main.out main.toc main.pdf

distclean: clean
	rm -f $(PDF)
