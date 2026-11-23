#!/usr/bin/env python3
"""Explicit operator preparation of the pinned plantiSMASH SIF from public sources."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
RECIPE=ROOT/'software/plantismash'
sys.path.insert(0,str(RECIPE))
from prepare import prepare, digest
from package_sif import package


def require_space(path, minimum, allowance=0):
    if shutil.disk_usage(path).free < minimum + allowance:
        raise ValueError('Insufficient storage for preparation while preserving the free-space reserve')


def build_image(command, log, log_path, minimum, timeout=3600):
    process = subprocess.Popen(command, env=dict(os.environ, DOCKER_BUILDKIT='0', BUILDX_GIT_INFO='false'),
                               stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            require_space(log_path.parent, minimum, 2 * 1024**3)
            if time.monotonic() > deadline:
                raise TimeoutError('plantiSMASH image preparation exceeded its time budget')
            time.sleep(1)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    except BaseException:
        # Target only this legacy build's current intermediate container.
        log.flush()
        ids = re.findall(r'Running in ([0-9a-f]{12})', log_path.read_text())
        if ids:
            subprocess.run(['docker', 'stop', '--time', '2', ids[-1]], stdout=log, stderr=subprocess.STDOUT)
        process.terminate()
        process.wait(timeout=30)
        raise



def retire_preparation_stage(tag, final_tag, attempt):
    """Retire only this invocation's temporary stage; keep provenance and locks."""
    metadata=json.loads(subprocess.check_output(['docker','image','inspect',tag]))[0]
    final=json.loads(subprocess.check_output(['docker','image','inspect',final_tag]))[0]
    if metadata['Id']==final['Id'] or metadata.get('RepoTags') != [tag]:
        raise ValueError('Preparation stage has an unexpected identity or retained tag')
    out=attempt/'stage-retirement';out.mkdir(exist_ok=False)
    allowed=set(re.findall(r' ---> ([0-9a-f]{12})', (attempt/'preparation.log').read_text()))
    identity=metadata['Id'];rows=[]
    while identity:
        inspected=subprocess.run(['docker','image','inspect',identity],capture_output=True,text=True)
        if inspected.returncode:break  # Docker already retired an unused parent.
        item=json.loads(inspected.stdout)[0]
        if identity != metadata['Id'] and (identity[7:19] not in allowed or item.get('RepoTags')):break
        if subprocess.check_output(['docker','ps','-aq','--filter','ancestor='+identity],text=True).strip():break
        (out/(identity[7:]+'.json')).write_text(inspected.stdout)
        (out/(identity[7:]+'.history.jsonl')).write_bytes(subprocess.check_output(
            ['docker','image','history','--no-trunc','--format','{{json .}}',identity]))
        removed=subprocess.run(['docker','image','rm',tag if identity==metadata['Id'] else identity],capture_output=True,text=True)
        rows.append({'image':identity,'returncode':removed.returncode,'stdout':removed.stdout,'stderr':removed.stderr})
        if removed.returncode:break  # A shared/retained child is never forced away.
        identity=item.get('Parent')
    (out/'receipt.json').write_text(json.dumps({'final_image':final['Id'],'temporary_stage':metadata['Id'],
        'reason':'Scientific runtime retained in final image; redundant preparation layers retired without force. Exact controls, acquisition receipts, image metadata and build outcome retained.',
        'operations':rows},indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-image',required=True,help='Locally built complete worker image with pinned Apptainer')
    parser.add_argument('--software-root',required=True,type=Path,help='Operator-owned prepared software directory')
    parser.add_argument('--cache',required=True,type=Path,help='Verified reusable public-source download cache')
    parser.add_argument('--attempts',required=True,type=Path,help='Retained build contexts and logs; each attempt is new')
    parser.add_argument('--min-free-gib',type=int,default=30,help='Free-space reserve; cannot be less than 30 GiB')
    parser.add_argument('--build-allowance-gib',type=int,default=36,help='Prospective space for source acquisition, context, image and temporary copy layers')
    parser.add_argument('--max-export-gib',type=int,default=8)
    parser.add_argument('--tmpfs-build-gib',type=int,default=12)
    args=parser.parse_args();lock=json.loads((RECIPE/'runtime.lock.json').read_text())
    if args.min_free_gib < 30 or args.build_allowance_gib < 1 or args.max_export_gib < 1 or not 0 <= args.tmpfs_build_gib <= 32:
        parser.error('Invalid preparation budget (minimum reserve is 30 GiB)')
    if digest(ROOT/'config/plantismash-profile.json') != lock['profile_sha256']:
        raise ValueError('Runtime lock does not match the requested scientific profile')
    for filename, key in [('sources.lock.json','recipe_source_lock_sha256'), ('resources.lock.json','resources_lock_sha256')]:
        if key not in lock or digest(RECIPE/filename) != lock[key]:
            raise ValueError('Runtime lock does not match '+filename)
    output=args.software_root/'plantismash/plant.sif'
    if output.exists():
        if digest(output)==lock['preferred_sif_sha256']:
            print('Pinned plantiSMASH is prepared; verified reuse.');return
        raise ValueError('Existing SIF differs. Preserve it and select a new software root; preparation never silently replaces it.')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    attempt=args.attempts/stamp;attempt.mkdir(parents=True,exist_ok=False)
    minimum=args.min_free_gib*1024**3
    for path in [attempt,args.cache,args.software_root]:
        path.mkdir(parents=True,exist_ok=True)
        require_space(path,minimum,args.build_allowance_gib*1024**3)
    (attempt/'runtime.lock.json').write_text(json.dumps(lock,indent=2)+'\n')
    with (attempt/'preparation.log').open('w') as log:
        prepare(args.cache,attempt/'context')
        source=json.loads((RECIPE/'sources.lock.json').read_text());base=source['base_image']
        if subprocess.run(['docker','image','inspect',base],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
            subprocess.run(['docker','pull',base],stdout=log,stderr=subprocess.STDOUT,check=True)
        tag='clusterweave-plantismash:prepare-'+stamp.lower()
        builder_tag=tag+'-builder'
        for target, selected_tag in [('builder',builder_tag),(None,tag)]:
            command=['docker','build','--pull=false','--network','none','--cpu-quota','200000','--memory','8g','-t',selected_tag]
            if target:command += ['--target',target]
            command.append(str(attempt/'context'))
            build_image(command,log,attempt/'preparation.log',minimum)
        log.flush()
        retire_preparation_stage(builder_tag,tag,attempt)
        require_space(args.software_root,minimum,(args.max_export_gib+4)*1024**3)
        result=package(tag,args.worker_image,output,lock['preferred_sif_sha256'],
                       max_export_bytes=args.max_export_gib*1024**3,min_free_bytes=minimum,
                       tmpfs_build_gib=args.tmpfs_build_gib)
        (attempt/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Prepared and checksum-verified '+str(output))

if __name__=='__main__':main()
