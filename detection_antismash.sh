###############################################################################
# antiSMASH flag helper (unchanged from your script)
###############################################################################
ANTISMASH_FLAGS_CANDIDATES=(
  --verbose
  --fullhmmer
  --asf
  --clusterhmmer
  --tigrfam
  --cc-mibig
  --cb-general
  --cb-knownclusters
  --cb-subclusters
  --pfam2go
  --smcog-trees
  --tfbs
  --rre
  --allow-long-headers
)

antismash_supported_flags() {
  local taxon_group="${1:-fungi}"
  local genefinding_tool="${2:-none}"
  local help
  help="$(antismash_exec antismash --help-showall 2>&1 || true)"

  # antiSMASH 8.0.4 supports both arguments and they define the scientific
  # prediction route, so never silently omit them.
  local out=(--taxon "${taxon_group}" --genefinding-tool "${genefinding_tool}")
  local i=0
  while [[ $i -lt ${#ANTISMASH_FLAGS_CANDIDATES[@]} ]]; do
    local tok="${ANTISMASH_FLAGS_CANDIDATES[$i]}"
    if [[ "${tok}" == --* ]]; then
      if grep -Fq -- "${tok}" <<< "${help}"; then out+=("${tok}"); fi
    fi
    i=$((i+1))
  done

  printf "%s\n" "${out[@]}"
}

###############################################################################
# Done checks (RESULTS_ROOT canonical)
###############################################################################
antismash_outputs_valid() {
  local outdir="$1"
  [[ -d "${outdir}" ]] || return 1
  [[ -s "${outdir}/index.html" ]] || return 1

  if [[ -n "$(find "${outdir}" -maxdepth 3 -type f \( -name "regions.js" -o -name "*.antismash.json" -o -name "overview*.js" \) -print -quit 2>/dev/null)" ]]; then
    return 0
  fi
  return 1
}

antismash_done() {
  local outdir="$1"
  [[ -f "${outdir}/.done" ]] || return 1
  antismash_outputs_valid "${outdir}"
}

mark_antismash_done() {
  local outdir="$1"
  rm -f "${outdir}/.done" 2>/dev/null || true
  antismash_outputs_valid "${outdir}" || return 1
  touch "${outdir}/.done"
}

###############################################################################
# GBK diagnostics/filtering (run via the configured FunBGCeX runtime)
###############################################################################
gbk_diag_summary() {
  local gbk="$1"
  local label="${2:-GBK}"
  repository_helper_python_exec "${ANNOTATION_GENBANK_HELPER}" diagnose "${gbk}" "${label}"
}

filter_gbk_drop_gene_less_records() {
  local in_gbk="$1"
  local out_gbk="$2"
  repository_helper_python_exec "${ANNOTATION_GENBANK_HELPER}" \
    drop-gene-less "${in_gbk}" "${out_gbk}"
}


list_genbank_record_ids() {
  local gbk="$1"
  local min_record_bp="${2:-${ANTISMASH_MIN_RECORD_BP:-1000}}"
  repository_helper_python_exec "${ANNOTATION_GENBANK_HELPER}" \
    list-record-ids "${gbk}" "${min_record_bp}"
}


safe_antismash_record_id() {
  local record_id="${1:-record}"
  local safe_id=""
  safe_id="$(printf '%s' "${record_id}" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_')"
  safe_id="${safe_id:0:120}"
  case "${safe_id}" in
    ""|.|..) safe_id="record" ;;
  esac
  if [[ "${safe_id}" == -* || "${safe_id}" == .* ]]; then
    safe_id="record_${safe_id}"
  fi
  printf '%s\n' "${safe_id}"
}


antismash_record_ids_are_stable() {
  local record_ids_file="$1"
  local record_id=""
  local safe_record_id=""

  ANTISMASH_UNSTABLE_RECORD_ID=""
  ANTISMASH_UNSTABLE_SAFE_ID=""
  while IFS= read -r record_id || [[ -n "${record_id}" ]]; do
    safe_record_id="$(safe_antismash_record_id "${record_id}")"
    if [[ "${safe_record_id}" != "${record_id}" ]]; then
      ANTISMASH_UNSTABLE_RECORD_ID="${record_id}"
      ANTISMASH_UNSTABLE_SAFE_ID="${safe_record_id}"
      return 1
    fi
  done < "${record_ids_file}"
}

antismash_public_failure_message() {
  local error_log="${1:-}"
  local record_id=""
  if [[ -s "${error_log}" ]] && grep -qi 'location contains overlapping exons' "${error_log}"; then
    record_id="$(sed -nE 's/^([A-Za-z0-9_.-]+): location contains overlapping exons.*$/\1/p' "${error_log}" | head -n1)"
    if [[ -n "${record_id}" ]]; then
      printf 'antiSMASH rejected record %s: overlapping exon coordinates in an annotated feature\n' "${record_id}"
    else
      printf 'antiSMASH rejected an annotated feature with overlapping exon coordinates\n'
    fi
  elif [[ -s "${error_log}" ]] && grep -Eqi 'no space left on device|disk quota exceeded' "${error_log}"; then
    printf 'antiSMASH could not write its results because storage was exhausted\n'
  elif [[ -s "${error_log}" ]] && grep -Eqi 'out of memory|cannot allocate memory|killed' "${error_log}"; then
    printf 'antiSMASH exceeded the available memory for this genome\n'
  elif [[ -s "${error_log}" ]] && grep -Eqi 'invalid.*(genbank|location|feature)|malformed.*(genbank|location|feature)' "${error_log}"; then
    printf 'antiSMASH rejected an invalid GenBank annotation feature\n'
  else
    printf 'antiSMASH exited before producing a valid result; verify the assembly annotations and retry\n'
  fi
}


sanitize_antismash_duplicate_cds_locations() {
  local in_gbk="$1"
  local out_gbk="$2"
  local genome_id="${3:-genome}"

  antismash_input_python_exec "${ANTISMASH_INPUT_PREPARER}" sanitize \
    "${in_gbk}" "${out_gbk}" --genome-id "${genome_id}"
}

run_antismash_record_shard() {
  local genome_id="$1"
  local ant_input="$2"
  local record_id="$3"
  local safe_record_id="$4"
  local ordinal="$5"
  local total_records="$6"
  local shard_dir="$7"
  local row_file="$8"
  local stdout_log="$9"
  local stderr_log="${10}"
  local started_at finished_at elapsed region_count status rc start_percent end_percent compactor_python

  mkdir -p "${shard_dir}"
  started_at="$(date +%s)"
  start_percent=$(((ordinal - 1) * 100 / total_records))
  end_percent=$((ordinal * 100 / total_records))
  antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${start_percent}" "Starting antiSMASH record shard"

  rc=0
  status="ok"
  if CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANTISMASH_SHARD_CPUS}" run_tool_with_activity "${genome_id}" "antismash" "record_${ordinal}" "${stdout_log}" "${stderr_log}" antismash_exec antismash \
      "${ant_input}" \
      --minlength "${ANTISMASH_MIN_RECORD_BP}" \
      --output-dir "${shard_dir}" \
      --output-basename "${safe_record_id}" \
      --cpus "${ANTISMASH_SHARD_CPUS}" \
      "${ANT_FLAGS_ARRAY[@]}"; then
    compactor_python="$(resolve_python_cmd)"
    if "${compactor_python}" "${ANTISMASH_SHARD_COMPACTOR}" \
        --shard-dir "${shard_dir}" \
        --record-id "${record_id}" \
        --json-name "${safe_record_id}.json" \
        --retain "${ANTISMASH_RETAIN_SHARD_WORK}" \
        >> "${stdout_log}" 2>> "${stderr_log}"; then
      antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${end_percent}" "antiSMASH record shard complete"
    else
      rc=$?
      status="failed"
      antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${end_percent}" "antiSMASH record shard compaction failed"
    fi
  else
    rc=$?
    if [[ -s "${stderr_log}" ]] \
        && grep -Eqi 'No CDS features found in record' "${stderr_log}" \
        && grep -Eqi 'No genes found, skipping record' "${stderr_log}" \
        && grep -Eqi '(^|[[:space:]])all records skipped([[:space:]]|$)' "${stderr_log}" \
        && [[ -z "$(find "${shard_dir}" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
      # A one-record shard with no CDS and no predicted genes has no scientific
      # antiSMASH result to merge.  Preserve it explicitly as empty only when
      # antiSMASH emitted the complete diagnostic and no partial output exists.
      rc=0
      status="empty"
      antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${end_percent}" "antiSMASH record shard empty (no genes)"
    else
      status="failed"
      antismash_record_progress "${genome_id}" "${record_id}" "${ordinal}" "${total_records}" "${end_percent}" "antiSMASH record shard failed"
    fi
  fi

  finished_at="$(date +%s)"
  elapsed=$((finished_at - started_at))
  region_count="$(find "${shard_dir}" -type f -name '*region*.gbk' -print 2>/dev/null | wc -l | tr -d '[:space:]')"
  region_count="${region_count:-0}"
  if ! printf '%s\t%s\t%s\t%s\t%s\n' \
      "${record_id}" "${shard_dir}" "${status}" "${elapsed}" "${region_count}" > "${row_file}"; then
    return 1
  fi
  return "${rc}"
}

merge_antismash_shard_jsons() {
  local output_json="$1"
  local python_cmd=""
  local -a merge_args=()
  shift
  [[ "$#" -gt 0 ]] || return 1
  if declare -F resolve_python_cmd >/dev/null 2>&1; then
    python_cmd="$(resolve_python_cmd)" || return 1
  elif command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  else
    return 1
  fi
  while [[ "$#" -gt 0 ]]; do
    [[ "$#" -ge 2 ]] || return 1
    merge_args+=(--record-json-pair "$1" "$2")
    shift 2
  done
  "${python_cmd}" "${ANTISMASH_SHARD_COMPACTOR}" \
    --merge-output "${output_json}" "${merge_args[@]}"
}

render_antismash_shard_web_bundle() {
  local genome_id="$1"
  local canonical_json="$2"
  local ant_out="$3"
  local shard_root="$4"
  local aggregate_stdout="$5"
  local aggregate_stderr="$6"
  local render_json="${shard_root}/assembled_web_results.json"
  local render_dir="${shard_root}/assembled_web_bundle"
  local region_record_count=""
  local preparer_python=""

  preparer_python="$(resolve_python_cmd)"
  rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
  region_record_count="$(
    "${preparer_python}" "${ANTISMASH_WEB_RESULTS_PREPARER}" \
      "${canonical_json}" "${render_json}" 2>> "${aggregate_stderr}"
  )" || return 1
  [[ "${region_record_count}" =~ ^[0-9]+$ ]] || return 1
  if [[ "${region_record_count}" -eq 0 ]]; then
    return 2
  fi

  log "${genome_id}: rendering complete antiSMASH web bundle from ${region_record_count} region-bearing record(s)"
  if ! CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANTISMASH_SHARD_CPUS}" \
      antismash_exec antismash \
        --reuse-results "${render_json}" \
        --output-dir "${render_dir}" \
        --output-basename "${genome_id}" \
        --cpus "${ANTISMASH_SHARD_CPUS}" \
        >> "${aggregate_stdout}" 2>> "${aggregate_stderr}"; then
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  fi
  if [[ ! -s "${render_dir}/index.html" || ! -s "${render_dir}/regions.js" ]]; then
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  fi
  # Keep the already assembled canonical JSON and region GBKs byte-for-byte;
  # only genuinely missing web-bundle files are copied into the result root.
  cp -a -n "${render_dir}/." "${ant_out}/" || {
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  }
  # The sharded placeholder index is intentionally replaced by antiSMASH's
  # real landing page; canonical JSON and assembled region GBKs remain intact.
  cp -f "${render_dir}/index.html" "${ant_out}/index.html" || {
    rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
    return 1
  }
  rm -rf "${render_dir}" "${render_json}" 2>/dev/null || true
  [[ -s "${ant_out}/index.html" && -s "${ant_out}/regions.js" ]]
}

html_escape() {
  printf '%s' "${1:-}" | sed \
    -e 's/&/\&amp;/g' \
    -e 's/</\&lt;/g' \
    -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' \
    -e "s/'/\\&#39;/g"
}

write_antismash_shard_index() {
  local genome_id="$1"
  local ant_out="$2"
  local record_count="$3"
  local region_count="$4"
  local display_genome region_name display_region
  display_genome="$(html_escape "$(safe_antismash_record_id "${genome_id}")")"

  {
    printf '%s\n' '<!doctype html>'
    printf '%s\n' '<html lang="en"><head><meta charset="utf-8">'
    printf '<title>antiSMASH record shards - %s</title></head><body>\n' "${display_genome}"
    printf '<h1>antiSMASH results: %s</h1>\n' "${display_genome}"
    printf '<p>Completed %s record shard(s); assembled %s region file(s).</p>\n' "${record_count}" "${region_count}"
    printf '%s\n' '<p>Shard manifest: <code>shard_manifest.tsv</code></p>'
    printf '%s\n' '<h2>Region GenBank files</h2><ul>'
    while IFS= read -r region_name; do
      [[ -n "${region_name}" ]] || continue
      display_region="$(html_escape "${region_name}")"
      printf '<li><code>%s</code></li>\n' "${display_region}"
    done < <(find "${ant_out}" -maxdepth 1 -type f -name '*region*.gbk' -printf '%f\n' 2>/dev/null | LC_ALL=C sort)
    printf '%s\n' '</ul></body></html>'
  } > "${ant_out}/index.html"
}

cleanup_antismash_assembled_outputs() {
  local ant_out="$1"
  local canonical_json="$2"
  find "${ant_out}" -maxdepth 1 -type f -name '*region*.gbk' -delete 2>/dev/null || true
  rm -f \
    "${canonical_json}" \
    "${canonical_json}.tmp" \
    "${ant_out}/index.html" \
    "${ant_out}/.done" \
    2>/dev/null || true
}

run_antismash_sharded() {
  local genome_id="$1"
  local ant_input="$2"
  local ant_out="$3"
  local record_ids_file="$4"
  local shard_root="$5"
  local aggregate_stdout="$6"
  local aggregate_stderr="$7"
  local total_records active_jobs shard_failure assembled_count successful_shards empty_shards
  local index ordinal record_id base_safe safe_record_id suffix shard_input shard_dir row_file split_manifest
  local shard_stdout shard_stderr row_status row_elapsed row_regions row_record row_dir
  local region_file source_name destination_name destination collision expected_json canonical_json
  local -a record_ids=() safe_record_ids=() shard_inputs=() shard_dirs=() row_files=() stdout_logs=() stderr_logs=()
  local -a shard_json_args=() fallback_json_files=()
  local -A used_safe_record_ids=()

  mapfile -t record_ids < "${record_ids_file}"
  total_records="${#record_ids[@]}"
  canonical_json="${ant_out}/${genome_id}.antismash.json"
  if [[ "${total_records}" -le 1 ]]; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 2
  fi

  rm -rf "${shard_root}" 2>/dev/null || true
  mkdir -p "${shard_root}/manifest_rows" "${shard_root}/record_inputs"
  : > "${aggregate_stdout}"
  : > "${aggregate_stderr}"

  for index in "${!record_ids[@]}"; do
    ordinal=$((index + 1))
    record_id="${record_ids[${index}]}"
    base_safe="$(safe_antismash_record_id "${record_id}")"
    safe_record_id="${base_safe}"
    suffix=1
    while [[ -n "${used_safe_record_ids[${safe_record_id}]+set}" ]]; do
      suffix=$((suffix + 1))
      safe_record_id="${base_safe}_${suffix}"
    done
    used_safe_record_ids["${safe_record_id}"]=1
    shard_dir="${shard_root}/$(printf '%06d' "${ordinal}")_${safe_record_id}"
    shard_input="${shard_root}/record_inputs/$(printf '%06d' "${ordinal}")_${safe_record_id}.gbk"
    row_file="${shard_root}/manifest_rows/$(printf '%06d' "${ordinal}").tsv"
    shard_stdout="${WORK_ROOT}/logs/${genome_id}.antismash.shard.$(printf '%06d' "${ordinal}").stdout.log"
    shard_stderr="${WORK_ROOT}/logs/${genome_id}.antismash.shard.$(printf '%06d' "${ordinal}").stderr.log"
    safe_record_ids+=("${safe_record_id}")
    shard_inputs+=("${shard_input}")
    shard_dirs+=("${shard_dir}")
    row_files+=("${row_file}")
    stdout_logs+=("${shard_stdout}")
    stderr_logs+=("${shard_stderr}")
  done

  split_manifest="${shard_root}/record_inputs.tsv"
  : > "${split_manifest}"
  for index in "${!record_ids[@]}"; do
    printf '%s\t%s\n' "${record_ids[${index}]}" "${shard_inputs[${index}]}" >> "${split_manifest}"
  done
  if ! antismash_input_python_exec "${ANTISMASH_INPUT_PREPARER}" split-records \
      "${ant_input}" "${split_manifest}" >> "${aggregate_stdout}" 2>> "${aggregate_stderr}"; then
    warn "${genome_id}: failed to isolate antiSMASH record inputs"
    return 1
  fi

  active_jobs=0
  shard_failure=0
  for index in "${!record_ids[@]}"; do
    ordinal=$((index + 1))
    run_antismash_record_shard \
      "${genome_id}" "${shard_inputs[${index}]}" "${record_ids[${index}]}" "${safe_record_ids[${index}]}" \
      "${ordinal}" "${total_records}" "${shard_dirs[${index}]}" "${row_files[${index}]}" \
      "${stdout_logs[${index}]}" "${stderr_logs[${index}]}" &
    active_jobs=$((active_jobs + 1))
    while [[ "${active_jobs}" -ge "${ANTISMASH_RECORD_PARALLELISM}" ]]; do
      if ! wait_for_antismash_shard_job; then shard_failure=1; fi
      active_jobs=$((active_jobs - 1))
    done
  done
  while [[ "${active_jobs}" -gt 0 ]]; do
    if ! wait_for_antismash_shard_job; then shard_failure=1; fi
    active_jobs=$((active_jobs - 1))
  done

  for index in "${!record_ids[@]}"; do
    printf '\n===== record %s (%s) =====\n' "$((index + 1))" "${record_ids[${index}]}" >> "${aggregate_stdout}"
    if [[ -f "${stdout_logs[${index}]}" ]]; then
      cat "${stdout_logs[${index}]}" >> "${aggregate_stdout}" || true
    fi
    printf '\n===== record %s (%s) =====\n' "$((index + 1))" "${record_ids[${index}]}" >> "${aggregate_stderr}"
    if [[ -f "${stderr_logs[${index}]}" ]]; then
      cat "${stderr_logs[${index}]}" >> "${aggregate_stderr}" || true
    fi
  done

  if ! printf 'record_id\tshard_dir\tstatus\telapsed_seconds\tregion_count\n' > "${ant_out}/shard_manifest.tsv"; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 1
  fi
  for index in "${!record_ids[@]}"; do
    if [[ ! -s "${row_files[${index}]}" ]]; then
      shard_failure=1
      printf '%s\t%s\t%s\t%s\t%s\n' \
        "${record_ids[${index}]}" "${shard_dirs[${index}]}" "failed" "0" "0" > "${row_files[${index}]}"
    fi
    if ! cat "${row_files[${index}]}" >> "${ant_out}/shard_manifest.tsv"; then
      cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
      return 1
    fi
  done

  assembled_count=0
  successful_shards=0
  empty_shards=0
  for index in "${!record_ids[@]}"; do
    row_record=""
    row_dir=""
    row_status="failed"
    row_elapsed="0"
    row_regions="0"
    IFS=$'\t' read -r row_record row_dir row_status row_elapsed row_regions < "${row_files[${index}]}" || true
    case "${row_status}" in
      empty)
        empty_shards=$((empty_shards + 1))
        continue
        ;;
      ok)
        successful_shards=$((successful_shards + 1))
        ;;
      *)
        shard_failure=1
        continue
        ;;
    esac
    expected_json="${shard_dirs[${index}]}/${safe_record_ids[${index}]}.json"
    if [[ ! -s "${expected_json}" ]]; then
      fallback_json_files=()
      mapfile -d '' -t fallback_json_files < <(
        find "${shard_dirs[${index}]}" -maxdepth 1 -type f -name '*.antismash.json' -print0 2>/dev/null
      )
      if [[ "${#fallback_json_files[@]}" -eq 1 && -s "${fallback_json_files[0]}" ]]; then
        expected_json="${fallback_json_files[0]}"
      else
        warn "${genome_id}: missing expected antiSMASH shard JSON for record=${record_ids[${index}]} shard=${shard_dirs[${index}]}"
        shard_failure=1
        continue
      fi
    fi
    shard_json_args+=("${record_ids[${index}]}" "${expected_json}")
    while IFS= read -r -d '' region_file; do
      source_name="${region_file##*/}"
      destination_name="${source_name}"
      case "${destination_name}" in
        "${safe_record_ids[${index}]}".*) ;;
        *) destination_name="${safe_record_ids[${index}]}.${destination_name}" ;;
      esac
      destination="${ant_out}/${destination_name}"
      if [[ -e "${destination}" ]]; then
        if cmp -s "${region_file}" "${destination}"; then
          log "${genome_id}: deduplicated assembled antiSMASH region ${destination_name}"
          continue
        fi
        warn "${genome_id}: conflicting antiSMASH region collision at ${destination}"
        shard_failure=1
        continue
      fi
      if cp -f "${region_file}" "${destination}"; then
        assembled_count=$((assembled_count + 1))
      else
        shard_failure=1
      fi
    done < <(find "${shard_dirs[${index}]}" -type f -name '*region*.gbk' -print0 2>/dev/null)
  done

  if [[ "${successful_shards}" -eq 0 ]]; then
    warn "${genome_id}: every antiSMASH record shard was empty; no sibling result is available to assemble"
    shard_failure=1
  fi
  if [[ "${shard_failure}" -eq 0 ]]; then
    if ! merge_antismash_shard_jsons "${canonical_json}" "${shard_json_args[@]}" 2>> "${aggregate_stderr}"; then
      warn "${genome_id}: failed to merge antiSMASH shard JSON into ${canonical_json}"
      shard_failure=1
    fi
  fi
  if [[ "${shard_failure}" -ne 0 ]]; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 1
  fi
  if [[ "${empty_shards}" -gt 0 ]]; then
    log "${genome_id}: retained ${empty_shards} antiSMASH record shard(s) as empty after no-gene diagnostics"
  fi
  if [[ "${assembled_count}" -gt 0 ]]; then
    if ! render_antismash_shard_web_bundle \
        "${genome_id}" "${canonical_json}" "${ant_out}" "${shard_root}" \
        "${aggregate_stdout}" "${aggregate_stderr}"; then
      warn "${genome_id}: failed to render the complete antiSMASH web bundle"
      cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
      return 1
    fi
  elif ! write_antismash_shard_index "${genome_id}" "${ant_out}" "${total_records}" "${assembled_count}"; then
    cleanup_antismash_assembled_outputs "${ant_out}" "${canonical_json}"
    return 1
  fi
  return 0
}
