#!/usr/bin/env python3
"""Build the hosted modified-plantiSMASH corresponding-source download."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.parse
import zipfile
from prepare import acquire, ROOT


def build(cache, output):
    lock=json.loads((ROOT/'sources.lock.json').read_text())
    row=next(x for x in lock['python'] if Path(urllib.parse.urlsplit(x['url']).path).name.startswith('plantismash-'))
    wheel=Path(cache)/Path(urllib.parse.urlsplit(row['url']).path).name
    acquire(row['url'],row['sha256'],wheel)
    files={}
    with zipfile.ZipFile(wheel) as upstream:
        for name in upstream.namelist():
            path=Path(name)
            if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe source member')
            if name.endswith('/') or name.endswith('.pyc'):continue
            files['plantismash/'+name]=upstream.read(name)
    for change in json.loads((ROOT/'modifications.json').read_text()):
        name='plantismash/'+change['path']
        if hashlib.sha256(files[name]).hexdigest()!=change['upstream_sha256']:raise ValueError('Unexpected upstream source')
        data=(ROOT/'modifications'/change['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=change['modified_sha256']:raise ValueError('Unexpected modification')
        files[name]=data
    for path in sorted(ROOT.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc','.sif'}:
            files['build/'+path.relative_to(ROOT).as_posix()]=path.read_bytes()
    for name,source in [('plantismash-profile.json',ROOT.parents[1]/'config/plantismash-profile.json'),('plantismash_prereqs.py',ROOT.parents[1]/'bin/plantismash_prereqs.py')]:
        if not source.is_file():source=ROOT/name
        files['build/'+name]=source.read_bytes()
    files['README.txt']=(
        'Modified plantiSMASH 2.0.4 corresponding source and pinned build recipe.\n'
        'AGPL-3.0-or-later: see build/LICENSE.txt and upstream package notices.\n'
        'Changes preserve supplied CDS and core detection rules and add strict\n'
        'completion/identity validation plus compatibility fixes; modifications.json\n'
        'binds original and modified bytes. The ClusterWeave repository documents use.\n'
        'sources.lock.json and resources.lock.json bind dependencies and analysis datasets.\n'
        'This is source code, not a prebuilt runtime or a grant of trademark rights.\n'
    ).encode()
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as stream,zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644<<16;archive.writestr(info,data)
    return hashlib.sha256(output.read_bytes()).hexdigest()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(build(args.cache,args.output))
