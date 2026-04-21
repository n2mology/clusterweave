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
    output_dir = "",
    top_n = 15L
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
    } else if (key == "--top-n" && i < length(args)) {
      options$top_n <- as.integer(args[[i + 1L]])
      i <- i + 2L
    } else {
      stop(sprintf("Unknown or incomplete argument: %s", key), call. = FALSE)
    }
  }

  if (is.na(options$top_n) || options$top_n < 1L) {
    options$top_n <- 15L
  }
  if (!nzchar(options$output_dir)) {
    options$output_dir <- file.path(options$project_root, "Data", "Results", options$project_name, "figures")
  }
  options
}

clean_label <- function(x) {
  x <- ifelse(is.na(x), "", x)
  x <- trimws(x)
  x <- sub("^([^;|]+).*", "\\1", x)
  x <- gsub("_", " ", x, fixed = TRUE)
  x <- gsub("\\s+", " ", x)
  trimws(x)
}

pick_priority_label <- function(df) {
  label <- clean_label(df$antismash_knowncluster_product)
  fallback_1 <- clean_label(df$nearest_mibig_or_annotation_if_available)
  fallback_2 <- clean_label(df$funbgcex_putative_product)
  fallback_3 <- clean_label(df$antismash_region)
  label[label == ""] <- fallback_1[label == ""]
  label[label == ""] <- fallback_2[label == ""]
  label[label == ""] <- fallback_3[label == ""]
  label
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
  bgc_df$class_norm[bgc_df$class_norm == ""] <- "unclassified"
  totals <- xtabs(total ~ class_norm + tool, data = bgc_df)
  if (nrow(totals) == 0L || ncol(totals) == 0L) {
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
    main = "BGC calls by tool and class"
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
    main = "Shared vs unshared BGC calls"
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

plot_priority_scores <- function(priority_df, out_path, top_n) {
  if (is.null(priority_df) || nrow(priority_df) == 0L) {
    return(FALSE)
  }
  priority_df$priority_score_num <- suppressWarnings(as.numeric(priority_df$priority_score))
  priority_df$rank_num <- suppressWarnings(as.integer(priority_df$rank))
  priority_df <- priority_df[order(-priority_df$priority_score_num, priority_df$rank_num), , drop = FALSE]
  priority_df <- head(priority_df, top_n)
  if (nrow(priority_df) == 0L) {
    return(FALSE)
  }

  labels <- pick_priority_label(priority_df)
  labels <- rev(labels)
  scores <- rev(priority_df$priority_score_num)
  palette <- rep("#54A24B", length(scores))

  grDevices::png(out_path, width = 1900, height = max(1000, 90 * length(scores)), res = 150)
  par(mar = c(5, max(12, max(nchar(labels)) * 0.8), 4, 2) + 0.1)
  bar_positions <- barplot(
    scores,
    horiz = TRUE,
    names.arg = labels,
    las = 1,
    col = palette,
    xlab = "Priority score",
    main = "Top prioritized candidate BGCs"
  )
  text(scores, bar_positions, labels = priority_df$priority_tier[rev(seq_len(nrow(priority_df)))], pos = 4, cex = 0.8)
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
  ranking_path <- file.path(summary_root, "targeted_candidate_ranking.tsv")

  shared_summary <- safe_read_csv(shared_summary_path)
  ranking <- safe_read_tsv(ranking_path)

  figures_written <- character()

  bgc_totals_path <- file.path(opts$output_dir, "bgc_calls_by_tool_class.png")
  if (plot_bgc_totals(shared_summary, bgc_totals_path)) {
    figures_written <- c(figures_written, bgc_totals_path)
    message(sprintf("Wrote %s", bgc_totals_path))
  }

  shared_path <- file.path(opts$output_dir, "shared_vs_unshared_bgc_calls.png")
  if (plot_shared_unshared(shared_summary, shared_path)) {
    figures_written <- c(figures_written, shared_path)
    message(sprintf("Wrote %s", shared_path))
  }

  priority_path <- file.path(opts$output_dir, "top_prioritized_bgcs.png")
  if (plot_priority_scores(ranking, priority_path, opts$top_n)) {
    figures_written <- c(figures_written, priority_path)
    message(sprintf("Wrote %s", priority_path))
  }

  manifest_path <- file.path(opts$output_dir, "figure_manifest.txt")
  write_manifest(figures_written, manifest_path)
  message(sprintf("Wrote %s", manifest_path))
}

main()
