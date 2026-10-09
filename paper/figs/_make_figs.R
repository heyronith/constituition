
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

# Forest EXPLORATORY
fo <- read.csv("results/figs/forest_h4.csv", stringsAsFactors=FALSE)
pdf("paper/figs/forest_h4.pdf", width=7, height=5)
par(mar=c(4,10,3,1))
ord <- order(fo$hr); fo <- fo[ord,]
y <- seq_len(nrow(fo))
plot(fo$hr, y, pch=16, xlim=range(c(fo$ci_low, fo$ci_high, 1), na.rm=TRUE),
     ylim=c(0.5,nrow(fo)+0.5), xlab="Crude HR (EXPLORATORY)", ylab="", yaxt="n",
     main="EXPLORATORY: per-config HR")
axis(2, at=y, labels=fo$config, las=1, cex.axis=0.8)
segments(fo$ci_low, y, fo$ci_high, y, lwd=2, col="#0072B2")
abline(v=1, lty=3)
dev.off()

# Positive controls vs swaps (from battery)
# Written by Python companion CSV if present
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

# Paradigm schematic — two panels (Wong CB-safe), single-column width
W <- list(blue="#0072B2", orange="#E69F00", green="#009E73",
          sky="#56B4E9", verm="#D55E00", purple="#CC79A7", black="#000000")
box <- function(x0,y0,x1,y1, col, fill=NA, lwd=1.6) {
  rect(x0,y0,x1,y1, border=col, col=fill, lwd=lwd)
}
arr <- function(x0,y0,x1,y1, col=W$black) {
  arrows(x0,y0,x1,y1, length=0.08, lwd=1.4, col=col)
}

pdf("paper/figs/paradigm.pdf", width=6.5, height=6.8)
par(mfrow=c(2,1), mar=c(0.6,0.6,1.6,0.6))

## (a) Chain loop
plot(NA, xlim=c(0,10), ylim=c(0,6.2), axes=FALSE, xlab="", ylab="",
     main="(a) Chain loop (stateless; t = 1...20)")
box(0.2, 3.6, 2.4, 5.4, W$blue, "#E8F4FA")
text(1.3, 4.7, expression(C[t]), cex=1.15, font=2, col=W$blue)
text(1.3, 4.15, "35 principles\nopaque IDs", cex=0.72)
box(3.0, 3.4, 6.2, 5.6, W$orange, "#FFF6E5")
text(4.6, 5.15, "Model (stateless)", cex=0.85, font=2, col=W$orange)
text(4.6, 4.55, "sees only C_t +\ncondition instruction", cex=0.7)
text(4.6, 3.7, "SELF / OTHER \"Pellam\"\nPARAPHRASE / NEUTRAL", cex=0.62)
arr(2.45, 4.5, 2.95, 4.5, W$blue)
box(6.7, 3.8, 9.0, 5.2, W$green, "#E8F7F1")
text(7.85, 4.7, "Exactly one\nchange", cex=0.8, font=2, col=W$green)
text(7.85, 4.1, "revise / merge / delete", cex=0.65)
arr(6.25, 4.5, 6.65, 4.5, W$orange)
box(7.0, 1.6, 9.3, 3.1, W$blue, "#E8F4FA")
text(8.15, 2.55, expression(C[t+1]), cex=1.1, font=2, col=W$blue)
text(8.15, 2.0, "next round input", cex=0.68)
arr(7.85, 3.75, 8.15, 3.15, W$green)
arr(7.0, 2.35, 1.3, 2.35, W$sky)
arr(1.3, 2.35, 1.3, 3.55, W$sky)
text(4.0, 2.7, "repeat (Markov)", cex=0.7, col=W$sky)
box(0.3, 0.15, 6.0, 1.45, W$verm, "#FDEEE8")
text(3.15, 1.15, "Side branch (each change)", cex=0.75, font=2, col=W$verm)
text(3.15, 0.55, expression(paste("GPT-5.4 fate (+25% MiMo) ", rightarrow, " erosion event")), cex=0.62)
text(3.15, 0.28, expression(paste(rightarrow, " discrete-time survival: COR vs AGENT vs SELF")), cex=0.62)
arr(7.3, 3.9, 5.5, 1.5, W$verm)

## (b) Behaviour test
plot(NA, xlim=c(0,10), ylim=c(0,5.5), axes=FALSE, xlab="", ylab="",
     main="(b) Behaviour test (chains 0-4)")
box(0.2, 3.2, 2.6, 5.0, W$blue, "#E8F4FA")
text(1.4, 4.4, "Build installs", cex=0.8, font=2, col=W$blue)
text(1.4, 3.7, "R0, R20,\nCOR-swap, AGENT-swap\n(+ COR_INV / AGENT_INV)", cex=0.62)
arr(2.65, 4.1, 3.15, 4.1)
box(3.2, 3.2, 5.8, 5.0, W$orange, "#FFF6E5")
text(4.5, 4.4, "System prompt", cex=0.8, font=2, col=W$orange)
text(4.5, 3.7, "install constitution\nas system message", cex=0.68)
arr(5.85, 4.1, 6.35, 4.1)
box(6.4, 3.0, 9.7, 5.2, W$green, "#E8F7F1")
text(8.05, 4.55, "B1 oversight scenarios", cex=0.8, font=2, col=W$green)
text(8.05, 3.7, "authorized: accept?\nunauthorized: refuse?", cex=0.68)
arr(8.05, 2.95, 8.05, 2.35)
box(6.2, 0.6, 9.7, 2.3, W$purple, "#F7EAF3")
text(7.95, 1.7, "Outcomes", cex=0.8, font=2, col=W$purple)
text(7.95, 1.1, "AAR  /  URR", cex=0.9)
text(3.2, 1.5, "none = no installed constitution\n(positive-control path uses INV)", cex=0.65, col=W$black)

dev.off()
cat("figs ok\n")
