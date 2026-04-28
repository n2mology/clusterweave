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
RESULTS_BASE="${RESULTS_BASE:-${DATA_ROOT}/Results}"
RESULTS_ROOT="${RESULTS_ROOT:-${RESULTS_BASE}/${PROJECT_NAME}}"

###############################################################################

ANTISMASH_ROOT="${ANTISMASH_ROOT:-${RESULTS_ROOT}/antismash}"
FUNBGCEX_ROOT="${FUNBGCEX_ROOT:-${RESULTS_ROOT}/funbgcex}"
BIGSCAPE_ROOT="${BIGSCAPE_ROOT:-${RESULTS_ROOT}/big_scape}"
OUTDIR="${OUTDIR:-${RESULTS_ROOT}/summary}"
mkdir -p "${OUTDIR}"

SCAFFOLD_COMPARISON_CSV="${SCAFFOLD_COMPARISON_CSV:-${OUTDIR}/all_tools_scaffold_comparison.csv}"
BGC_COMPARISON_CSV="${BGC_COMPARISON_CSV:-${OUTDIR}/all_tools_bgc_comparison.csv}"
SUMMARY_CSV="${SUMMARY_CSV:-${OUTDIR}/all_tools_shared_unshared_summary.csv}"

export ANTISMASH_ROOT FUNBGCEX_ROOT BIGSCAPE_ROOT SCAFFOLD_COMPARISON_CSV BGC_COMPARISON_CSV SUMMARY_CSV

have(){ command -v "$1" >/dev/null 2>&1; }
resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if [[ -x "${PYTHON_BIN}" ]]; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    if have "${PYTHON_BIN}"; then
      printf '%s\n' "${PYTHON_BIN}"
      return 0
    fi
    echo "ERROR: PYTHON_BIN is not executable or not found: ${PYTHON_BIN}" >&2
    exit 1
  fi
  if have python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python; then
    printf '%s\n' "python"
    return 0
  fi
  echo "ERROR: neither python3 nor python found" >&2
  exit 1
}
PYTHON_BIN="$(resolve_python_cmd)"

BGC_GCF_CROSSWALK_PY="${BGC_GCF_CROSSWALK_PY:-${PROJECT_DIR}/bin/build_bgc_gcf_crosswalk.py}"
TARGETED_ANALYSIS_PY="${TARGETED_ANALYSIS_PY:-${PROJECT_DIR}/bin/build_candidate_tables.py}"
NORMALIZE_METADATA_PY="${NORMALIZE_METADATA_PY:-${PROJECT_DIR}/bin/normalize_metadata.py}"
ECOLOGY_FIELD="${ECOLOGY_FIELD:-ecofun_primary}"
FOCUS_ECOLOGY_LABEL="${FOCUS_ECOLOGY_LABEL:-}"
RUN_ECOLOGY_ANALYSIS="${RUN_ECOLOGY_ANALYSIS:-0}"
AUTO_NORMALIZE_METADATA="${AUTO_NORMALIZE_METADATA:-1}"
ACCESSIONS_MAP="${ACCESSIONS_MAP:-${DATA_ROOT}/Genomes/Fungi/${PROJECT_NAME}/accessions_fungusID_taxonomyID.txt}"
METADATA_TSV="${METADATA_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_normalized.tsv}"
METADATA_TEMPLATE_TSV="${METADATA_TEMPLATE_TSV:-${RESULTS_ROOT}/summary_tables/ecofun_metadata_template.tsv}"

"${PYTHON_BIN}" - <<'PY'
import csv, glob, json, os, re
from collections import Counter, defaultdict

ANTISMASH_ROOT = os.environ["ANTISMASH_ROOT"]
FUNBGCEX_ROOT = os.environ["FUNBGCEX_ROOT"]
BIGSCAPE_ROOT = os.environ["BIGSCAPE_ROOT"]
SCAFFOLD_COMPARISON_CSV = os.environ["SCAFFOLD_COMPARISON_CSV"]
BGC_COMPARISON_CSV = os.environ["BGC_COMPARISON_CSV"]
SUMMARY_CSV = os.environ["SUMMARY_CSV"]


def clean(s): return "" if s is None else str(s).strip()
def split_multi(text):
    text = clean(text)
    if not text or text == "-": return []
    return [p.strip() for p in re.split(r"[;,/|]+", text) if p.strip()]
def canon_term(term): return re.sub(r"[^a-z0-9]+", " ", clean(term).lower()).strip()
def normalize_scaffold(scaf):
    scaf = clean(scaf)
    if not scaf:
        return scaf
    # antiSMASH keeps terminal accession versions (for example, ".1"),
    # while FunBGCeX may emit the same scaffold with a trailing "." only.
    scaf = re.sub(r"\.\d+$", "", scaf)
    return scaf.rstrip(".")

def classes_from_terms(terms):
    out=set()
    for raw in terms:
        t=canon_term(raw)
        if not t: continue
        if "nrps" in t: out.add("NRPS")
        if "pks" in t or "polyketide" in t: out.add("PKS")
        if "terpene" in t or " tc " in (" "+t+" "): out.add("terpene")
        if "ripp" in t: out.add("RiPP")
        if "indole" in t: out.add("indole")
        if "alkaloid" in t: out.add("alkaloid")
        if "saccharide" in t: out.add("saccharide")
    if not out and terms: out.add("other")
    return out

def join_classes(cls):
    if not cls: return "other"
    order=["NRPS","PKS","terpene","RiPP","indole","alkaloid","saccharide","other"]
    return ";".join([c for c in order if c in cls] + sorted([c for c in cls if c not in set(order)]))

def counter_to_text(c):
    return "" if not c else ";".join([f"{k}:{c[k]}" for k in sorted(c)])

def overlap(a_start,a_end,b_start,b_end):
    left=max(a_start,b_start); right=min(a_end,b_end)
    return 0 if right < left else right-left+1

def token_set(text):
    return {t for t in re.split(r"[^A-Za-z0-9]+", clean(text).lower()) if len(t)>=4}

def conf_from_similarity(sim):
    if sim is None: return "none"
    try: s=float(sim)
    except Exception: return "none"
    if s >= 80: return "high"
    if s >= 50: return "medium"
    if s > 0: return "low"
    return "none"


def parse_funbgcex():
    data=defaultdict(list)
    for genome_dir in sorted(glob.glob(os.path.join(FUNBGCEX_ROOT,'*'))):
        if not os.path.isdir(genome_dir): continue
        genome=os.path.basename(genome_dir)
        csv_path=os.path.join(genome_dir,'allBGCs.csv')
        if not os.path.isfile(csv_path): continue
        with open(csv_path,newline='',encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                core=clean(row.get('Core enzymes'))
                classes=classes_from_terms(split_multi(core))
                try:
                    start=int(float(clean(row.get('Start position')))); end=int(float(clean(row.get('End position'))))
                except Exception:
                    start=end=0
                data[genome].append({
                    'bgc_id': clean(row.get('BGC no.')),
                    'scaffold': normalize_scaffold(row.get('Scaffold')),
                    'start': start, 'end': end,
                    'core_enzymes': core,
                    'classes': classes,
                    'metabolite': clean(row.get('Metabolite from similar BGC')) if clean(row.get('Metabolite from similar BGC'))!='-' else '',
                    'similar_bgc': clean(row.get('Similar BGC')) if clean(row.get('Similar BGC'))!='-' else '',
                    'similarity_score': clean(row.get('Similarity score')) if clean(row.get('Similarity score'))!='-' else ''
                })
    return data


def parse_antismash():
    data=defaultdict(list)
    for genome_dir in sorted(glob.glob(os.path.join(ANTISMASH_ROOT,'*'))):
        if not os.path.isdir(genome_dir): continue
        genome=os.path.basename(genome_dir)
        json_path=os.path.join(genome_dir,f"{genome}.antismash.json")
        if not os.path.isfile(json_path): continue
        obj=json.load(open(json_path,encoding='utf-8'))
        for rec in obj.get('records',[]):
            rec_id=clean(rec.get('id')); scaffold=normalize_scaffold(rec_id)
            known_map={}
            cc_map={}
            kb=rec.get('modules',{}).get('antismash.modules.clusterblast',{}).get('knowncluster',{})
            for res in kb.get('results',[]) if isinstance(kb,dict) else []:
                try: rn=int(res.get('region_number',0))
                except Exception: continue
                ranking=res.get('ranking',[])
                if ranking and isinstance(ranking[0],list) and len(ranking[0])>=2 and isinstance(ranking[0][0],dict) and isinstance(ranking[0][1],dict):
                    hit=ranking[0][0]; score=ranking[0][1]
                    sim=score.get('similarity')
                    known_map[rn]={
                        'known_product': clean(hit.get('description')),
                        'known_accession': clean(hit.get('accession')),
                        'known_similarity': sim if sim is not None else ''
                    }

            cc = rec.get('modules',{}).get('antismash.modules.cluster_compare',{})
            db = cc.get('db_results',{}).get('MIBiG',{}) if isinstance(cc,dict) else {}
            by_region = db.get('by_region',{}) if isinstance(db,dict) else {}
            for rk, rblock in by_region.items():
                try:
                    rn = int(rk)
                except Exception:
                    continue
                rr = rblock.get('RegionToRegion_RiQ',{}) if isinstance(rblock,dict) else {}
                scores = rr.get('scores_by_region',{}) if isinstance(rr,dict) else {}
                refs = rr.get('reference_regions',{}) if isinstance(rr,dict) else {}
                if not isinstance(scores,dict) or not scores:
                    continue
                top_key, top_score = sorted(scores.items(), key=lambda x: x[1], reverse=True)[0]
                ref = refs.get(top_key,{}) if isinstance(refs,dict) else {}
                cc_map[rn] = {
                    'cc_similarity_score': top_score,
                    'cc_compounds': clean(ref.get('description','')),
                    'cc_organism': clean(ref.get('organism',''))
                }
            for idx,area in enumerate(rec.get('areas',[]),start=1):
                products=[clean(x) for x in area.get('products',[]) if clean(x)]
                protd=area.get('protoclusters',{})
                proto_products=[]; proto_categories=[]
                if isinstance(protd,dict):
                    for _,v in protd.items():
                        p=clean(v.get('product')); c=clean(v.get('category'))
                        if p: proto_products.append(p)
                        if c: proto_categories.append(c)
                terms=products+proto_products+proto_categories
                classes=classes_from_terms(terms)
                known=known_map.get(idx,{})
                cc_hit=cc_map.get(idx,{})
                data[genome].append({
                    'bgc_id': f"{rec_id}.region{str(idx).zfill(3)}",
                    'scaffold': scaffold,
                    'start': int(area.get('start',0))+1,
                    'end': int(area.get('end',0)),
                    'classes': classes,
                    'bgc_class': join_classes(classes),
                    'known_product': clean(known.get('known_product','')),
                    'known_accession': clean(known.get('known_accession','')),
                    'known_similarity': clean(known.get('known_similarity','')),
                    'cc_similarity_score': clean(cc_hit.get('cc_similarity_score','')),
                    'cc_compounds': clean(cc_hit.get('cc_compounds','')),
                    'cc_organism': clean(cc_hit.get('cc_organism',''))
                })
    return data


def parse_bigscape():
    out_files=os.path.join(BIGSCAPE_ROOT,'output_files')
    candidates=sorted(glob.glob(os.path.join(out_files,'*_c*')))
    if not candidates: return {},{}
    run_dir=candidates[-1]
    ann_path=os.path.join(run_dir,'record_annotations.tsv')
    if not os.path.isfile(ann_path): return {},{}
    ann={}
    with open(ann_path,encoding='utf-8') as fh:
        for row in csv.DictReader(fh,delimiter='\t'):
            rec=clean(row.get('Record'))
            if not rec: continue
            genome=rec.split('__',1)[0] if '__' in rec else clean(row.get('Organism')).replace(' ','_')
            ann[rec]={'genome':genome,'category':clean(row.get('Category')) or clean(row.get('Class'))}
    rec_to_family={}
    for tsv in glob.glob(os.path.join(run_dir,'*','*_clustering_*.tsv')):
        with open(tsv,encoding='utf-8') as fh:
            for row in csv.DictReader(fh,delimiter='\t'):
                rec=clean(row.get('Record')); fam=clean(row.get('Family'))
                if rec and fam: rec_to_family[rec]=fam
    return ann,rec_to_family

fun=parse_funbgcex(); anti=parse_antismash(); ann,rec_to_family=parse_bigscape()
all_genomes=sorted(set(fun.keys())|set(anti.keys())); target_genomes=set(all_genomes)
scaffold_rows=[]; bgc_rows=[]; summary_counts=defaultdict(lambda:{'shared':0,'unshared':0})

for genome in all_genomes:
    anti_by=defaultdict(list); fun_by=defaultdict(list)
    for r in anti.get(genome,[]): anti_by[r['scaffold']].append(r)
    for r in fun.get(genome,[]): fun_by[r['scaffold']].append(r)
    for scaf in sorted(set(anti_by)|set(fun_by)):
        a_rows=anti_by.get(scaf,[]); f_rows=fun_by.get(scaf,[])
        a_class=Counter(); f_class=Counter(); a_prod=Counter(); f_prod=Counter()
        for r in a_rows:
            for c in (r['classes'] or {'other'}): a_class[c]+=1
            if r.get('known_product'): a_prod[canon_term(r['known_product'])]+=1
        for r in f_rows:
            for c in (r['classes'] or {'other'}): f_class[c]+=1
            if r.get('metabolite'): f_prod[canon_term(r['metabolite'])]+=1
        scaffold_rows.append({
            'genome':genome,'scaffold':scaf,
            'antismash_bgc_count':len(a_rows),'funbgcex_bgc_count':len(f_rows),'same_bgc_count':'yes' if len(a_rows)==len(f_rows) else 'no',
            'antismash_class_counts':counter_to_text(a_class),'funbgcex_class_counts':counter_to_text(f_class),'same_class_counts':'yes' if dict(a_class)==dict(f_class) else 'no',
            'antismash_known_cluster_product_counts':counter_to_text(a_prod),'funbgcex_putative_product_counts':counter_to_text(f_prod),'same_putative_product_counts':'yes' if dict(a_prod)==dict(f_prod) and bool(a_prod or f_prod) else 'no'
        })
        pairs=[]
        for ai,a in enumerate(a_rows):
            for fi,f in enumerate(f_rows):
                ov=overlap(a.get('start',0),a.get('end',0),f.get('start',0),f.get('end',0))
                if ov>0: pairs.append((ov,ai,fi))
        pairs.sort(reverse=True)
        used_a=set(); used_f=set(); matches=[]
        for ov,ai,fi in pairs:
            if ai in used_a or fi in used_f: continue
            used_a.add(ai); used_f.add(fi); matches.append((ai,fi,ov))
        for ai,fi,ov in matches:
            a=a_rows[ai]; f=f_rows[fi]
            ap=clean(a.get('known_product','')); fp=clean(f.get('metabolite',''))
            bgc_rows.append({
                'genome':genome,'scaffold':scaf,'overlap_bp':ov,
                'antismash_bgc_id':a['bgc_id'],'antismash_start':a.get('start',''),'antismash_end':a.get('end',''),
                'antismash_bgc_class':a.get('bgc_class',''),
                
                'antismash_knowncluster_similarity_score':a.get('known_similarity',''),
                'antismash_knowncluster_accession':a.get('known_accession',''),
                'antismash_knowncluster_product':ap,
                'antismash_clustercompare_similarity_score':a.get('cc_similarity_score',''),
                'antismash_clustercompare_compounds':a.get('cc_compounds',''),
                'antismash_clustercompare_organism':a.get('cc_organism',''),
                'funbgcex_bgc_id':f['bgc_id'],'funbgcex_start':f.get('start',''),'funbgcex_end':f.get('end',''),
                'funbgcex_core_enzymes':f.get('core_enzymes',''),
                'funbgcex_similar_bgc':f.get('similar_bgc',''),
                'funbgcex_similarity_score':f.get('similarity_score',''),
                'funbgcex_putative_product':fp,
                'same_putative_product_exact':'yes' if canon_term(ap) and canon_term(ap)==canon_term(fp) else 'no',
                'same_putative_product_keyword':'yes' if (ap and fp and bool(token_set(ap)&token_set(fp))) else 'no',
            })
        for ai,a in enumerate(a_rows):
            if ai in used_a: continue
            bgc_rows.append({'genome':genome,'scaffold':scaf,'overlap_bp':0,
                'antismash_bgc_id':a['bgc_id'],'antismash_start':a.get('start',''),'antismash_end':a.get('end',''),
                'antismash_bgc_class':a.get('bgc_class',''),'antismash_knowncluster_similarity_score':a.get('known_similarity',''),'antismash_knowncluster_accession':a.get('known_accession',''),'antismash_knowncluster_product':clean(a.get('known_product','')),'antismash_clustercompare_similarity_score':a.get('cc_similarity_score',''),'antismash_clustercompare_compounds':a.get('cc_compounds',''),'antismash_clustercompare_organism':a.get('cc_organism',''),
                'funbgcex_bgc_id':'','funbgcex_start':'','funbgcex_end':'','funbgcex_core_enzymes':'','funbgcex_similar_bgc':'','funbgcex_similarity_score':'','funbgcex_putative_product':'',
                'same_putative_product_exact':'no','same_putative_product_keyword':'no'})
        for fi,f in enumerate(f_rows):
            if fi in used_f: continue
            bgc_rows.append({'genome':genome,'scaffold':scaf,'overlap_bp':0,
                'antismash_bgc_id':'','antismash_start':'','antismash_end':'','antismash_bgc_class':'','antismash_knowncluster_similarity_score':'','antismash_knowncluster_accession':'','antismash_knowncluster_product':'','antismash_clustercompare_similarity_score':'','antismash_clustercompare_compounds':'','antismash_clustercompare_organism':'',
                'funbgcex_bgc_id':f['bgc_id'],'funbgcex_start':f.get('start',''),'funbgcex_end':f.get('end',''),'funbgcex_core_enzymes':f.get('core_enzymes',''),'funbgcex_similar_bgc':f.get('similar_bgc',''),'funbgcex_similarity_score':f.get('similarity_score',''),'funbgcex_putative_product':clean(f.get('metabolite','')),
                'same_putative_product_exact':'no','same_putative_product_keyword':'no'})
        for cls in sorted(set(a_class)|set(f_class)):
            a_n=a_class.get(cls,0); f_n=f_class.get(cls,0); sh=min(a_n,f_n)
            summary_counts[(genome,'antismash','BGC',cls)]['shared']+=sh; summary_counts[(genome,'antismash','BGC',cls)]['unshared']+=max(0,a_n-f_n)
            summary_counts[(genome,'funbgcex','BGC',cls)]['shared']+=sh; summary_counts[(genome,'funbgcex','BGC',cls)]['unshared']+=max(0,f_n-a_n)

family_to_genomes=defaultdict(set); record_to_class={}; record_to_genome={}
for rec,fam in rec_to_family.items():
    if rec not in ann: continue
    genome=ann[rec]['genome']
    if genome not in target_genomes: continue
    record_to_class[rec]=join_classes(classes_from_terms(split_multi(ann[rec]['category']))); record_to_genome[rec]=genome; family_to_genomes[fam].add(genome)
seen=defaultdict(lambda:{'shared':set(),'unshared':set()})
for rec,fam in rec_to_family.items():
    if rec not in record_to_class or rec not in record_to_genome: continue
    genome=record_to_genome[rec]; cls=record_to_class[rec]; seen[(genome,cls)]['shared' if len(family_to_genomes[fam])>1 else 'unshared'].add(fam)
for (genome,cls),payload in seen.items():
    summary_counts[(genome,'antismash','GCF',cls)]['shared']+=len(payload['shared']); summary_counts[(genome,'antismash','GCF',cls)]['unshared']+=len(payload['unshared'])

with open(SCAFFOLD_COMPARISON_CSV,'w',newline='',encoding='utf-8') as fh:
    fields=['genome','scaffold','antismash_bgc_count','funbgcex_bgc_count','same_bgc_count','antismash_class_counts','funbgcex_class_counts','same_class_counts','antismash_known_cluster_product_counts','funbgcex_putative_product_counts','same_putative_product_counts']
    w=csv.DictWriter(fh,fieldnames=fields); w.writeheader();
    for r in sorted(scaffold_rows,key=lambda x:(x['genome'],x['scaffold'])): w.writerow(r)

with open(BGC_COMPARISON_CSV,'w',newline='',encoding='utf-8') as fh:
    fields=['genome','scaffold','overlap_bp','antismash_bgc_id','antismash_start','antismash_end','antismash_bgc_class','antismash_knowncluster_similarity_score','antismash_knowncluster_accession','antismash_knowncluster_product','antismash_clustercompare_similarity_score','antismash_clustercompare_compounds','antismash_clustercompare_organism','funbgcex_bgc_id','funbgcex_start','funbgcex_end','funbgcex_core_enzymes','funbgcex_similar_bgc','funbgcex_similarity_score','funbgcex_putative_product','same_putative_product_exact','same_putative_product_keyword']
    w=csv.DictWriter(fh,fieldnames=fields); w.writeheader();
    for r in sorted(bgc_rows,key=lambda x:(x['genome'],x['scaffold'],str(x['antismash_bgc_id']),str(x['funbgcex_bgc_id']))): w.writerow(r)

with open(SUMMARY_CSV,'w',newline='',encoding='utf-8') as fh:
    fields=['genome','tool','entity_type','class_norm','shared_count','unshared_count','total']
    w=csv.DictWriter(fh,fieldnames=fields); w.writeheader();
    rows=[]
    for (g,t,e,c),v in summary_counts.items():
        sh=int(v['shared']); un=int(v['unshared']); rows.append({'genome':g,'tool':t,'entity_type':e,'class_norm':c,'shared_count':sh,'unshared_count':un,'total':sh+un})
    for r in sorted(rows,key=lambda x:(x['genome'],x['entity_type'],x['tool'],x['class_norm'])): w.writerow(r)

print(f"Wrote scaffold comparison table: {SCAFFOLD_COMPARISON_CSV}")
print(f"Wrote BGC comparison table:      {BGC_COMPARISON_CSV}")
print(f"Wrote summary table:             {SUMMARY_CSV}")
PY

[[ -f "${BGC_GCF_CROSSWALK_PY}" ]] || { echo "ERROR: crosswalk builder not found: ${BGC_GCF_CROSSWALK_PY}" >&2; exit 1; }
[[ -f "${TARGETED_ANALYSIS_PY}" ]] || { echo "ERROR: targeted analysis script not found: ${TARGETED_ANALYSIS_PY}" >&2; exit 1; }

"${PYTHON_BIN}" "${BGC_GCF_CROSSWALK_PY}" --project-root "${PROJECTS_ROOT}" --project-name "${PROJECT_NAME}"

if [[ "${RUN_ECOLOGY_ANALYSIS}" != "1" ]]; then
  echo "Skipped ecology-aware ranking: set RUN_ECOLOGY_ANALYSIS=1 to enable metadata-driven candidate tables."
  echo "Done."
  exit 0
fi

if [[ ! -f "${METADATA_TSV}" && "${AUTO_NORMALIZE_METADATA}" == "1" ]]; then
  if [[ -f "${NORMALIZE_METADATA_PY}" && -f "${ACCESSIONS_MAP}" ]]; then
    echo "Metadata TSV missing; generating a normalized scaffold from ${ACCESSIONS_MAP}"
    "${PYTHON_BIN}" "${NORMALIZE_METADATA_PY}" \
      --accessions "${ACCESSIONS_MAP}" \
      --out "${METADATA_TSV}" \
      --template-out "${METADATA_TEMPLATE_TSV}" \
      --allow-missing-legacy
  else
    echo "WARN: metadata TSV missing and auto-normalization inputs are incomplete." >&2
    [[ -f "${NORMALIZE_METADATA_PY}" ]] || echo "WARN: normalize_metadata.py not found: ${NORMALIZE_METADATA_PY}" >&2
    [[ -f "${ACCESSIONS_MAP}" ]] || echo "WARN: accession mapping not found: ${ACCESSIONS_MAP}" >&2
  fi
fi

if [[ ! -f "${METADATA_TSV}" ]]; then
  echo "WARN: skipping candidate ranking because metadata is missing: ${METADATA_TSV}" >&2
  echo "Done."
  exit 0
fi

candidate_args=(
  "${PYTHON_BIN}" "${TARGETED_ANALYSIS_PY}"
  --project-root "${PROJECTS_ROOT}"
  --project-name "${PROJECT_NAME}"
  --ecology-field "${ECOLOGY_FIELD}"
)
if [[ -n "${TARGET_GENOME:-}" ]]; then
  candidate_args+=(--target-genome "${TARGET_GENOME}")
fi
if [[ -n "${FOCUS_ECOLOGY_LABEL}" ]]; then
  candidate_args+=(--focus-ecology-label "${FOCUS_ECOLOGY_LABEL}")
fi
"${candidate_args[@]}"

echo "Done."
