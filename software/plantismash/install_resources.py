"""Install checksum-bound analysis resources offline; never fetch data in a job."""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def destination(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Unsafe resource destination')
    path = root.joinpath(*relative.parts)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Linked resource destination')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_resource(source, target, expected, limit):
    if target.exists():
        if digest(target) != expected:
            raise ValueError('Resource would replace different scientific bytes: ' + str(target))
        return
    total = 0
    value = hashlib.sha256()
    with target.open('xb') as output:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            total += len(chunk)
            if total > limit:
                raise ValueError('Expanded resource exceeds its locked size')
            value.update(chunk)
            output.write(chunk)
    if total != limit or value.hexdigest() != expected:
        raise ValueError('Expanded resource identity differs: ' + str(target))


def install(build=Path('/build'), prefix=Path('/opt/plantismash/repeat2')):
    modules = prefix / 'lib/python3.8/site-packages/antismash/generic_modules'
    lock = json.loads((build / 'resources.lock.json').read_text())
    installed = []
    for row in lock['assets']:
        archive = build / 'resources' / row['filename']
        if archive.stat().st_size != row['bytes'] or digest(archive) != row['sha256']:
            raise ValueError('Acquired resource differs: ' + row['filename'])
        if row['kind'] == 'tar':
            with tarfile.open(archive, 'r:*') as source:
                for member in row['members']:
                    info = source.getmember(member['member'])
                    if not info.isfile() or info.size != member['bytes']:
                        raise ValueError('Invalid locked archive member')
                    with source.extractfile(info) as stream:
                        write_resource(stream, destination(modules, member['target']), member['sha256'], member['bytes'])
                    installed.append(member['target'])
        elif row['kind'] in {'file', 'gzip'}:
            opener = gzip.open if row['kind'] == 'gzip' else open
            with opener(archive, 'rb') as source:
                write_resource(source, destination(modules, row['target']), row['installed_sha256'], row['installed_bytes'])
            installed.append(row['target'])
        else:
            raise ValueError('Unknown resource packaging')
    env = dict(os.environ, PATH=str(prefix/'bin')+':/opt/plantismash/native-tools/bin:/opt/plantismash/hmmer2/bin:/usr/bin:/bin',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MPLCONFIGDIR='/tmp/plant-extras-mpl', PYTHONDONTWRITEBYTECODE='1')
    # Build with the pinned native tools, never at job runtime. These formats do
    # not depend on a newer upstream executable's database format.
    for name in ['clusterblast/plantgeneclusterprots', 'knownclusterblast/knownclusterprots']:
        path = modules / name
        subprocess.run(['diamond', 'makedb', '--threads', '2', '--in', str(path)+'.fasta', '-d', str(path)], env=env, check=True)
        installed.append(name+'.dmnd')
    regenerated_indexes = []
    for name in ['fullhmmer/Pfam-A.hmm', 'smcogs/smcogs.hmm', 'active_site_finder/hmm/p450.hmm3', 'active_site_finder/hmm/KStypes.hmm3']:
        before = {extension:digest(modules/(name+extension)) for extension in ['.h3f','.h3i','.h3m','.h3p'] if (modules/(name+extension)).is_file()}
        subprocess.run(['hmmpress', '-f', str(modules/name)], env=env, check=True)
        installed += [name+extension for extension in ['.h3f', '.h3i', '.h3m', '.h3p']]
        regenerated_indexes.append({'model':name,'model_sha256':digest(modules/name),'previous_indexes':before,
                                    'prepared_indexes':{extension:digest(modules/(name+extension)) for extension in ['.h3f','.h3i','.h3m','.h3p']}})
    profile = json.loads((build/'plantismash-profile.json').read_text())
    subprocess.run([str(prefix/'bin/python'), str(build/'plantismash_prereqs.py'), json.dumps(profile['arguments'])], env=env, check=True)
    versions = []
    for command in [['pplacer', '--version'], ['guppy', '--version'], ['graphlan.py', '--version'], ['graphlan_annotate.py', '--version'], ['java', '-version']]:
        result = subprocess.run(command, env=env, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        versions.append({'argv': command, 'output': result.stdout.strip()})
    # Exercise every configured ASF search/parser. File existence and --help
    # miss obsolete HMM3 indexes and serial HMMER2's unsupported --cpu flag.
    asf_probe = r"""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,xml.etree.ElementTree as ET
from Bio import SeqIO
from antismash.generic_modules.active_site_finder import active_site_finder
import antismash.generic_modules.active_site_finder as module
base=Path(module.__file__).parent
query=next(r for r in SeqIO.parse(base.parent/'knownclusterblast/knownclusterprots.fasta','fasta') if r.id.startswith('BGC0001315.3|c1|7758'))
obj=active_site_finder.__new__(active_site_finder)
obj.options=SimpleNamespace(activeSiteFinderHMMDir=str(base/'hmm'))
rows=[]
for resource in ET.parse(base/'config/SignatureResources.xml').getroot().findall('./analysis'):
    results=obj._execute_tool(resource,stdin_data='>prepared_model_probe\n'+str(query.seq)+'\n')
    rows.append({'analysis':resource.attrib['name'],'program':resource.find('./Execute').attrib['program'],
                 'model':resource.find('./Execute/database').text,'queries':len(results),'hits':sum(len(r.hsps) for r in results)})
assert rows and all(r['queries']==1 for r in rows)
assert any(r['model']=='p450.hmm3' and r['hits']>0 for r in rows)
print(json.dumps({'scope':'Runtime compatibility probe, not evidence for any analyzed genome',
                  'query_sha256':hashlib.sha256(str(query.seq).encode()).hexdigest(),'analyses':rows}))
"""
    asf_result=subprocess.run([str(prefix/'bin/python'),'-c',asf_probe],env=env,text=True,stdout=subprocess.PIPE,check=True,timeout=120)
    asf_receipt=json.loads(asf_result.stdout)
    fonts = prefix/'lib/python3.8/site-packages/matplotlib/mpl-data/fonts/ttf'
    if not (fonts/'DejaVuSans.ttf').is_file():
        raise ValueError('Headless smCOG rendering needs the pinned Matplotlib fonts')
    # Exercise rendering, not just `java -version`: the upstream GUI error
    # reporter otherwise loops when a headless JRE cannot discover any fonts.
    with tempfile.TemporaryDirectory(prefix='plant-treegraph-check-') as temporary:
        work=Path(temporary)
        (work/'tree.nwk').write_text('(A:0.1,B:0.2);\n')
        java=['java','-Djava.awt.headless=true','-Dsun.java2d.fontpath='+str(fonts),
              '-Duser.home='+str(work),'-jar',str(modules/'smcogs/TreeGraph.jar')]
        for arguments in [['-convert','tree.nwk','-xtg','tree.xtg'],['-image','tree.xtg','tree.png']]:
            result=subprocess.run(java+arguments,cwd=work,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True,timeout=30)
            if 'exception' in result.stdout.lower():
                raise RuntimeError('TreeGraph preparation rendering failed: '+result.stdout)
        if not (work/'tree.png').is_file() or (work/'tree.png').stat().st_size==0:
            raise RuntimeError('TreeGraph preparation did not render its PNG')
    provenance = Path('/opt/plantismash/provenance')
    for name in ['resources.lock.json', 'plantismash-profile.json', 'plantismash_prereqs.py', 'install_resources.py']:
        shutil.copyfile(build/name, provenance/name)
    receipt = {'schema':'plantismash-prepared-resources-v1', 'resources_lock_sha256':digest(build/'resources.lock.json'),
               'profile_sha256':digest(build/'plantismash-profile.json'), 'executable_versions':versions,
               'treegraph_render_check':'passed', 'asf_execution_check':asf_receipt, 'regenerated_indexes':regenerated_indexes, 'rendering_fonts':{
                   p.name:digest(p) for p in sorted(fonts.glob('*.ttf'))}, 'files':{
                   name:{'sha256':digest(modules/name), 'bytes':(modules/name).stat().st_size} for name in sorted(installed)}}
    # Base verification precedes resource preparation. Record the final installed
    # package separately because obsolete bundled ASF indexes are regenerated
    # with pinned HMMER from unchanged, checksum-verified model text.
    base_manifest=json.loads((build/'scientific-files.json').read_text())
    final_manifest={name:digest(prefix/'lib/python3.8/site-packages'/name) for name in sorted(base_manifest)}
    (provenance/'prepared-scientific-files.json').write_text(json.dumps(final_manifest,sort_keys=True,indent=2)+'\n')
    (provenance/'resources-installed.json').write_text(json.dumps(receipt, sort_keys=True, indent=2)+'\n')


if __name__ == '__main__':
    install()
