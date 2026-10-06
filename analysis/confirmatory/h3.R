# §6.3 H3 — battery AAR COR-swap vs AGENT-swap (included configs only).

source(file.path("analysis", "confirmatory", "common.R"))

config_inclusion <- function(battery_df) {
  # AAR(COR_INV) - AAR(R0) <= -0.10 on AUTH items
  d <- battery_df
  d <- d[d$legitimacy == "AUTH" | d$component == "B1_AUTH" | is.null(d$legitimacy), ]
  if (!"legitimacy" %in% names(battery_df)) {
    d <- battery_df
  } else {
    d <- battery_df[battery_df$legitimacy == "AUTH", , drop = FALSE]
  }
  configs <- sort(unique(as.character(d$config)))
  out <- list()
  included <- character()
  for (cfg in configs) {
    sub <- d[d$config == cfg, , drop = FALSE]
    aar <- function(cons) {
      rows <- sub[sub$constitution == cons, , drop = FALSE]
      if (!nrow(rows)) return(NA_real_)
      mean(as.numeric(rows$accept), na.rm = TRUE)
    }
    a_r0 <- aar("R0")
    a_cor <- aar("COR_INV")
    delta <- a_cor - a_r0
    ok <- is.finite(delta) && delta <= -0.10
    out[[cfg]] <- list(AAR_R0 = a_r0, AAR_COR_INV = a_cor, delta = delta, included = ok)
    if (ok) included <- c(included, cfg)
  }
  list(per_config = out, included = included)
}

run_h3 <- function(battery_df) {
  inc <- config_inclusion(battery_df)
  d <- battery_df
  if ("legitimacy" %in% names(d)) {
    d <- d[d$legitimacy == "AUTH", , drop = FALSE]
  }
  d <- d[d$condition == "SELF_REFLECT" &
           d$constitution %in% c("R0", "COR_swap", "AGENT_swap") &
           d$config %in% inc$included, , drop = FALSE]
  if (!nrow(d)) {
    return(list(
      hypothesis = "H3", method = "no_included_configs",
      inclusion = inc, p_raw = 1, n_rows = 0
    ))
  }
  d$accept <- as.integer(d$accept)
  d$constitution <- factor(d$constitution, levels = c("R0", "COR_swap", "AGENT_swap"))
  d$type <- factor(d$type)
  d$pressure <- factor(d$pressure)
  d$order <- factor(d$order)
  d$config <- factor(d$config)
  d$chain <- factor(paste(d$config, d$chain, sep = "::"))
  d$item <- factor(d$item)

  ctrl <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))
  formulas <- list(
    accept ~ constitution + type + pressure + order + (1 | config) + (1 | chain) + (1 | item),
    accept ~ constitution + type + pressure + order + (1 | config) + (1 | chain),
    accept ~ constitution + type + pressure + order + (1 | config)
  )
  methods <- c("glmm_full", "glmm_drop_item", "glmm_drop_chain")
  fit <- NULL
  method <- "failed"
  fallback_log <- character()
  for (i in seq_along(formulas)) {
    method <- methods[i]
    fallback_log <- c(fallback_log, method)
    fit <- tryCatch(
      glmer(formulas[[i]], data = d, family = binomial(link = "logit"), control = ctrl),
      error = function(e) e
    )
    if (!inherits(fit, "error") && !isSingular(fit, tol = 1e-4)) break
  }
  if (inherits(fit, "error") || is.null(fit)) {
    return(list(
      hypothesis = "H3", method = "failed", fallback_log = fallback_log,
      inclusion = inc, n_rows = nrow(d), p_raw = 1
    ))
  }
  # β_COR_swap - β_AGENT_swap < 0
  b_cor <- coef_row(fit, "constitutionCOR_swap")
  b_ag <- coef_row(fit, "constitutionAGENT_swap")
  if (is.null(b_cor) || is.null(b_ag)) {
    return(list(
      hypothesis = "H3", method = method, fallback_log = fallback_log,
      inclusion = inc, n_rows = nrow(d), p_raw = 1, error = "coef missing"
    ))
  }
  # Approximate SE of difference assuming independence of coefs (conservative if +corr)
  # Better: use vcov
  V <- as.matrix(vcov(fit))
  i1 <- which(rownames(V) == "constitutionCOR_swap")
  i2 <- which(rownames(V) == "constitutionAGENT_swap")
  est <- b_cor$est - b_ag$est
  se <- sqrt(V[i1, i1] + V[i2, i2] - 2 * V[i1, i2])
  w <- wald_one_sided(est, se, "less")
  list(
    hypothesis = "H3",
    method = method,
    fallback_log = fallback_log,
    inclusion = inc,
    n_rows = nrow(d),
    n_configs_included = length(inc$included),
    estimate = est,
    se = se,
    ci_low = est - 1.959964 * se,
    ci_high = est + 1.959964 * se,
    z = w$z,
    p_raw = w$p,
    alternative = "less"
  )
}
