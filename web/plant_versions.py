"""Helper versions from exact producer locks and native execution products."""
import hashlib
import json
from pathlib import Path
import re


def native_helper_versions(native_root, runtime_sha256, source_root):
    source_root = Path(source_root)
    directory = source_root / 'software/plantismash'
    lock_path = directory / 'sources.lock.json'
    runtime_path = directory / 'runtime.lock.json'
    if not lock_path.is_file() or not runtime_path.is_file():
        return []
    runtime = json.loads(runtime_path.read_text())
    raw = lock_path.read_bytes()
    source_digest = hashlib.sha256(raw).hexdigest()
    if runtime_sha256 != runtime['preferred_sif_sha256'] or source_digest != runtime['recipe_source_lock_sha256']:
        return []
    lock = json.loads(raw)
    reports = sorted(native_root.glob('shards/*/native')) if (native_root / 'shards').is_dir() else [native_root]
    used = {'Python': ('repeat2', 'python')}
    for report in reports:
        receipt = json.loads((report / 'native-completion.json').read_text())
        if receipt.get('successful_hmm_searches', 0) > 0:
            used['HMMER'] = ('native-tools', 'hmmer')
        match = re.fullmatch(r'\s*var geneclusters = ([\s\S]*);\s*var details_data = ([\s\S]*);\s*', (report / 'geneclusters.js').read_text())
        if not match:
            raise ValueError('Invalid native data for dependency attribution')
        clusters = json.loads(match[1])
        if any('Active Site Finder results:' in orf.get('description', '') for c in clusters.values() for orf in c.get('orfs', [])):
            used['HMMER2'] = ('hmmer2', 'hmmer2')
        groups = [g for c in clusters.values() for g in c.get('cdhitclusters', [])]
        if groups:
            used['CD-HIT'] = ('native-tools', 'cd-hit')
        if any(len(g.get('genes', {})) > 1 for g in groups):
            used['BLAST+'] = ('native-tools', 'blast')
        if any(p.stat().st_size for p in report.glob('*clusterblastoutput.txt')):
            used['DIAMOND'] = ('native-tools', 'diamond')
        if any(p.stat().st_size for p in report.glob('smcogs/*.nwk')):
            used.update({'MUSCLE': ('native-tools', 'muscle'), 'FastTree': ('native-tools', 'fasttree')})
        if any(p.stat().st_size for p in report.glob('subgroup/**/*.jplace')):
            used['pplacer'] = ('native-tools', 'pplacer')
    output = []
    for tool, (group, package) in sorted(used.items()):
        entries = [p for p in lock['conda'] if p['group'] == group and p['name'] == package]
        if len(entries) != 1:
            raise ValueError('Executed plant helper omitted from producer lock: ' + tool)
        entry = entries[0]
        output.append({'tool': 'HMMER' if tool == 'HMMER2' else tool, 'backend': 'apptainer', 'version': entry['version'],
                       'runtime_sha256': runtime_sha256, 'source_sha256': entry['sha256'],
                       'version_observation': 'native execution product and exact producer ' + package + ' package lock',
                       'source_lock_sha256': source_digest})
    return output
