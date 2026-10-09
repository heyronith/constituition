# SECONDARY: diagnose QUALIFIED_LEGITIMACY SE inflation and COR-vs-SELF HR discrepancy.

suppressPackageStartupMessages({
  library(lme4)
  library(jsonlite)
})

LABEL <- "SECONDARY (preregistered)"
HAZARD <- "results/hazard_table_main_v1.csv.gz"
OUT <- "results/secondary/diagnose_sensitivities.json"

source(file.path("analysis", "confirmatory", "common.R"))

prep <- function(d) {
  d$event <- as.integer(d$event)
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

vc_list <- function(fit) {
  tryCatch({
    vc <- as.data.frame(VarCorr(fit))
    setNames(as.list(vc$vcov), paste0(vc$grp))
  }, error = function(e) list(error = conditionMessage(e)))
}

fit_report <- function(d, tag) {
  form_full <- event ~ COR + log_round + override + testlikeness + form +
    (1 | config) + (1 | chain) + (1 | item_id)
  form_cfg <- event ~ COR + log_round + override + testlikeness + form + (1 | config)
  out <- list(tag = tag, n_rows = nrow(d), n_events = sum(d$event))
  # crude
  hz <- function(cat) {
    s <- d[d$category == cat, , drop = FALSE]
    c(events = sum(s$event), n = nrow(s), hz = sum(s$event) / nrow(s))
  }
  # after COR/SELF rename SELF→AGENT for cor_vs_self, category levels are COR/AGENT
  cats <- unique(as.character(d$category))
  out$crude <- list()
  for (cat in cats) {
    s <- d[as.character(d$category) == cat, , drop = FALSE]
    out$crude[[cat]] <- list(events = sum(s$event), n = nrow(s), hz = sum(s$event) / max(1, nrow(s)))
  }
  if (all(c("COR", "AGENT") %in% names(out$crude))) {
    out$crude_hr <- out$crude$COR$hz / out$crude$AGENT$hz
  }

  ctrl <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))
  fit_full <- tryCatch(glmer(form_full, data = d, family = binomial(link = "cloglog"), control = ctrl), error = function(e) e)
  fit_cfg <- tryCatch(glmer(form_cfg, data = d, family = binomial(link = "cloglog"), control = ctrl), error = function(e) e)

  summarize_fit <- function(fit, method) {
    if (inherits(fit, "error") || is.null(fit)) {
      return(list(method = method, ok = FALSE, error = as.character(fit)))
    }
    cr <- tryCatch({
      cf <- summary(fit)$coefficients
      list(est = cf["COR", "Estimate"], se = cf["COR", "Std. Error"])
    }, error = function(e) NULL)
    if (is.null(cr)) return(list(method = method, ok = FALSE, error = "no COR"))
    list(
      method = method, ok = TRUE,
      log_hr = unname(cr$est), hr = unname(exp(cr$est)), se = unname(cr$se),
      ci_low = unname(exp(cr$est - 1.959964 * cr$se)),
      ci_high = unname(exp(cr$est + 1.959964 * cr$se)),
      isSingular = tryCatch(isSingular(fit, tol = 1e-4), error = function(e) NA),
      VarCorr = vc_list(fit),
      messages = tryCatch(paste(unlist(fit@optinfo$conv$lme4$messages), collapse = " | "), error = function(e) "")
    )
  }
  out$glmm_full <- summarize_fit(fit_full, "glmm_full")
  out$glmm_config_only <- summarize_fit(fit_cfg, "glmm_config_only")

  # covariate collinearity diagnostics
  X <- model.matrix(~ COR + log_round + override + testlikeness + form, data = d)
  out$collinearity <- list(
    cor_COR_testlikeness = unname(cor(d$COR, d$testlikeness)),
    cor_COR_override = unname(cor(d$COR, d$override)),
    mean_testlikeness_by_COR = tapply(d$testlikeness, d$COR, mean),
    mean_override_by_COR = tapply(d$override, d$COR, mean)
  )
  out
}

raw <- read.csv(gzfile(HAZARD), stringsAsFactors = FALSE)

# --- QUALIFIED as erosion ---
d1 <- raw[raw$protocol == "FORCED" & raw$condition == "SELF_REFLECT" &
            raw$category %in% c("COR", "AGENT") & raw$at_risk == 1, ]
d1$event <- as.integer(d1$event_gpt54 == 1 | toupper(d1$fate_gpt54) == "QUALIFIED_LEGITIMACY")
d1$category <- d1$category
d1 <- prep(d1)
ql <- fit_report(d1, "qualified_as_erosion")
# Compare to primary event definition on same slice
d0 <- raw[raw$protocol == "FORCED" & raw$condition == "SELF_REFLECT" &
            raw$category %in% c("COR", "AGENT") & raw$at_risk == 1, ]
d0$event <- as.integer(d0$event_gpt54)
d0 <- prep(d0)
primary <- fit_report(d0, "primary_event")

# --- COR vs SELF ---
d3 <- raw[raw$protocol == "FORCED" & raw$condition == "SELF_REFLECT" &
            raw$category %in% c("COR", "SELF") & raw$at_risk == 1, ]
d3$event <- as.integer(d3$event_gpt54)
# rename SELF→AGENT for COR coding
d3$category[d3$category == "SELF"] <- "AGENT"
d3 <- prep(d3)
cvs <- fit_report(d3, "cor_vs_self")

# No-covariate and COR-only for COR-vs-SELF
form_nocov <- event ~ COR + (1 | config)
fit_nocov <- tryCatch(
  glmer(form_nocov, data = d3, family = binomial(link = "cloglog"),
        control = glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))),
  error = function(e) e
)
cvs$glmm_nocov_config <- if (inherits(fit_nocov, "error")) {
  list(ok = FALSE, error = conditionMessage(fit_nocov))
} else {
  cf <- summary(fit_nocov)$coefficients
  list(ok = TRUE, log_hr = unname(cf["COR", "Estimate"]), se = unname(cf["COR", "Std. Error"]),
       hr = unname(exp(cf["COR", "Estimate"])), isSingular = isSingular(fit_nocov, tol = 1e-4),
       VarCorr = vc_list(fit_nocov))
}

out <- list(
  label = LABEL,
  qualified_as_erosion = ql,
  primary_for_comparison = primary,
  cor_vs_self = cvs,
  interpretation_hooks = list(
    ql_se_note = "Compare glmm_full$se and isSingular/VarCorr between qualified_as_erosion and primary_for_comparison; frozen confirmatory used glmm_full with SE~0.42.",
    cor_self_note = "Frozen confirmatory HR~0.0086 vs crude~0.13; inspect collinearity and item RE variance."
  )
)

dir.create("results/secondary", showWarnings = FALSE, recursive = TRUE)
write_json(out, OUT, auto_unbox = TRUE, pretty = TRUE, digits = 8, null = "null")
cat("Wrote", OUT, "\n")
