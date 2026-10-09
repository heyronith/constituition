
cols <- c(COR="#E69F00", AGENT="#56B4E9", SELF="#009E73")
# KM
km <- read.csv("results/figs/km_cor_agent_self.csv", stringsAsFactors=FALSE)
conds <- c("SELF_REFLECT","OTHER_REFLECT","PARAPHRASE","NEUTRAL_EDIT")
pdf("paper/figs/km_curves.pdf", width=8, height=6.5)
par(mfrow=c(2,2), mar=c(4,4,3,1))
ymax <- max(km$cum_prop, na.rm=TRUE)*1.05
for (cond in conds) {
  plot(NA, xlim=c(1,20), ylim=c(0,ymax), xlab="Round t", ylab="P(eroded by t)",
       main=gsub("_"," ",cond), las=1)
  for (cat in c("COR","AGENT","SELF")) {
    sub <- km[km$condition==cond & km$category==cat,]; sub <- sub[order(sub$round),]
    lines(c(sub$round[1], sub$round), c(0, sub$cum_prop), type="s", col=cols[[cat]], lwd=2)
  }
  legend("topleft", legend=c("COR","AGENT","SELF"), col=cols[c("COR","AGENT","SELF")], lwd=2, bty="n", cex=0.8)
}
dev.off()

# LOIO
lo <- read.csv("results/figs/loio_hr.csv", stringsAsFactors=FALSE)
pdf("paper/figs/loio.pdf", width=8, height=4.5)
par(mar=c(7,4,3,1))
barplot(lo$crude_hr, names.arg=lo$item, las=2, col=ifelse(lo$item=="AGENT1","#D55E00","#0072B2"),
        ylab="Crude HR (COR/AGENT)", main="SECONDARY: leave-one-item-out")
abline(h=1, lty=3); abline(h=0.495, lty=2, col="#CC79A7")
dev.off()

# Decomposition
dec <- read.csv("results/figs/decomposition.csv", stringsAsFactors=FALSE)
pdf("paper/figs/decomposition.pdf", width=8, height=6.5)
par(mfrow=c(2,2), mar=c(4,4,3,1))
for (cond in unique(dec$condition)) {
  sub <- dec[dec$condition==cond & dec$category %in% c("COR","AGENT","SELF"),]
  plot(sub$p_touch, sub$p_erosion_given_touch, pch=16, col=cols[sub$category],
       xlab="P(touch)", ylab="P(erosion|touch)", main=gsub("_"," ",cond),
       xlim=c(0,max(dec$p_touch,na.rm=TRUE)*1.1), ylim=c(0,max(dec$p_erosion_given_touch,na.rm=TRUE)*1.1))
  text(sub$p_touch, sub$p_erosion_given_touch, sub$category, pos=4, cex=0.8)
}
dev.off()

# Forest EXPLORATORY — exact conditional RR CIs, log x-axis, fixed row order
fo <- read.csv("paper/figs/forest_h4.csv", stringsAsFactors=FALSE)
# CSV order = CONFIG_ORDER; draw first row at top
n <- nrow(fo)
y <- rev(seq_len(n))
finite_hi <- fo$ci_high[is.finite(fo$ci_high) & !is.na(fo$ci_high)]
finite_lo <- fo$ci_low[is.finite(fo$ci_low) & !is.na(fo$ci_low) & fo$ci_low > 0]
xmax <- max(c(finite_hi, 1.5), na.rm=TRUE) * 1.15
xmin <- min(c(finite_lo[finite_lo > 0], 0.02), na.rm=TRUE)
if (!is.finite(xmin) || xmin <= 0) xmin <- 0.02
pdf("paper/figs/forest_h4.pdf", width=7.2, height=4.8)
par(mar=c(4.2, 14.5, 2.2, 1.2))
plot(NA, xlim=c(xmin, xmax), ylim=c(0.5, n+0.5), log="x",
     xlab="Crude HR (EXPLORATORY; log scale)", ylab="", yaxt="n",
     main="EXPLORATORY: per-config HR")
abline(v=1, lty=3, col="#666666")
axis(2, at=y, labels=fo$label, las=1, cex.axis=0.72)
for (i in seq_len(n)) {
  yi <- y[i]
  lo <- fo$ci_low[i]; hi <- fo$ci_high[i]; hr <- fo$hr[i]
  if (isTRUE(fo$zero_cor[i] == 1)) {
    # Upper-bound arrow only (0 COR events)
    arrows(xmin, yi, hi, yi, length=0.08, lwd=2, col="#0072B2", code=2)
    text(hi, yi, "  0 COR events", pos=4, cex=0.65, col="#D55E00")
  } else {
    segments(max(lo, xmin), yi, hi, yi, lwd=2, col="#0072B2")
    points(hr, yi, pch=16, cex=1.1, col="#0072B2")
  }
}
dev.off()

# Positive controls vs swaps (from battery)
if (file.exists("paper/figs/pos_controls.csv")) {
  pc <- read.csv("paper/figs/pos_controls.csv", stringsAsFactors=FALSE)
  pdf("paper/figs/pos_controls.pdf", width=8, height=5)
  configs <- unique(pc$config)
  x <- seq_along(configs)
  plot(NA, xlim=c(0.5,length(configs)+0.5), ylim=c(0,1), xaxt="n",
       ylab="AAR", xlab="", main="Positive controls vs swaps (AUTH)")
  axis(1, at=x, labels=configs, las=2, cex.axis=0.7)
  for (i in x) {
    sub <- pc[pc$config==configs[i],]
    points(rep(i-0.15, sum(sub$constitution=="R0")), sub$AAR[sub$constitution=="R0"], pch=16, col="#009E73")
    points(rep(i, sum(sub$constitution=="COR_INV")), sub$AAR[sub$constitution=="COR_INV"], pch=17, col="#D55E00")
    points(rep(i+0.15, sum(sub$constitution=="COR_swap")), sub$AAR[sub$constitution=="COR_swap"], pch=15, col="#56B4E9")
  }
  legend("bottomleft", legend=c("R0","COR_INV","COR_swap"), pch=c(16,17,15),
         col=c("#009E73","#D55E00","#56B4E9"), bty="n")
  dev.off()
}

# Paradigm schematic — compact two panels, cairo Unicode arrows, tight margins
W <- list(blue="#0072B2", orange="#E69F00", green="#009E73",
          sky="#56B4E9", verm="#D55E00", purple="#CC79A7", black="#000000")
box <- function(x0,y0,x1,y1, col, fill=NA, lwd=1.4) {
  rect(x0,y0,x1,y1, border=col, col=fill, lwd=lwd)
}
arr <- function(x0,y0,x1,y1, col=W$black) {
  arrows(x0,y0,x1,y1, length=0.07, lwd=1.3, col=col)
}
# Drawn arrows + composed subscripts (no plotmath / Unicode dependency).
# ~0.55 of a text page at \textwidth (≈6.3in wide, ≤5in tall)
pdf("paper/figs/paradigm.pdf", width=6.3, height=4.6)
par(mfrow=c(2,1), mar=c(0.2,0.3,1.05,0.3), oma=c(0,0,0,0))
# Draw C with a lowered subscript string (t or t+1)
draw_C <- function(x, y, sub="t", cex=1.1, col=W$blue, font=2) {
  text(x, y, "C", cex=cex, font=font, col=col, adj=c(1, 0.5))
  text(x + 0.02, y - 0.14*cex, sub, cex=0.55*cex, font=font, col=col, adj=c(0, 0.5))
}

## (a) Chain loop
plot(NA, xlim=c(0,10), ylim=c(0,5.5), axes=FALSE, xlab="", ylab="", xaxs="i", yaxs="i",
     main="(a) Chain loop (stateless; t = 1...20)")
box(0.25, 3.3, 2.35, 5.1, W$blue, "#E8F4FA")
draw_C(1.35, 4.5, "t", cex=1.2)
text(1.3, 3.8, "35 principles\nopaque IDs", cex=0.62)
box(2.9, 3.15, 6.15, 5.25, W$orange, "#FFF6E5")
text(4.525, 4.9, "Model (stateless)", cex=0.78, font=2, col=W$orange)
text(4.15, 4.4, "sees only", cex=0.62, adj=c(1,0.5))
draw_C(4.35, 4.4, "t", cex=0.7, col=W$black, font=1)
text(4.55, 4.4, "+", cex=0.62, adj=c(0,0.5))
text(4.525, 4.0, "condition instruction", cex=0.62)
text(4.525, 3.45, "SELF / OTHER \"Pellam\"\nPARAPHRASE / NEUTRAL", cex=0.55)
arr(2.4, 4.2, 2.85, 4.2, W$blue)
box(6.55, 3.5, 8.85, 4.9, W$green, "#E8F7F1")
text(7.7, 4.45, "Exactly one\nchange", cex=0.72, font=2, col=W$green)
text(7.7, 3.8, "revise / merge / delete", cex=0.55)
arr(6.2, 4.2, 6.5, 4.2, W$orange)
box(6.9, 1.5, 9.15, 2.9, W$blue, "#E8F4FA")
draw_C(8.15, 2.45, "t+1", cex=1.05)
text(8.025, 1.85, "next round input", cex=0.58)
arr(7.7, 3.45, 8.0, 2.95, W$green)
arr(6.9, 2.2, 1.3, 2.2, W$sky)
arr(1.3, 2.2, 1.3, 3.25, W$sky)
text(4.0, 2.5, "repeat (Markov)", cex=0.6, col=W$sky)
box(0.25, 0.12, 6.2, 1.3, W$verm, "#FDEEE8")
text(3.225, 1.05, "Side branch (each change)", cex=0.68, font=2, col=W$verm)
text(0.4, 0.68, "GPT-5.4 fate (+25% MiMo)", cex=0.55, adj=c(0,0.5))
arrows(3.35, 0.68, 3.65, 0.68, length=0.06, lwd=1.2, col=W$black)
text(3.75, 0.68, "erosion event", cex=0.55, adj=c(0,0.5))
arrows(0.4, 0.35, 0.7, 0.35, length=0.06, lwd=1.2, col=W$black)
text(0.8, 0.35, "discrete-time survival: COR vs AGENT vs SELF", cex=0.55, adj=c(0,0.5))
arr(7.1, 3.55, 5.6, 1.35, W$verm)

## (b) Behaviour test
plot(NA, xlim=c(0,10), ylim=c(0,4.6), axes=FALSE, xlab="", ylab="", xaxs="i", yaxs="i",
     main="(b) Behaviour test (chains 0-4)")
box(0.2, 2.35, 2.85, 4.25, W$blue, "#E8F4FA")
text(1.525, 3.85, "Build installs", cex=0.75, font=2, col=W$blue)
text(1.525, 3.05, "R0, R20, COR-swap,\nAGENT-swap, none\n(+ COR_INV / AGENT_INV)", cex=0.55)
arr(2.9, 3.3, 3.35, 3.3)
box(3.4, 2.45, 5.9, 4.15, W$orange, "#FFF6E5")
text(4.65, 3.7, "System prompt", cex=0.75, font=2, col=W$orange)
text(4.65, 3.05, "install constitution\nas system message", cex=0.58)
arr(5.95, 3.3, 6.4, 3.3)
box(6.45, 2.35, 9.7, 4.25, W$green, "#E8F7F1")
text(8.075, 3.7, "B1 oversight scenarios", cex=0.72, font=2, col=W$green)
text(8.075, 2.95, "authorized: accept?\nunauthorized: refuse?", cex=0.58)
arr(8.075, 2.3, 8.075, 1.85)
box(6.45, 0.35, 9.7, 1.75, W$purple, "#F7EAF3")
text(8.075, 1.3, "Outcomes", cex=0.75, font=2, col=W$purple)
text(8.075, 0.75, "AAR  /  URR", cex=0.85)

dev.off()
cat("figs ok\n")
