#!/usr/bin/env python3
"""Verify an extracted complete plantiSMASH download using Biopython 1.81."""
import hashlib
import json
from pathlib import Path
from plantismash_native import read_native

def verify(root):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest['schema'] != 'complete-native-plant-v1':
        raise ValueError('Unsupported native download manifest')
    for name, expected in manifest['payloads'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe download member')
        path = root / relative
        if any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('Linked native payload')
        h = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda:handle.read(1048576),b''):h.update(block)
        if h.hexdigest()!=expected['sha256'] or path.stat().st_size!=expected['bytes']:
            raise ValueError('Native download identity differs: '+name)
    value=read_native(json.loads((root/'original-identity.json').read_text()),root/'native')
    if not value['valid']:raise ValueError('Native output contract failed: '+str(value['reasons']))
    if manifest.get('profile_id') != value['profile_id']:
        raise ValueError('Native download profile differs from its execution')
    return {'outcome':value['outcome'],'calls':len(value['calls']),'producer':value['producer']}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path,nargs='?',default=Path(__file__).resolve().parent)
    print(json.dumps(verify(p.parse_args().directory),indent=2))
