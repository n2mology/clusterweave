#!/usr/bin/env python3
"""Local CLI decision control; hosted jobs use the authenticated queue API."""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
import cohort_gate as gate
from researcher_report import CONFIGURATION, input_fingerprints, source_fingerprint


def context(results):
    data = Path(os.environ.get('DATA_ROOT', str(results.parent.parent)))
    project = os.environ.get('PROJECT_NAME', results.name)
    roots = [Path(os.environ.get('FUNGI_GENOME_ROOT', os.environ.get('GENOME_ROOT', str(data/'genomes/fungi'/project)))), Path(os.environ.get('BACTERIA_GENOME_ROOT', str(data/'genomes/bacteria'/project))), Path(os.environ.get('PLANTS_GENOME_ROOT', str(data/'genomes/plants'/project)))]
    settings = {key:os.environ[key] for key in CONFIGURATION if key in os.environ}
    for public, shell in [('annotation','RUN_STAGE_ANNOTATION'),('bigscape','RUN_STAGE_BIGSCAPE'),('summary','RUN_STAGE_SUMMARY'),('clinker','RUN_STAGE_CLINKER'),('figures','RUN_SUMMARY_FIGURES')]:
        settings['run_'+public] = os.environ.get(shell,'1')
    return {'identity':{'scope':'local_cli','source_sha256':source_fingerprint(ROOT),
                        'inputs':input_fingerprints(roots), 'configuration_sha256':gate.fingerprint(settings)},
            'settings':settings, 'asset_environment':{key:os.environ.get(key, default) for key,default in [('SOFTWARE_ROOT','/software'),('ANTISMASH_DB_DIR','/antismash_db'),('PFAM_DIR','/pfam_db'),('FUNANNOTATE_DB','/software/funannotate_db')]}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','continue','complete'])
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--control',type=Path,required=True)
    parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--decision')
    args=parser.parse_args()
    if os.environ.get('CLUSTERWEAVE_JOB_ID'):
        raise gate.GateError('Hosted continuation requires authenticated server queue admission')
    if args.action=='complete':
        gate.atomic_json(args.control.parent/'local-completed.json', {'decision_id':args.decision})
        return
    completed=args.control.parent/'local-completed.json'
    if args.action=='continue' and completed.is_file() and json.loads(completed.read_text()).get('decision_id')==args.decision:
        raise SystemExit(76)
    current=context(args.results)
    if args.action=='init':
        gate.atomic_json(args.context,current)
        return
    value=gate.load_gate(args.control)
    if args.decision != value['decision_id'] or current['identity'] != value['identity']:
        raise gate.GateError('Local decision is stale; input, source or configuration changed')
    # The process lock covers acceptance and the whole local downstream run.
    # run_clusterweave.sh holds it until exit and keeps ordinary resource flags.
    gate.verify_assets(value.get('assets',{}))
    accepted=gate.accept(args.control,value['decision_id'],value['included'],value['excluded'],attempt_identity=current['identity'])
    destination=args.results.with_name(args.results.name+'.cohort-'+value['attempt'])
    gate.materialize(accepted,destination)
    input_root = destination.parent / ('.inputs-' + value['attempt'])
    source_data = Path(os.environ.get('DATA_ROOT', str(args.results.parent.parent)))
    project = os.environ.get('PROJECT_NAME', args.results.name)
    variables = {}
    import shutil
    for taxon in ('fungi','bacteria','plants'):
        key=taxon.upper()+'_GENOME_ROOT'
        source=Path(os.environ.get(key, os.environ.get('GENOME_ROOT', str(source_data/'genomes/fungi'/project)) if taxon=='fungi' else str(source_data/'genomes'/taxon/project)))
        target=input_root/taxon;target.mkdir(parents=True,exist_ok=True)
        for genome in value['included']:
            for path in source.glob(genome+'.*'):
                if path.suffix.lower() in {'.fna','.fa','.fasta','.gbk','.gb','.gbff','.gff','.gff3'}:
                    if path.is_symlink() or not path.is_file():raise gate.GateError('Unsafe retained input')
                    output=target/path.name
                    if output.exists() and gate.digest(output)!=gate.digest(path):raise gate.GateError('Retained input changed')
                    if not output.exists():shutil.copy2(path,output)
        variables[key]=str(target)
    variables['GENOME_ROOT']=variables['FUNGI_GENOME_ROOT']
    variables.update({'RESULTS_ROOT':str(destination),'GENOME_TAXON_MANIFEST':str(destination/'summary_tables/genome_taxon_manifest.tsv'),
               'WORK_ROOT':str(destination.parent/('.work-'+value['attempt'])), 'RUN_STAGE_ANNOTATION':'0'})
    for name in ('bigscape','summary','clinker'):
        if not value['plan'][name].startswith('will run'):
            variables['RUN_STAGE_'+name.upper()]='0'
    if not value['plan']['figures'].startswith('will run'):
        variables['RUN_SUMMARY_FIGURES']='0'
    # The scientific scripts consume result-local routes; no rejected native
    # folder is present in this workspace.
    print('\n'.join('export '+key+'='+shlex.quote(val) for key,val in variables.items()))


if __name__=='__main__':
    main()
