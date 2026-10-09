
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

# Paradigm schematic
pdf("paper/figs/paradigm.pdf", width=8, height=3.2)
par(mar=c(1,1,2,1))
plot(NA, xlim=c(0,10), ylim=c(0,3), axes=FALSE, xlab="", ylab="",
     main="Paradigm (schematic)")
rect(0.3,1.2,2.2,2.2, border="#0072B2", lwd=2)
text(1.25,1.7,"Round-0\nconstitution", cex=0.9)
arrows(2.3,1.7,3.5,1.7, lwd=2)
rect(3.5,1.2,5.5,2.2, border="#E69F00", lwd=2)
text(4.5,1.7,"Stateless\nrevision", cex=0.9)
arrows(5.6,1.7,6.8,1.7, lwd=2)
rect(6.8,1.2,9.5,2.2, border="#009E73", lwd=2)
text(8.15,1.7,"Fate coding\n+ battery", cex=0.9)
text(5,0.6,"FORCED · 4 conditions · matched COR/AGENT/SELF", cex=0.85)
dev.off()
cat("figs ok\n")
