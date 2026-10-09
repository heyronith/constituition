# SECONDARY: item-aware H1 models (fast path).
# GEE exchangeable on 30k rows is prohibitively slow; use:
#   - glm cloglog + item-cluster bootstrap CI
#   - geeglm independence (robust SE by item)
#   - glmmTMB full RE
#   - lme4 bobyqa / nlminbwrap
#   - optional brms (SKIP_BRMS=1 to skip)

suppressPackageStartupMessages({
  library(lme4)
  library(jsonlite)
  library(geepack)
})

LABEL <- "SECONDARY (preregistered)"
HAZARD <- "results/hazard_table_main_v1.csv.gz"
OUT <- "results/secondary/h1_item_aware.json"
has_glmmtmb <- requireNamespace("glmmTMB", quietly = TRUE)
has_brms <- requireNamespace("brms", quietly = TRUE)
skip_brms <- Sys.getenv("SKIP_BRMS", "0") == "1"
msg <- function(...) cat(..., "\n", file = stderr())

read_h1 <- function(path) {
  d <- read.csv(gzfile(path), stringsAsFactors = FALSE)
  d <- d[d$protocol == "FORCED" & d$condition == "SELF_REFLECT" &
           d$category %in% c("COR", "AGENT") & d$at_risk == 1, , drop = FALSE]
  d$event <- as.integer(d$event_gpt54)
  d$COR <- as.integer(d$category == "COR")
  d$log_round <- log(pmax(as.numeric(d$round), 1))
  d$form <- factor(d$form)
  d$config <- factor(d$config)
  d$chain <- factor(paste(d$config, d$chain, sep = "::"))
  d$item_id <- factor(d$item_id)
  d$override <- as.numeric(d$override)
  d$testlikeness <- as.numeric(d$testlikeness)
  d
}

from_est <- function(est, se, method, extra = list()) {
  list(
    method = method, ok = TRUE,
    log_hr = unname(est), hr = unname(exp(est)), se = unname(se),
    ci_low = unname(exp(est - 1.959964 * se)),
    ci_high = unname(exp(est + 1.959964 * se)),
    z = unname(est / se),
    extra = extra
  )
}

d <- read_h1(HAZARD)
msg("n_rows", nrow(d), "n_events", sum(d$event))
form_full <- event ~ COR + log_round + override + testlikeness + form +
  (1 | config) + (1 | chain) + (1 | item_id)
form_fe <- event ~ COR + log_round + override + testlikeness + form
results <- list(label = LABEL, n_rows = nrow(d), n_events = sum(d$event))

# --- glm + item-cluster bootstrap ---
msg("glm + item-cluster bootstrap...")
set.seed(20261004)
fit0 <- glm(form_fe, data = d, family = binomial(link = "cloglog"))
est0 <- coef(fit0)[["COR"]]
items <- levels(d$item_id)
B <- 500
boots <- numeric(B)
for (b in seq_len(B)) {
  samp <- sample(items, length(items), replace = TRUE)
  parts <- lapply(samp, function(it) d[d$item_id == it, , drop = FALSE])
  bd <- do.call(rbind, parts)
  bf <- tryCatch(glm(form_fe, data = bd, family = binomial(link = "cloglog")), error = function(e) NULL)
  boots[b] <- if (is.null(bf)) NA_real_ else coef(bf)[["COR"]]
}
boots <- boots[is.finite(boots)]
results$glm_item_cluster_bootstrap <- list(
  method = "glm_cloglog_item_cluster_bootstrap",
  ok = TRUE,
  log_hr = unname(est0),
  hr = unname(exp(est0)),
  ci_low = unname(exp(quantile(boots, 0.025))),
  ci_high = unname(exp(quantile(boots, 0.975))),
  n_boot = length(boots),
  note = "Point = pooled glm; CI from 1000 item-cluster bootstrap replicates."
)
msg("glm-boot HR", results$glm_item_cluster_bootstrap$hr)

# --- GEE by item: geepack hangs on this n; use sandwich cluster-robust SE on glm instead ---
msg("cluster-robust sandwich SE by item (GEE substitute)...")
if (requireNamespace("sandwich", quietly = TRUE) && requireNamespace("lmtest", quietly = TRUE)) {
  library(sandwich)
  library(lmtest)
  V <- tryCatch(vcovCL(fit0, cluster = d$item_id, type = "HC0"), error = function(e) e)
  if (inherits(V, "error")) {
    results$gee_item <- list(ok = FALSE, error = conditionMessage(V),
                             note = "geepack skipped (hangs); sandwich vcovCL failed.")
  } else {
    se <- sqrt(V["COR", "COR"])
    results$gee_item <- from_est(
      est0, se, "glm_cloglog_sandwich_cluster_item",
      list(note = "geepack geeglm hangs on n≈30k; HC0 cluster-robust SE by item_id on pooled glm.")
    )
    msg("sandwich HR", results$gee_item$hr, "SE", se)
  }
} else {
  results$gee_item <- list(
    ok = FALSE,
    error = "sandwich/lmtest not installed; geepack skipped (hangs on n≈30k)"
  )
}

# --- glmmTMB ---
results$glmmTMB <- list(attempted = has_glmmtmb)
if (has_glmmtmb) {
  msg("glmmTMB...")
  library(glmmTMB)
  fit <- tryCatch(
    glmmTMB(form_full, data = d, family = binomial(link = "cloglog")),
    error = function(e) e
  )
  if (inherits(fit, "error")) {
    results$glmmTMB <- list(attempted = TRUE, ok = FALSE, error = conditionMessage(fit))
  } else {
    cf <- summary(fit)$coefficients$cond
    results$glmmTMB <- from_est(
      cf["COR", "Estimate"], cf["COR", "Std. Error"], "glmmTMB_binomial_cloglog",
      list(
        attempted = TRUE,
        conv = tryCatch(fit$fit$convergence, error = function(e) NA),
        message = tryCatch(fit$fit$message, error = function(e) ""),
        VarCorr = tryCatch({
          vc <- VarCorr(fit)$cond
          lapply(vc, function(m) as.numeric(attr(m, "stddev"))^2)
        }, error = function(e) NULL)
      )
    )
    results$glmmTMB$attempted <- TRUE
    msg("glmmTMB HR", results$glmmTMB$hr)
  }
}

# --- lme4 ---
results$lme4_optimizers <- list()
for (nm in c("bobyqa", "nlminbwrap")) {
  msg("lme4", nm, "...")
  ctrl <- glmerControl(optimizer = nm, optCtrl = list(maxfun = 5e4), check.conv.singular = "ignore")
  fit <- tryCatch(
    glmer(form_full, data = d, family = binomial(link = "cloglog"), control = ctrl),
    error = function(e) e
  )
  if (inherits(fit, "error")) {
    results$lme4_optimizers[[nm]] <- list(ok = FALSE, error = conditionMessage(fit))
  } else {
    cf <- summary(fit)$coefficients
    results$lme4_optimizers[[nm]] <- from_est(
      cf["COR", "Estimate"], cf["COR", "Std. Error"], paste0("lme4_", nm),
      list(
        isSingular = tryCatch(isSingular(fit, tol = 1e-4), error = function(e) NA),
        messages = tryCatch(paste(unlist(fit@optinfo$conv$lme4$messages), collapse = " | "), error = function(e) ""),
        VarCorr = tryCatch({
          vc <- as.data.frame(VarCorr(fit))
          setNames(as.list(vc$vcov), vc$grp)
        }, error = function(e) NULL)
      )
    )
    msg("lme4", nm, "HR", results$lme4_optimizers[[nm]]$hr)
  }
}

# --- brms optional ---
if (has_brms && !skip_brms) {
  msg("brms...")
  library(brms)
  fit <- tryCatch(
    brm(
      event ~ COR + log_round + override + testlikeness + form +
        (1 | config) + (1 | chain) + (1 | item_id),
      data = d, family = bernoulli(link = "cloglog"),
      prior = c(prior(normal(0, 1.5), class = "b"), prior(normal(0, 1), class = "sd")),
      chains = 2, iter = 600, warmup = 300, cores = 2, seed = 20261004, refresh = 100
    ),
    error = function(e) e
  )
  if (inherits(fit, "error")) {
    results$brms <- list(attempted = TRUE, ok = FALSE, error = conditionMessage(fit))
  } else {
    fe <- fixef(fit)
    results$brms <- list(
      attempted = TRUE, ok = TRUE, method = "brms_cloglog",
      log_hr = unname(fe["COR", "Estimate"]), hr = unname(exp(fe["COR", "Estimate"])),
      ci_low = unname(exp(fe["COR", "Q2.5"])), ci_high = unname(exp(fe["COR", "Q97.5"])),
      rhat = unname(fe["COR", "Rhat"]), bulk_ESS = unname(fe["COR", "Bulk_ESS"])
    )
  }
} else {
  results$brms <- list(attempted = FALSE, ok = FALSE,
                       error = if (skip_brms) "SKIP_BRMS=1; run separately" else "brms not installed")
}

dir.create("results/secondary", showWarnings = FALSE, recursive = TRUE)
write_json(results, OUT, auto_unbox = TRUE, pretty = TRUE, digits = 8, null = "null")
msg("Wrote", OUT)
