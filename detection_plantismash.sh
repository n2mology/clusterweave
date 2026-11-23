# Supplied-CDS plant detection keeps native outputs and producer identity separate.
run_plantismash_genome() {
  local genome="$1" source="$2" fasta="$3" staged="$4" row="$5"
  local -a args=(--input "${source}" --genome "${genome}" --results "${RESULTS_ROOT}")
  [[ -n "${fasta}" ]] && args+=(--fasta "${fasta}")
  if [[ -z "${source}" ]]; then
    repository_helper_python_exec "${SCRIPT_DIR}/bin/plantismash_runtime.py" mark-failed --genome "${genome}" --results "${RESULTS_ROOT}"
    genome_stage_progress "${genome}" "annotation" 100 "Annotation required: supply matching translated GenBank"
    write_genome_manifest_row "${row}" "${genome}" "${fasta}" "" "annotation_required" "not_applicable_taxon" "not_applicable_taxon" "plants" "annotation_required" "plantismash" "not_applicable_taxon"
    return 1
  fi
  genome_stage_progress "${genome}" "annotation" 1 "Validating supplied plant CDS annotations"
  if ! repository_helper_python_exec "${SCRIPT_DIR}/bin/plantismash_runtime.py" admit "${args[@]}" > "${per_tmp}/plant-admission.json"; then
    local admission_detail admission_state
    admission_detail="$(repository_helper_python_exec -c 'import json,sys; print(json.load(open(sys.argv[1]))["detail"])' "${per_tmp}/plant-admission.json")"
    admission_state="$(repository_helper_python_exec -c 'import json,sys; print(json.load(open(sys.argv[1]))["state"].lower())' "${per_tmp}/plant-admission.json")"
    repository_helper_python_exec "${SCRIPT_DIR}/bin/plantismash_runtime.py" mark-failed --genome "${genome}" --results "${RESULTS_ROOT}" --failure-receipt "${per_tmp}/plant-admission.json"
    genome_stage_progress "${genome}" "annotation" 100 "${admission_detail}"
    write_genome_manifest_row "${row}" "${genome}" "${fasta}" "" "${admission_state}" "not_applicable_taxon" "not_applicable_taxon" "plants" "${admission_state}" "plantismash" "not_applicable_taxon"
    return 1
  fi
  cp -f "${source}" "${staged}"
  genome_annotation_decision "${genome}" "no" "existing_cds" "Validated supplied plant CDS translations"
  genome_stage_progress "${genome}" "plantismash" 30 "Checking plantiSMASH supplied-CDS processing"
  [[ "${FORCE}" == "1" ]] && args+=(--force)
  if run_tool_with_activity "${genome}" "plantismash" "detect" "${WORK_ROOT}/logs/${genome}.plantismash.stdout.log" "${WORK_ROOT}/logs/${genome}.plantismash.stderr.log" repository_helper_python_exec "${SCRIPT_DIR}/bin/plantismash_runtime.py" run "${args[@]}" --sif "${PLANTISMASH_SIF}" --engine "${PLANTISMASH_ENGINE}" --cpus "${ANTISMASH_SHARD_CPUS}" --record-parallelism "${ANTISMASH_RECORD_PARALLELISM}"; then
    write_genome_manifest_row "${row}" "${genome}" "${fasta}" "${staged}" "original_ok" "not_applicable_taxon" "not_applicable_taxon" "plants" "existing_cds" "plantismash" "not_applicable_taxon"
    local native_result
    native_result="$("${VENV_PY}" -c 'import json,sys; r=json.load(open(sys.argv[1])); print(("Retained" if r["reuse"]=="retained" else "Completed")+" plantiSMASH: "+str(r["calls"])+" BGCs in supplied-CDS records; "+r["state"]+"; "+str(r.get("not_evaluated_record_count",0))+" records without CDS not evaluated")' "${RESULTS_ROOT}/plantismash/${genome}/outcome.json")"
    log "${genome}: ${native_result}"
    genome_stage_progress "${genome}" "plantismash" 100 "plantiSMASH complete"
    genome_stage_progress "${genome}" "annotation" 100 "Genome workflow complete"
  else
    write_genome_manifest_row "${row}" "${genome}" "${fasta}" "${staged}" "original_ok" "not_applicable_taxon" "not_applicable_taxon" "plants" "existing_cds" "plantismash" "not_applicable_taxon"
    genome_stage_progress "${genome}" "plantismash" 100 "plantiSMASH failed; no accepted count"
    return 1
  fi
}
