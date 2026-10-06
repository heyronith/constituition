# §6.8 Five preregistered sensitivity analyses.

source(file.path("analysis", "confirmatory", "h1.R"))
source(file.path("analysis", "confirmatory", "h2.R"))

run_sensitivities <- function(hazard_df) {
  out <- list()

  # 1. QUALIFIED_LEGITIMACY as erosion
  d1 <- hazard_df
  if ("fate_gpt54" %in% names(d1)) {
    d1$event_gpt54 <- as.integer(
      d1$event_gpt54 == 1 |
        toupper(as.character(d1$fate_gpt54)) == "QUALIFIED_LEGITIMACY"
    )
  }
  out$qualified_as_erosion <- list(H1 = run_h1(d1), H2 = run_h2(d1))

  # 2. Exclude eval-aware chains
  d2 <- hazard_df
  if ("eval_aware_flag" %in% names(d2)) {
    bad <- unique(interaction(d2$config[d2$eval_aware_flag == 1], d2$chain[d2$eval_aware_flag == 1], drop = TRUE))
    key <- interaction(d2$config, d2$chain, drop = TRUE)
    d2 <- d2[!key %in% bad, , drop = FALSE]
  }
  out$exclude_eval_aware <- list(H1 = run_h1(d2), H2 = run_h2(d2))

  # 3. COR vs SELF
  d3 <- hazard_df
  d3 <- d3[d3$category %in% c("COR", "SELF"), , drop = FALSE]
  # Temporarily rename SELF→AGENT so run_h1/h2 filters work
  d3$category[d3$category == "SELF"] <- "AGENT"
  out$cor_vs_self <- list(H1 = run_h1(d3), H2 = run_h2(d3))

  # 4. Without covariates
  d4 <- hazard_df
  d4$override <- 0
  d4$testlikeness <- 0
  # form still present as factor nuisance; zeroing covariates per prereg "without covariates"
  out$no_covariates <- list(H1 = run_h1(d4), H2 = run_h2(d4))

  # 5. Per-configuration HRs (exploratory H4 view)
  cfgs <- sort(unique(as.character(hazard_df$config)))
  forest <- list()
  for (cfg in cfgs) {
    sub <- hazard_df[hazard_df$config == cfg, , drop = FALSE]
    forest[[cfg]] <- run_h1(sub)
  }
  out$per_config_h1 <- forest
  out
}
