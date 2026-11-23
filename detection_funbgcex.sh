# FunBGCeX completion, prepared-runtime dispatch and per-genome detection.

funbgcex_outputs_valid() {
  local outdir="$1"
  [[ -d "${outdir}" ]] || return 1
  [[ -n "$(find "${outdir}" -maxdepth 4 -type f \
    \( -name "allBGCs.csv" -o -name "allBGCs.html" -o -name "BGCs.csv" -o -name "results.html" \) \
    -size +0c -print -quit 2>/dev/null)" ]]
}

funbgcex_done() {
  local outdir="$1"
  [[ -f "${outdir}/.done" ]] || return 1
  funbgcex_outputs_valid "${outdir}"
}

mark_funbgcex_done() {
  local outdir="$1"
  rm -f "${outdir}/.done" 2>/dev/null || true
  funbgcex_outputs_valid "${outdir}" || return 1
  touch "${outdir}/.done"
}

funbgcex_host_deps_ok() {
  local dep=""
  local missing=()
  for dep in hmmscan hmmfetch hmmpress diamond; do
    if ! have "${dep}"; then
      missing+=("${dep}")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    warn "Host FunBGCeX mode requires external binaries on PATH: $(join_by ', ' "${missing[@]}")"
    return 1
  fi
  return 0
}

configure_funbgcex_host_runtime() {
  local cmd="$1"
  local py="$2"

  [[ -x "${cmd}" ]] || die "FunBGCeX command not executable: ${cmd}"
  if [[ "${py}" == */* ]]; then
    [[ -x "${py}" ]] || die "FunBGCeX python not executable: ${py}"
  else
    have "${py}" || die "FunBGCeX python not found in PATH: ${py}"
  fi
  funbgcex_host_deps_ok || die "Install HMMER and DIAMOND on the host, or prepare the configured FunBGCeX runtime."
  "${py}" -c "import Bio" >/dev/null 2>&1 || die "FunBGCeX python is missing Biopython support: ${py}"

  FUNBGCEX_RUNTIME="host"
  FUNBGCEX_CMD="${cmd}"
  FUNBGCEX_PYTHON_CMD="${py}"
  log "FunBGCeX runtime configured from host/venv: ${FUNBGCEX_CMD}"
}

ensure_funbgcex_runtime() {
  local cmd_path=""
  local py=""

  if [[ "${ENGINE}" == "docker" || "${FUNBGCEX_USE_DOCKER_IMAGE}" == "1" ]]; then
    if docker image inspect "${FUNBGCEX_DOCKER_IMAGE}" >/dev/null 2>&1; then
      log "FunBGCeX Docker image present: ${FUNBGCEX_DOCKER_IMAGE}"
      FUNBGCEX_RUNTIME="docker"
      FUNBGCEX_CMD="run_funbgcex"
      FUNBGCEX_PYTHON_CMD="python3"
      log "FunBGCeX runtime configured from Docker image: ${FUNBGCEX_DOCKER_IMAGE}"
      return 0
    fi
    warn "FunBGCeX Docker image is unavailable: ${FUNBGCEX_DOCKER_IMAGE}"
    if [[ "${ENGINE}" == "docker" ]]; then
      runtime_preparation_hint
      return 1
    fi
  fi

  if [[ -s "${FUNBGCEX_SIF}" ]]; then
    FUNBGCEX_RUNTIME="sif"
    FUNBGCEX_CMD="funbgcex"
    FUNBGCEX_PYTHON_CMD="python3"
    log "FunBGCeX SIF present: ${FUNBGCEX_SIF}"
    return 0
  fi

  if [[ -x "${FUNBGCEX_VENV_DIR}/bin/funbgcex" && -x "${FUNBGCEX_VENV_DIR}/bin/python" ]]; then
    if funbgcex_host_deps_ok; then
      configure_funbgcex_host_runtime "${FUNBGCEX_VENV_DIR}/bin/funbgcex" "${FUNBGCEX_VENV_DIR}/bin/python"
      return 0
    fi
    warn "Ignoring existing FunBGCeX venv because host dependencies are incomplete."
  fi

  if have funbgcex; then
    cmd_path="$(command -v funbgcex)"
    py="$(resolve_python_cmd)"
    if funbgcex_host_deps_ok && "${py}" -c "import Bio" >/dev/null 2>&1; then
      configure_funbgcex_host_runtime "${cmd_path}" "${py}"
      return 0
    fi
    warn "Host funbgcex found at ${cmd_path}, but its dependencies are incomplete."
  fi

  warn "FunBGCeX SIF missing: ${FUNBGCEX_SIF}"
  warn "AUTO_BUILD_FUNBGCEX_SIF=${AUTO_BUILD_FUNBGCEX_SIF}, AUTO_BUILD_FUNBGCEX_DOCKER=${AUTO_BUILD_FUNBGCEX_DOCKER}, and FUNBGCEX_BOOTSTRAP=${FUNBGCEX_BOOTSTRAP} are accepted compatibility inputs; canonical jobs do not acquire runtimes."
  [[ -n "${FUNBGCEX_IMAGE_URI}" ]] && warn "Configured FunBGCeX image source: ${FUNBGCEX_IMAGE_URI}"
  runtime_preparation_hint
  return 1
}

funbgcex_python_exec() {
  case "${FUNBGCEX_RUNTIME}" in
    sif) sing_exec "${FUNBGCEX_SIF}" "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    docker) CLUSTERWEAVE_CHILD_DOCKER_CPUS=1 docker_exec "${FUNBGCEX_DOCKER_IMAGE}" "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    host) "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    *) die "FunBGCeX runtime not configured before python exec" ;;
  esac
}

run_funbgcex_cli() {
  local gbk_dir="$1"
  local out_dir="$2"

  case "${FUNBGCEX_RUNTIME}" in
    sif)
      sing_exec "${FUNBGCEX_SIF}" env CUDA_VISIBLE_DEVICES= TF_CPP_MIN_LOG_LEVEL=2 \
        funbgcex "${gbk_dir}" "${out_dir}" --workers "${WORKERS}"
      ;;
    docker)
      CLUSTERWEAVE_CHILD_DOCKER_CPUS="${WORKERS}" docker_exec "${FUNBGCEX_DOCKER_IMAGE}" run_funbgcex "${gbk_dir}" "${out_dir}" "${WORKERS}"
      ;;
    host)
      CUDA_VISIBLE_DEVICES="" TF_CPP_MIN_LOG_LEVEL=2 "${FUNBGCEX_CMD}" "${gbk_dir}" "${out_dir}" --workers "${WORKERS}"
      ;;
    *)
      die "FunBGCeX runtime not configured before CLI execution"
      ;;
  esac
}

run_funbgcex_detection() {
  # Write the detector outcome to the caller's status variable.
  local genome_id="$1" fbx_done="$2" fbx_input="$3" fbx_out="$4"
  local per_tmp="$5" fbx_stdout="$6" fbx_err="$7" GENLOG="$8" status_var="$9"
  local gbk_dir
  if [[ "${fbx_done}" -eq 1 ]]; then
    printf -v "${status_var}" '%s' "skipped_done"
    log "${genome_id}: FunBGCeX already done -> ${fbx_out}" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "funbgcex" 100 "FunBGCeX already complete"
  else
    rm -rf "${fbx_out}" 2>/dev/null || true
    mkdir -p "${fbx_out}"

    gbk_dir="${per_tmp}/funbgcex_in"
    rm -rf "${gbk_dir}" 2>/dev/null || true
    mkdir -p "${gbk_dir}"
    cp -f "${fbx_input}" "${gbk_dir}/"

    log "${genome_id}: running FunBGCeX (outdir=${fbx_out})" | tee -a "${GENLOG}"
    genome_stage_progress "${genome_id}" "funbgcex" 80 "Running FunBGCeX"
    if run_funbgcex_cli "${gbk_dir}" "${fbx_out}" >"${fbx_stdout}" 2>"${fbx_err}" \
        && mark_funbgcex_done "${fbx_out}"; then
      printf -v "${status_var}" '%s' "ran_ok"
      log "${genome_id}: FunBGCeX OK" | tee -a "${GENLOG}"
      genome_stage_progress "${genome_id}" "funbgcex" 100 "FunBGCeX complete"
    else
      printf -v "${status_var}" '%s' "failed"
      warn "${genome_id}: FunBGCeX FAILED (see ${fbx_err})" | tee -a "${GENLOG}"
      genome_stage_progress "${genome_id}" "funbgcex" 100 "FunBGCeX failed"
    fi
  fi
}
