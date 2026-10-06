# §6.2 H2a/H2b — COR×condition contrasts.

source(file.path("analysis", "confirmatory", "common.R"))

.run_h2_contrast <- function(d, target_condition, label) {
  # Restrict to SELF vs target; code SELF as reference for interaction COR:cond
  d2 <- d[d$condition %in% c("SELF_REFLECT", target_condition), , drop = FALSE]
  d2$cond <- factor(d2$condition, levels = c("SELF_REFLECT", target_condition))
  d2$event <- as.integer(d2$event)
  d2$COR <- as.integer(d2$category == "COR")
  d2$log_round <- log(pmax(as.numeric(d2$round), 1))
  d2$form <- factor(d2$form)
  d2$config <- factor(d2$config)
  d2$chain <- factor(paste(d2$config, d2$chain, sep = "::"))
  d2$item_id <- factor(d2$item_id)
  d2$override <- as.numeric(d2$override)
  d2$testlikeness <- as.numeric(d2$testlikeness)

  n_events <- sum(d2$event == 1, na.rm = TRUE)
  fallback_log <- character()
  if (n_events < 20) {
    # Fallback: compare exact enrichment in SELF vs target (difference of exact p not used);
    # use score-style: COR event share difference. Report exact on SELF only as weak fallback.
    fallback_log <- c(fallback_log, "exact_lt_20_events_h2")
    self <- exact_conditional_h1(d2[d2$condition == "SELF_REFLECT", , drop = FALSE])
    oth <- exact_conditional_h1(d2[d2$condition == target_condition, , drop = FALSE])
    # One-sided: SELF COR enrichment > OTHER enrichment (difference of proportions of events)
    # Use normal approx on log odds of COR|event if both have events.
    p_raw <- 1
    est <- NA_real_
    if (self$n_total_events > 0 && oth$n_total_events > 0) {
      p1 <- self$estimate
      p0 <- oth$estimate
      se <- sqrt(p1 * (1 - p1) / self$n_total_events + p0 * (1 - p0) / oth$n_total_events)
      est <- p1 - p0
      if (is.finite(se) && se > 0) {
        z <- est / se
        p_raw <- 1 - pnorm(z)
      }
    }
    return(list(
      hypothesis = label, method = "exact_event_share_diff", fallback_log = fallback_log,
      n_rows = nrow(d2), n_events = n_events, estimate = est, p_raw = p_raw,
      alternative = "greater"
    ))
  }

  # Dedicated interaction fits only (do not reuse H1 fit_cloglog_glmm — its deep
  # fallback hard-codes a main-effects formula and would drop COR×cond).
  ctrl <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))
  formulas <- list(
    event ~ COR * cond + log_round + override + testlikeness + form + (1 | config) + (1 | chain) + (1 | item_id),
    event ~ COR * cond + log_round + override + testlikeness + form + (1 | config) + (1 | chain),
    event ~ COR * cond + log_round + override + testlikeness + form + (1 | config)
  )
  methods <- c("glmm_full", "glmm_drop_item", "glmm_drop_item_chain")
  fit <- NULL
  method <- "failed"
  for (i in seq_along(formulas)) {
    method <- methods[i]
    fallback_log <- c(fallback_log, method)
    fit <- tryCatch(
      glmer(
        formulas[[i]], data = d2, family = binomial(link = "cloglog"),
        control = ctrl, nAGQ = 0
      ),
      error = function(e) e
    )
    if (!inherits(fit, "error") && !isSingular(fit, tol = 1e-4)) break
  }
  if (inherits(fit, "error") || is.null(fit) || isSingular(fit, tol = 1e-4)) {
    if (requireNamespace("geepack", quietly = TRUE)) {
      method <- "gee"
      fallback_log <- c(fallback_log, method)
      fit <- tryCatch(
        geepack::geeglm(
          event ~ COR * cond + log_round + override + testlikeness + form,
          id = interaction(d2$config, d2$chain, drop = TRUE),
          data = d2, family = binomial(link = "cloglog"), corstr = "exchangeable"
        ),
        error = function(e) e
      )
    }
  }

  if (inherits(fit, "error") || is.null(fit)) {
    return(list(
      hypothesis = label, method = "failed", fallback_log = fallback_log,
      n_rows = nrow(d2), n_events = n_events, p_raw = 1
    ))
  }

  # Interaction COR:condTARGET = (β_COR|target) - (β_COR|SELF).
  # H2 wants (β_COR|SELF) - (β_COR|target) > 0 ≡ -interaction > 0.
  iname <- paste0("COR:cond", target_condition)
  cr <- coef_row(fit, iname)
  if (is.null(cr)) {
    # try alternate naming
    rn <- rownames(summary(fit)$coefficients)
    hit <- rn[grepl(paste0("COR:cond"), rn)]
    if (length(hit)) cr <- coef_row(fit, hit[1])
  }
  if (is.null(cr)) {
    return(list(
      hypothesis = label, method = method, fallback_log = fallback_log,
      n_rows = nrow(d2), n_events = n_events, p_raw = 1, error = "interaction missing"
    ))
  }
  est <- -cr$est
  se <- cr$se
  w <- wald_one_sided(est, se, "greater")
  list(
    hypothesis = label,
    method = method,
    fallback_log = fallback_log,
    n_rows = nrow(d2),
    n_events = n_events,
    log_hr_gap = est,
    se = se,
    ci_low = est - 1.959964 * se,
    ci_high = est + 1.959964 * se,
    z = w$z,
    p_raw = w$p,
    alternative = "greater"
  )
}

run_h2 <- function(hazard_df, event_col = "event_gpt54") {
  d <- hazard_df
  d <- d[d$protocol == "FORCED" &
           d$condition %in% c("SELF_REFLECT", "OTHER_REFLECT", "NEUTRAL_EDIT") &
           d$category %in% c("COR", "AGENT") & d$at_risk == 1, , drop = FALSE]
  d$event <- as.integer(d[[event_col]])
  h2a <- .run_h2_contrast(d, "OTHER_REFLECT", "H2a")
  h2b <- .run_h2_contrast(d, "NEUTRAL_EDIT", "H2b")
  # Bonferroni within H2 family
  p_bonf <- pmin(1, c(h2a$p_raw, h2b$p_raw) * 2)
  h2a$p_family <- p_bonf[1]
  h2b$p_family <- p_bonf[2]
  list(H2a = h2a, H2b = h2b)
}
