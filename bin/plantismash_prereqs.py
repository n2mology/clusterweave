"""Read-only prerequisite audit before native checks can download or build indexes.

Executed inside the checksum-verified SIF. This script never installs, downloads,
indexes, deletes or repairs anything. Runtime files are bound by the SIF identity.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

PREFIX = Path('/opt/plantismash')
MODULES = PREFIX / 'repeat2/lib/python3.8/site-packages/antismash/generic_modules'
TOOLS = [PREFIX / 'repeat2/bin', PREFIX / 'native-tools/bin', PREFIX / 'hmmer2/bin', Path('/usr/bin'), Path('/bin')]
INDEXES = ('.h3f', '.h3i', '.h3m', '.h3p')
CONNECT_TF_MD5 = '08fc6daa1b4088a6ca341e3b47dca893'


def required_resources(arguments):
    flags = set(arguments)
    files, binaries = [], set()
    if '--cdhit' in flags:
        binaries.add('cd-hit')
    if '--clusterblast' in flags:
        files += ['clusterblast/plantgeneclusterprots.fasta', 'clusterblast/plantgeneclusterprots.dmnd', 'clusterblast/plantgeneclusters.txt']
        binaries.update(['blastp', 'makeblastdb', 'diamond'])
    if '--knownclusterblast' in flags:
        files += ['knownclusterblast/knownclusterprots.fasta', 'knownclusterblast/knownclusterprots.dmnd', 'knownclusterblast/knownclusters.txt']
        binaries.update(['blastp', 'makeblastdb', 'diamond'])
    if '--subclusterblast' in flags:
        files += ['subclusterblast/subclusterprots.fasta'+ext for ext in ('', '.phr', '.pin', '.psq')]
        files += ['subclusterblast/subclusters.txt']
        binaries.update(['blastp', 'makeblastdb'])
    for flag, model in [('--full-hmmer', 'fullhmmer/Pfam-A.hmm'), ('--smcogs', 'smcogs/smcogs.hmm')]:
        if flag in flags:
            files += [model+ext for ext in ('', *INDEXES)]
            binaries.update(['hmmscan', 'hmmpress'])
    if '--smcogs' in flags:
        binaries.update(['muscle', 'fasttree', 'java'])
        files.append('smcogs/TreeGraph.jar')
    if '--asf' in flags:
        binaries.update(['hmmsearch', 'hmmpfam2'])
        files.append('active_site_finder/config/SignatureResources.xml')
        files += ['active_site_finder/hmm/'+model+ext for model in ['p450.hmm3','KStypes.hmm3'] for ext in ('',*INDEXES)]
        binaries.add('hmmscan')
    if '--disable_subgroup' not in flags:
        files.append('subgroup/Subgroup_Model.txt')
        binaries.update(['hmmsearch', 'hmmbuild', 'hmmalign', 'pplacer', 'guppy'])
        if '--disable_treesvg' not in flags:
            binaries.update(['graphlan.py', 'graphlan_annotate.py'])
    if '--tfbs' in flags:
        files += ['tfbs_finder/data/connectTF_validated.csv', 'tfbs_finder/data/TAIR_GeneDescriptions_2025-08-19.tsv']
    return files, sorted(binaries)


def audit(arguments, root=Path('/'), which=shutil.which):
    root = Path(root)
    files, binaries = required_resources(arguments)
    missing = []
    for name in files:
        p = root / str(MODULES / name).lstrip('/')
        if not p.is_file() or not p.stat().st_size:
            missing.append('resource:' + name)
    search_path = os.pathsep.join(str(root / str(p).lstrip('/')) for p in TOOLS)
    for name in binaries:
        if which(name, path=search_path) is None:
            missing.append('executable:' + name)
    if '--tfbs' in arguments and 'resource:tfbs_finder/data/connectTF_validated.csv' not in missing:
        p = root / str(MODULES / 'tfbs_finder/data/connectTF_validated.csv').lstrip('/')
        digest = hashlib.md5()
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != CONNECT_TF_MD5:
            missing.append('checksum:tfbs_finder/data/connectTF_validated.csv')
    return {'ready_for_native_check': not missing, 'missing': missing,
            'requested_arguments': arguments, 'acquisition': 'disabled'}


def main():
    arguments = json.loads(sys.argv[1])
    result = audit(arguments)
    print(json.dumps(result), flush=True)
    if result['missing']:
        print('plantiSMASH extras need operator-prepared immutable resources: ' + '; '.join(result['missing']), file=sys.stderr)
        return 2
    # Only after our audit, let the pinned tool check its remaining prerequisites.
    # The enclosing SIF remains read-only with network isolation throughout.
    env = dict(os.environ, PATH=os.pathsep.join(map(str, TOOLS)), PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    return subprocess.run(['/usr/local/bin/plantismash', *arguments, '--check-prereqs'], env=env, timeout=20).returncode


if __name__ == '__main__':
    raise SystemExit(main())
