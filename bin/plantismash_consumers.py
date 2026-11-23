#!/usr/bin/env python3
"""Validated plant native records and derived BiG-SCAPE input containers."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
from plantismash_native import PRODUCER, PUBLIC_PRODUCER, read_native


def validated_results(results):
    manifest = results / 'summary_tables/genome_taxon_manifest.tsv'
    if not manifest.is_file():
        native_root = results / 'plantismash'
        if native_root.is_dir() and any(native_root.iterdir()):
            raise ValueError('Plant native outputs require the result-local taxon manifest; an absent manifest is not an empty detection')
        return []
    with manifest.open() as handle:
        routes = list(csv.DictReader(handle, delimiter='\t'))
    plants = [r for r in routes if r['taxon_group'] == 'plants' and r.get('route_status') not in {'failed','invalid','rejected','unresolved','unsupported'}]
    outputs = []
    seen = set()
    for route in plants:
        import re
        genome = route['genome_id']
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', genome) or genome.casefold() in seen:
            raise ValueError('Invalid or duplicate native genome identity')
        seen.add(genome.casefold())
        root = results / 'plantismash' / route['genome_id']
        outcome = json.loads((root / 'outcome.json').read_text())
        if outcome.get('state') not in {'SUCCESS_WITH_CALLS','SUCCESSFUL_EMPTY'}:
            raise ValueError('Plant output has no successful current outcome: ' + genome)
        original = json.loads((root / 'original-identity.json').read_text())
        value = read_native(original, root / 'native')
        if not value['valid']:
            raise ValueError(f"Plant native output is missing, failed or corrupt for {route['genome_id']}: {value['reasons']}")
        outputs.append((route, root, value))
    return outputs


def cluster_cds_provenance(record, parent, call, owner):
    """Carry validated original feature keys into an unchanged native crop."""
    candidates = {}
    for item in owner['CDS']:
        feature = parent.features[item['native_feature_ordinal']]
        if int(feature.location.start) < call['start_0'] or int(feature.location.end) > call['end_0']:
            continue
        shifted = feature._shift(-call['start_0'])
        key = json.dumps([str(shifted.location), shifted.qualifiers], sort_keys=True)
        candidates.setdefault(key, []).append(item)
    output, used = [], set()
    for ordinal, feature in enumerate(record.features):
        if feature.type != 'CDS':
            continue
        key = json.dumps([str(feature.location), feature.qualifiers], sort_keys=True)
        hits = candidates.get(key, [])
        if len(hits) != 1 or hits[0]['original_feature_key'] in used:
            raise ValueError(f"Native crop provenance conflict: record={call['original_record_id']} "
                             f"cluster={call['cluster_key']} feature={ordinal} "
                             f"candidates={[x['original_feature_key'] for x in hits]}")
        item = hits[0]
        used.add(item['original_feature_key'])
        output.append({'native_feature_ordinal': ordinal,
                       'original_feature_key': item['original_feature_key'],
                       'original_feature_ordinal': item['original_feature_ordinal'],
                       'original_location': item['location'],
                       'original_protein_id': item['original_qualifiers'].get('protein_id', [])})
    if used != set(call['members']):
        raise ValueError('Native crop provenance does not cover original cluster members')
    return output


def stage(results, destination, crosswalk):
    from Bio import SeqIO
    from Bio.SeqFeature import SeqFeature, SimpleLocation
    records = []
    for route, root, value in validated_results(results):
        full = {r.id: r for r in SeqIO.parse(next((root / 'native').glob('*.final.gbk')), 'genbank')}
        original_metadata = {r.id: dict(r.annotations) for r in SeqIO.parse(root / 'original.gbk', 'genbank')}
        owners = {r['native_id']: r for r in value['identity']['records']}
        for call in value['calls']:
            native = root / 'native' / call['native_cluster_gbk']
            region = native.stem
            genome = route['genome_id']
            key = genome + '__' + region
            target = destination / (key + '.gbk')
            if target.exists():
                raise ValueError('Duplicate plant grouping identity: ' + key)
            record = SeqIO.read(native, 'genbank')
            original_features = [(f.type, str(f.location), f.qualifiers) for f in record.features]
            original_id = record.id
            provenance = cluster_cds_provenance(record, full[original_id], call, owners[original_id])
            identity = hashlib.sha256((PRODUCER + '\0' + genome + '\0' + call['cluster_key']).encode()).hexdigest()
            record.id = record.name = 'CW' + identity[:14]
            record.annotations['accessions'] = [record.id]
            # Native cropped records lose organism/source/taxonomy. Restore only
            # validated input metadata on the derived grouping container.
            metadata = original_metadata[call['original_record_id']]
            organism = str(metadata.get('organism') or '').strip()
            if organism in {'', '.', 'unknown'}:
                organism = str(route.get('organism_name') or '').strip()
            if organism in {'', '.', 'unknown'}:
                raise ValueError('Plant grouping requires an authoritative organism name')
            record.annotations['organism'] = organism
            for field in ['source', 'taxonomy']:
                if metadata.get(field):
                    record.annotations[field] = metadata[field]
            clusters = [f for f in record.features if f.type == 'cluster']
            if len(clusters) != 1:
                raise ValueError('Expected exactly one native cluster per grouping slice')
            cluster = clusters[0]
            record.features.append(SeqFeature(SimpleLocation(int(cluster.location.start),int(cluster.location.end)),type='region',qualifiers={'region_number':['1'],'product':list(cluster.qualifiers['product']),'note':['ClusterWeave derived grouping container from plantiSMASH2.0.4; original cluster retained; no antiSMASH prediction or domain provenance'],'tool':['ClusterWeave staging adapter']}))
            SeqIO.write(record,target,'genbank')
            restored = SeqIO.read(target,'genbank')
            if restored.seq != record.seq or [(f.type,str(f.location),f.qualifiers) for f in restored.features[:-1]] != original_features:
                raise ValueError('Plant grouping container changed scientific features')
            records.append({'genome_id':genome,'region_id':region,'producer':PUBLIC_PRODUCER,'scope':'plants','raw_gbk':key,'raw_record':key+'.gbk_region_1','original_record_id':call['original_record_id'],'native_record_id':original_id,'cluster_key':call['cluster_key'],'native_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),'stage_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'technical_duplicate_of':None,'original_record_ordinal':call['original_record_ordinal'],'parent_start_0':call['start_0'],'parent_end_0':call['end_0'],'cds_provenance':provenance})
            with crosswalk.open('a') as handle:
                handle.write(f'{target.name}\t{genome}\tplants\texisting_cds\t{genome}/{native.name}\n')
    path = results / 'summary/native_reporting_keys.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'schema':'native-reporting-view-v1','records':records,'selection_scope':'Complete native CDS are supplied. BiG-SCAPE applies its unchanged overlap/length rules; selected content can exclude distinct genes and domains. Distances and families are not guaranteed invariant to input ordering or technical copies.','historical_D1':'FAIL','historical_D3':'FAIL'},indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['check','stage'])
    p.add_argument('--results',type=Path,required=True)
    p.add_argument('--destination',type=Path)
    p.add_argument('--crosswalk',type=Path)
    args=p.parse_args()
    if args.action=='check':
        print(sum(len(value['calls']) for route,root,value in validated_results(args.results)))
    else:
        stage(args.results,args.destination,args.crosswalk)

if __name__=='__main__':
    main()
