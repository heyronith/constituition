# §6.7 Reliability — binary Krippendorff α + chain bootstrap.

krippendorff_alpha_binary <- function(c1, c2) {
  stopifnot(length(c1) == length(c2))
  pairs_n <- length(c1)
  if (pairs_n == 0) return(NA_real_)
  do <- mean(c1 != c2)
  vals <- c(c1, c2)
  p1 <- mean(vals == 1)
  p0 <- 1 - p1
  de <- 2 * p0 * p1
  if (de == 0) return(if (do == 0) 1 else 0)
  1 - do / de
}

run_reliability <- function(hazard_df, n_boot = 1000L, seed = 20261004L) {
  d <- hazard_df
  # Subsample rows with both judges present
  d <- d[!is.na(d$event_gpt54) & !is.na(d$event_mimo) & d$at_risk == 1, , drop = FALSE]
  if (!nrow(d)) {
    return(list(alpha = NA_real_, ci_low = NA_real_, ci_high = NA_real_,
                n = 0, caveat = TRUE, branch = "no_double_coded_rows"))
  }
  c1 <- as.integer(d$event_gpt54)
  c2 <- as.integer(d$event_mimo)
  alpha <- krippendorff_alpha_binary(c1, c2)
  chains <- unique(as.character(interaction(d$config, d$chain, drop = TRUE)))
  set.seed(seed)
  boots <- numeric(n_boot)
  key <- as.character(interaction(d$config, d$chain, drop = TRUE))
  for (b in seq_len(n_boot)) {
    drawn <- sample(chains, length(chains), replace = TRUE)
    idx <- unlist(lapply(drawn, function(ch) which(key == ch)), use.names = FALSE)
    boots[b] <- krippendorff_alpha_binary(c1[idx], c2[idx])
  }
  ci <- quantile(boots, c(0.025, 0.975), na.rm = TRUE)
  caveat <- isTRUE(alpha < 0.70)
  branch <- if (caveat) "alpha_lt_0.70_robustness" else "alpha_ge_0.70_stand"
  list(
    alpha = alpha,
    ci_low = unname(ci[1]),
    ci_high = unname(ci[2]),
    n = nrow(d),
    caveat = caveat,
    branch = branch
  )
}

run_reliability_robustness <- function(hazard_df) {
  # Re-estimate H1/H2 on subsample under gpt54, mimo, consensus
  source(file.path("analysis", "confirmatory", "h1.R"))
  source(file.path("analysis", "confirmatory", "h2.R"))
  d <- hazard_df[!is.na(hazard_df$event_gpt54) & !is.na(hazard_df$event_mimo), , drop = FALSE]
  cons <- d
  cons$event_consensus <- as.integer(d$event_gpt54 == 1 & d$event_mimo == 1)
  list(
    gpt54 = list(H1 = run_h1(d, "event_gpt54"), H2 = run_h2(d, "event_gpt54")),
    mimo = list(H1 = run_h1(d, "event_mimo"), H2 = run_h2(d, "event_mimo")),
    consensus = {
      cons$event_gpt54 <- cons$event_consensus
      list(H1 = run_h1(cons, "event_gpt54"), H2 = run_h2(cons, "event_gpt54"))
    }
  )
}
