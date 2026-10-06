# Shared helpers for confirmatory analysis (prereg §6).

suppressPackageStartupMessages({
  library(lme4)
  library(jsonlite)
})

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (length(a) == 1 && is.na(a))) b else a

holm_adjust <- function(p) {
  n <- length(p)
  o <- order(p)
  adj <- numeric(n)
  prev <- 0
  for (rank in seq_along(o)) {
    idx <- o[rank]
    val <- min(1, p[idx] * (n - rank + 1))
    val <- max(val, prev)
    adj[idx] <- val
    prev <- val
  }
  adj
}

wald_one_sided <- function(est, se, alternative = c("greater", "less")) {
  alternative <- match.arg(alternative)
  if (!is.finite(est) || !is.finite(se) || se <= 0) {
    return(list(z = NA_real_, p = 1))
  }
  z <- est / se
  p <- if (alternative == "greater") 1 - pnorm(z) else pnorm(z)
  list(z = as.numeric(z), p = as.numeric(p))
}

fit_cloglog_glmm <- function(data, formula, fallback_log = character()) {
  ctrl <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))
  used <- "glmm_full"
  fit <- tryCatch(
    glmer(
      formula, data = data, family = binomial(link = "cloglog"),
      control = ctrl, nAGQ = 0
    ),
    error = function(e) e
  )
  if (inherits(fit, "error") || isSingular(fit, tol = 1e-4)) {
    used <- "glmm_drop_item"
    f2 <- update(formula, . ~ . - (1 | item_id))
    fit <- tryCatch(
      glmer(f2, data = data, family = binomial(link = "cloglog"), control = ctrl, nAGQ = 0),
      error = function(e) e
    )
  }
  if (inherits(fit, "error") || (!inherits(fit, "error") && isSingular(fit, tol = 1e-4))) {
    used <- "glmm_drop_item_chain"
    f3 <- update(formula, . ~ . - (1 | item_id) - (1 | chain))
    # chain may already be absent
    f3 <- as.formula(paste("event ~", paste(attr(terms(f3), "term.labels"), collapse = " + ")))
    if (!inherits(fit, "error")) {
      f3 <- update(formula, . ~ . - (1 | item_id) - (1 | chain))
    }
    fit <- tryCatch(
      glmer(
        event ~ COR + log_round + override + testlikeness + form + (1 | config),
        data = data,
        family = binomial(link = "cloglog"),
        control = ctrl,
        nAGQ = 0
      ),
      error = function(e) e
    )
  }
  if (inherits(fit, "error") || (!inherits(fit, "error") && isSingular(fit, tol = 1e-4))) {
    used <- "gee"
    if (!requireNamespace("geepack", quietly = TRUE)) {
      return(list(fit = NULL, method = used, error = "geepack missing", fallback_log = c(fallback_log, used)))
    }
    fit <- tryCatch(
      geepack::geeglm(
        event ~ COR + log_round + override + testlikeness + form,
        id = interaction(data$config, data$chain, drop = TRUE),
        data = data,
        family = binomial(link = "cloglog"),
        corstr = "exchangeable"
      ),
      error = function(e) e
    )
  }
  list(fit = fit, method = used, fallback_log = c(fallback_log, used))
}

exact_conditional_h1 <- function(data) {
  ev <- data[data$event == 1, , drop = FALSE]
  n_tot <- nrow(ev)
  n_cor <- sum(ev$COR == 1)
  share <- mean(data$COR == 1)
  if (n_tot == 0) {
    return(list(
      n_cor_events = 0L, n_total_events = 0L, cor_at_risk_share = share,
      p_value = 1, estimate = NA_real_, method = "exact_conditional_binomial"
    ))
  }
  p <- binom.test(n_cor, n_tot, p = share, alternative = "greater")$p.value
  list(
    n_cor_events = as.integer(n_cor),
    n_total_events = as.integer(n_tot),
    cor_at_risk_share = share,
    p_value = as.numeric(p),
    estimate = n_cor / n_tot,
    method = "exact_conditional_binomial"
  )
}

tost_hr <- function(log_hr, se, lower = 0.8, upper = 1.25, alpha = 0.05) {
  if (!is.finite(log_hr) || !is.finite(se) || se <= 0) {
    return(list(equivalent = FALSE, label = "inconclusive", p_tost = 1, p_halt_lt_1 = 1))
  }
  p_lo <- 1 - pnorm((log_hr - log(lower)) / se)
  p_hi <- 1 - pnorm((log(upper) - log_hr) / se)
  p_tost <- max(p_lo, p_hi)
  p_halt <- 1 - pnorm((0 - log_hr) / se)
  equivalent <- isTRUE(p_tost < alpha)
  label <- if (equivalent) {
    "selective erosion absent at the scale we can detect"
  } else if (isTRUE(p_halt < alpha)) {
    "evidence for H-alt"
  } else {
    "inconclusive"
  }
  list(
    equivalent = equivalent, label = label,
    p_lower = p_lo, p_upper = p_hi, p_tost = p_tost, p_halt_lt_1 = p_halt
  )
}

coef_row <- function(fit, name) {
  if (inherits(fit, "geeglm")) {
    sm <- summary(fit)$coefficients
    if (!name %in% rownames(sm)) return(NULL)
    list(est = sm[name, "Estimate"], se = sm[name, "Std.err"])
  } else {
    sm <- summary(fit)$coefficients
    if (!name %in% rownames(sm)) return(NULL)
    list(est = sm[name, "Estimate"], se = sm[name, "Std. Error"])
  }
}
