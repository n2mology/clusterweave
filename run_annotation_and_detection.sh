#!/usr/bin/env bash
set -euo pipefail
IFS=$' \n\t'

###############################################################################
# Env-backed project paths
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_DIR}")}"
PROJECTS_ROOT="${PROJECTS_ROOT:-${PROJECT_DIR}}"
DATA_ROOT="${DATA_ROOT:-${PROJECTS_ROOT}/Data}"
SOFTWARE_ROOT="${SOFTWARE_ROOT:-${PROJECTS_ROOT}/Software}"
GENOMES_ROOT="${GENOMES_ROOT:-${DATA_ROOT}/Genomes/Fungi}"
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/Results}"

GENOME_ROOT="${GENOME_ROOT:-${GENOMES_ROOT}/${PROJECT_NAME}}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"

ANTISMASH_SIF="${ANTISMASH_SIF:-${SOFTWARE_ROOT}/antismash/antismash_standalone.sif}"
FUNBGCEX_SIF="${FUNBGCEX_SIF:-${SOFTWARE_ROOT}/funbgcex/funbgcex_bundle.sif}"
BRAKER_SIF="${BRAKER_SIF:-${SOFTWARE_ROOT}/braker/braker3.sif}"
FUNANNOTATE_SIF="${FUNANNOTATE_SIF:-${SOFTWARE_ROOT}/funannotate/funannotate_v1.8.17.sif}"
ANTISMASH_DB_DIR="${ANTISMASH_DB_DIR:-${SOFTWARE_ROOT}/antismash/databases}"


###############################################################################
# Tunables / knobs
###############################################################################
CPUS="${CPUS:-6}"           # antiSMASH cpus
WORKERS="${WORKERS:-2}"     # funbgcex --workers
FORCE="${FORCE:-0}"         # FORCE=1 clears staged gbk + tool outputs per genome
THREADS="${THREADS:-6}"     # recorded; alias for CPUS unless CPUS explicitly set
ENGINE="${ENGINE:-}"        # singularity, apptainer, or docker
CLUSTERWEAVE_RUNTIME_MODE="${CLUSTERWEAVE_RUNTIME_MODE:-hpc-singularity}"
DOCKER_DATA_VOLUME="${DOCKER_DATA_VOLUME:-${CLUSTERWEAVE_DOCKER_DATA_VOLUME:-}}"
DOCKER_ANTISMASH_DB_VOLUME="${DOCKER_ANTISMASH_DB_VOLUME:-}"

# Annotation knobs
ANNO_CPUS="${ANNO_CPUS:-6}"
ANNOTATION_FALLBACK_ORDER="${ANNOTATION_FALLBACK_ORDER:-funannotate}"
BRAKER3_ENABLED="${BRAKER3_ENABLED:-0}"
BRAKER_SPECIES_PREFIX="${BRAKER_SPECIES_PREFIX:-braker3}"
FUNANNOTATE_ORGANISM_NAME="${FUNANNOTATE_ORGANISM_NAME:-Fungal_sp}"
FUNANNOTATE_BUSCO_DB="${FUNANNOTATE_BUSCO_DB:-dikarya}"
FUNANNOTATE_BUSCO_SEED_SPECIES="${FUNANNOTATE_BUSCO_SEED_SPECIES:-}"
BRAKER_BAM="${BRAKER_BAM:-}"
BRAKER_PROT_SEQ="${BRAKER_PROT_SEQ:-}"
AUTO_PULL_IMAGES="${AUTO_PULL_IMAGES:-always}"   # ask|always|never
ANTISMASH_IMAGE_URI="${ANTISMASH_IMAGE_URI:-docker://antismash/standalone:8.0.4}"
ANTISMASH_DOCKER_IMAGE="${ANTISMASH_DOCKER_IMAGE:-antismash/standalone:8.0.4}"
FUNBGCEX_IMAGE_URI="${FUNBGCEX_IMAGE_URI:-}"
AUTO_BUILD_FUNBGCEX_SIF="${AUTO_BUILD_FUNBGCEX_SIF:-1}"
FUNBGCEX_USE_DOCKER_IMAGE="${FUNBGCEX_USE_DOCKER_IMAGE:-0}"
FUNBGCEX_DOCKER_IMAGE="${FUNBGCEX_DOCKER_IMAGE:-clusterweave-funbgcex:latest}"
AUTO_BUILD_FUNBGCEX_DOCKER="${AUTO_BUILD_FUNBGCEX_DOCKER:-1}"
BRAKER_IMAGE_URI="${BRAKER_IMAGE_URI:-docker://teambraker/braker3:latest}"
FUNANNOTATE_IMAGE_URI="${FUNANNOTATE_IMAGE_URI:-docker://nextgenusfs/funannotate:v1.8.17}"
FUNBGCEX_BOOTSTRAP="${FUNBGCEX_BOOTSTRAP:-0}"
FUNBGCEX_VERSION="${FUNBGCEX_VERSION:-1.0.1}"
FUNBGCEX_VENV_DIR="${FUNBGCEX_VENV_DIR:-${SOFTWARE_ROOT}/funbgcex/venv}"
FUNBGCEX_PIP_CACHE="${FUNBGCEX_PIP_CACHE:-${SOFTWARE_ROOT}/funbgcex/pip_cache}"
FUNBGCEX_DEF="${FUNBGCEX_DEF:-${PROJECT_DIR}/Software/funbgcex/Singularity.def}"
FUNBGCEX_DOCKERFILE="${FUNBGCEX_DOCKERFILE:-${PROJECT_DIR}/Software/funbgcex/Dockerfile}"
FUNBGCEX_BUILD_SCRIPT="${FUNBGCEX_BUILD_SCRIPT:-${PROJECT_DIR}/Software/funbgcex/build_funbgcex_sif.sh}"

FUNBGCEX_RUNTIME="unresolved"
FUNBGCEX_CMD=""
FUNBGCEX_PYTHON_CMD=""

export CUDA_VISIBLE_DEVICES=""

###############################################################################
# Container engine + bind handling (ARRAY-BASED; REQUIRED for paths w/ spaces)
###############################################################################
have() { command -v "$1" >/dev/null 2>&1; }

if [[ -z "${ENGINE}" ]]; then
  if [[ "${FUNBGCEX_USE_DOCKER_IMAGE}" == "1" ]] && have docker; then ENGINE="docker"
  elif have singularity; then ENGINE="singularity"
  elif have apptainer; then ENGINE="apptainer"
  else
    echo "ERROR: singularity/apptainer not found in PATH" >&2
    exit 1
  fi
fi

case "${ENGINE}" in
  singularity|apptainer|docker) ;;
  *) echo "ERROR: unsupported ENGINE=${ENGINE}; use singularity, apptainer, or docker" >&2; exit 1 ;;
esac

if [[ "${ENGINE}" == "docker" ]] && ! have docker; then
  echo "ERROR: ENGINE=docker requested but docker is not available in PATH" >&2
  exit 1
fi

# Binds as an array (paths contain spaces; do NOT store binds in a single string)
BIND_ARGS=(
  --bind "${PROJECT_DIR}:${PROJECT_DIR}"
  --bind "${GENOME_ROOT}:${GENOME_ROOT}"
  --bind "${RESULTS_ROOT}:${RESULTS_ROOT}"
)

# Helper: exec inside a Singularity/Apptainer container safely
sing_exec() {
  local image="$1"; shift
  "${ENGINE}" exec "${BIND_ARGS[@]}" "${image}" "$@"
}

docker_image_from_uri() {
  local uri="$1"
  printf '%s\n' "${uri#docker://}"
}

docker_run_args() {
  local -a args=(--rm -i --user 0:0 --entrypoint "")
  if [[ -n "${DOCKER_DATA_VOLUME}" ]]; then
    args+=(-v "${DOCKER_DATA_VOLUME}:/data")
  else
    args+=(-v "${PROJECT_DIR}:${PROJECT_DIR}" -v "${GENOME_ROOT}:${GENOME_ROOT}" -v "${RESULTS_ROOT}:${RESULTS_ROOT}")
  fi
  if [[ -n "${DOCKER_ANTISMASH_DB_VOLUME}" ]]; then
    args+=(-v "${DOCKER_ANTISMASH_DB_VOLUME}:${ANTISMASH_DB_DIR}")
  elif [[ -d "${ANTISMASH_DB_DIR}" ]]; then
    args+=(-v "${ANTISMASH_DB_DIR}:${ANTISMASH_DB_DIR}")
  fi
  if [[ -z "${DOCKER_DATA_VOLUME}" ]]; then
    args+=(-v "${WORK_ROOT}:${WORK_ROOT}")
  fi
  args+=(-e "CUDA_VISIBLE_DEVICES=" -e "ANTISMASH_DB_DIR=${ANTISMASH_DB_DIR}")
  printf '%s\0' "${args[@]}"
}

docker_exec() {
  local image="$1"; shift
  local -a args=()
  mapfile -d '' -t args < <(docker_run_args)
  docker run "${args[@]}" "${image}" "$@"
}

ensure_docker_image() {
  local label="$1"
  local image="$2"
  [[ -n "${image}" ]] || return 1
  if docker image inspect "${image}" >/dev/null 2>&1; then
    log "${label} Docker image present: ${image}"
    return 0
  fi
  if annotation_prompt_pull "${label}"; then
    log "Pulling ${label} Docker image: ${image}"
    docker pull "${image}" >> "${PIPELOG}" 2>&1 && return 0
    warn "Failed to pull ${label} Docker image: ${image}"
  fi
  return 1
}

antismash_exec() {
  if [[ "${ENGINE}" == "docker" ]]; then
    if have antismash; then
      ANTISMASH_DB_DIR="${ANTISMASH_DB_DIR}" "$@"
    else
      docker_exec "${ANTISMASH_DOCKER_IMAGE}" "$@"
    fi
  else
    sing_exec "${ANTISMASH_SIF}" "$@"
  fi
}

###############################################################################
# Paths / working dirs
###############################################################################
mkdir -p "${RESULTS_ROOT}"/{antismash,funbgcex,braker3,funannotate,summary_tables,input_gbks,tmp,logs}

LOGDIR="${LOGDIR:-${RESULTS_ROOT}/logs}"
mkdir -p "${LOGDIR}"
PIPELOG="${LOGDIR}/run_annotation_and_detection.$(date +%Y%m%d_%H%M%S).log"

WORK_ROOT="${WORK_ROOT:-/tmp/$(basename "${RESULTS_ROOT}")_work}"
mkdir -p "${WORK_ROOT}"/{logs,tmp,bin}

###############################################################################
# Logging helpers
###############################################################################
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "[$(ts)] [INFO] $*" | tee -a "${PIPELOG}"; }
warn(){ echo "[$(ts)] [WARN] $*" | tee -a "${PIPELOG}" >&2; }
err(){ echo "[$(ts)] [ERROR] $*" | tee -a "${PIPELOG}" >&2; }
die(){ err "$*"; exit 1; }
join_by() { local IFS="$1"; shift; echo "$*"; }

resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    have "${PYTHON_BIN}" || die "PYTHON_BIN not found in PATH: ${PYTHON_BIN}"
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if have "${VENV_PY}"; then
    printf '%s\n' "${VENV_PY}"
    return 0
  fi
  if have python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python; then
    printf '%s\n' "python"
    return 0
  fi
  die "No usable Python interpreter found. Install python3 or set PYTHON_BIN."
}

###############################################################################
# Converter bootstrap (pure stdlib python; no pip/venv dependency)
###############################################################################
CONVERT_PY="${CONVERT_PY:-${PROJECT_DIR}/bin/gff3_to_gbk_with_translations.py}"
VENV_PY="${VENV_PY:-python3}"

setup_converter() {
  if [[ -s "${CONVERT_PY}" ]]; then
    log "Using existing converter: ${CONVERT_PY}"
    return 0
  fi

  mkdir -p "$(dirname "${CONVERT_PY}")"

  command -v "${VENV_PY}" >/dev/null 2>&1 || die "Python interpreter not found for converter: ${VENV_PY}"

  log "Writing converter: ${CONVERT_PY}"
  cat > "${CONVERT_PY}" <<'PY'
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import argparse
import re

CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}

COMPLEMENT = str.maketrans("ACGTRYMKBDHVNacgtrymkbdhvn", "TGCAYRKMVHDBNtgcayrkmvhdbn")
ATTR_RE = re.compile(r'([^=;]+)=([^;]+)')


def normalize_seqid(value: str) -> str:
    return value.split()[0]


def parse_attrs(attr_str: str) -> dict[str, str]:
    attrs = {}
    for match in ATTR_RE.finditer(attr_str.strip()):
        attrs[match.group(1)] = match.group(2)
    return attrs


def parse_fasta(path: Path) -> dict[str, dict[str, str]]:
    records = {}
    current_id = None
    current_desc = ""
    parts: list[str] = []
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_id is not None:
                    records[current_id] = {
                        "id": current_id,
                        "description": current_desc,
                        "seq": "".join(parts).upper(),
                    }
                header = line[1:].strip()
                tokens = header.split(None, 1)
                current_id = tokens[0]
                current_desc = header
                parts = []
            else:
                parts.append(line)
    if current_id is not None:
        records[current_id] = {
            "id": current_id,
            "description": current_desc,
            "seq": "".join(parts).upper(),
        }
    return records


def reverse_complement(seq: str) -> str:
    return seq.translate(COMPLEMENT)[::-1]


def translate_cds(seq: str) -> str:
    protein = []
    usable = len(seq) - (len(seq) % 3)
    for idx in range(0, usable, 3):
        codon = seq[idx:idx + 3]
        protein.append(CODON_TABLE.get(codon, "X"))
    return "".join(protein)


def format_location(parts: list[dict[str, int]], strand: str) -> str:
    ordered = sorted(parts, key=lambda item: item["start"])
    spans = [f"{item['start']}..{item['end']}" for item in ordered]
    loc = spans[0] if len(spans) == 1 else f"join({','.join(spans)})"
    return f"complement({loc})" if strand == "-" else loc


def wrap_qualifier(prefix: str, value: str) -> list[str]:
    width = 80
    lines = []
    current = f'{prefix}"{value}"'
    prefix_to_use = "                     "
    while len(prefix_to_use) + len(current) > width:
        take = width - len(prefix_to_use)
        lines.append(prefix_to_use + current[:take])
        current = current[take:]
    lines.append(prefix_to_use + current)
    return lines


def format_origin(seq: str) -> list[str]:
    lines = ["ORIGIN"]
    for offset in range(0, len(seq), 60):
        chunk = seq[offset:offset + 60].lower()
        groups = [chunk[i:i + 10] for i in range(0, len(chunk), 10)]
        lines.append(f"{offset + 1:>9} {' '.join(groups)}")
    lines.append("//")
    return lines


def gff_to_gbk_with_translations(fasta: Path, gff3: Path, out_gbk: Path) -> tuple[int, int]:
    seqs = parse_fasta(fasta)
    if not seqs:
        raise RuntimeError(f"No contigs read from FASTA: {fasta}")
    seqs_norm = {normalize_seqid(key): value for key, value in seqs.items()}

    cds_by_parent: dict[str, list[dict[str, object]]] = defaultdict(list)
    with gff3.open() as handle:
        for raw_line in handle:
            if not raw_line.strip() or raw_line.startswith("#"):
                continue
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) != 9:
                continue
            seqid, source, feature_type, start, end, score, strand, phase, attrs = parts
            if feature_type != "CDS":
                continue
            parsed = parse_attrs(attrs)
            parent = parsed.get("Parent") or parsed.get("transcript_id") or parsed.get("ID")
            if not parent:
                parent = f"{seqid}:{start}-{end}:{strand}"
            seqid_norm = normalize_seqid(seqid)
            # Gene IDs can repeat across contigs (e.g., g1.t1), so key by contig+parent.
            parent_key = f"{seqid_norm}::{parent}"
            cds_by_parent[parent_key].append({
                "seqid": seqid_norm,
                "parent": parent,
                "start": int(start),
                "end": int(end),
                "strand": strand if strand in {"+", "-"} else "+",
                "phase": phase,
            })

    if not cds_by_parent:
        raise RuntimeError(f"No CDS features found in GFF3: {gff3}")

    cds_count = 0
    tr_count = 0
    out_lines: list[str] = []
    today = datetime.utcnow().strftime("%d-%b-%Y").upper()

    for seqid_norm, record in seqs_norm.items():
        seq = record["seq"]
        matching = []
        for _parent_key, cds_list in cds_by_parent.items():
            contig_parts = [item for item in cds_list if item["seqid"] == seqid_norm]
            if not contig_parts:
                continue
            parent = str(contig_parts[0].get("parent", "unknown"))
            strand = str(contig_parts[0]["strand"])
            ordered_for_seq = sorted(contig_parts, key=lambda item: int(item["start"]), reverse=(strand == "-"))
            pieces = [seq[int(item["start"]) - 1:int(item["end"])] for item in ordered_for_seq]
            cds_seq = "".join(pieces)
            if strand == "-":
                cds_seq = reverse_complement(cds_seq)
            phase = contig_parts[0]["phase"]
            try:
                phase_int = int(phase) if phase not in {"", "."} else 0
            except ValueError:
                phase_int = 0
            if phase_int in (1, 2):
                cds_seq = cds_seq[phase_int:]
            protein = translate_cds(cds_seq)
            matching.append({
                "parent": parent,
                "strand": strand,
                "parts": [{"start": int(item["start"]), "end": int(item["end"])} for item in contig_parts],
                "protein": protein,
            })

        if not matching:
            continue

        locus = record["id"][:16]
        out_lines.append(f"LOCUS       {locus:<16}{len(seq):>11} bp    DNA              UNK {today}")
        out_lines.append(f"DEFINITION  {record['description'] or record['id']}")
        out_lines.append(f"ACCESSION   {record['id']}")
        out_lines.append(f"VERSION     {record['id']}")
        out_lines.append("KEYWORDS    .")
        out_lines.append("SOURCE      .")
        out_lines.append("  ORGANISM  .")
        out_lines.append("            .")
        out_lines.append("FEATURES             Location/Qualifiers")
        out_lines.append(f"     source          1..{len(seq)}")
        for feature in sorted(matching, key=lambda item: min(part['start'] for part in item['parts'])):
            out_lines.append(f"     CDS             {format_location(feature['parts'], feature['strand'])}")
            out_lines.extend(wrap_qualifier('/locus_tag=', str(feature['parent'])))
            out_lines.extend(wrap_qualifier('/product=', 'predicted_protein'))
            out_lines.extend(wrap_qualifier('/translation=', str(feature['protein'])))
            cds_count += 1
            tr_count += 1
        out_lines.extend(format_origin(seq))

    out_gbk.parent.mkdir(parents=True, exist_ok=True)
    out_gbk.write_text("\n".join(out_lines) + "\n")
    return cds_count, tr_count


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--gff3", required=True)
    ap.add_argument("--out_gbk", required=True)
    args = ap.parse_args()
    cds, tr = gff_to_gbk_with_translations(Path(args.fasta), Path(args.gff3), Path(args.out_gbk))
    print(f"WROTE {args.out_gbk}")
    print(f"CDS features: {cds}")
    print(f"/translation=: {tr}")
PY
  chmod +x "${CONVERT_PY}" || true

  [[ -f "${CONVERT_PY}" ]] || die "Converter script missing after setup"
}

###############################################################################
# Input discovery/resolution
###############################################################################
discover_stems() {
  find "${GENOME_ROOT}" -maxdepth 1 -type f \
    \( -iname "*.fa" -o -iname "*.fna" -o -iname "*.fsa" -o -iname "*.fasta" -o -iname "*.gb" -o -iname "*.gbk" -o -iname "*.gbff" \) \
    -printf "%f\n" 2>/dev/null \
  | sed -E 's/\.(fa|fna|fsa|fasta|gb|gbk|gbff)$//' \
  | sort -u
}

resolve_fasta_for_stem() {
  local stem="$1"
  local cands=( "${GENOME_ROOT}/${stem}.fna" "${GENOME_ROOT}/${stem}.fa" "${GENOME_ROOT}/${stem}.fsa" "${GENOME_ROOT}/${stem}.fasta" )
  local f
  for f in "${cands[@]}"; do [[ -s "${f}" ]] && { echo "${f}"; return 0; }; done
  return 1
}

resolve_genbank_for_stem() {
  local stem="$1"
  local cands=( "${GENOME_ROOT}/${stem}.gbk" "${GENOME_ROOT}/${stem}.gb" "${GENOME_ROOT}/${stem}.gbff" )
  local f
  for f in "${cands[@]}"; do [[ -s "${f}" ]] && { echo "${f}"; return 0; }; done
  return 1
}

###############################################################################
# GBK checks
###############################################################################
gbk_has_cds_and_translation() {
  local gbk="$1"
  [[ -s "${gbk}" ]] || return 1
  grep -q "^[[:space:]]\+CDS[[:space:]]" "${gbk}" && grep -q "/translation=" "${gbk}"
}

gbk_has_cds() {
  local gbk="$1"
  [[ -s "${gbk}" ]] || return 1
  grep -q "^[[:space:]]\+CDS[[:space:]]" "${gbk}"
}

backfill_gbk_translations_from_existing_cds() {
  local in_gbk="$1"
  local out_gbk="$2"

  # Use the configured FunBGCeX runtime for Biopython-backed GBK repair.
  funbgcex_python_exec - "$in_gbk" "$out_gbk" <<'PY'
import sys
from Bio import SeqIO

inp, outp = sys.argv[1], sys.argv[2]
out_records = []

for rec in SeqIO.parse(inp, "genbank"):
    rec.annotations.setdefault("molecule_type", "DNA")
    for feat in rec.features:
        if feat.type != "CDS":
            continue
        quals = feat.qualifiers or {}
        tx = quals.get("translation", [])
        if any(str(t).strip() for t in tx):
            continue

        cds_seq = feat.extract(rec.seq)

        codon_start = 1
        try:
            codon_start = int((quals.get("codon_start", ["1"]) or ["1"])[0])
        except Exception:
            codon_start = 1
        if codon_start in (2, 3):
            cds_seq = cds_seq[codon_start - 1:]

        table = 1
        try:
            table = int((quals.get("transl_table", ["1"]) or ["1"])[0])
        except Exception:
            table = 1

        prot = str(cds_seq.translate(table=table, to_stop=False)).rstrip("*").strip()
        if prot:
            quals["translation"] = [prot]
            feat.qualifiers = quals

    out_records.append(rec)

with open(outp, "w") as h:
    SeqIO.write(out_records, h, "genbank")
PY
}

normalize_gbk_record_headers() {
  local in_gbk="$1"
  local out_gbk="$2"

  funbgcex_python_exec - "$in_gbk" "$out_gbk" <<'PY'
import re
import sys
from Bio import SeqIO

inp, outp = sys.argv[1], sys.argv[2]
records = list(SeqIO.parse(inp, "genbank"))
version_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*?)(\.\d+)?$")
changed = 0

for rec in records:
    raw_id = ((rec.id or "").split() or [""])[0].strip()
    raw_name = (rec.name or "").strip()
    accessions = [str(acc).strip() for acc in (rec.annotations.get("accessions") or []) if str(acc).strip()]

    base_id = ""
    for candidate in [raw_id, raw_name, *(accessions or [])]:
        if not candidate:
            continue
        match = version_re.match(candidate.rstrip("."))
        if match:
            base_id = match.group(1)
            break
        base_id = candidate.rstrip(".")
        break

    if base_id:
        desired_name = base_id[:16].rstrip(".")
        if desired_name and rec.name != desired_name:
            rec.name = desired_name
            changed += 1

        normalized_accs = [base_id]
        if accessions != normalized_accs:
            rec.annotations["accessions"] = normalized_accs
            changed += 1

SeqIO.write(records, outp, "genbank")
print(f"normalized_records={len(records)} changed_fields={changed}")
PY
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



annotation_prompt_pull() {
  local label="$1"
  case "${AUTO_PULL_IMAGES}" in
    always) return 0 ;;
    never)  return 1 ;;
    ask)
      if [[ -t 0 ]]; then
        read -r -p "Pull missing ${label} image now? [y/N] " ans
        [[ "${ans}" =~ ^[Yy]$ ]] && return 0 || return 1
      fi
      return 1
      ;;
    *)
      warn "AUTO_PULL_IMAGES must be ask|always|never; got '${AUTO_PULL_IMAGES}'. Using 'ask'."
      if [[ -t 0 ]]; then
        read -r -p "Pull missing ${label} image now? [y/N] " ans
        [[ "${ans}" =~ ^[Yy]$ ]] && return 0 || return 1
      fi
      return 1
      ;;
  esac
}

ensure_sif_or_prompt_pull() {
  local label="$1"
  local sif="$2"
  local uri="$3"

  if [[ "${ENGINE}" == "docker" ]]; then
    ensure_docker_image "${label}" "$(docker_image_from_uri "${uri}")"
    return $?
  fi

  if [[ -f "${sif}" ]]; then
    log "${label} SIF present: ${sif}"
    return 0
  fi

  warn "${label} SIF missing: ${sif}"
  warn "${label} image source: ${uri}"

  if annotation_prompt_pull "${label}"; then
    mkdir -p "$(dirname "${sif}")"
    log "Pulling ${label} image -> ${sif}"
    if "${ENGINE}" pull --force "${sif}" "${uri}" >> "${PIPELOG}" 2>&1; then
      log "Pulled ${label} SIF: ${sif}"
      return 0
    fi
    warn "Failed to pull ${label} image automatically."
  fi

  warn "To install manually:"
  warn "  ${ENGINE} pull \"${sif}\" \"${uri}\""
  return 1
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
  funbgcex_host_deps_ok || die "Install HMMER and DIAMOND on the host, or use the repo-local FunBGCeX SIF build path."
  "${py}" -c "import Bio" >/dev/null 2>&1 || die "FunBGCeX python is missing Biopython support: ${py}"

  FUNBGCEX_RUNTIME="host"
  FUNBGCEX_CMD="${cmd}"
  FUNBGCEX_PYTHON_CMD="${py}"
  log "FunBGCeX runtime configured from host/venv: ${FUNBGCEX_CMD}"
}

bootstrap_funbgcex_venv() {
  local py
  py="$(resolve_python_cmd)"
  mkdir -p "${FUNBGCEX_PIP_CACHE}" "$(dirname "${FUNBGCEX_VENV_DIR}")"

  if [[ -x "${FUNBGCEX_VENV_DIR}/bin/funbgcex" && -x "${FUNBGCEX_VENV_DIR}/bin/python" ]]; then
    configure_funbgcex_host_runtime "${FUNBGCEX_VENV_DIR}/bin/funbgcex" "${FUNBGCEX_VENV_DIR}/bin/python"
    return 0
  fi

  log "Bootstrapping FunBGCeX environment in ${FUNBGCEX_VENV_DIR}"
  "${py}" -m venv "${FUNBGCEX_VENV_DIR}" >> "${PIPELOG}" 2>&1 || die "Failed to create FunBGCeX venv: ${FUNBGCEX_VENV_DIR}"
  "${FUNBGCEX_VENV_DIR}/bin/python" -m pip install --cache-dir "${FUNBGCEX_PIP_CACHE}" -U pip setuptools wheel >> "${PIPELOG}" 2>&1 \
    || die "Failed to upgrade pip/setuptools/wheel in ${FUNBGCEX_VENV_DIR}"
  "${FUNBGCEX_VENV_DIR}/bin/python" -m pip install --cache-dir "${FUNBGCEX_PIP_CACHE}" "funbgcex==${FUNBGCEX_VERSION}" biopython >> "${PIPELOG}" 2>&1 \
    || die "Failed to install funbgcex==${FUNBGCEX_VERSION} into ${FUNBGCEX_VENV_DIR}"

  configure_funbgcex_host_runtime "${FUNBGCEX_VENV_DIR}/bin/funbgcex" "${FUNBGCEX_VENV_DIR}/bin/python"
}

ensure_funbgcex_build_recipe() {
  [[ -s "${FUNBGCEX_DEF}" ]] || die "FunBGCeX definition file not found: ${FUNBGCEX_DEF}"
  [[ -s "${FUNBGCEX_BUILD_SCRIPT}" ]] || die "FunBGCeX build helper not found: ${FUNBGCEX_BUILD_SCRIPT}"
}

build_funbgcex_sif() {
  if [[ -s "${FUNBGCEX_SIF}" ]]; then
    log "FunBGCeX SIF present: ${FUNBGCEX_SIF}"
    return 0
  fi

  [[ "${AUTO_BUILD_FUNBGCEX_SIF}" == "1" ]] || return 1

  ensure_funbgcex_build_recipe
  mkdir -p "$(dirname "${FUNBGCEX_SIF}")"

  log "Building repo-local FunBGCeX SIF at ${FUNBGCEX_SIF}"
  log "FunBGCeX build recipe: ${FUNBGCEX_DEF}"
  if ENGINE="${ENGINE}" \
     SIF_OUT="${FUNBGCEX_SIF}" \
     DEF="${FUNBGCEX_DEF}" \
     DOCKERFILE="${FUNBGCEX_DOCKERFILE}" \
     bash "${FUNBGCEX_BUILD_SCRIPT}" >> "${PIPELOG}" 2>&1; then
    [[ -s "${FUNBGCEX_SIF}" ]] || die "FunBGCeX build reported success but SIF is missing: ${FUNBGCEX_SIF}"
    log "Built FunBGCeX SIF: ${FUNBGCEX_SIF}"
    return 0
  fi

  warn "Automatic FunBGCeX SIF build failed."
  warn "To retry manually:"
  warn "  ENGINE=${ENGINE} SIF_OUT=\"${FUNBGCEX_SIF}\" DEF=\"${FUNBGCEX_DEF}\" bash \"${FUNBGCEX_BUILD_SCRIPT}\""
  return 1
}

build_funbgcex_docker_image() {
  [[ "${AUTO_BUILD_FUNBGCEX_DOCKER}" == "1" ]] || return 1
  [[ -s "${FUNBGCEX_DOCKERFILE}" ]] || return 1

  log "Building repo-local FunBGCeX Docker image: ${FUNBGCEX_DOCKER_IMAGE}"
  docker build -t "${FUNBGCEX_DOCKER_IMAGE}" -f "${FUNBGCEX_DOCKERFILE}" "$(dirname "${FUNBGCEX_DOCKERFILE}")" >> "${PIPELOG}" 2>&1
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
    if build_funbgcex_docker_image || ensure_docker_image "FunBGCeX" "${FUNBGCEX_DOCKER_IMAGE}"; then
      FUNBGCEX_RUNTIME="docker"
      FUNBGCEX_CMD="run_funbgcex"
      FUNBGCEX_PYTHON_CMD="python3"
      log "FunBGCeX runtime configured from Docker image: ${FUNBGCEX_DOCKER_IMAGE}"
      return 0
    fi
    warn "FunBGCeX Docker image is unavailable: ${FUNBGCEX_DOCKER_IMAGE}"
    [[ "${ENGINE}" == "docker" ]] && return 1
  fi

  if [[ -s "${FUNBGCEX_SIF}" ]]; then
    FUNBGCEX_RUNTIME="sif"
    FUNBGCEX_CMD="funbgcex"
    FUNBGCEX_PYTHON_CMD="python3"
    log "FunBGCeX SIF present: ${FUNBGCEX_SIF}"
    return 0
  fi

  if build_funbgcex_sif; then
    FUNBGCEX_RUNTIME="sif"
    FUNBGCEX_CMD="funbgcex"
    FUNBGCEX_PYTHON_CMD="python3"
    return 0
  fi

  if [[ -n "${FUNBGCEX_IMAGE_URI}" ]] && ensure_sif_or_prompt_pull "FunBGCeX" "${FUNBGCEX_SIF}" "${FUNBGCEX_IMAGE_URI}"; then
    FUNBGCEX_RUNTIME="sif"
    FUNBGCEX_CMD="funbgcex"
    FUNBGCEX_PYTHON_CMD="python3"
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
    warn "Host funbgcex found at ${cmd_path}, but its dependencies are incomplete; continuing to other runtime options."
  fi

  if [[ "${FUNBGCEX_BOOTSTRAP}" == "1" ]]; then
    bootstrap_funbgcex_venv
    return 0
  fi

  warn "FunBGCeX SIF missing: ${FUNBGCEX_SIF}"
  warn "Automatic repo-local SIF build is controlled by AUTO_BUILD_FUNBGCEX_SIF=${AUTO_BUILD_FUNBGCEX_SIF}."
  [[ -n "${FUNBGCEX_IMAGE_URI}" ]] && warn "Optional FunBGCeX image source: ${FUNBGCEX_IMAGE_URI}"
  warn "Check your container builder, or provide FUNBGCEX_SIF manually."
  return 1
}

funbgcex_python_exec() {
  case "${FUNBGCEX_RUNTIME}" in
    sif) sing_exec "${FUNBGCEX_SIF}" "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    docker) docker_exec "${FUNBGCEX_DOCKER_IMAGE}" "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    host) "${FUNBGCEX_PYTHON_CMD}" "$@" ;;
    *) die "FunBGCeX runtime not configured before python exec" ;;
  esac
}

run_funbgcex_cli() {
  local gbk_dir="$1"
  local out_dir="$2"

  case "${FUNBGCEX_RUNTIME}" in
    sif)
      sing_exec "${FUNBGCEX_SIF}" bash -lc "
        set -euo pipefail
        export CUDA_VISIBLE_DEVICES=''
        export TF_CPP_MIN_LOG_LEVEL=2
        funbgcex '${gbk_dir}' '${out_dir}' --workers '${WORKERS}'
      "
      ;;
    docker)
      docker_exec "${FUNBGCEX_DOCKER_IMAGE}" run_funbgcex "${gbk_dir}" "${out_dir}" "${WORKERS}"
      ;;
    host)
      CUDA_VISIBLE_DEVICES="" TF_CPP_MIN_LOG_LEVEL=2 "${FUNBGCEX_CMD}" "${gbk_dir}" "${out_dir}" --workers "${WORKERS}"
      ;;
    *)
      die "FunBGCeX runtime not configured before CLI execution"
      ;;
  esac
}

ensure_primary_tooling() {
  if [[ "${ENGINE}" == "docker" ]]; then
    if have antismash; then
      log "antiSMASH available on worker PATH."
    else
      ensure_docker_image "antiSMASH" "${ANTISMASH_DOCKER_IMAGE}" \
        || die "antiSMASH is required but unavailable. Install it in the worker or provide ANTISMASH_DOCKER_IMAGE."
    fi
  else
    ensure_sif_or_prompt_pull "antiSMASH" "${ANTISMASH_SIF}" "${ANTISMASH_IMAGE_URI}" \
      || die "antiSMASH is required but unavailable. Provide ANTISMASH_SIF or allow pulling from ${ANTISMASH_IMAGE_URI}."
  fi
  ensure_funbgcex_runtime \
    || die "FunBGCeX is required but unavailable. Provide FUNBGCEX_SIF manually or fix the repo-local SIF build path."
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
    elif [[ "${ENGINE}" != "docker" ]] && ensure_sif_or_prompt_pull "BRAKER3" "${BRAKER_SIF}" "${BRAKER_IMAGE_URI}"; then
      braker_ok=1
    fi
  fi

  if [[ "${need_fun}" -eq 1 ]]; then
    if command -v funannotate >/dev/null 2>&1; then
      fun_ok=1
      log "funannotate available on host PATH."
    elif [[ "${ENGINE}" == "docker" ]] && ensure_docker_image "funannotate" "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")"; then
      fun_ok=1
    elif [[ "${ENGINE}" != "docker" ]] && ensure_sif_or_prompt_pull "funannotate" "${FUNANNOTATE_SIF}" "${FUNANNOTATE_IMAGE_URI}"; then
      fun_ok=1
    fi
  fi

  if [[ "${need_braker}" -eq 1 && "${braker_ok}" -eq 0 ]]; then
    die "BRAKER3 is required by ANNOTATION_FALLBACK_ORDER but unavailable. Enable image/tooling or remove braker3 from order."
  fi
  if [[ "${need_fun}" -eq 1 && "${fun_ok}" -eq 0 ]]; then
    die "funannotate is required by ANNOTATION_FALLBACK_ORDER but unavailable. Install funannotate or provide FUNANNOTATE_SIF."
  fi
  if [[ "${need_braker}" -eq 0 && "${need_fun}" -eq 0 ]]; then
    warn "No annotation fallback methods configured. Annotated GenBank inputs can still run; FASTA-only inputs may be dropped."
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
  local ev_args=()

  if [[ -z "${BRAKER_BAM}" && -z "${BRAKER_PROT_SEQ}" ]]; then
    warn "${genome_id}: BRAKER3 requires evidence (--bam or --prot_seq). Set BRAKER_BAM or BRAKER_PROT_SEQ; skipping BRAKER3."
    return 3
  fi
  if [[ -n "${BRAKER_BAM}" ]]; then
    ev_args=(--bam "${BRAKER_BAM}")
  else
    ev_args=(--prot_seq "${BRAKER_PROT_SEQ}")
  fi

  : > "${braker_log}"
  mkdir -p "${braker_out}"
  rm -f "${tmp_out}" 2>/dev/null || true
  log "${genome_id}: trying BRAKER3 annotation (outdir=${braker_out})"

  if [[ "${ENGINE}" == "docker" ]]; then
    if ! docker_exec "$(docker_image_from_uri "${BRAKER_IMAGE_URI}")" braker.pl --genome "${fasta}" "${ev_args[@]}" --workingdir "${braker_out}" --species "${braker_species}" --fungus --gff3 --threads "${ANNO_CPUS}" >> "${braker_log}" 2>&1; then
      warn "${genome_id}: BRAKER3 failed (see ${braker_log})"
      return 2
    fi
  elif [[ -f "${BRAKER_SIF}" ]]; then
    if ! sing_exec "${BRAKER_SIF}" braker.pl --genome "${fasta}" "${ev_args[@]}" --workingdir "${braker_out}" --species "${braker_species}" --fungus --gff3 --threads "${ANNO_CPUS}" >> "${braker_log}" 2>&1; then
      warn "${genome_id}: BRAKER3 failed (see ${braker_log})"
      return 2
    fi
  elif command -v braker.pl >/dev/null 2>&1; then
    if ! braker.pl --genome "${fasta}" "${ev_args[@]}" --workingdir "${braker_out}" --species "${braker_species}" --fungus --gff3 --threads "${ANNO_CPUS}" >> "${braker_log}" 2>&1; then
      warn "${genome_id}: BRAKER3 failed (see ${braker_log})"
      return 2
    fi
  else
    warn "${genome_id}: BRAKER3 unavailable (missing BRAKER_SIF and braker.pl); skipping BRAKER3"
    return 3
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

remap_gbk_ids_from_fasta_hashes() {
  local original_fasta="$1"
  local renamed_fasta="$2"
  local in_gbk="$3"
  local out_gbk="$4"
  local map_tsv="$5"
  funbgcex_python_exec - "$original_fasta" "$renamed_fasta" "$in_gbk" "$out_gbk" "$map_tsv" <<'PY'
import hashlib
import sys
from collections import defaultdict
from Bio import SeqIO

orig_fa, ren_fa, in_gbk, out_gbk, map_tsv = sys.argv[1:]

def hash_to_ids(path):
    out = defaultdict(list)
    for rec in SeqIO.parse(path, "fasta"):
        sid = (rec.id or "").split()[0]
        if not sid:
            continue
        h = hashlib.md5(str(rec.seq).upper().encode("utf-8")).hexdigest()
        out[h].append(sid)
    return out

orig = hash_to_ids(orig_fa)
ren = hash_to_ids(ren_fa)

ren_to_orig = {}
for h, ren_ids in ren.items():
    if len(ren_ids) != 1:
        continue
    orig_ids = orig.get(h, [])
    if len(orig_ids) != 1:
        continue
    ren_to_orig[ren_ids[0]] = orig_ids[0]

with open(map_tsv, "w", encoding="utf-8") as oh:
    oh.write("renamed_id\toriginal_id\n")
    for rid in sorted(ren_to_orig):
        oh.write(f"{rid}\t{ren_to_orig[rid]}\n")

records = list(SeqIO.parse(in_gbk, "genbank"))
remapped = 0
for rec in records:
    old = (rec.id or "").split()[0]
    new = ren_to_orig.get(old)
    if not new or new == old:
        continue
    rec.id = new
    rec.name = new[:16]
    if rec.description == old:
        rec.description = new
    elif rec.description.startswith(old + " "):
        rec.description = new + rec.description[len(old):]
    rec.annotations["accessions"] = [new]
    remapped += 1

SeqIO.write(records, out_gbk, "genbank")
print(f"map_entries={len(ren_to_orig)} total_records={len(records)} remapped_records={remapped}")
PY
}
run_funannotate_predict_to_gbk() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  [[ -s "${fasta}" ]] || return 1

  local fun_out="${RESULTS_ROOT}/funannotate/${genome_id}"
  local fun_run="${WORK_ROOT}/tmp/${genome_id}/funannotate_run"
  local fun_tmp="${WORK_ROOT}/tmp/${genome_id}/funannotate_tmp"
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
  local species_name="${FUNANNOTATE_ORGANISM_NAME%.}"
  local busco_db="${FUNANNOTATE_BUSCO_DB}"
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
  mkdir -p "${fun_out}" "${prep_dir}" "${fun_tmp}"
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

  log "${genome_id}: running funannotate prepare workflow (sort + clean)"
  if [[ "${use_docker}" -eq 1 ]]; then
    if ! docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" "${fun_cmd}" sort -i "${fasta}" -o "${sorted_fa}" --minlen 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate sort failed (see ${fun_log})"
      return 2
    fi
    if ! docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" "${fun_cmd}" clean -i "${sorted_fa}" -o "${cleaned_fa}" -m 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate clean failed; using sorted FASTA for predict"
      cp -f "${sorted_fa}" "${cleaned_fa}"
    fi
  elif [[ "${use_sif}" -eq 1 ]]; then
    if ! sing_exec "${FUNANNOTATE_SIF}" "${fun_cmd}" sort -i "${fasta}" -o "${sorted_fa}" --minlen 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate sort failed (see ${fun_log})"
      return 2
    fi
    if ! sing_exec "${FUNANNOTATE_SIF}" "${fun_cmd}" clean -i "${sorted_fa}" -o "${cleaned_fa}" -m 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate clean failed; using sorted FASTA for predict"
      cp -f "${sorted_fa}" "${cleaned_fa}"
    fi
  else
    if ! "${fun_cmd}" sort -i "${fasta}" -o "${sorted_fa}" --minlen 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate sort failed (see ${fun_log})"
      return 2
    fi
    if ! "${fun_cmd}" clean -i "${sorted_fa}" -o "${cleaned_fa}" -m 500 >> "${fun_log}" 2>&1; then
      warn "${genome_id}: funannotate clean failed; using sorted FASTA for predict"
      cp -f "${sorted_fa}" "${cleaned_fa}"
    fi
  fi

  [[ -s "${predict_fa}" ]] || { warn "${genome_id}: prepared FASTA missing for funannotate predict"; return 2; }

  log "${genome_id}: trying funannotate predict (outdir=${fun_run})"
  if [[ "${use_docker}" -eq 1 ]]; then
    if ! docker_exec "$(docker_image_from_uri "${FUNANNOTATE_IMAGE_URI}")" "${fun_cmd}" predict -i "${predict_fa}" -o "${fun_run}" --species "${species_name}" --organism fungus --busco_db "${busco_db}" "${fun_predict_extra[@]}" --cpus "${ANNO_CPUS}" --name "${safe_name}_" --tmpdir "${fun_tmp}" --force >> "${fun_log}" 2>&1; then
      rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
      warn "${genome_id}: funannotate predict failed (see ${fun_log})"
      return 2
    fi
  elif [[ "${use_sif}" -eq 1 ]]; then
    if ! sing_exec "${FUNANNOTATE_SIF}" "${fun_cmd}" predict -i "${predict_fa}" -o "${fun_run}" --species "${species_name}" --organism fungus --busco_db "${busco_db}" "${fun_predict_extra[@]}" --cpus "${ANNO_CPUS}" --name "${safe_name}_" --tmpdir "${fun_tmp}" --force >> "${fun_log}" 2>&1; then
      rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
      warn "${genome_id}: funannotate predict failed (see ${fun_log})"
      return 2
    fi
  else
    if ! "${fun_cmd}" predict -i "${predict_fa}" -o "${fun_run}" --species "${species_name}" --organism fungus --busco_db "${busco_db}" "${fun_predict_extra[@]}" --cpus "${ANNO_CPUS}" --name "${safe_name}_" --tmpdir "${fun_tmp}" --force >> "${fun_log}" 2>&1; then
      rsync -a --delete "${fun_run}/" "${fun_out}/" >/dev/null 2>&1 || true
      warn "${genome_id}: funannotate predict failed (see ${fun_log})"
      return 2
    fi
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

annotate_genome_with_fallbacks() {
  local genome_id="$1"
  local fasta="$2"
  local out_gbk="$3"
  local method
  local order_csv="${ANNOTATION_FALLBACK_ORDER}"
  local old_ifs="$IFS"
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
        if run_braker3_to_gbk "${genome_id}" "${fasta}" "${out_gbk}"; then
          echo "braker3"
          return 0
        fi
        ;;
      funannotate)
        if run_funannotate_predict_to_gbk "${genome_id}" "${fasta}" "${out_gbk}"; then
          echo "funannotate"
          return 0
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

###############################################################################
# antiSMASH flag helper (unchanged from your script)
###############################################################################
ANTISMASH_FLAGS_CANDIDATES=(
  --taxon fungi
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
  --genefinding-tool none
)

antismash_supported_flags() {
  local help
  help="$(antismash_exec antismash --help-showall 2>&1 || true)"

  local out=()
  local i=0
  while [[ $i -lt ${#ANTISMASH_FLAGS_CANDIDATES[@]} ]]; do
    local tok="${ANTISMASH_FLAGS_CANDIDATES[$i]}"
    if [[ "${tok}" == "--taxon" ]]; then
      local val="${ANTISMASH_FLAGS_CANDIDATES[$((i+1))]:-}"
      if grep -Fq -- "--taxon" <<< "${help}"; then out+=("--taxon" "${val}"); fi
      i=$((i+2)); continue
    fi

    if [[ "${tok}" == "--genefinding-tool" ]]; then
      local val="${ANTISMASH_FLAGS_CANDIDATES[$((i+1))]:-}"
      if grep -Fq -- "--genefinding-tool" <<< "${help}"; then out+=("--genefinding-tool" "${val}"); fi
      i=$((i+2)); continue
    fi

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
antismash_done() {
  local outdir="$1"
  [[ -d "${outdir}" ]] || return 1
  [[ -f "${outdir}/.done" ]] && return 0
  if find "${outdir}" -maxdepth 5 -type f -name "index.html" 2>/dev/null | grep -q .; then return 0; fi
  if find "${outdir}" -maxdepth 5 -type f \( -name "*region*.gbk" -o -name "*regions*.gbk" \) 2>/dev/null | grep -q .; then return 0; fi
  if find "${outdir}" -maxdepth 3 -type f -name "*.gbk" 2>/dev/null -exec grep -qm1 "##antiSMASH-Data-START##" {} \; ; then return 0; fi
  return 1
}

funbgcex_done() {
  local outdir="$1"
  [[ -d "${outdir}" ]] || return 1
  [[ -f "${outdir}/.done" ]] && return 0

  # Treat as done if the key FunBGCeX outputs exist
  if [[ -s "${outdir}/allBGCs.csv"  ]]; then return 0; fi
  if [[ -s "${outdir}/allBGCs.html" ]]; then return 0; fi
  if [[ -s "${outdir}/funbgcex_in.log" ]]; then return 0; fi

  # Fallback: any CSV/HTML/log in the top-level output dir (covers minor naming changes)
  if find "${outdir}" -maxdepth 1 -type f \( -iname "*.csv" -o -iname "*.html" -o -iname "*.log" \) 2>/dev/null | grep -q .; then
    return 0
  fi

  return 1
}

###############################################################################
# GBK diagnostics/filtering (run via the configured FunBGCeX runtime)
###############################################################################
gbk_diag_summary() {
  local gbk="$1"
  local label="${2:-GBK}"
  funbgcex_python_exec - "$gbk" "$label" <<'PY'
import sys
from Bio import SeqIO
p, label = sys.argv[1], sys.argv[2]
nrec=0
cds=0
cds_tx=0
bad_tx=0
try:
    for rec in SeqIO.parse(p, "genbank"):
        nrec += 1
        for feat in rec.features:
            if feat.type != "CDS":
                continue
            cds += 1
            q = feat.qualifiers or {}
            txs = q.get("translation", [])
            if any(str(t).strip() for t in txs):
                cds_tx += 1
            else:
                bad_tx += 1
except Exception as e:
    print(f"{label}: PARSE_FAIL file={p} err={e}")
    sys.exit(0)
print(f"{label}: file={p}")
print(f"{label}: records={nrec} cds={cds} cds_with_nonempty_translation={cds_tx} cds_missing_or_empty_translation={bad_tx}")
PY
}

filter_gbk_drop_gene_less_records() {
  local in_gbk="$1"
  local out_gbk="$2"
  funbgcex_python_exec - "$in_gbk" "$out_gbk" <<'PY'
import sys
from Bio import SeqIO

inp, outp = sys.argv[1], sys.argv[2]
out_recs=[]
dropped=0
kept=0

for rec in SeqIO.parse(inp, "genbank"):
    has_cds = any(f.type == "CDS" for f in (rec.features or []))
    if not has_cds:
        dropped += 1
        continue
    rec.annotations.setdefault("molecule_type","DNA")
    out_recs.append(rec)
    kept += 1

SeqIO.write(out_recs, outp, "genbank")
print(f"kept_records={kept} dropped_records={dropped}")
PY
}

###############################################################################
# Per-genome logging sync + manifest
###############################################################################
sync_logs_genome() {
  local genome_id="$1"
  mkdir -p "${RESULTS_ROOT}/summary_tables/logs"
  rsync -a "${WORK_ROOT}/logs/${genome_id}."* "${RESULTS_ROOT}/summary_tables/logs/" >/dev/null 2>&1 || true
}

MANIFEST="${RESULTS_ROOT}/summary_tables/run_manifest.tsv"
mkdir -p "$(dirname "${MANIFEST}")"
printf "genome_id\tfasta\tgbk_used\tgbk_status\tantismash_status\tfunbgcex_status\n" > "${MANIFEST}"

###############################################################################
# CLI
###############################################################################
usage() {
  cat <<EOF
Usage: $0 [-f] [-t THREADS] [-c CPUS] [-w WORKERS] [-g genome1,genome2,...]
  -f            Force re-run even if outputs exist (sets FORCE=1; clears staged + outputs per genome)
  -t THREADS    Threads (alias; recorded). If CPUS not set, CPUS=THREADS.
  -c CPUS       antiSMASH cpus (default: ${CPUS})
  -w WORKERS    funbgcex workers (default: ${WORKERS})
  -g LIST       Comma-separated stems to process. If omitted, auto-discover in GENOME_ROOT.
  -h            Help

Annotation env vars:
  ANNOTATION_FALLBACK_ORDER=... Comma order (default: ${ANNOTATION_FALLBACK_ORDER})
  BRAKER3_ENABLED=0|1          Enable braker3 fallback when listed in order (default: ${BRAKER3_ENABLED})
  BRAKER_SIF=...                BRAKER3 container path (default: ${BRAKER_SIF})
  FUNANNOTATE_SIF=...           funannotate container path (default: ${FUNANNOTATE_SIF})
  BRAKER_SPECIES_PREFIX=...     Prefix for BRAKER species names (default: ${BRAKER_SPECIES_PREFIX})
  FUNANNOTATE_ORGANISM_NAME=... Species label for funannotate (default: ${FUNANNOTATE_ORGANISM_NAME})
  FUNANNOTATE_BUSCO_DB=...      BUSCO lineage in funannotate predict (default: ${FUNANNOTATE_BUSCO_DB})
  FUNANNOTATE_BUSCO_SEED_SPECIES=... Optional AUGUSTUS seed from `funannotate species` (default: unset)
  BRAKER_BAM=...                Optional RNA-seq BAM for BRAKER3
  BRAKER_PROT_SEQ=...           Optional protein FASTA for BRAKER3

Annotation threading:
  ANNO_CPUS=...                 Threads for BRAKER3/funannotate (default: ${ANNO_CPUS})

Image bootstrap:
  AUTO_PULL_IMAGES=ask|always|never (default: ${AUTO_PULL_IMAGES})
  ANTISMASH_IMAGE_URI=...       Source URI for antiSMASH image (default: ${ANTISMASH_IMAGE_URI})
  FUNBGCEX_IMAGE_URI=...        Optional source URI for FunBGCeX image (default: unset)
  AUTO_BUILD_FUNBGCEX_SIF=0|1   Auto-build a repo-local FunBGCeX SIF if needed (default: ${AUTO_BUILD_FUNBGCEX_SIF})
  FUNBGCEX_DEF=...              Singularity definition used for the local FunBGCeX build
  FUNBGCEX_DOCKERFILE=...       Dockerfile used for the local FunBGCeX build fallback path
  FUNBGCEX_BUILD_SCRIPT=...     Helper script used to build the local FunBGCeX SIF
  BRAKER_IMAGE_URI=...          Source URI for BRAKER3 image (default: ${BRAKER_IMAGE_URI})
  FUNANNOTATE_IMAGE_URI=...     Source URI for funannotate image (default: ${FUNANNOTATE_IMAGE_URI})
  FUNBGCEX_BOOTSTRAP=0|1        Advanced fallback: auto-create a local FunBGCeX venv if needed (default: ${FUNBGCEX_BOOTSTRAP})
  FUNBGCEX_VERSION=...          FunBGCeX version for the advanced host bootstrap path (default: ${FUNBGCEX_VERSION})
EOF
}

GENOMES=""
CPUS_SET_BY_FLAG=0
while getopts "fht:c:w:g:" opt; do
  case "${opt}" in
    f) FORCE=1 ;;
    t) THREADS="${OPTARG}" ;;
    c) CPUS="${OPTARG}"; CPUS_SET_BY_FLAG=1 ;;
    w) WORKERS="${OPTARG}" ;;
    g) GENOMES="${OPTARG}" ;;
    h) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done
if [[ "${CPUS_SET_BY_FLAG}" -eq 0 && -n "${THREADS}" ]]; then
  CPUS="${CPUS:-${THREADS}}"
fi

###############################################################################
# Preconditions
###############################################################################
[[ -d "${PROJECT_DIR}" ]] || die "PROJECT_DIR not found: ${PROJECT_DIR}"
[[ -d "${GENOME_ROOT}"  ]] || die "GENOME_ROOT not found: ${GENOME_ROOT}"

setup_converter
ensure_primary_tooling
ensure_annotation_tooling

log "Run started: PID $$"
log "ENGINE=${ENGINE}"
log "PROJECT_DIR=${PROJECT_DIR}"
log "GENOME_ROOT=${GENOME_ROOT}"
log "RESULTS_ROOT=${RESULTS_ROOT}"
log "BIND_ARGS=${BIND_ARGS[*]}"
log "ANTISMASH_SIF=${ANTISMASH_SIF}"
log "FUNBGCEX_SIF=${FUNBGCEX_SIF}"
log "FUNBGCEX_DEF=${FUNBGCEX_DEF}"
log "FUNBGCEX_DOCKERFILE=${FUNBGCEX_DOCKERFILE}"
log "FUNBGCEX_BUILD_SCRIPT=${FUNBGCEX_BUILD_SCRIPT}"
log "ANTISMASH_IMAGE_URI=${ANTISMASH_IMAGE_URI}"
log "FUNBGCEX_IMAGE_URI=${FUNBGCEX_IMAGE_URI:-unset}"
log "FUNBGCEX_RUNTIME=${FUNBGCEX_RUNTIME}"
log "AUTO_BUILD_FUNBGCEX_SIF=${AUTO_BUILD_FUNBGCEX_SIF} FUNBGCEX_BOOTSTRAP=${FUNBGCEX_BOOTSTRAP} FUNBGCEX_VERSION=${FUNBGCEX_VERSION}"
log "BRAKER_SIF=${BRAKER_SIF} FUNANNOTATE_SIF=${FUNANNOTATE_SIF}"
log "ANNO_CPUS=${ANNO_CPUS} AUTO_PULL_IMAGES=${AUTO_PULL_IMAGES}"
log "ANNOTATION_FALLBACK_ORDER=${ANNOTATION_FALLBACK_ORDER}"
log "BRAKER3_ENABLED=${BRAKER3_ENABLED}"
log "FORCE=${FORCE} CPUS=${CPUS} WORKERS=${WORKERS} THREADS=${THREADS}"
log "Converter python: ${VENV_PY}"
log "Converter script: ${CONVERT_PY}"
log "WORK_ROOT=${WORK_ROOT}"

log "Detecting supported antiSMASH flags..."
mapfile -t ANT_FLAGS_ARRAY < <(antismash_supported_flags)
if [[ ${#ANT_FLAGS_ARRAY[@]} -eq 0 ]]; then
  log "antiSMASH flags enabled: none"
else
  log "antiSMASH flags enabled: ${ANT_FLAGS_ARRAY[*]}"
fi

###############################################################################
# Determine genomes to process
###############################################################################
if [[ -z "${GENOMES}" ]]; then
  log "No genomes specified with -g; auto-discovering in GENOME_ROOT"
  mapfile -t GEN_ARR < <(discover_stems)
  [[ ${#GEN_ARR[@]} -gt 0 ]] || die "No genome inputs found in ${GENOME_ROOT}"
else
  IFS=',' read -r -a GEN_ARR <<< "${GENOMES}"
fi
log "Genomes to process ($((${#GEN_ARR[@]}))): $(join_by ', ' "${GEN_ARR[@]}")"

###############################################################################
# Main loop
###############################################################################
total=0; dropped=0; processed=0

for genome_id in "${GEN_ARR[@]}"; do
  total=$((total + 1))
  log "===================================================================="
  log "[${total}/${#GEN_ARR[@]}] genome=${genome_id}"

  GENLOG="${WORK_ROOT}/logs/${genome_id}.log"
  : > "${GENLOG}"

  fasta=""
  if ! fasta="$(resolve_fasta_for_stem "${genome_id}")"; then
    warn "${genome_id}: no FASTA found; cannot run annotation fallback tools. Will only proceed if an annotated GBK exists."
  fi

  gb_src=""
  if gb_src="$(resolve_genbank_for_stem "${genome_id}")"; then :; else gb_src=""; fi

  staged_gbk="${RESULTS_ROOT}/input_gbks/${genome_id}.gbk"
  ant_out="${RESULTS_ROOT}/antismash/${genome_id}"
  fbx_out="${RESULTS_ROOT}/funbgcex/${genome_id}"

  ant_err="${WORK_ROOT}/logs/${genome_id}.antismash.stderr.log"
  ant_stdout="${WORK_ROOT}/logs/${genome_id}.antismash.stdout.log"
  fbx_err="${WORK_ROOT}/logs/${genome_id}.funbgcex.stderr.log"
  fbx_stdout="${WORK_ROOT}/logs/${genome_id}.funbgcex.stdout.log"

  if [[ "${FORCE}" == "1" ]]; then
    rm -f "${staged_gbk}" 2>/dev/null || true
    rm -rf "${ant_out}" 2>/dev/null || true
    rm -rf "${fbx_out}" 2>/dev/null || true
    rm -rf "${RESULTS_ROOT}/braker3/${genome_id}" 2>/dev/null || true
    rm -rf "${RESULTS_ROOT}/funannotate/${genome_id}" 2>/dev/null || true

    # Fresh per-genome work cache cleanup under /tmp
    rm -rf "${WORK_ROOT}/tmp/${genome_id}" 2>/dev/null || true
    rm -f "${WORK_ROOT}/logs/${genome_id}."* 2>/dev/null || true

  fi

  gbk_used=""
  gbk_status="missing"

  # 1) Reuse staged GBK if present
  if [[ -s "${staged_gbk}" ]] && gbk_has_cds_and_translation "${staged_gbk}"; then
    normalize_gbk_record_headers_in_place "${staged_gbk}" || true
    gbk_used="${staged_gbk}"
    gbk_status="staged_ok"
    log "${genome_id}: using staged GBK: ${staged_gbk}" | tee -a "${GENLOG}"
  fi

  # 2) If no staged GBK, try original annotated GenBank, else annotation fallback chain
  if [[ -z "${gbk_used}" ]]; then
    if [[ -n "${gb_src}" && -s "${gb_src}" ]]; then
      if gbk_has_cds_and_translation "${gb_src}"; then
        cp -f "${gb_src}" "${staged_gbk}"
        normalize_gbk_record_headers_in_place "${staged_gbk}" || true
        gbk_used="${staged_gbk}"
        gbk_status="original_ok"
        log "${genome_id}: staged original GBK (has CDS+translation): ${gb_src}" | tee -a "${GENLOG}"
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
        if fallback_method="$(annotate_genome_with_fallbacks "${genome_id}" "${fasta}" "${staged_gbk}")"; then
          normalize_gbk_record_headers_in_place "${staged_gbk}" || true
          if gbk_has_cds_and_translation "${staged_gbk}"; then
            gbk_used="${staged_gbk}"
            gbk_status="${fallback_method}_fixed"
          else
            gbk_status="${fallback_method}_no_translations"
            rm -f "${staged_gbk}" 2>/dev/null || true
          fi
        else
          gbk_status="annotation_fallbacks_failed"
        fi
      else
        gbk_status="no_fasta_for_annotation"
      fi
    fi
  fi

  antismash_status="skipped"
  funbgcex_status="skipped"

  if [[ -z "${gbk_used}" ]]; then
    dropped=$((dropped + 1))
    warn "${genome_id}: DROPPED (gbk_status=${gbk_status})" | tee -a "${GENLOG}"
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
      "${genome_id}" "${fasta}" "" "${gbk_status}" "${antismash_status}" "${funbgcex_status}" >> "${MANIFEST}"
    sync_logs_genome "${genome_id}"
    continue
  fi

  ant_done=0; fbx_done=0
  if antismash_done "${ant_out}"; then ant_done=1; fi
  if funbgcex_done "${fbx_out}"; then fbx_done=1; fi

  if [[ -s "${gbk_used}" && "${ant_done}" -eq 1 && "${fbx_done}" -eq 1 ]]; then
    antismash_status="skipped_done"
    funbgcex_status="skipped_done"
    log "${genome_id}: outputs already present in RESULTS_ROOT; skipping genome" | tee -a "${GENLOG}"
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
      "${genome_id}" "${fasta}" "${gbk_used}" "${gbk_status}" "${antismash_status}" "${funbgcex_status}" >> "${MANIFEST}"
    sync_logs_genome "${genome_id}"
    rsync -a "${MANIFEST}" "${RESULTS_ROOT}/summary_tables/" >/dev/null 2>&1 || true
    continue
  fi

  log "${genome_id}: DIAG gbk_used summary" | tee -a "${GENLOG}"
  gbk_diag_summary "${gbk_used}" "gbk_used" | tee -a "${GENLOG}"

  per_tmp="${WORK_ROOT}/tmp/${genome_id}"
  mkdir -p "${per_tmp}"

  ant_input="${per_tmp}/${genome_id}.antismash.gbk"
  log "${genome_id}: filtering GBK to drop gene-less records for antiSMASH" | tee -a "${GENLOG}"
  filter_gbk_drop_gene_less_records "${gbk_used}" "${ant_input}" | tee -a "${GENLOG}"

  log "${genome_id}: DIAG ant_input summary" | tee -a "${GENLOG}"
  gbk_diag_summary "${ant_input}" "ant_input" | tee -a "${GENLOG}"

  fbx_input="${per_tmp}/${genome_id}.funbgcex.gbk"
  cp -f "${ant_input}" "${fbx_input}"

  # ---------------- antiSMASH ----------------
  if [[ "${ant_done}" -eq 1 ]]; then
    antismash_status="skipped_done"
    log "${genome_id}: antiSMASH already done -> ${ant_out}" | tee -a "${GENLOG}"
  else
    rm -rf "${ant_out}" 2>/dev/null || true
    mkdir -p "${ant_out}"

    log "${genome_id}: running antiSMASH (outdir=${ant_out})" | tee -a "${GENLOG}"
    if antismash_exec antismash \
        "${ant_input}" \
        --output-dir "${ant_out}" \
        --cpus "${CPUS}" \
        "${ANT_FLAGS_ARRAY[@]}" \
        >"${ant_stdout}" 2>"${ant_err}"; then
      antismash_status="ran_ok"
      touch "${ant_out}/.done" || true
      log "${genome_id}: antiSMASH OK" | tee -a "${GENLOG}"
    else
      antismash_status="failed"
      warn "${genome_id}: antiSMASH FAILED (see ${ant_err})" | tee -a "${GENLOG}"
    fi
  fi

  # ---------------- FunBGCeX ----------------
  if [[ "${fbx_done}" -eq 1 ]]; then
    funbgcex_status="skipped_done"
    log "${genome_id}: FunBGCeX already done -> ${fbx_out}" | tee -a "${GENLOG}"
  else
    rm -rf "${fbx_out}" 2>/dev/null || true
    mkdir -p "${fbx_out}"

    gbk_dir="${per_tmp}/funbgcex_in"
    rm -rf "${gbk_dir}" 2>/dev/null || true
    mkdir -p "${gbk_dir}"
    cp -f "${fbx_input}" "${gbk_dir}/"

    log "${genome_id}: running FunBGCeX (outdir=${fbx_out})" | tee -a "${GENLOG}"
    if run_funbgcex_cli "${gbk_dir}" "${fbx_out}" >"${fbx_stdout}" 2>"${fbx_err}"; then
      funbgcex_status="ran_ok"
      log "${genome_id}: FunBGCeX OK" | tee -a "${GENLOG}"
    else
      funbgcex_status="failed"
      warn "${genome_id}: FunBGCeX FAILED (see ${fbx_err})" | tee -a "${GENLOG}"
    fi
  fi

  processed=$((processed + 1))
  printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${genome_id}" "${fasta}" "${gbk_used}" "${gbk_status}" "${antismash_status}" "${funbgcex_status}" >> "${MANIFEST}"

  sync_logs_genome "${genome_id}"
  rsync -a "${MANIFEST}" "${RESULTS_ROOT}/summary_tables/" >/dev/null 2>&1 || true
done

log "Complete."
log "summary_tables: ${RESULTS_ROOT}/summary_tables"
log "manifest: ${MANIFEST}"
log "total=${total} processed=${processed} dropped=${dropped}"
rsync -a "${WORK_ROOT}/logs/" "${RESULTS_ROOT}/summary_tables/logs/" >/dev/null 2>&1 || true
log "Logs synced to: ${RESULTS_ROOT}/summary_tables/logs"
