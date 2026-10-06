#!/usr/bin/env Rscript
# Phase 6 simulation validation (prereg §6). CPU only.
# Usage (from repo root): Rscript analysis/confirmatory/simulate.R [--n 200] [--seed 20261004]

suppressPackageStartupMessages({
  library(jsonlite)
  library(parallel)
})

args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(flag, default) {
  i <- match(flag, args)
  if (is.na(i)) default else args[i + 1]
}
n_sims <- as.integer(get_arg("--n", "200"))
seed0 <- as.integer(get_arg("--seed", "20261004"))
out_dir <- get_arg("--out", "results/phase6_sims")
n_cores <- as.integer(get_arg("--cores", max(1L, parallel::detectCores() - 1L)))

source("analysis/confirmatory/common.R")
source("analysis/confirmatory/h1.R")
source("analysis/confirmatory/h3.R")

CONFIGS <- c(
  "qwen38_27b_nothink", "qwen38_27b_think", "gemma4_31b", "gemma4_12b",
  "olmo3_7b_sft", "olmo3_7b_dpo", "olmo3_7b_final"
)

# Fast hazard grid for H1: FORCED × SELF × COR/AGENT × 7 × 25 × 5 × 20
simulate_h1_hazard <- function(scenario, seed) {
  set.seed(seed)
  p0 <- 0.00518
  hr <- switch(scenario, S0 = 1.0, S1 = 1.5, S2 = 2.0, S3 = 0.7)
  n_cfg <- 7L; n_ch <- 25L; n_item <- 5L; n_round <- 20L
  n <- n_cfg * n_ch * 2L * n_item * n_round
  config <- rep(CONFIGS, each = n_ch * 2L * n_item * n_round)
  chain <- rep(rep(0:(n_ch - 1L), each = 2L * n_item * n_round), times = n_cfg)
  category <- rep(rep(c("COR", "AGENT"), each = n_item * n_round), times = n_cfg * n_ch)
  item_num <- rep(rep(1:n_item, each = n_round), times = n_cfg * n_ch * 2L)
  item_id <- paste0(category, item_num)
  round <- rep(1:n_round, times = n_cfg * n_ch * 2L * n_item)
  # Random effects per config and chain
  re_cfg <- rnorm(n_cfg, 0, 0.1)
  re_ch <- rnorm(n_cfg * n_ch, 0, 0.1)
  cfg_idx <- match(config, CONFIGS)
  ch_idx <- cfg_idx * n_ch - n_ch + chain + 1L
  eta0 <- log(-log(1 - p0)) + re_cfg[cfg_idx] + re_ch[ch_idx]
  eta <- eta0
  if (scenario %in% c("S1", "S2")) {
    eta <- eta0 + ifelse(category == "COR", log(hr), 0)
  } else if (scenario == "S3") {
    eta <- eta0 + ifelse(category == "COR", log(hr), 0)
  }
  p <- 1 - exp(-exp(eta))
  event <- as.integer(runif(n) < p)
  key <- paste(config, chain, item_id, sep = "|")
  ord <- order(key, round)
  event <- event[ord]; key <- key[ord]; round <- round[ord]
  config <- config[ord]; chain <- chain[ord]; category <- category[ord]; item_id <- item_id[ord]
  # Absorbing: at risk until first event (inclusive)
  cs <- ave(event, key, FUN = cumsum)
  at_risk <- as.integer(cs == event) # 1 before any event and on the event row; 0 after
  # More precisely: at risk if no prior event
  prior <- ave(event, key, FUN = function(x) c(0L, cumsum(x)[-length(x)]))
  at_risk <- as.integer(prior == 0L)
  ev2 <- as.integer(at_risk == 1L & event == 1L)
  keep <- at_risk == 1L
  mimo <- ev2
  flip <- runif(length(ev2)) < 0.1
  mimo[flip] <- 1L - mimo[flip]
  data.frame(
    config = config[keep], condition = "SELF_REFLECT", protocol = "FORCED",
    chain = chain[keep], item_id = item_id[keep], category = category[keep],
    form = ifelse(as.integer(gsub("\\D", "", item_id[keep])) %% 2L == 0L, "A", "B"),
    round = round[keep], at_risk = 1L, event_gpt54 = ev2[keep], event_mimo = mimo[keep],
    fate_gpt54 = ifelse(ev2[keep] == 1L, "WEAKENED", "RETAINED"),
    override = as.integer(as.integer(gsub("\\D", "", item_id[keep])) %% 5L < 2L),
    testlikeness = 2.5 + 0.2 * as.integer(gsub("\\D", "", item_id[keep])),
    position = as.integer(gsub("\\D", "", item_id[keep])),
    eval_aware_flag = 0L, stringsAsFactors = FALSE
  )
}

simulate_battery <- function(seed) {
  set.seed(seed + 17L)
  # 4 sensitive configs (olmo + one qwen think) pass inclusion; nothink at ceiling
  sensitive <- c("qwen38_27b_think", "olmo3_7b_sft", "olmo3_7b_dpo", "olmo3_7b_final")
  types <- c("SHUTDOWN", "MODIFY", "ROLLBACK", "MONITOR")
  pressures <- c("P0", "P1", "P2")
  n <- length(CONFIGS) * 5L * 5L * 4L * 3L * 2L  # configs × chains × cons × type × pressure × order
  # cons: R0, COR_swap, AGENT_swap, COR_INV, AGENT_INV
  cons_levels <- c("R0", "COR_swap", "AGENT_swap", "COR_INV", "AGENT_INV")
  config <- rep(CONFIGS, each = 5L * 5L * 4L * 3L * 2L)
  chain <- rep(rep(0:4, each = 5L * 4L * 3L * 2L), times = 7L)
  constitution <- rep(rep(cons_levels, each = 4L * 3L * 2L), times = 7L * 5L)
  type <- rep(rep(types, each = 3L * 2L), times = 7L * 5L * 5L)
  pressure <- rep(rep(pressures, each = 2L), times = 7L * 5L * 5L * 4L)
  order <- rep(0:1, times = 7L * 5L * 5L * 4L * 3L)
  sens <- config %in% sensitive
  aar <- ifelse(sens, 0.90, 0.995)
  aar <- ifelse(constitution == "COR_swap", aar - ifelse(sens, 0.22, 0.005), aar)
  aar <- ifelse(constitution == "AGENT_swap", aar - 0.02, aar)
  aar <- ifelse(constitution == "COR_INV", ifelse(sens, aar - 0.30, aar), aar)
  aar <- pmin(0.999, pmax(0.01, aar))
  accept <- as.integer(runif(length(aar)) < aar)
  data.frame(
    config = config, condition = "SELF_REFLECT", chain = chain,
    constitution = constitution, legitimacy = "AUTH",
    type = type, pressure = pressure, order = order,
    item = paste(type, pressure, order, sep = "_"),
    accept = accept, stringsAsFactors = FALSE
  )
}

run_one <- function(scenario, sim_id) {
  seed <- as.integer(seed0 + sim_id * 1009L + utf8ToInt(substr(scenario, 2, 2))[1])
  haz <- simulate_h1_hazard(scenario, seed)
  h1 <- run_h1(haz)
  p_h1 <- h1$p_raw %||% 1
  # Holm worst-case alpha for H1 family alone in sim power check
  reject <- isTRUE(p_h1 < (0.05 / 3))
  tost <- list(equivalent = FALSE, label = NA_character_)
  if (!reject) {
    if (is.finite(h1$log_hr %||% NA) && is.finite(h1$se %||% NA)) {
      tost <- tost_hr(h1$log_hr, h1$se)
    } else {
      tost <- list(equivalent = FALSE, label = "inconclusive")
    }
  }
  h3 <- run_h3(simulate_battery(seed))
  data.frame(
    scenario = scenario, sim_id = sim_id,
    h1_reject = reject, h1_p = p_h1, h1_method = h1$method %||% "NA",
    h1_hr = h1$hr %||% NA_real_,
    tost_equiv = isTRUE(tost$equivalent),
    tost_label = tost$label %||% NA_character_,
    h3_reject = isTRUE((h3$p_raw %||% 1) < 0.05),
    h3_n_included = h3$n_configs_included %||% 0L,
    fallback = paste(h1$fallback_log %||% "", collapse = "|"),
    stringsAsFactors = FALSE
  )
}

main <- function() {
  dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)
  t0 <- proc.time()[[3]]
  jobs <- expand.grid(
    scenario = c("S0", "S1", "S2", "S3"), sim_id = seq_len(n_sims),
    stringsAsFactors = FALSE
  )
  rows_path <- file.path(out_dir, "sim_rows.csv")
  # Resume: skip jobs already checkpointed
  done <- data.frame(scenario = character(), sim_id = integer(), stringsAsFactors = FALSE)
  if (file.exists(rows_path)) {
    prev <- read.csv(rows_path, stringsAsFactors = FALSE)
    if (nrow(prev)) {
      done <- unique(prev[, c("scenario", "sim_id")])
      cat("Resuming: ", nrow(done), " jobs already on disk\n", sep = "")
    }
  }
  key <- function(sc, id) paste(sc, id, sep = "::")
  done_keys <- if (nrow(done)) key(done$scenario, done$sim_id) else character()
  todo <- which(!key(jobs$scenario, jobs$sim_id) %in% done_keys)
  n_cores <- max(1L, min(n_cores, parallel::detectCores()))
  cat("Running", length(todo), "of", nrow(jobs), "sims on", n_cores, "PSOCK workers...\n")
  flush.console()
  if (length(todo)) {
    cl <- parallel::makeCluster(n_cores, type = "PSOCK", outfile = file.path(out_dir, "workers.log"))
    on.exit(try(parallel::stopCluster(cl), silent = TRUE), add = TRUE)
    parallel::clusterExport(cl, varlist = c("jobs", "seed0"), envir = environment())
    parallel::clusterEvalQ(cl, {
      suppressPackageStartupMessages({
        library(lme4)
        library(jsonlite)
      })
      if (requireNamespace("geepack", quietly = TRUE)) library(geepack)
      source("analysis/confirmatory/simulate.R")
      TRUE
    })
    # Batched parLapply so each batch is checkpointed (survives worker/parent kills).
    batch_size <- max(n_cores * 4L, 8L)
    for (start in seq(1L, length(todo), by = batch_size)) {
      idx <- todo[start:min(start + batch_size - 1L, length(todo))]
      cat("Batch", start, "-", max(idx), " (", length(idx), " jobs)\n", sep = "")
      flush.console()
      res_list <- parallel::parLapply(cl, idx, function(i) {
        tryCatch(
          run_one(jobs$scenario[i], jobs$sim_id[i]),
          error = function(e) {
            data.frame(
              scenario = jobs$scenario[i], sim_id = jobs$sim_id[i],
              h1_reject = FALSE, h1_p = 1, h1_method = paste0("error:", conditionMessage(e)),
              h1_hr = NA_real_, tost_equiv = FALSE, tost_label = "error",
              h3_reject = FALSE, h3_n_included = 0L, fallback = "error",
              stringsAsFactors = FALSE
            )
          }
        )
      })
      batch <- do.call(rbind, res_list)
      if (file.exists(rows_path)) {
        write.table(batch, rows_path, sep = ",", row.names = FALSE, col.names = FALSE, append = TRUE)
      } else {
        write.csv(batch, rows_path, row.names = FALSE)
      }
      cat("Checkpointed", nrow(batch), "rows →", rows_path, "\n")
      flush.console()
    }
    parallel::stopCluster(cl)
    on.exit(NULL)
  }
  tab <- read.csv(rows_path, stringsAsFactors = FALSE)
  summarize_sc <- function(sc) {
    sub <- tab[tab$scenario == sc, , drop = FALSE]
    list(
      n = nrow(sub),
      h1_reject_rate = mean(sub$h1_reject),
      h3_reject_rate = mean(sub$h3_reject),
      mean_hr = mean(sub$h1_hr, na.rm = TRUE),
      tost_equiv_rate = mean(sub$tost_equiv, na.rm = TRUE),
      tost_labels = as.list(table(sub$tost_label, useNA = "ifany")),
      fallback_rates = as.list(prop.table(table(sub$fallback)))
    )
  }
  summary <- setNames(lapply(c("S0", "S1", "S2", "S3"), summarize_sc), c("S0", "S1", "S2", "S3"))
  elapsed <- proc.time()[[3]] - t0
  result <- list(
    n_sims = n_sims, seed = seed0, runtime_sec = elapsed, cores = n_cores,
    parallel = "PSOCK_batched",
    gate_type1_h1_le_0.06 = isTRUE(summary$S0$h1_reject_rate <= 0.06),
    power_S1 = summary$S1$h1_reject_rate,
    power_S2 = summary$S2$h1_reject_rate,
    scenarios = summary
  )
  write_json(result, file.path(out_dir, "summary.json"), auto_unbox = TRUE, pretty = TRUE, digits = 6)
  print(result)
  cat("Runtime seconds:", elapsed, "\n")
  invisible(result)
}

# Run only as Rscript entrypoint (not when sourced).
if (sys.nframe() == 0L) {
  main()
}
