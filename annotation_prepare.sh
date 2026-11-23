# GenBank preparation, reuse and configured annotation fallback coordination.

setup_converter() {
  if [[ -s "${CONVERT_PY}" ]]; then
    log "Using existing converter: ${CONVERT_PY}"
    return 0
  fi
  die "GFF3-to-GenBank converter not found: ${CONVERT_PY}. Restore the tracked helper or set CONVERT_PY to an existing compatible converter."
}

gbk_has_cds_and_translation() {
  local gbk="$1"
  [[ -s "${gbk}" ]] || return 1
  [[ -s "${GENBANK_TRANSLATION_CHECKER}" ]] || return 1
  "${VENV_PY}" "${GENBANK_TRANSLATION_CHECKER}" "${gbk}" >/dev/null 2>&1
}

gbk_has_cds() {
  local gbk="$1"
  [[ -s "${gbk}" ]] || return 1
  awk '
    /^LOCUS[[:space:]]/ { loci++ }
    /^[[:space:]]+CDS[[:space:]]/ { cds=1 }
    /^\/\/[[:space:]\r]*$/ { terminators++ }
    NF { last=$0 }
    END {
      sub(/\r$/, "", last)
      exit !(cds && loci > 0 && terminators == loci && last ~ /^\/\/[[:space:]]*$/)
    }
  ' "${gbk}"
}

backfill_gbk_translations_from_existing_cds() {
  local in_gbk="$1"
  local out_gbk="$2"
  repository_helper_python_exec "${ANNOTATION_GENBANK_HELPER}" \
    backfill-translations "${in_gbk}" "${out_gbk}"
}

normalize_gbk_record_headers() {
  local in_gbk="$1"
  local out_gbk="$2"
  repository_helper_python_exec "${ANNOTATION_GENBANK_HELPER}" \
    normalize-headers "${in_gbk}" "${out_gbk}"
}

normalize_gbk_record_headers_in_place() {
  local gbk="$1"
  local tmp="${gbk}.headers_norm"
  [[ -s "${gbk}" ]] || return 1
  if normalize_gbk_record_headers "${gbk}" "${tmp}" >/dev/null 2>&1; then
    mv -f "${tmp}" "${gbk}"
    return 0
  fi
  rm -f "${tmp}" 2>/dev/null || true
  return 1
}

ensure_annotation_tooling() {
  local braker_ok=0
  local fun_ok=0
  local need_braker=0
  local need_fun=0
  local method
  local old_ifs="$IFS"
  local methods=()

  IFS=','
  read -r -a methods <<< "${ANNOTATION_FALLBACK_ORDER}"
  IFS="$old_ifs"

  for method in "${methods[@]}"; do
    method="$(echo "${method}" | tr -d '[:space:]')"
    case "${method}" in
      braker3)
        if [[ "${BRAKER3_ENABLED}" == "1" ]]; then
          need_braker=1
        else
          warn "BRAKER3 appears in ANNOTATION_FALLBACK_ORDER but BRAKER3_ENABLED=0; BRAKER3 will be skipped."
        fi
        ;;
      funannotate) need_fun=1 ;;
      none|skip|off) ;;
      "") ;;
      *) warn "Unknown annotation fallback method in ANNOTATION_FALLBACK_ORDER: ${method}" ;;
    esac
  done

  if [[ "${need_braker}" -eq 1 ]]; then
    if command -v braker.pl >/dev/null 2>&1; then
      braker_ok=1
      log "BRAKER3 available on host PATH (braker.pl)."
    elif [[ "${ENGINE}" == "docker" ]] && ensure_docker_image "BRAKER3" "$(docker_image_from_uri "${BRAKER_IMAGE_URI}")"; then
      braker_ok=1
    elif [[ "${ENGINE}" != "docker" ]] && ensure_prepared_sif "BRAKER3" "${BRAKER_SIF}" "${BRAKER_IMAGE_URI}"; then
      braker_ok=1
    fi
  fi

  if [[ "${need_fun}" -eq 1 ]]; then
    if command -v funannotate >/dev/null 2>&1; then
      fun_ok=1
      log "funannotate available on host PATH."
    elif [[ "${ENGINE}" == "docker" ]] && ensure_funannotate_docker_runtime; then
      fun_ok=1
    elif [[ "${ENGINE}" != "docker" ]] && ensure_funannotate_sif_runtime; then
      fun_ok=1
    fi
  fi

  if [[ "${need_braker}" -eq 1 && "${braker_ok}" -eq 0 ]]; then
    die "BRAKER3 is required by ANNOTATION_FALLBACK_ORDER but unavailable after runtime preparation. Remove braker3 from the order only if it is not required."
  fi
  if [[ "${need_fun}" -eq 1 && "${fun_ok}" -eq 0 ]]; then
    die "funannotate is required by ANNOTATION_FALLBACK_ORDER but unavailable after runtime preparation. Provide FUNANNOTATE_SIF or a prepared Docker image."
  fi
  if [[ "${need_braker}" -eq 0 && "${need_fun}" -eq 0 ]]; then
    warn "No annotation fallback methods configured. Annotated GenBank inputs can still run; FASTA-only inputs may be dropped."
  fi
}

fungal_annotation_fallback_needed() {
  local candidate root staged source_gbk source_fasta
  for candidate in "$@"; do
    [[ "$(route_taxon_for_genome "${candidate}")" == "fungi" ]] || continue
    root="$(route_root_for_genome "${candidate}")"
    staged="${RESULTS_ROOT}/input_gbks/${candidate}.gbk"
    if [[ "${FORCE}" != "1" && -s "${staged}" ]] && gbk_has_cds_and_translation "${staged}"; then
      continue
    fi
    source_gbk=""
    if source_gbk="$(resolve_genbank_for_stem "${candidate}" "${root}")" \
        && gbk_has_cds_and_translation "${source_gbk}"; then
      continue
    fi
    source_fasta=""
    if source_fasta="$(resolve_fasta_for_stem "${candidate}" "${root}")" && [[ -s "${source_fasta}" ]]; then
      return 0
    fi
  done
  return 1
}

bacterial_genbank_prepare() {
  local python_cmd="$1" sanitizer="$2" manifest="$3" input_root="$4" provenance="$5"
  shift 5
  if [[ "${sanitizer}" == "${SCRIPT_DIR}/bin/sanitize_bacterial_genbank.py" ]]; then
    FORCE="${FORCE:-0}" "${python_cmd}" "${SCRIPT_DIR}/bin/cached_genbank.py" bacteria \
      --route-manifest "${manifest}" --acquired-root "${input_root}" \
      --provenance "${provenance}" "$@"
  else
    "${python_cmd}" "${sanitizer}" "$@"
  fi
}

prepare_original_fungal_genbank() {
  local source="$1" destination="$2" genome_id="$3" input_root="$4"
  if [[ "${ENGINE}" == "docker" && "${ANNOTATION_GENBANK_HELPER}" == "${SCRIPT_DIR}/bin/annotation_genbank.py" ]]; then
    FORCE="${FORCE:-0}" repository_helper_python_exec "${SCRIPT_DIR}/bin/cached_genbank.py" fungi \
      --input "${source}" --output "${destination}" --genome-id "${genome_id}" \
      --route-manifest "${GENOME_TAXON_MANIFEST}" --acquired-root "${input_root}" \
      --provenance "${RESULTS_ROOT}/reproducibility/accession_cache/${genome_id}.fungi.json" >/dev/null
  else
    cp -f "${source}" "${destination}"
    normalize_gbk_record_headers_in_place "${destination}" || true
  fi
}

annotate_genome_with_fallbacks() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  local method
  local order_csv="${ANNOTATION_FALLBACK_ORDER}"
  local old_ifs="$IFS"
  ANNOTATION_FALLBACK_METHOD=""
  ANNOTATION_FALLBACK_FAILURE_REASON=""
  ANNOTATION_FALLBACK_FAILURE_DETAIL=""
  IFS=','
  read -r -a methods <<< "${order_csv}"
  IFS="$old_ifs"

  for method in "${methods[@]}"; do
    method="$(echo "${method}" | tr -d '[:space:]')"
    case "${method}" in
      braker3)
        if [[ "${BRAKER3_ENABLED}" != "1" ]]; then
          warn "${genome_id}: BRAKER3 disabled (BRAKER3_ENABLED=0); skipping braker3 fallback."
          continue
        fi
        genome_annotation_decision "${genome_id}" "yes" "braker3" "BRAKER3 annotation required"
        if run_braker3_to_gbk "${genome_id}" "${fasta}" "${out_gbk}"; then
          ANNOTATION_FALLBACK_METHOD="braker3"
          return 0
        fi
        ;;
      funannotate)
        genome_annotation_decision "${genome_id}" "yes" "funannotate" "Funannotate annotation required"
        if run_funannotate_predict_to_gbk "${genome_id}" "${fasta}" "${out_gbk}"; then
          ANNOTATION_FALLBACK_METHOD="funannotate"
          return 0
        fi
        if [[ -n "${FUNANNOTATE_LAST_FAILURE_STATUS}" ]]; then
          ANNOTATION_FALLBACK_FAILURE_REASON="${FUNANNOTATE_LAST_FAILURE_STATUS}"
          ANNOTATION_FALLBACK_FAILURE_DETAIL="${FUNANNOTATE_LAST_FAILURE_DETAIL}"
        fi
        ;;
      "") ;;
      *)
        warn "${genome_id}: unknown annotation fallback method in ANNOTATION_FALLBACK_ORDER: ${method}"
        ;;
    esac
  done
  return 1
}

prepare_annotation_tooling() {
  FUNGAL_ANNOTATION_FALLBACK_NEEDED=0
  if [[ "${HAS_FUNGAL_ROUTES}" -eq 1 ]] \
      && fungal_annotation_fallback_needed "$@"; then
    FUNGAL_ANNOTATION_FALLBACK_NEEDED=1
    log "Fungal input inspection selected an annotation fallback; bootstrapping configured annotation tooling."
    setup_converter
    ensure_annotation_tooling
  elif [[ "${HAS_FUNGAL_ROUTES}" -eq 1 ]]; then
    log "Skipping fungal annotation runtime bootstrap: every reusable fungal GenBank already has complete non-empty CDS translations, or no fallback-capable FASTA is present."
  else
    log "Skipping fungal annotation runtime bootstrap: no fungal routes are present."
  fi
}

prepare_genome_genbank() {
  # Update caller-local preparation outputs without losing fallback state.
  # Outputs: gbk_used, gbk_status, prediction_method, ant_input,
  # antismash_record_ids_file and antismash_input_sanitized.
  local genome_id="$1" taxon_group="$2" genome_input_root="$3"
  local fasta="$4" gb_src="$5" staged_gbk="$6" per_tmp="$7" GENLOG="$8"
  local bacteria_source bacterial_record_map bacterial_sanitize_summary bacterial_stage_temp python_cmd
  local fallback_method
  gbk_used=""
  gbk_status="missing"
  if [[ "${taxon_group}" == "bacteria" ]]; then
    ant_input="${per_tmp}/${genome_id}.bacteria.antismash.gbk"
    antismash_record_ids_file="${per_tmp}/antismash_record_ids.txt"
    bacterial_record_map="${RESULTS_ROOT}/summary_tables/bacterial_record_maps/${genome_id}.record_map.tsv"
    bacteria_source=""
    if [[ -n "${gb_src}" && -s "${gb_src}" ]]; then
      bacteria_source="${gb_src}"
    elif [[ -n "${fasta}" && -s "${fasta}" ]]; then
      bacteria_source="${fasta}"
    fi
    if [[ -z "${bacteria_source}" ]]; then
      gbk_status="no_bacterial_sequence_input"
    else
      python_cmd="$(resolve_python_cmd)" || true
      if [[ -n "${python_cmd}" ]] && bacterial_sanitize_summary="$(
          bacterial_genbank_prepare "${python_cmd}" "${BACTERIAL_GENBANK_SANITIZER}" \
            "${GENOME_TAXON_MANIFEST}" "${genome_input_root}" \
            "${RESULTS_ROOT}/reproducibility/accession_cache/${genome_id}.bacteria.json" \
            --input "${bacteria_source}" \
            --output "${ant_input}" \
            --record-map "${bacterial_record_map}" \
            --record-ids "${antismash_record_ids_file}" \
            --genome-id "${genome_id}" \
            --min-record-bp "${ANTISMASH_MIN_RECORD_BP}" \
            --max-record-bp "${ANTISMASH_MAX_RECORD_BP}" 2>> "${GENLOG}"
        )"; then
        printf '%s\n' "${bacterial_sanitize_summary}" | tee -a "${GENLOG}"
        bacterial_stage_temp="${staged_gbk}.tmp.${BASHPID:-$$}"
        if cp -f "${ant_input}" "${bacterial_stage_temp}" \
            && mv -f "${bacterial_stage_temp}" "${staged_gbk}"; then
          gbk_used="${staged_gbk}"
          gbk_status="bacterial_sequence_sanitized"
          antismash_input_sanitized=1
          genome_stage_progress "${genome_id}" "annotation" 25 "Feature-free bacterial GenBank ready"
        else
          rm -f "${bacterial_stage_temp}" 2>/dev/null || true
          gbk_status="bacterial_staging_failed"
        fi
      else
        gbk_status="bacterial_sanitizer_failed"
      fi
    fi
  else

  # 1) Reuse staged GBK if present
  if [[ -s "${staged_gbk}" ]] && gbk_has_cds_and_translation "${staged_gbk}"; then
    normalize_gbk_record_headers_in_place "${staged_gbk}" || true
    gbk_used="${staged_gbk}"
    gbk_status="staged_ok"
    prediction_method="existing_cds"
    log "${genome_id}: using staged GBK: ${staged_gbk}" | tee -a "${GENLOG}"
    genome_annotation_decision "${genome_id}" "no" "existing_cds" "Complete CDS translations already available"
    genome_stage_progress "${genome_id}" "annotation" 20 "Staged GenBank ready"
  fi

  # 2) If no staged GBK, try original annotated GenBank, else annotation fallback chain
  if [[ -z "${gbk_used}" ]]; then
    if [[ -n "${gb_src}" && -s "${gb_src}" ]]; then
      if gbk_has_cds_and_translation "${gb_src}"; then
        if ! prepare_original_fungal_genbank "${gb_src}" "${staged_gbk}" "${genome_id}" "${genome_input_root}"; then
          cp -f "${gb_src}" "${staged_gbk}"
          normalize_gbk_record_headers_in_place "${staged_gbk}" || true
        fi
        gbk_used="${staged_gbk}"
        gbk_status="original_ok"
        prediction_method="existing_cds"
        log "${genome_id}: staged original GBK (has CDS+translation): ${gb_src}" | tee -a "${GENLOG}"
        genome_annotation_decision "${genome_id}" "no" "existing_cds" "Complete CDS translations already available"
      else
        gbk_status="original_missing_translations"
        log "${genome_id}: original GBK lacks usable CDS translations; using annotation workflow (${ANNOTATION_FALLBACK_ORDER})" | tee -a "${GENLOG}"
      fi
    else
      gbk_status="missing_genbank"
      log "${genome_id}: no original GBK detected; will try fallback annotation chain (${ANNOTATION_FALLBACK_ORDER}) if FASTA available" | tee -a "${GENLOG}"
    fi

    if [[ -z "${gbk_used}" ]]; then
      if [[ -n "${fasta}" && -s "${fasta}" ]]; then
        fallback_method=""
        genome_stage_progress "${genome_id}" "annotation" 10 "Running annotation fallback"
        if annotate_genome_with_fallbacks "${genome_id}" "${fasta}" "${staged_gbk}"; then
          fallback_method="${ANNOTATION_FALLBACK_METHOD:-annotation}"
          prediction_method="${fallback_method}"
          normalize_gbk_record_headers_in_place "${staged_gbk}" || true
          if gbk_has_cds_and_translation "${staged_gbk}"; then
            gbk_used="${staged_gbk}"
            gbk_status="${fallback_method}_fixed"
            genome_stage_progress "${genome_id}" "annotation" 25 "Annotation fallback produced GenBank"
          else
            gbk_status="${fallback_method}_no_translations"
            rm -f "${staged_gbk}" 2>/dev/null || true
          fi
        else
          gbk_status="${ANNOTATION_FALLBACK_FAILURE_REASON:-annotation_fallbacks_failed}"
          if [[ -n "${ANNOTATION_FALLBACK_FAILURE_DETAIL}" ]]; then
            log "${genome_id}: annotation fallback detail: ${ANNOTATION_FALLBACK_FAILURE_DETAIL}" | tee -a "${GENLOG}"
          fi
        fi
      else
        gbk_status="no_fasta_for_annotation"
      fi
    fi
  fi
  fi
}
