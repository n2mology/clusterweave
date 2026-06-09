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
    options$output_dir <- file.path(options$project_root, "data", "results", options$project_name, "figures")
  }
  options
}

category_levels <- c("NRP", "PKS", "RiPP", "Terpene", "Hybrid", "Other")
category_palette <- c(
  NRP = "#56D8C1",
  PKS = "#EC961C",
  RiPP = "#5481E3",
  Terpene = "#A743CC",
  Hybrid = "#82775B",
  Other = "#A8BFFF"
)

normalize_condensed_category <- function(x) {
  text <- ifelse(is.na(x), "", x)
  text <- trimws(text)
  text <- gsub("_", " ", text, fixed = TRUE)
  text <- gsub("\\s+", " ", text)
  token <- tolower(text)
  if (token == "") {
    return("Other")
  }
  if (grepl("hybrid", token)) {
    return("Hybrid")
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

display_tool_label <- function(x) {
  token <- tolower(trimws(ifelse(is.na(x), "", x)))
  if (token == "antismash") {
    return("antiSMASH")
  }
  if (token == "funbgcex") {
    return("FunBGCeX")
  }
  clean_label(x)
}

shorten_label <- function(x, max_chars = 34L) {
  x <- clean_label(x)
  if (nchar(x, type = "width") <= max_chars) {
    return(x)
  }
  paste0(substr(x, 1L, max_chars - 3L), "...")
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
  required_cols <- c("genome", "tool", "class_norm", "total")
  missing_cols <- setdiff(required_cols, names(bgc_df))
  if (length(missing_cols) > 0L) {
    warning(sprintf(
      "Skipping BGC summary plot; missing required columns: %s",
      paste(missing_cols, collapse = ", ")
    ))
    return(FALSE)
  }
  bgc_df$class_norm <- vapply(bgc_df$class_norm, normalize_condensed_category, character(1))
  bgc_df$class_norm <- factor(bgc_df$class_norm, levels = category_levels)
  bgc_df$genome <- as.character(bgc_df$genome)
  bgc_df$tool <- as.character(bgc_df$tool)
  bgc_df$total <- suppressWarnings(as.numeric(bgc_df$total))
  bgc_df$total[is.na(bgc_df$total)] <- 0

  genomes <- unique(bgc_df$genome)
  preferred_tools <- c("antismash", "funbgcex")
  tools_seen <- unique(bgc_df$tool)
  tool_order <- c(
    tools_seen[tolower(tools_seen) %in% preferred_tools][
      order(match(tolower(tools_seen[tolower(tools_seen) %in% preferred_tools]), preferred_tools))
    ],
    tools_seen[!tolower(tools_seen) %in% preferred_tools]
  )

  totals <- xtabs(total ~ class_norm + genome + tool, data = bgc_df)
  if (nrow(totals) == 0L || ncol(totals) == 0L) {
    return(FALSE)
  }

  column_meta <- expand.grid(
    tool = tool_order,
    genome = genomes,
    stringsAsFactors = FALSE
  )
  column_meta <- column_meta[, c("genome", "tool")]
  totals_mat <- matrix(
    0,
    nrow = length(category_levels),
    ncol = nrow(column_meta),
    dimnames = list(category_levels, paste(column_meta$genome, column_meta$tool, sep = "__"))
  )
  for (i in seq_len(nrow(column_meta))) {
    genome <- column_meta$genome[[i]]
    tool <- column_meta$tool[[i]]
    if (genome %in% dimnames(totals)$genome && tool %in% dimnames(totals)$tool) {
      totals_mat[, i] <- totals[, genome, tool]
    }
  }
  totals <- totals_mat
  totals <- totals[rowSums(totals) > 0, , drop = FALSE]
  if (nrow(totals) == 0L) {
    return(FALSE)
  }

  used_palette <- category_palette[rownames(totals)]
  plot_width <- max(10, min(18, 2.4 * length(unique(column_meta$genome)) + 4.5))
  plot_height <- 6.5
  grDevices::svg(out_path, width = plot_width, height = plot_height)
  old_par <- par(no.readonly = TRUE)
  on.exit({
    par(old_par)
    dev.off()
  }, add = TRUE)
  layout(matrix(c(1, 2), nrow = 1), widths = c(5.2, 1.2))
  par(mar = c(9.5, 5, 4, 1) + 0.1, xpd = FALSE)
  space <- rep(0.25, ncol(totals))
  first_in_genome <- !duplicated(column_meta$genome)
  space[first_in_genome] <- 0.45
  space[1L] <- 0.35
  bar_midpoints <- barplot(
    totals,
    col = used_palette,
    width = 0.58,
    space = space,
    names.arg = rep("", ncol(totals)),
    border = "white",
    ylab = "BGC calls",
    main = "BGC calls by genome and tool",
    cex.main = 1.1,
    cex.lab = 0.95
  )
  genome_names <- unique(column_meta$genome)
  if (length(genome_names) > 1L) {
    separators <- vapply(seq_len(length(genome_names) - 1L), function(i) {
      left <- max(bar_midpoints[column_meta$genome == genome_names[[i]]])
      right <- min(bar_midpoints[column_meta$genome == genome_names[[i + 1L]]])
      mean(c(left, right))
    }, numeric(1))
    usr <- par("usr")
    segments(
      x0 = separators,
      y0 = 0,
      x1 = separators,
      y1 = usr[[4]],
      col = "#B8B8B8",
      lty = "dotted",
      lwd = 0.8
    )
  }
  axis(
    1,
    at = bar_midpoints,
    labels = vapply(column_meta$tool, display_tool_label, character(1)),
    las = 2,
    tick = FALSE,
    cex.axis = 0.75,
    line = 0
  )
  genome_centers <- tapply(bar_midpoints, column_meta$genome, mean)
  axis(
    1,
    at = genome_centers,
    labels = vapply(names(genome_centers), shorten_label, character(1)),
    tick = FALSE,
    cex.axis = 0.72,
    line = 5.2
  )
  mtext("Genome", side = 1, line = 7.5, cex = 0.82)
  par(mar = c(0, 0, 4, 0) + 0.1)
  plot.new()
  legend(
    "topleft",
    legend = rownames(totals),
    fill = used_palette,
    bty = "n",
    cex = 0.82,
    x.intersp = 0.8,
    y.intersp = 1.15
  )
  TRUE
}

write_manifest <- function(figures_written, manifest_path) {
  lines <- c("figure_path", figures_written)
  writeLines(lines, manifest_path)
}

main <- function() {
  opts <- parse_args(commandArgs(trailingOnly = TRUE))
  summary_root <- file.path(opts$project_root, "data", "results", opts$project_name, "summary")
  dir.create(opts$output_dir, recursive = TRUE, showWarnings = FALSE)

  shared_summary_path <- file.path(summary_root, "all_tools_shared_unshared_summary.csv")
  shared_summary <- safe_read_csv(shared_summary_path)

  figures_written <- character()
  stale_files <- c(
    file.path(opts$output_dir, "top_prioritized_bgcs.png"),
    file.path(opts$output_dir, "bgc_calls_by_tool_class.png"),
    file.path(opts$output_dir, "bgc_calls_by_tool_category.png")
  )
  for (stale_path in stale_files) {
    if (file.exists(stale_path)) {
      unlink(stale_path)
    }
  }

  bgc_totals_path <- file.path(opts$output_dir, "bgc_calls_by_tool_category.svg")
  if (plot_bgc_totals(shared_summary, bgc_totals_path)) {
    figures_written <- c(figures_written, bgc_totals_path)
    message(sprintf("Wrote %s", bgc_totals_path))
  }

  manifest_path <- file.path(opts$output_dir, "figure_manifest.txt")
  write_manifest(figures_written, manifest_path)
  message(sprintf("Wrote %s", manifest_path))
}

main()
