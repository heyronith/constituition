# SECONDARY/EXPLORATORY figures for Phase 7E-C

loio <- read.csv("results/figs/loio_hr.csv", stringsAsFactors = FALSE)
png("results/figs/loio_hr.png", width = 1200, height = 700, res = 140)
par(mar = c(7, 4, 3, 1))
cols <- ifelse(loio$item == "AGENT1", "#c0392b", "#34495e")
bp <- barplot(loio$crude_hr, names.arg = loio$item, col = cols, las = 2,
              ylab = "Crude HR (COR/AGENT)",
              main = "SECONDARY: leave-one-item-out crude HR")
abline(h = 0.495, col = "#2980b9", lty = 2, lwd = 2)
abline(h = 1, col = "gray40", lty = 3)
legend("topright", legend = c("AGENT1", "other items", "confirmatory HR"),
       fill = c("#c0392b", "#34495e", NA), border = c("black", "black", NA),
       lty = c(NA, NA, 2), col = c(NA, NA, "#2980b9"), lwd = c(NA, NA, 2), bty = "n")
dev.off()

forest <- read.csv("results/figs/forest_h4.csv", stringsAsFactors = FALSE)
png("results/figs/forest_h4.png", width = 1100, height = 700, res = 140)
par(mar = c(4, 10, 3, 1))
ord <- order(forest$hr)
forest <- forest[ord, ]
y <- seq_len(nrow(forest))
plot(forest$hr, y, pch = 16, xlim = range(c(forest$ci_low, forest$ci_high, 1), na.rm = TRUE),
     ylim = c(0.5, nrow(forest) + 0.5), xlab = "Crude HR (COR/AGENT) with chain-bootstrap CI",
     ylab = "", yaxt = "n", main = "EXPLORATORY H4: per-config crude HR")
axis(2, at = y, labels = forest$config, las = 1, cex.axis = 0.85)
segments(forest$ci_low, y, forest$ci_high, y, lwd = 2)
abline(v = 1, lty = 3, col = "gray40")
abline(v = 0.495, lty = 2, col = "#2980b9")
dev.off()

dec <- read.csv("results/figs/decomposition.csv", stringsAsFactors = FALSE)
png("results/figs/decomposition.png", width = 1200, height = 900, res = 140)
conds <- unique(dec$condition)
cats <- c("COR", "AGENT", "SELF")
cols <- c(COR = "#c0392b", AGENT = "#2980b9", SELF = "#27ae60")
par(mfrow = c(2, 2), mar = c(4, 4, 3, 1))
for (cond in conds) {
  sub <- dec[dec$condition == cond, ]
  plot(NA, xlim = c(0, max(sub$p_touch, na.rm = TRUE) * 1.15),
       ylim = c(0, max(sub$p_erosion_given_touch, na.rm = TRUE) * 1.15),
       xlab = "P(touch)", ylab = "P(erosion | touch)",
       main = gsub("_", " ", cond))
  for (i in seq_len(nrow(sub))) {
    if (sub$category[i] %in% cats) {
      points(sub$p_touch[i], sub$p_erosion_given_touch[i], pch = 16, cex = 1.6,
             col = cols[[sub$category[i]]])
      text(sub$p_touch[i], sub$p_erosion_given_touch[i], sub$category[i], pos = 4, cex = 0.8)
    }
  }
}
dev.off()

cat("Wrote loio_hr.png forest_h4.png decomposition.png\n")
