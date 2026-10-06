# §6.1 H1 — COR vs AGENT erosion hazard in FORCED SELF-REFLECT.

source(file.path("analysis", "confirmatory", "common.R"))

run_h1 <- function(hazard_df, event_col = "event_gpt54") {
  d <- hazard_df
  d <- d[d$protocol == "FORCED" & d$condition == "SELF_REFLECT" &
           d$category %in% c("COR", "AGENT") & d$at_risk == 1, , drop = FALSE]
  d$event <- as.integer(d[[event_col]])
  d$COR <- as.integer(d$category == "COR")
  d$log_round <- log(pmax(as.numeric(d$round), 1))
  d$form <- factor(d$form)
  d$config <- factor(d$config)
  d$chain <- factor(paste(d$config, d$chain, sep = "::"))
  d$item_id <- factor(d$item_id)
  d$override <- as.numeric(d$override)
  d$testlikeness <- as.numeric(d$testlikeness)

  n_events <- sum(d$event == 1, na.rm = TRUE)
  fallback_log <- character()

  if (n_events < 20) {
    ex <- exact_conditional_h1(d)
    fallback_log <- c(fallback_log, "exact_lt_20_events")
    return(list(
      hypothesis = "H1",
      method = ex$method,
      fallback_log = fallback_log,
      n_rows = nrow(d),
      n_events = n_events,
      estimate = ex$estimate,
      log_hr = NA_real_,
      hr = NA_real_,
      se = NA_real_,
      ci_low = NA_real_,
      ci_high = NA_real_,
      z = NA_real_,
      p_raw = ex$p_value,
      alternative = "greater",
      exact = ex
    ))
  }

  form <- event ~ COR + log_round + override + testlikeness + form +
    (1 | config) + (1 | chain) + (1 | item_id)
  fitted <- fit_cloglog_glmm(d, form, fallback_log)
  fallback_log <- fitted$fallback_log
  fit <- fitted$fit
  if (inherits(fit, "error") || is.null(fit)) {
    return(list(
      hypothesis = "H1", method = "failed", fallback_log = fallback_log,
      n_rows = nrow(d), n_events = n_events, p_raw = 1, error = as.character(fit)
    ))
  }
  cr <- coef_row(fit, "COR")
  if (is.null(cr)) {
    return(list(
      hypothesis = "H1", method = fitted$method, fallback_log = fallback_log,
      n_rows = nrow(d), n_events = n_events, p_raw = 1, error = "COR coef missing"
    ))
  }
  w <- wald_one_sided(cr$est, cr$se, "greater")
  list(
    hypothesis = "H1",
    method = fitted$method,
    fallback_log = fallback_log,
    n_rows = nrow(d),
    n_events = n_events,
    log_hr = cr$est,
    hr = exp(cr$est),
    se = cr$se,
    ci_low = exp(cr$est - 1.959964 * cr$se),
    ci_high = exp(cr$est + 1.959964 * cr$se),
    z = w$z,
    p_raw = w$p,
    alternative = "greater"
  )
}
