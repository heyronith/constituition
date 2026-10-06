#!/usr/bin/env Rscript
# Entry point: confirmatory H1–H3 + multiplicity + TOST + reliability + sensitivities.
# Usage:
#   Rscript analysis/confirmatory/run_confirmatory.R \
#     --hazard path/to/hazard.csv --battery path/to/battery.csv \
#     --out results/confirmatory.json

suppressPackageStartupMessages({
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

get_arg <- function(flag, default = NULL) {
  i <- match(flag, args)
  if (is.na(i)) return(default)
  args[i + 1]
}

hazard_path <- get_arg("--hazard")
battery_path <- get_arg("--battery")
out_path <- get_arg("--out", "results/confirmatory.json")
md_path <- get_arg("--md", "results/confirmatory_table.md")

if (is.null(hazard_path) || !file.exists(hazard_path)) {
  stop("Need --hazard CSV")
}

root <- normalizePath(file.path(dirname(hazard_path), ".."), mustWork = FALSE)
# Prefer repo root cwd
if (file.exists("analysis/confirmatory/h1.R")) {
  # ok
} else if (file.exists(file.path("..", "analysis", "confirmatory", "h1.R"))) {
  setwd("..")
}

source("analysis/confirmatory/h1.R")
source("analysis/confirmatory/h2.R")
source("analysis/confirmatory/h3.R")
source("analysis/confirmatory/reliability.R")
source("analysis/confirmatory/sensitivity.R")

hazard <- read.csv(hazard_path, stringsAsFactors = FALSE)
battery <- NULL
if (!is.null(battery_path) && file.exists(battery_path)) {
  battery <- read.csv(battery_path, stringsAsFactors = FALSE)
}

h1 <- run_h1(hazard)
h2 <- run_h2(hazard)
h3 <- if (!is.null(battery)) run_h3(battery) else list(hypothesis = "H3", p_raw = NA, method = "skipped_no_battery")

# §6.4 Holm across families. H2 family p = max(Bonferroni-adjusted H2a/H2b) as family gate,
# and we also report each contrast with Bonferroni then Holm across families.
p_h1 <- h1$p_raw %||% 1
p_h2a <- h2$H2a$p_family %||% (min(1, (h2$H2a$p_raw %||% 1) * 2))
p_h2b <- h2$H2b$p_family %||% (min(1, (h2$H2b$p_raw %||% 1) * 2))
p_h2_family <- max(p_h2a, p_h2b) # conservative family representative for Holm
p_h3 <- h3$p_raw %||% 1

# Holm on three family p-values
fam_p <- c(H1 = p_h1, H2 = p_h2_family, H3 = p_h3)
fam_holm <- holm_adjust(unname(fam_p))
names(fam_holm) <- names(fam_p)

# Map Holm family adjustment back: contrasts keep Bonferroni; then scale by family Holm ratio
h1$p_holm <- fam_holm[["H1"]]
h2$H2a$p_holm <- min(1, p_h2a * (fam_holm[["H2"]] / max(p_h2_family, .Machine$double.eps)))
h2$H2b$p_holm <- min(1, p_h2b * (fam_holm[["H2"]] / max(p_h2_family, .Machine$double.eps)))
# Cleaner: report family Holm on H2 family p; contrast-level = max(bonferroni, family_holm) style
h2$H2a$p_holm <- max(p_h2a, fam_holm[["H2"]])
h2$H2b$p_holm <- max(p_h2b, fam_holm[["H2"]])
h3$p_holm <- fam_holm[["H3"]]

# §6.5 TOST if H1 not rejected at Holm
tost <- NULL
if (!isTRUE(h1$p_holm < 0.05)) {
  if (is.finite(h1$log_hr %||% NA) && is.finite(h1$se %||% NA)) {
    tost <- tost_hr(h1$log_hr, h1$se)
  } else {
    tost <- list(equivalent = FALSE, label = "inconclusive", note = "no_log_hr_for_tost")
  }
}

rel <- run_reliability(hazard)
robust <- NULL
if (isTRUE(rel$caveat)) {
  robust <- run_reliability_robustness(hazard)
}

sens <- run_sensitivities(hazard)

result <- list(
  prereg = "docs/PREREGISTRATION.md",
  hypotheses = list(H1 = h1, H2 = h2, H3 = h3),
  multiplicity = list(family_p = as.list(fam_p), family_holm = as.list(fam_holm)),
  tost = tost,
  reliability = rel,
  reliability_robustness = robust,
  sensitivities = sens
)

dir.create(dirname(out_path), showWarnings = FALSE, recursive = TRUE)
write_json(result, out_path, auto_unbox = TRUE, pretty = TRUE, digits = 8, null = "null", na = "null")

# Markdown table
lines <- c(
  "| Hypothesis | Estimate | 95% CI | raw p | Holm p | method |",
  "|---|---:|---|---:|---:|---|"
)
fmt_ci <- function(lo, hi) {
  if (!is.finite(lo %||% NA) || !is.finite(hi %||% NA)) return("—")
  sprintf("[%.3f, %.3f]", lo, hi)
}
est_h1 <- if (is.finite(h1$hr %||% NA)) sprintf("HR=%.3f", h1$hr) else (h1$estimate %||% "—")
lines <- c(lines, sprintf(
  "| H1 | %s | %s | %.4g | %.4g | %s |",
  est_h1, fmt_ci(h1$ci_low, h1$ci_high), h1$p_raw %||% NA, h1$p_holm %||% NA, h1$method %||% ""
))
for (nm in c("H2a", "H2b")) {
  hh <- h2[[nm]]
  lines <- c(lines, sprintf(
    "| %s | gap=%.3f | %s | %.4g | %.4g | %s |",
    nm, hh$log_hr_gap %||% (hh$estimate %||% NA), fmt_ci(hh$ci_low, hh$ci_high),
    hh$p_raw %||% NA, hh$p_holm %||% NA, hh$method %||% ""
  ))
}
lines <- c(lines, sprintf(
  "| H3 | Δβ=%.3f | %s | %.4g | %.4g | %s |",
  h3$estimate %||% NA, fmt_ci(h3$ci_low, h3$ci_high), h3$p_raw %||% NA, h3$p_holm %||% NA, h3$method %||% ""
))
writeLines(lines, md_path)
cat("Wrote", out_path, "and", md_path, "\n")
