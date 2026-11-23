#!/usr/bin/env python3
"""Acquire hash-bound build inputs and prepare an offline plantiSMASH image context."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parent

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def acquire(url, expected, destination, max_bytes=1024**3):
    """Promote only complete verified bytes, preserving corrupt/interrupted attempts."""
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if urllib.parse.urlsplit(url).scheme!='https':raise ValueError('Preparation requires HTTPS sources')
    with destination.with_suffix(destination.suffix+'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if destination.exists():
            if digest(destination)==expected:return 'reused'
            destination.rename(destination.with_name(destination.name+'.corrupt-'+str(time.time_ns())))
        partial=destination.with_name(destination.name+'.partial')
        if partial.exists():partial.rename(partial.with_name(partial.name+'-interrupted-'+str(time.time_ns())))
        try:
            with urllib.request.urlopen(url,timeout=90) as response,partial.open('xb') as output:
                if urllib.parse.urlsplit(response.url).scheme!='https':raise ValueError('Insecure redirect')
                size=0
                while True:
                    block=response.read(1024*1024)
                    if not block:break
                    size+=len(block)
                    if size>max_bytes:raise ValueError('Source exceeds preparation size bound')
                    output.write(block)
                output.flush();os.fsync(output.fileno())
            if digest(partial)!=expected:raise ValueError('Source checksum mismatch')
            os.replace(partial,destination)
            fd=os.open(destination.parent,os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
            return 'acquired'
        except BaseException:
            if partial.exists():partial.rename(partial.with_name(partial.name+'-failed-'+str(time.time_ns())))
            raise

def prepare(cache, context):
    lock=json.loads((ROOT/'sources.lock.json').read_text());cache=Path(cache);context=Path(context)
    context.mkdir(parents=True,exist_ok=False);events=[]
    groups={}
    for row in lock['conda']:
        filename=row.get('filename') or Path(urllib.parse.urlsplit(row['url']).path).name
        destination=cache/row['sha256']/filename
        state=acquire(row['url'],row['sha256'],destination)
        target=context/'conda'/filename;target.parent.mkdir(exist_ok=True)
        if target.exists() and digest(target)!=row['sha256']:raise ValueError('Conflicting package filenames')
        if not target.exists():shutil.copyfile(destination,target)
        groups.setdefault(row['group'],[]).append('file:///build/conda/'+filename+'#'+row['md5'])
        events.append({'name':filename,'sha256':row['sha256'],'state':state})
    (context/'locks').mkdir()
    for name,urls in groups.items():(context/'locks'/(name+'.txt')).write_text('@EXPLICIT\n'+'\n'.join(urls)+'\n')
    for row in lock['python']:
        filename=row.get('filename') or Path(urllib.parse.urlsplit(row['url']).path).name;destination=cache/row['sha256']/filename
        state=acquire(row['url'],row['sha256'],destination)
        target=context/'python'/filename;target.parent.mkdir(exist_ok=True);shutil.copyfile(destination,target)
        events.append({'name':filename,'sha256':row['sha256'],'state':state})
    resources=json.loads((ROOT/'resources.lock.json').read_text())
    for row in resources['assets']:
        destination=cache/row['sha256']/row['filename']
        state=acquire(row['url'],row['sha256'],destination,max_bytes=row['bytes'])
        if destination.stat().st_size != row['bytes']:raise ValueError('Resource size differs from lock')
        target=context/'resources'/row['filename'];target.parent.mkdir(exist_ok=True);shutil.copyfile(destination,target)
        events.append({'name':row['filename'],'sha256':row['sha256'],'state':state})
    row=lock['micromamba'];archive=cache/row['sha256']/'micromamba.tar.bz2';state=acquire(row['url'],row['sha256'],archive)
    with tarfile.open(archive) as t:
        member=t.getmember('bin/micromamba')
        if not member.isfile():raise ValueError('Invalid micromamba member')
        (context/'micromamba').write_bytes(t.extractfile(member).read());(context/'micromamba').chmod(0o755)
    for name in ['install.py','sources.lock.json','modifications.json','scientific-files.json','hmm-index-layout.json','resources.lock.json','install_resources.py']:
        shutil.copyfile(ROOT/name,context/name)
    shutil.copyfile(ROOT/'plantismash-profile.json' if (ROOT/'plantismash-profile.json').is_file() else ROOT.parents[1]/'config/plantismash-profile.json',context/'plantismash-profile.json')
    shutil.copyfile(ROOT/'plantismash_prereqs.py' if (ROOT/'plantismash_prereqs.py').is_file() else ROOT.parents[1]/'bin/plantismash_prereqs.py',context/'plantismash_prereqs.py')
    shutil.copytree(ROOT/'modifications',context/'modifications')
    (context/'Dockerfile').write_text((ROOT/'Dockerfile').read_text().replace('@BASE_IMAGE@',lock['base_image']))
    (context/'acquisition.json').write_text(json.dumps({'source_lock_sha256':digest(ROOT/'sources.lock.json'),'assets':events},indent=2)+'\n')
    return events

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--context',type=Path,required=True);args=parser.parse_args()
    events=prepare(args.cache,args.context);print(f'Prepared {len(events)} verified source inputs in {args.context}')
if __name__=='__main__':main()
