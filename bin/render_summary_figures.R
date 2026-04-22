#!/usr/bin/env Rscript

get_script_path <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) > 0) {
    return(normalizePath(sub("^--file=", "", file_arg[1]), winslash = "/", mustWork = TRUE))
  }
  normalizePath(".", winslash = "/", mustWork = TRUE)
}

parse_args <- function(args) {
  script_path <- get_script_path()
  project_root <- normalizePath(file.path(dirname(script_path), ".."), winslash = "/", mustWork = TRUE)
  options <- list(
    project_root = project_root,
    project_name = basename(project_root),
    output_dir = ""
  )

  i <- 1L
  while (i <= length(args)) {
    key <- args[[i]]
    if (key == "--project-root" && i < length(args)) {
      options$project_root <- normalizePath(args[[i + 1L]], winslash = "/", mustWork = FALSE)
      i <- i + 2L
    } else if (key == "--project-name" && i < length(args)) {
      options$project_name <- args[[i + 1L]]
      i <- i + 2L
    } else if (key == "--output-dir" && i < length(args)) {
      options$output_dir <- normalizePath(args[[i + 1L]], winslash = "/", mustWork = FALSE)
      i <- i + 2L
    } else {
      stop(sprintf("Unknown or incomplete argument: %s", key), call. = FALSE)
    }
  }

  if (!nzchar(options$output_dir)) {
    options$output_dir <- file.path(options$project_root, "Data", "Results", options$project_name, "figures")
  }
  options
}

category_levels <- c("NRP", "PKS", "RiPP", "Terpene", "Hybrid", "Other")

normalize_condensed_category <- function(x) {
  text <- ifelse(is.na(x), "", x)
  text <- trimws(text)
  text <- gsub("_", " ", text, fixed = TRUE)
  text <- gsub("\\s+", " ", text)
  token <- tolower(text)
  if (token == "") {
    return("Other")
  }
  has_nrp <- grepl("nrps|nrp", token)
  has_pks <- grepl("pks|polyketide", token)
  has_ripp <- grepl("ripp", token)
  has_terpene <- grepl("terpene|\\btc\\b|cyclase|synthase", token)
  major_count <- sum(c(has_nrp, has_pks, has_ripp, has_terpene))
  if (major_count > 1) {
    return("Hybrid")
  }
  if (has_nrp) {
    return("NRP")
  }
  if (has_pks) {
    return("PKS")
  }
  if (has_ripp) {
    return("RiPP")
  }
  if (has_terpene) {
    return("Terpene")
  }
  "Other"
}

clean_label <- function(x) {
  x <- ifelse(is.na(x), "", x)
  x <- trimws(x)
  x <- sub("^([^;|]+).*", "\\1", x)
  x <- gsub("_", " ", x, fixed = TRUE)
  x <- gsub("\\s+", " ", x)
  trimws(x)
}

safe_read_csv <- function(path) {
  if (!file.exists(path)) {
    return(NULL)
  }
  read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
}

safe_read_tsv <- function(path) {
  if (!file.exists(path)) {
    return(NULL)
  }
  read.delim(path, stringsAsFactors = FALSE, check.names = FALSE)
}

plot_bgc_totals <- function(summary_df, out_path) {
  if (is.null(summary_df)) {
    return(FALSE)
  }
  bgc_df <- summary_df[summary_df$entity_type == "BGC", , drop = FALSE]
  if (nrow(bgc_df) == 0L) {
    return(FALSE)
  }
  bgc_df$class_norm <- vapply(bgc_df$class_norm, normalize_condensed_category, character(1))
  bgc_df$class_norm <- factor(bgc_df$class_norm, levels = category_levels)
  totals <- xtabs(total ~ class_norm + tool, data = bgc_df)
  if (nrow(totals) == 0L || ncol(totals) == 0L) {
    return(FALSE)
  }
  totals <- totals[rownames(totals) %in% category_levels, , drop = FALSE]
  totals <- totals[rowSums(totals) > 0, , drop = FALSE]
  if (nrow(totals) == 0L) {
    return(FALSE)
  }

  palette <- grDevices::hcl.colors(max(3L, nrow(totals)), "Dark 3")
  grDevices::png(out_path, width = 1800, height = 1100, res = 150)
  par(mar = c(10, 5, 4, 2) + 0.1)
  barplot(
    totals,
    col = palette[seq_len(nrow(totals))],
    las = 2,
    ylab = "Total BGC calls",
    main = "BGC calls by tool and condensed category"
  )
  legend(
    "topright",
    legend = rownames(totals),
    fill = palette[seq_len(nrow(totals))],
    bty = "n",
    cex = 0.9
  )
  dev.off()
  TRUE
}

plot_shared_unshared <- function(summary_df, out_path) {
  if (is.null(summary_df)) {
    return(FALSE)
  }
  bgc_df <- summary_df[summary_df$entity_type == "BGC", , drop = FALSE]
  if (nrow(bgc_df) == 0L) {
    return(FALSE)
  }
  agg <- aggregate(cbind(shared_count, unshared_count) ~ tool, data = bgc_df, sum)
  if (nrow(agg) == 0L) {
    return(FALSE)
  }
  mat <- t(as.matrix(agg[, c("shared_count", "unshared_count")]))
  colnames(mat) <- agg$tool

  grDevices::png(out_path, width = 1600, height = 1000, res = 150)
  par(mar = c(8, 5, 4, 2) + 0.1)
  barplot(
    mat,
    beside = FALSE,
    col = c("#4C78A8", "#F58518"),
    las = 2,
    ylab = "BGC count",
    main = "Shared vs unshared BGC calls by tool"
  )
  legend(
    "topright",
    legend = c("shared", "unshared"),
    fill = c("#4C78A8", "#F58518"),
    bty = "n"
  )
  dev.off()
  TRUE
}

write_manifest <- function(figures_written, manifest_path) {
  lines <- c("figure_path", figures_written)
  writeLines(lines, manifest_path)
}

main <- function() {
  opts <- parse_args(commandArgs(trailingOnly = TRUE))
  summary_root <- file.path(opts$project_root, "Data", "Results", opts$project_name, "summary")
  dir.create(opts$output_dir, recursive = TRUE, showWarnings = FALSE)

  shared_summary_path <- file.path(summary_root, "all_tools_shared_unshared_summary.csv")
  shared_summary <- safe_read_csv(shared_summary_path)

  figures_written <- character()
  stale_files <- c(
    file.path(opts$output_dir, "top_prioritized_bgcs.png"),
    file.path(opts$output_dir, "bgc_calls_by_tool_class.png")
  )
  for (stale_path in stale_files) {
    if (file.exists(stale_path)) {
      unlink(stale_path)
    }
  }

  bgc_totals_path <- file.path(opts$output_dir, "bgc_calls_by_tool_category.png")
  if (plot_bgc_totals(shared_summary, bgc_totals_path)) {
    figures_written <- c(figures_written, bgc_totals_path)
    message(sprintf("Wrote %s", bgc_totals_path))
  }

  shared_path <- file.path(opts$output_dir, "shared_vs_unshared_bgc_calls.png")
  if (plot_shared_unshared(shared_summary, shared_path)) {
    figures_written <- c(figures_written, shared_path)
    message(sprintf("Wrote %s", shared_path))
  }

  manifest_path <- file.path(opts$output_dir, "figure_manifest.txt")
  write_manifest(figures_written, manifest_path)
  message(sprintf("Wrote %s", manifest_path))
}

main()
