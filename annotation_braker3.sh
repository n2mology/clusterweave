# BRAKER3 execution and conversion through the shared annotation argv helper.

braker3_exec() {
  if [[ "${ENGINE}" == "docker" ]]; then
    CLUSTERWEAVE_CHILD_DOCKER_CPUS="${ANNO_CPUS}" \
      docker_exec "$(docker_image_from_uri "${BRAKER_IMAGE_URI}")" "$@"
  elif [[ -f "${BRAKER_SIF}" ]]; then
    sing_exec "${BRAKER_SIF}" "$@"
  else
    "$@"
  fi
}

run_braker3_to_gbk() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  [[ -s "${fasta}" ]] || return 1

  local braker_out="${RESULTS_ROOT}/braker3/${genome_id}"
  local braker_log="${WORK_ROOT}/logs/${genome_id}.braker3.log"
  local braker_species="${BRAKER_SPECIES_PREFIX}_${genome_id}"
  local gff3=""
  local tmp_out="${out_gbk}.tmp"
  local evidence_kind=""
  local evidence_path=""

  if [[ -z "${BRAKER_BAM}" && -z "${BRAKER_PROT_SEQ}" ]]; then
    warn "${genome_id}: BRAKER3 requires evidence (--bam or --prot_seq). Set BRAKER_BAM or BRAKER_PROT_SEQ; skipping BRAKER3."
    return 3
  fi
  if [[ -n "${BRAKER_BAM}" ]]; then
    evidence_kind="bam"
    evidence_path="${BRAKER_BAM}"
  else
    evidence_kind="prot_seq"
    evidence_path="${BRAKER_PROT_SEQ}"
  fi

  : > "${braker_log}"
  mkdir -p "${braker_out}"
  rm -f "${tmp_out}" 2>/dev/null || true
  log "${genome_id}: trying BRAKER3 annotation (outdir=${braker_out})"

  if [[ "${ENGINE}" != "docker" && ! -f "${BRAKER_SIF}" ]] \
      && ! command -v braker.pl >/dev/null 2>&1; then
    warn "${genome_id}: BRAKER3 unavailable (missing BRAKER_SIF and braker.pl); skipping BRAKER3"
    return 3
  fi
  annotation_runtime_argv braker3 \
    --fasta "${fasta}" \
    --evidence-kind "${evidence_kind}" \
    --evidence-path "${evidence_path}" \
    --working-dir "${braker_out}" \
    --species "${braker_species}" \
    --cpus "${ANNO_CPUS}"
  if ! braker3_exec "${ANNOTATION_RUNTIME_ARGV[@]}" >> "${braker_log}" 2>&1; then
    warn "${genome_id}: BRAKER3 failed (see ${braker_log})"
    return 2
  fi

  gff3="$(find "${braker_out}" -type f \( -name 'braker.gff3' -o -name '*.gff3' \) | head -n1)"
  if [[ -z "${gff3}" || ! -s "${gff3}" ]]; then
    warn "${genome_id}: BRAKER3 produced no GFF3 (see ${braker_log})"
    return 4
  fi

  if ! "${VENV_PY}" "${CONVERT_PY}" --fasta "${fasta}" --gff3 "${gff3}" --out_gbk "${tmp_out}" >> "${braker_log}" 2>&1; then
    warn "${genome_id}: BRAKER3 GFF3->GBK conversion failed (see ${braker_log})"
    return 5
  fi

  if [[ -s "${tmp_out}" ]] && gbk_has_cds_and_translation "${tmp_out}"; then
    mv -f "${tmp_out}" "${out_gbk}"
    log "${genome_id}: BRAKER3 produced staged GBK with CDS+translations"
    return 0
  fi

  warn "${genome_id}: BRAKER3 output GBK lacks CDS/translations"
  return 6
}
