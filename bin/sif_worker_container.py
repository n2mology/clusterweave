#!/usr/bin/env python3
"""Render/create a confined SIF worker from a rendered Compose configuration.

Run on the operator host, never as an application daemon. Compose cannot express
per-path OCI proc masking; this adapter supplies only the measured exception and
keeps the equivalent AppArmor denials. It never updates or removes a container.
"""
from pathlib import Path
import argparse
import json
import re
import math
import subprocess


def size(value):
    match = re.fullmatch(r'(\d+)([kmgt]?)b?', str(value).lower())
    if not match:
        raise ValueError('Invalid memory limit')
    return int(match[1]) * 1024 ** ('kmgt'.index(match[2]) + 1 if match[2] else 0)


def render(model, image, security_dir):
    worker = model['services']['worker']
    instance = model['name']
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,48}', instance):
        raise ValueError('Use a unique lowercase instance name')
    if worker['container_name'] != instance + '-worker':
        raise ValueError('Worker name must belong to this instance')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', worker['image']):
        raise ValueError('Worker image must be an exact local image ID')
    if image['Id'] != worker['image']:
        raise ValueError('Image identity mismatch')
    if worker.get('user') != '65534:65534' or not worker.get('read_only'):
        raise ValueError('Nonroot user and read-only root are required')
    if worker.get('cap_drop') != ['ALL'] or worker.get('cap_add') or worker.get('privileged'):
        raise ValueError('All initial-namespace capabilities must be dropped')
    if worker.get('labels', {}).get('org.clusterweave.runtime') != 'confined-sif-v1':
        raise ValueError('Wrong runtime profile')
    mounts=[]
    targets={'/data':('job_data',False), '/data/software':('software',True),
             '/var/cache/clusterweave':('accession_cache',False),
             '/databases/antismash':('antismash_db',True), '/databases/pfam':('pfam_db',True)}
    for mount in worker['volumes']:
        key, readonly=targets.pop(mount['target'])
        if mount['type'] != 'volume' or mount['source'] != key or bool(mount.get('read_only')) != readonly:
            raise ValueError('Unexpected worker mount')
        definition=model['volumes'][key]; name=definition['name']
        if not readonly and (definition.get('external') or name != instance+'_'+key):
            raise ValueError('Writable volume must belong to this instance')
        if key=='software' and (definition.get('external') or name != instance+'_software'):
            raise ValueError('Prepared software volume must belong to this instance')
        mounts.append({'Type':'volume','Source':name,'Target':mount['target'],'ReadOnly':readonly,'VolumeOptions':{'NoCopy':True}})
    if targets:
        raise ValueError('Missing required mounts')
    devices=worker.get('devices')
    if devices != [{'source':'/dev/fuse','target':'/dev/fuse','permissions':'rw'}]:
        raise ValueError('Only the measured FUSE device is permitted')
    opts=worker['security_opt']; aa=[x.split(':',1)[1] for x in opts if x.startswith('apparmor:')]
    if len(aa)!=1 or aa[0]=='unconfined' or not re.fullmatch(r'[a-zA-Z0-9_-]+',aa[0]):
        raise ValueError('A named enforcing AppArmor profile is required')
    if set(x for x in opts if not x.startswith('apparmor:')) != {'no-new-privileges:true','seccomp:./config/security/apptainer-worker-seccomp.json'}:
        raise ValueError('Unexpected security options')
    seccomp=json.loads((Path(security_dir)/'apptainer-worker-seccomp.json').read_text())
    if seccomp['defaultAction']!='SCMP_ACT_ERRNO':
        raise ValueError('Default-deny seccomp required')
    env=dict(x.split('=',1) for x in image['Config'].get('Env',[]))
    env.update({k:str(v) for k,v in worker['environment'].items() if v is not None})
    for key,value in {'ENGINE':'apptainer','CLUSTERWEAVE_ENABLE_DOCKER_SOCKET':'0','CLUSTERWEAVE_LOCAL_PREPARED_ONLY':'1'}.items():
        if env.get(key)!=value:raise ValueError('Unexpected runtime setting: '+key)
    if env.get('DOCKER_HOST') or env.get('APPTAINER_DOCKER_HOST'):
        raise ValueError('Job-time Docker dispatch is not supported')
    cpus=float(worker['cpus']); memory=size(worker['mem_limit']); pids=int(worker['pids_limit'])
    concurrency=int(env.get('WORKER_CONCURRENCY', '1'))
    if not math.isfinite(cpus) or cpus < 1 or memory <= 0 or pids <= 0 or not 1 <= concurrency <= int(cpus):
        raise ValueError('Explicit positive worker limits and CPU-bounded concurrency are required')
    if worker['tmpfs'] != ['/tmp:rw,exec,nosuid,nodev,size=4g']:
        raise ValueError('Unexpected temporary filesystem')
    network=model['networks']['default']['name']
    if network != instance+'_default' or model['networks']['default'].get('external'):
        raise ValueError('Private instance network required')
    return {'Image':image['Id'],'User':'65534:65534','Env':[k+'='+v for k,v in sorted(env.items())],
            'Entrypoint':image['Config']['Entrypoint'],'Cmd':image['Config'].get('Cmd'),
            'WorkingDir':image['Config'].get('WorkingDir','/'),
            'Labels':{'org.clusterweave.runtime':'confined-sif-v1','org.clusterweave.instance':instance},
            'HostConfig':{'Init':True,'NetworkMode':network,'ReadonlyRootfs':True,'CapDrop':['ALL'],
                         'SecurityOpt':['no-new-privileges','apparmor='+aa[0],'seccomp='+json.dumps(seccomp,separators=(',',':'))],
                         'Devices':[{'PathOnHost':'/dev/fuse','PathInContainer':'/dev/fuse','CgroupPermissions':'rw'}],
                         'Mounts':mounts,'Tmpfs':{'/tmp':'rw,exec,nosuid,nodev,size=4g'},
                         'MaskedPaths':['/sys/devices/virtual/powercap','/sys/firmware'], 'ReadonlyPaths':[],
                         'NanoCpus':int(cpus*1e9),'Memory':memory,'MemorySwap':memory,'PidsLimit':pids,
                         'ShmSize':size(worker.get('shm_size','512m')),'RestartPolicy':{'Name':'no'}}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration',type=Path,help='docker compose --profile sif-worker-template config --format json output')
    parser.add_argument('--output',required=True,type=Path,help='New private API specification; contains environment secrets')
    parser.add_argument('--create',action='store_true',help='Create only; explicit docker start follows verification')
    args=parser.parse_args();model=json.loads(args.configuration.read_text())
    identity=model['services']['worker']['image']
    image=json.loads(subprocess.check_output(['docker','image','inspect',identity]))[0]
    spec=render(model,image,Path(__file__).resolve().parents[1]/'config/security')
    with open(args.output,'x',opener=lambda path,flags:__import__('os').open(path,flags,0o600)) as f:
        json.dump(spec,f,indent=2);f.write('\n')
    if args.create:
        # Refuse local-driver bind tricks and non-bridge networks. These checks
        # inspect only the exact named resources selected by this instance.
        for mount in spec['HostConfig']['Mounts']:
            volume=json.loads(subprocess.check_output(['docker','volume','inspect',mount['Source']]))[0]
            if volume.get('Driver')!='local' or volume.get('Options'):
                raise ValueError('Only ordinary local named volumes are supported')
        network=json.loads(subprocess.check_output(['docker','network','inspect',spec['HostConfig']['NetworkMode']]))[0]
        if network.get('Driver')!='bridge':
            raise ValueError('The instance must use a private bridge network')
        # curl talks to the operator's local daemon once. No socket or host
        # launcher is supplied to the resulting worker or its descendants.
        name=model['services']['worker']['container_name']
        subprocess.run(['curl','--fail','--silent','--show-error','--unix-socket','/var/run/docker.sock',
                        '-H','Content-Type: application/json','--data-binary','@'+str(args.output.resolve()),
                        'http://localhost/v1.47/containers/create?name='+name],check=True)

if __name__=='__main__':main()
