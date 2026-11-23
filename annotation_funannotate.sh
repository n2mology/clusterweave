# Funannotate policy, prepared runtime dispatch and prediction.

funannotate_trim() {
  printf '%s\n' "${1:-}" | awk '{$1=$1; print}'
}

funannotate_lower() {
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

funannotate_env_value() {
  local key="$1"
  local default="${2:-}"
  local value="${!key:-}"
  value="$(funannotate_trim "${value}")"
  [[ -n "${value}" ]] || value="${default}"
  printf '%s\n' "${value}"
}

funannotate_busco_env_value() {
  local key="$1"
  local default="${2:-}"
  local value=""
  value="$(funannotate_env_value "${key}" "${default}")"
  case "$(funannotate_lower "${value}")" in
    auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      value="${default}"
      ;;
  esac
  printf '%s\n' "${value}"
}

funannotate_is_auto_busco() {
  case "$(funannotate_lower "${1:-}")" in
    ""|auto|taxonomy|lineage|from-taxonomy) return 0 ;;
    *) return 1 ;;
  esac
}

funannotate_is_auto_organism() {
  case "$(funannotate_lower "${1:-}")" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|fungal_sp|"fungal sp") return 0 ;;
    *) return 1 ;;
  esac
}

funannotate_species_from_text() {
  local value="${1:-}"
  local first=""
  local second=""
  value="${value//_/ }"
  value="$(funannotate_trim "${value}")"
  if [[ -z "${value}" ]]; then
    printf '%s\n' "Fungal sp"
    return 0
  fi
  read -r first second _ <<< "${value}"
  if [[ -n "${second}" ]]; then
    printf '%s %s\n' "${first}" "${second%.}"
  else
    printf '%s sp\n' "${first}"
  fi
}

funannotate_mapping_row() {
  local genome_id="$1"
  [[ -s "${GENOME_MAPPING_FILE}" ]] || return 1
  awk -F '\t' -v target="${genome_id}" '
    BEGIN { t = tolower(target) }
    tolower($1) == "accession" { next }
    {
      accession = tolower($1)
      genome = tolower($2)
      split(accession, accession_parts, /\./)
      accession_base = accession_parts[1]
      if (t == genome || t == accession || (t != "" && t == accession_base)) {
        print
        exit
      }
    }
  ' "${GENOME_MAPPING_FILE}"
}

funannotate_lineage_has_id() {
  local blob="${1:-}"
  local taxid="$2"
  local normalized=""
  normalized="${blob//[^0-9]/,}"
  [[ ",${normalized}," == *",${taxid},"* ]]
}

resolve_funannotate_policy() {
  local genome_id="$1"
  local row=""
  local map_accession=""
  local map_genome_id=""
  local map_taxid=""
  local map_size=""
  local map_organism=""
  local map_lineage_ids=""
  local map_lineage_names=""
  local lineage_blob=""
  local db_setting=""
  local default_db=""
  local fungi_db=""
  local dikarya_db=""
  local mucoromycota_db=""

  FUNANNOTATE_RESOLVED_BUSCO_DB="${FUNANNOTATE_BUSCO_DB}"
  FUNANNOTATE_RESOLVED_SPECIES="${FUNANNOTATE_ORGANISM_NAME}"
  FUNANNOTATE_RESOLVED_SOURCE="explicit"

  row="$(funannotate_mapping_row "${genome_id}" || true)"
  if [[ -n "${row}" ]]; then
    IFS=$'\t' read -r map_accession map_genome_id map_taxid map_size map_organism map_lineage_ids map_lineage_names <<< "${row}"
    lineage_blob="${map_lineage_ids},${map_taxid}"
  fi

  if funannotate_is_auto_organism "${FUNANNOTATE_ORGANISM_NAME}"; then
    if [[ -n "${map_organism}" ]]; then
      FUNANNOTATE_RESOLVED_SPECIES="$(funannotate_species_from_text "${map_organism}")"
    else
      FUNANNOTATE_RESOLVED_SPECIES="$(funannotate_species_from_text "${genome_id}")"
    fi
  else
    FUNANNOTATE_RESOLVED_SPECIES="${FUNANNOTATE_ORGANISM_NAME%.}"
  fi

  db_setting="$(funannotate_env_value FUNANNOTATE_BUSCO_DB auto)"
  if ! funannotate_is_auto_busco "${db_setting}"; then
    FUNANNOTATE_RESOLVED_BUSCO_DB="${db_setting}"
    FUNANNOTATE_RESOLVED_SOURCE="explicit"
  elif [[ -n "${row}" ]]; then
    default_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_DEFAULT dikarya)"
    fungi_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_FUNGI fungi)"
    dikarya_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_DIKARYA dikarya)"
    if funannotate_lineage_has_id "${lineage_blob}" "4827"; then
      mucoromycota_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MUCOROMYCOTA "${fungi_db}")"
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MUCORALES "${mucoromycota_db}")"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:mucorales"
    elif funannotate_lineage_has_id "${lineage_blob}" "1913637"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MUCOROMYCOTA "${fungi_db}")"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:mucoromycota"
    elif funannotate_lineage_has_id "${lineage_blob}" "6029"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_MICROSPORIDIA microsporidia)"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:microsporidia"
    elif funannotate_lineage_has_id "${lineage_blob}" "4890"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_ASCOMYCOTA ascomycota)"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:ascomycota"
    elif funannotate_lineage_has_id "${lineage_blob}" "5204"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_BASIDIOMYCOTA basidiomycota)"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:basidiomycota"
    elif funannotate_lineage_has_id "${lineage_blob}" "451864"; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="${dikarya_db}"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:dikarya"
    elif funannotate_lineage_has_id "${lineage_blob}" "4751" || [[ -n "${map_taxid}" ]]; then
      FUNANNOTATE_RESOLVED_BUSCO_DB="${fungi_db}"
      FUNANNOTATE_RESOLVED_SOURCE="taxonomy:fungi"
    else
      FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_NO_TAXONOMY "${default_db}")"
      FUNANNOTATE_RESOLVED_SOURCE="fallback:no-taxonomy"
    fi
  else
    default_db="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_DEFAULT dikarya)"
    FUNANNOTATE_RESOLVED_BUSCO_DB="$(funannotate_busco_env_value FUNANNOTATE_BUSCO_DB_NO_TAXONOMY "${default_db}")"
    FUNANNOTATE_RESOLVED_SOURCE="fallback:no-taxonomy"
  fi

  FUNANNOTATE_RESOLVED_BUSCO_DB="$(printf '%s' "${FUNANNOTATE_RESOLVED_BUSCO_DB}" | tr -d '[:space:]')"
  case "${FUNANNOTATE_RESOLVED_BUSCO_DB}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      FUNANNOTATE_RESOLVED_BUSCO_DB="dikarya"
      ;;
  esac

  case "${FUNANNOTATE_RESOLVED_SPECIES}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|Fungal_sp|"Fungal sp")
      FUNANNOTATE_RESOLVED_SPECIES="Fungal_sp"
      ;;
  esac
}

funannotate_busco_db_available() {
  local db="$1"
  local fun_cmd="${2:-funannotate}"
  local use_docker="${3:-0}"
  local use_sif="${4:-0}"
  local db_root="${FUNANNOTATE_DB:-/opt/databases}"

  case "${db}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      return 1
      ;;
  esac

  if [[ "${use_docker}" -eq 1 ]]; then
    CLUSTERWEAVE_CHILD_DOCKER_CPUS=1 docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" sh -lc \
      'db="$1"; base="${FUNANNOTATE_DB:-/opt/databases}"; test -d "${base}/${db}/hmms" && find "${base}/${db}/hmms" -type f -print -quit | grep -q .' \
      sh "${db}" >/dev/null 2>&1
    return $?
  fi

  if [[ "${use_sif}" -eq 1 ]]; then
    sing_exec "${FUNANNOTATE_SIF}" sh -lc \
      'db="$1"; base="${FUNANNOTATE_DB:-/opt/databases}"; test -d "${base}/${db}/hmms" && find "${base}/${db}/hmms" -type f -print -quit | grep -q .' \
      sh "${db}" >/dev/null 2>&1
    return $?
  fi

  [[ -d "${db_root}/${db}/hmms" ]] || return 1
  find "${db_root}/${db}/hmms" -type f -print -quit 2>/dev/null | grep -q .
}

validate_funannotate_busco_db() {
  local db="$1"
  local source="$2"
  local genome_id="$3"
  local fun_cmd="$4"
  local use_docker="$5"
  local use_sif="$6"
  local fallback_db

  if funannotate_busco_db_available "${db}" "${fun_cmd}" "${use_docker}" "${use_sif}"; then
    printf '%s\n' "${db}"
    return 0
  fi

  if [[ "${source}" == "explicit" ]]; then
    warn "${genome_id}: explicit FUNANNOTATE_BUSCO_DB='${db}' is not installed in the active funannotate runtime"
    return 1
  fi

  fallback_db="$(printf '%s' "${FUNANNOTATE_BUSCO_DB_DEFAULT:-dikarya}" | tr -d '[:space:]')"
  case "${fallback_db}" in
    ""|"{}"|none|null|auto|taxonomy|lineage|from-taxonomy|auto-lineage|auto_lineage|auto-lineage-euk|auto-lineage-prok)
      fallback_db="dikarya"
      ;;
  esac

  if [[ "${db}" != "${fallback_db}" ]] && funannotate_busco_db_available "${fallback_db}" "${fun_cmd}" "${use_docker}" "${use_sif}"; then
    warn "${genome_id}: auto-selected BUSCO db '${db}' for ${source} is not installed in the active funannotate runtime; falling back to broad '${fallback_db}'"
    printf '%s\n' "${fallback_db}"
    return 0
  fi

  warn "${genome_id}: selected BUSCO db '${db}' and fallback '${fallback_db}' are not installed in the active funannotate runtime"
  return 1
}


funannotate_predict_failed_in_p2g() {
  local fun_log="$1"
  [[ -s "${fun_log}" ]] || return 1
  grep -Eiq \
    'CMD ERROR:[[:space:]]*diamond blastx|funannotate-p2g\.py.*(error|failed|exception|traceback)|p2g\.diamond.*(error|failed|missing|no such file)|protein_alignments\.gff3.*(error|failed|missing|no such file)|(error|failed|exception|traceback|missing|no such file).*(funannotate-p2g\.py|p2g\.diamond|protein_alignments\.gff3)' \
    "${fun_log}"
}

funannotate_predict_failure_status() {
  local fun_log="$1"
  local not_enough_line=""
  local validated_line=""
  local training_models=""
  local required_models=""
  local validated_buscos=""
  [[ -s "${fun_log}" ]] || return 1

  not_enough_line="$(grep -E "Not enough gene models [0-9,]+ to train Augustus \([0-9,]+ required\)" "${fun_log}" | tail -n1 || true)"
  [[ -n "${not_enough_line}" ]] || return 1

  training_models="$(printf '%s\n' "${not_enough_line}" | sed -E 's/.*Not enough gene models ([0-9,]+) to train Augustus \(([0-9,]+) required\).*/\1/' | tr -d ',')"
  required_models="$(printf '%s\n' "${not_enough_line}" | sed -E 's/.*Not enough gene models ([0-9,]+) to train Augustus \(([0-9,]+) required\).*/\2/' | tr -d ',')"
  validated_line="$(grep -Eo "[0-9,]+ BUSCO predictions validated" "${fun_log}" | tail -n1 || true)"
  if [[ -n "${validated_line}" ]]; then
    validated_buscos="$(printf '%s\n' "${validated_line}" | sed -E 's/ .*//' | tr -d ',')"
  fi

  if [[ -n "${validated_buscos}" && "${validated_buscos}" == "${training_models}" ]]; then
    printf 'funannotate_busco_training_insufficient\tvalidated_busco_models=%s required_training_models=%s\n' "${validated_buscos}" "${required_models}"
  else
    printf 'funannotate_training_models_insufficient\ttraining_models=%s required_training_models=%s\n' "${training_models}" "${required_models}"
  fi
}

funannotate_normalize_min_training_models_fallback() {
  local value="${1:-150}"
  case "${value}" in
    ''|*[!0-9]*) value=150 ;;
    *)
      value="$(printf '%s\n' "${value}" | sed -E 's/^0+//')"
      [[ -n "${value}" ]] || value=0
      if [[ "${#value}" -gt 3 ]]; then
        value=200
      fi
      ;;
  esac
  if (( value < 100 )); then
    value=100
  elif (( value >= 200 )); then
    value=199
  fi
  printf '%s\n' "${value}"
}

funannotate_busco_training_fallback_threshold() {
  local fun_log="$1"
  local parsed=""
  local status=""
  local detail=""
  local validated_models=""
  local required_models=""
  local fallback_floor=""

  parsed="$(funannotate_predict_failure_status "${fun_log}" || true)"
  [[ -n "${parsed}" ]] || return 1
  IFS=$'\t' read -r status detail <<< "${parsed}"
  [[ "${status}" == "funannotate_busco_training_insufficient" ]] || return 1

  validated_models="$(printf '%s\n' "${detail}" | grep -Eo 'validated_busco_models=[0-9]+' | tail -n1 | cut -d= -f2 || true)"
  required_models="$(printf '%s\n' "${detail}" | grep -Eo 'required_training_models=[0-9]+' | tail -n1 | cut -d= -f2 || true)"
  [[ "${validated_models}" =~ ^[0-9]+$ && "${required_models}" =~ ^[0-9]+$ ]] || return 1

  fallback_floor="$(funannotate_normalize_min_training_models_fallback "${FUNANNOTATE_MIN_TRAINING_MODELS_FALLBACK:-150}")"
  (( validated_models >= fallback_floor && required_models > fallback_floor )) || return 1
  printf '%s\n' "${fallback_floor}"
}

funannotate_record_predict_failure() {
  local genome_id="$1"
  local fun_log="$2"
  local busco_db="$3"
  local source="$4"
  local parsed=""
  local status=""
  local detail=""
  FUNANNOTATE_LAST_FAILURE_STATUS=""
  FUNANNOTATE_LAST_FAILURE_DETAIL=""

  if parsed="$(funannotate_predict_failure_status "${fun_log}")"; then
    IFS=$'\t' read -r status detail <<< "${parsed}"
    FUNANNOTATE_LAST_FAILURE_STATUS="${status}"
    FUNANNOTATE_LAST_FAILURE_DETAIL="${detail} busco_db=${busco_db} policy=${source}"
    warn "${genome_id}: funannotate could not train AUGUSTUS; ${FUNANNOTATE_LAST_FAILURE_DETAIL}"
  fi
}

funannotate_exec() {
  local use_docker="$1"
  local use_sif="$2"
  shift 2
  # clean and augustus_parallel create relative scratch directories. Keep those
  # inside the owning genome's writable work tree under read-only confinement.
  (
    if [[ -n "${fun_work_cwd:-}" ]]; then
      cd -- "${fun_work_cwd}" || exit 1
    fi
    if [[ "${use_docker}" -eq 1 ]]; then
      CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANNO_CPUS}" \
        CLUSTERWEAVE_CHILD_DOCKER_WORKDIR="${fun_work_cwd:-}" \
        docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" "$@"
    elif [[ "${use_sif}" -eq 1 ]]; then
      CLUSTERWEAVE_CHILD_SIF_WORKDIR="${fun_work_cwd:-}" \
        sing_exec "${FUNANNOTATE_SIF}" "$@"
    else
      "$@"
    fi
  )
}

funannotate_exec_with_activity() {
  local use_docker="$1"
  local use_sif="$2"
  local genome_id="$3"
  local fun_log="$4"
  shift 4
  run_tool_with_activity "${genome_id}" "funannotate" "predict" "${fun_log}" "${fun_log}" \
    funannotate_exec "${use_docker}" "${use_sif}" "$@"
}

ensure_funannotate_docker_runtime() {
  local image=""
  image="$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")"
  [[ -n "${image}" ]] || return 1

  if docker image inspect "${image}" >/dev/null 2>&1; then
    log "funannotate Docker image present: ${image}"
    return 0
  fi

  warn "funannotate Docker image missing: ${image}"
  warn "AUTO_BUILD_FUNANNOTATE_DOCKER=${AUTO_BUILD_FUNANNOTATE_DOCKER} is accepted for compatibility; canonical jobs do not build images."
  runtime_preparation_hint
  return 1
}

ensure_funannotate_sif_runtime() {
  if [[ -s "${FUNANNOTATE_SIF}" ]]; then
    log "funannotate SIF present: ${FUNANNOTATE_SIF}"
    return 0
  fi

  warn "funannotate SIF missing: ${FUNANNOTATE_SIF}"
  warn "AUTO_BUILD_FUNANNOTATE_SIF=${AUTO_BUILD_FUNANNOTATE_SIF} is accepted for compatibility; canonical jobs do not build images."
  runtime_preparation_hint
  return 1
}

remap_gbk_ids_from_fasta_hashes() {
  local original_fasta="$1"
  local renamed_fasta="$2"
  local in_gbk="$3"
  local out_gbk="$4"
  local map_tsv="$5"
  repository_helper_python_exec "${ANNOTATION_GENBANK_HELPER}" remap-ids \
    "${original_fasta}" "${renamed_fasta}" "${in_gbk}" "${out_gbk}" "${map_tsv}"
}

run_funannotate_predict_to_gbk() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  [[ -s "${fasta}" ]] || return 1

  local fun_out="${RESULTS_ROOT}/funannotate/${genome_id}"
  local fun_run="${WORK_ROOT}/tmp/${genome_id}/funannotate_run"
  local fun_tmp="${WORK_ROOT}/tmp/${genome_id}/funannotate_tmp"
  local fun_work_cwd="${WORK_ROOT}/tmp/${genome_id}/funannotate_cwd"
  local fun_log="${WORK_ROOT}/logs/${genome_id}.funannotate.log"
  local tmp_out="${out_gbk}.tmp"
  local remap_out="${out_gbk}.remap"
  local pred_gbk=""
  local pred_gff3=""
  local prep_dir="${WORK_ROOT}/tmp/${genome_id}/funannotate_prep"
  local sorted_fa="${prep_dir}/${genome_id}.sorted.fna"
  local cleaned_fa="${prep_dir}/${genome_id}.clean.fna"
  local predict_fa="${cleaned_fa}"
  local id_map_tsv="${WORK_ROOT}/tmp/${genome_id}/funannotate_id_map.tsv"
  local safe_name="${genome_id//_/}"
  resolve_funannotate_policy "${genome_id}"
  local species_name="${FUNANNOTATE_RESOLVED_SPECIES%.}"
  local busco_db="${FUNANNOTATE_RESOLVED_BUSCO_DB}"
  local busco_seed_species="${FUNANNOTATE_BUSCO_SEED_SPECIES}"
  local fun_predict_extra=()
  busco_db="$(printf '%s' "${busco_db}" | tr -d '[:space:]')"
  if [[ -z "${busco_db}" || "${busco_db}" == "{}" || "${busco_db}" == "none" || "${busco_db}" == "null" ]]; then
    warn "${genome_id}: invalid FUNANNOTATE_BUSCO_DB='${busco_db}'; using dikarya"
    busco_db="dikarya"
  fi
  busco_seed_species="$(printf '%s' "${busco_seed_species}" | tr -d '[:space:]')"
  if [[ -n "${busco_seed_species}" ]]; then
    case "${busco_seed_species}" in
      "{}"|none|null)
        warn "${genome_id}: ignoring invalid FUNANNOTATE_BUSCO_SEED_SPECIES='${busco_seed_species}'"
        ;;
      *)
        fun_predict_extra+=(--busco_seed_species "${busco_seed_species}")
        log "${genome_id}: using BUSCO seed species override: ${busco_seed_species}"
        ;;
    esac
  fi
  if [[ "${species_name}" == "Fungal_sp" || "${species_name}" == "Fungal sp" ]]; then
    local gnorm="${genome_id//[^A-Za-z0-9_]/_}"
    local g1="${gnorm%%_*}"
    local rest="${gnorm#*_}"
    local g2="${rest%%_*}"
    if [[ -n "${g1}" && -n "${g2}" ]]; then
      species_name="${g1} ${g2}"
    fi
  fi
  : > "${fun_log}"
  mkdir -p "${fun_out}" "${prep_dir}" "${fun_tmp}" "${fun_work_cwd}"
  rm -rf "${fun_run}" 2>/dev/null || true
  mkdir -p "${fun_run}"
  rm -f "${tmp_out}" "${remap_out}" "${sorted_fa}" "${cleaned_fa}" "${id_map_tsv}" 2>/dev/null || true

  local fun_cmd="funannotate"
  local use_sif=0
  local use_docker=0

  if [[ "${ENGINE}" == "docker" ]]; then
    use_docker=1
  elif [[ -f "${FUNANNOTATE_SIF}" ]]; then
    use_sif=1
    if sing_exec "${FUNANNOTATE_SIF}" test -x "/venv/bin/funannotate" >/dev/null 2>&1; then
      fun_cmd="/venv/bin/funannotate"
    fi
  elif ! command -v funannotate >/dev/null 2>&1; then
    warn "${genome_id}: funannotate unavailable (missing FUNANNOTATE_SIF and funannotate binary); skipping funannotate"
    return 3
  fi

  if ! busco_db="$(validate_funannotate_busco_db "${busco_db}" "${FUNANNOTATE_RESOLVED_SOURCE}" "${genome_id}" "${fun_cmd}" "${use_docker}" "${use_sif}")"; then
    warn "${genome_id}: no installed funannotate BUSCO database available for predict"
    return 2
  fi
  log "${genome_id}: funannotate policy ${FUNANNOTATE_RESOLVED_SOURCE}: species='${species_name}' busco_db='${busco_db}'"

  log "${genome_id}: running funannotate prepare workflow (sort + clean)"
  tool_activity_emit_progress "${genome_id}" "funannotate" "prepare" "Preparing assembly"
  annotation_runtime_argv funannotate-sort \
    --tool-command "${fun_cmd}" --input "${fasta}" --output "${sorted_fa}"
  if ! funannotate_exec "${use_docker}" "${use_sif}" "${ANNOTATION_RUNTIME_ARGV[@]}" >> "${fun_log}" 2>&1; then
    warn "${genome_id}: funannotate sort failed (see ${fun_log})"
    return 2
  fi
  annotation_runtime_argv funannotate-clean \
    --tool-command "${fun_cmd}" --input "${sorted_fa}" --output "${cleaned_fa}"
  if ! funannotate_exec "${use_docker}" "${use_sif}" "${ANNOTATION_RUNTIME_ARGV[@]}" >> "${fun_log}" 2>&1; then
    warn "${genome_id}: funannotate clean failed; using sorted FASTA for predict"
    cp -f "${sorted_fa}" "${cleaned_fa}"
  fi

  [[ -s "${predict_fa}" ]] || { warn "${genome_id}: prepared FASTA missing for funannotate predict"; return 2; }

  local no_protein_alignments="${WORK_ROOT}/tmp/${genome_id}/funannotate_no_protein_alignments.gff3"
  funannotate_predict_attempt() {
    local attempt_label="$1"
    shift
    local attempt_extra=("$@")
    rm -rf "${fun_run}" 2>/dev/null || true
    mkdir -p "${fun_run}"
    log "${genome_id}: trying funannotate predict (${attempt_label}, outdir=${fun_run})"
    tool_activity_emit_progress "${genome_id}" "funannotate" "predict" "Predicting genes"
    annotation_runtime_argv funannotate-predict \
      --tool-command "${fun_cmd}" \
      --input "${predict_fa}" \
      --output-dir "${fun_run}" \
      --species "${species_name}" \
      --busco-db "${busco_db}" \
      --cpus "${ANNO_CPUS}" \
      --name "${safe_name}_" \
      --temp-dir "${fun_tmp}" \
      -- "${fun_predict_extra[@]}" "${attempt_extra[@]}"
    funannotate_exec_with_activity \
      "${use_docker}" "${use_sif}" "${genome_id}" "${fun_log}" \
      "${ANNOTATION_RUNTIME_ARGV[@]}"
  }

  local predict_succeeded=0
  local training_fallback_floor=""
  local -a training_retry_args=()
  if funannotate_predict_attempt "standard"; then
    predict_succeeded=1
  else
    # Classify the structured AUGUSTUS/BUSCO failure before considering the
    # independent protein-to-genome retry. A bare protein_alignments.gff3 path
    # in normal funannotate output is not evidence of a p2g failure.
    if training_fallback_floor="$(funannotate_busco_training_fallback_threshold "${fun_log}")"; then
      training_retry_args=(--min_training_models "${training_fallback_floor}")
      warn "${genome_id}: validated BUSCO models meet the bounded fallback floor; retrying funannotate with --min_training_models ${training_fallback_floor}"
      if funannotate_predict_attempt "reduced-training-model-threshold" "${training_retry_args[@]}"; then
        predict_succeeded=1
      fi
    fi

    if [[ "${predict_succeeded}" -eq 0 && "${FUNANNOTATE_RETRY_WITHOUT_PROTEIN_EVIDENCE}" == "1" ]] && funannotate_predict_failed_in_p2g "${fun_log}"; then
      warn "${genome_id}: funannotate protein-to-genome evidence mapping failed; retrying without default UniProt protein-to-genome evidence"
      printf '%s\n' '##gff-version 3' > "${no_protein_alignments}"
      if [[ -n "${training_fallback_floor}" ]]; then
        if funannotate_predict_attempt "reduced-training-and-no-protein-evidence" "${training_retry_args[@]}" --protein_alignments "${no_protein_alignments}"; then
          predict_succeeded=1
        fi
      elif funannotate_predict_attempt "no-protein-evidence" --protein_alignments "${no_protein_alignments}"; then
        predict_succeeded=1
      fi
    fi
  fi

  if [[ "${predict_succeeded}" -eq 0 ]]; then
    rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
    funannotate_record_predict_failure "${genome_id}" "${fun_log}" "${busco_db}" "${FUNANNOTATE_RESOLVED_SOURCE}"
    if [[ -n "${training_fallback_floor}" && -n "${FUNANNOTATE_LAST_FAILURE_DETAIL}" ]]; then
      FUNANNOTATE_LAST_FAILURE_DETAIL="${FUNANNOTATE_LAST_FAILURE_DETAIL} fallback_min_training_models=${training_fallback_floor}"
    fi
    warn "${genome_id}: funannotate predict failed after eligible bounded retries (see ${fun_log})"
    return 2
  fi

  pred_gbk="$(find "${fun_run}" -type f -path '*/predict_results/*.gbk' | head -n1)"
  if [[ -n "${pred_gbk}" && -s "${pred_gbk}" ]] && gbk_has_cds_and_translation "${pred_gbk}"; then
    cp -f "${pred_gbk}" "${out_gbk}"
    if remap_gbk_ids_from_fasta_hashes "${fasta}" "${predict_fa}" "${out_gbk}" "${remap_out}" "${id_map_tsv}" >> "${fun_log}" 2>&1; then
      mv -f "${remap_out}" "${out_gbk}"
      log "${genome_id}: remapped final GBK record IDs to original FASTA IDs (map=${id_map_tsv})"
    else
      warn "${genome_id}: could not remap GBK record IDs to original FASTA IDs; keeping funannotate IDs"
    fi
    rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
    log "${genome_id}: funannotate produced GBK with CDS+translations"
    return 0
  fi

  pred_gff3="$(find "${fun_run}" -type f -path '*/predict_results/*.gff3' | head -n1)"
  if [[ -n "${pred_gff3}" && -s "${pred_gff3}" ]]; then
    if "${VENV_PY}" "${CONVERT_PY}" --fasta "${predict_fa}" --gff3 "${pred_gff3}" --out_gbk "${tmp_out}" >> "${fun_log}" 2>&1; then
      if [[ -s "${tmp_out}" ]] && gbk_has_cds_and_translation "${tmp_out}"; then
        mv -f "${tmp_out}" "${out_gbk}"
        if remap_gbk_ids_from_fasta_hashes "${fasta}" "${predict_fa}" "${out_gbk}" "${remap_out}" "${id_map_tsv}" >> "${fun_log}" 2>&1; then
          mv -f "${remap_out}" "${out_gbk}"
          log "${genome_id}: remapped converted GBK record IDs to original FASTA IDs (map=${id_map_tsv})"
        else
          warn "${genome_id}: could not remap converted GBK record IDs to original FASTA IDs; keeping funannotate IDs"
        fi
        rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
        log "${genome_id}: funannotate GFF3 converted to GBK with CDS+translations"
        return 0
      fi
    fi
  fi

  rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
  warn "${genome_id}: funannotate did not yield usable GBK with CDS+translations"
  return 4
}
