"""Offline build step: install pinned inputs and verify unchanged scientific files."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import urllib.parse
import zipfile

root=Path('/build');prefix=Path('/opt/plantismash/repeat2');python=str(prefix/'bin/python');site=prefix/'lib/python3.8/site-packages'
lock=json.loads((root/'sources.lock.json').read_text())
env=dict(os.environ,CC='/opt/plantismash/build-tools/bin/x86_64-conda-linux-gnu-cc',CXX='/opt/plantismash/build-tools/bin/x86_64-conda-linux-gnu-c++',PATH='/opt/plantismash/build-tools/bin:'+str(prefix/'bin')+':/usr/bin:/bin',PYTHONDONTWRITEBYTECODE='1',SOURCE_DATE_EPOCH='315532800',CFLAGS='-O2 -g0',CXXFLAGS='-O2 -g0')
paths=[]
for row in lock['python']:
    path=root/'python'/(row.get('filename') or Path(urllib.parse.urlsplit(row['url']).path).name)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256'],path.name
    paths.append(str(path))
subprocess.run([python,'-m','pip','install','--no-index','--no-deps','--no-build-isolation','--no-compile',*paths],env=env,check=True)
for row in json.loads((root/'modifications.json').read_text()):
    path=site/row['path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==row['upstream_sha256'],str(path)
    source=root/'modifications'/row['path'];assert hashlib.sha256(source.read_bytes()).hexdigest()==row['modified_sha256']
    shutil.copyfile(source,path)
plants=site/'antismash/generic_modules/hmm_detection/plants'
# SSI reserves a filename field using the input path length but stores only
# its basename. A neutral padded alias reproduces the accepted index layout.
widths=json.loads((root/'hmm-index-layout.json').read_text())
for path in sorted(plants.glob('*.hmm')):
    alias_parent_length=widths[path.name]-len(path.name)-2
    alias=Path('/build')/('i'*(alias_parent_length-len('/build/')))
    if not alias.exists():alias.symlink_to(plants,target_is_directory=True)
    subprocess.run(['/opt/plantismash/native-tools/bin/hmmpress','-f',str(alias/path.name)],check=True,stdout=subprocess.DEVNULL)
manifest=json.loads((root/'scientific-files.json').read_text())
for name,want in manifest.items():
    path=site/name
    assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==want,'Scientific content differs: '+name
provenance=Path('/opt/plantismash/provenance');provenance.mkdir()
for name in ['sources.lock.json','modifications.json','scientific-files.json']:shutil.copyfile(root/name,provenance/name)
with zipfile.ZipFile(provenance/'plantismash-corresponding-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((site/'antismash').rglob('*')):
        if path.is_file() and path.suffix!='.pyc':
            info=zipfile.ZipInfo(str(path.relative_to(site)),(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,path.read_bytes())
    info=zipfile.ZipInfo('run_antismash.py',(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,(site/'run_antismash.py').read_bytes())
    for path in sorted(site.glob('plantismash-*.dist-info/*')):
        if path.is_file():
            info=zipfile.ZipInfo('package-notices/'+path.name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,path.read_bytes())
    for name in ['install.py','sources.lock.json','modifications.json','scientific-files.json','hmm-index-layout.json','resources.lock.json','install_resources.py','plantismash_prereqs.py','plantismash-profile.json']:
        info=zipfile.ZipInfo('build/'+name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,(root/name).read_bytes())
launcher=Path('/usr/local/bin/plantismash');launcher.write_text('#!/bin/sh\nexport PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1\nunset PYTHONPATH PYTHONHOME LD_PRELOAD\nexport PATH=/opt/plantismash/repeat2/bin:/opt/plantismash/native-tools/bin:/opt/plantismash/hmmer2/bin:/usr/bin:/bin\nexport OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1\nexec /opt/plantismash/repeat2/bin/plantismash "$@"\n');launcher.chmod(0o755)
(provenance/'scientific-verification.json').write_text(json.dumps({'verified_files':len(manifest),'producer':lock['scientific_producer'],'profile_sha256':lock['profile_sha256']},indent=2)+'\n')

# Installed Conda history is build metadata; actual acquisition/build times are
# retained by the preparation collector outside the reproducible runtime.
import re
for history in Path('/opt/plantismash').glob('*/conda-meta/history'):
    history.write_text(re.sub(r'==> [^\n]+ <==','==> 1980-01-01 00:00:00 <==',history.read_text()))
for path in Path('/opt/plantismash').rglob('*.pyc'):
    path.unlink()
