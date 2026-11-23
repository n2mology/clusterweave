"""Read the accepted plantiSMASH producer without changing native identities."""
from pathlib import Path
from Bio import SeqIO
import json, hashlib, collections, warnings, copy, zipfile, re

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
from plant_identity import LEGACY_PRODUCER, PUBLIC_PRODUCER, SUPPORTED_PRODUCERS
# The pinned SIF emits this immutable receipt identity. Public records use the
# stable supported-build identity; native receipts are never rewritten.
PRODUCER = LEGACY_PRODUCER
LEGACY_PROFILE = "annotated-plants-2.0.4-repeatstable-v2"
LEGACY_PROFILE_SHA256 = "1d83d1685003784f99b924b220b9d30c0903d2abc6ed6e2c6ac057de303ffc2d"
PROFILE = "annotated-plants-2.0.4-extras-v3"
PROFILE_SHA256 = "f8bce449f75d78eddb5d9a15faf95de73625c9936af41d3e7faa52f7949dd0d3"
SIF_SHA256 = "91b31f064585370abd1eff3f845c8cecf84537ad57b07bb2fd611137d6825679"
REDUCED_PROFILE_SIF_SHA256 = "288660c80d58743b6415931d3a891b2213d9f1aff90dafb4def3e805bb991a46"
LEGACY_SIF_SHA256 = "6c057b048752333a1860a1dcbcd9a44b285b7f4717c8e705f0b10215a5522406"
# Historical SIF identities remain metadata; the extras profile executes only its accepted SIF.
ACCEPTED_SIF_SHA256 = frozenset((SIF_SHA256,))
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
def loc(f):
 parts=getattr(f.location,'parts',[f.location]);return {'text':str(f.location),'operator':getattr(f.location,'operator',None),'parts':[{'start':int(x.start),'end':int(x.end),'strand':x.strand,'start_type':type(x.start).__name__,'end_type':type(x.end).__name__,'ref':x.ref,'ref_db':x.ref_db} for x in parts]}
illegal='!"#$%&()*+,:; \r\n\t=>?@[]^`\'{|}/ '
def normalized_id(s):return ''.join('_' if c in illegal else c for c in s)
def feature_tuple(f):return json.dumps([loc(f),sha(f.qualifiers.get('translation',[''])[0])],sort_keys=True)

def smcog_note_additions(original, native, profile):
 """Allow only recognized appended extras; every original note stays intact."""
 if profile != PROFILE or not isinstance(native,list) or native[:len(original)] != original:return False
 added=native[len(original):]
 number=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
 if not 1 <= len(added) <= 2 or not re.fullmatch(r'smCOG: SMCOG\d+:[^\r\n]+ \(Score: '+number+r'; E-value: '+number+r'\);',added[0]):return False
 return len(added)==1 or bool(re.fullmatch(r'smCOG tree PNG image: smcogs/[A-Za-z0-9_.-]+\.png',added[1]))

def crosswalk(original,native_records,record_correspondence=None,profile=LEGACY_PROFILE):
 reasons=[];mapping=[];used_records=set();not_evaluated=[]
 for old in original['records']:
  if not old['CDS']:
   not_evaluated.append({'original_record_ordinal':old['original_record_ordinal'],'original_id':old['original_id'],'sequence_sha256':old['sequence_sha256'],'length':old['length'],'state':'NOT_EVALUATED_NO_CDS','calls':None,'reason':'Native supplied-CDS profile skips records without CDS; full original sequence retained.'})
   continue
  candidates=[(i,r) for i,r in enumerate(native_records) if i not in used_records and sha(str(r.seq))==old['sequence_sha256']]
  if record_correspondence is not None:
   links=[x for x in record_correspondence if x['original_id']==old['original_id'] and x['sequence_sha256']==old['sequence_sha256']]
   if len(links)!=1:reasons.append('missing_or_ambiguous_native_identity_receipt:'+old['original_id']);continue
   candidates=[x for x in candidates if x[1].id==links[0]['native_id']]
  exact=[x for x in candidates if x[1].id==old['original_id']]
  if len(exact)==1:candidates=exact
  if len(candidates)!=1:reasons.append('ambiguous_or_missing_native_record:'+old['original_id']);continue
  ni,nr=candidates[0];used_records.add(ni);native=[(i,f) for i,f in enumerate(nr.features) if f.type=='CDS'];used=set();rows=[]
  tuple_index=collections.defaultdict(list)
  for fi,feature in native:tuple_index[feature_tuple(feature)].append((fi,feature))
  for cds in old['CDS']:
   hits=[(i,f) for i,f in tuple_index.get(cds['tuple'],[]) if i not in used]
   protein=[normalized_id(s) for s in cds['qualifiers'].get('protein_id',[])]
   if protein:
    specific=[(i,f) for i,f in hits if f.qualifiers.get('protein_id')==protein]
    if len(specific)==1:hits=specific
   if len(hits)!=1:reasons.append('ambiguous_or_missing_native_CDS:'+cds['feature_key']);continue
   fi,f=hits[0];used.add(fi);changes={k:{'original':v,'native':f.qualifiers.get(k)} for k,v in cds['qualifiers'].items() if f.qualifiers.get(k)!=v}
   allowed=['locus_tag','product','gene','protein_id']
   if 'note' in changes and smcog_note_additions(changes['note']['original'],changes['note']['native'],profile):allowed.append('note')
   if any(k not in allowed for k in changes):reasons.append('unexplained_original_qualifier_change:'+cds['feature_key'])
   rows.append({'original_feature_key':cds['feature_key'],'original_feature_ordinal':cds['feature_ordinal'],'native_feature_ordinal':fi,'original_qualifiers':cds['qualifiers'],'native_qualifiers':f.qualifiers,'location':cds['location'],'translation_sha256':cds['translation_sha256'],'qualifier_changes':changes})
  if len(used)!=len(native):reasons.append('gained_or_unmapped_native_CDS:'+old['original_id'])
  mapping.append({'original_record_ordinal':old['original_record_ordinal'],'original_id':old['original_id'],'native_id':nr.id,'native_record_index':ni,'sequence_sha256':old['sequence_sha256'],'length':old['length'],'CDS':rows})
 if len(used_records)!=len(native_records):reasons.append('gained_or_unmapped_native_record')
 return {'bijective':not reasons,'bijection_scope':'all_supplied_CDS_and_their_parent_records','reasons':reasons,'records':mapping,'not_evaluated_records':not_evaluated}



def extracted_feature_parity(parent, extracted, start, end):
    """Compare complete contained features in native relative coordinates.

    SeqRecord slicing preserves compound-part order, fuzzy ends and strand and
    excludes boundary-spanning features, as the native extractor does. Compare
    multisets to retain duplicate multiplicity without requiring feature order.
    Qualifiers are compared intact, including declared partials and exceptions;
    this check does not reinterpret or repair the supplied translation.
    """
    def inventory(record):
        return collections.Counter(
            json.dumps({'type': feature.type, 'location': loc(feature),
                        'qualifiers': feature.qualifiers}, sort_keys=True)
            for feature in record.features
        )
    expected = inventory(parent[start:end])
    actual = inventory(extracted)
    return {'valid': expected == actual,
            'expected_features': sum(expected.values()),
            'actual_features': sum(actual.values()),
            'missing_features': sum((expected - actual).values()),
            'unexpected_features': sum((actual - expected).values())}


def recorded_profile(folder):
    """Read execution identity, never relabel historical output as today's defaults."""
    path = Path(folder).parent / 'execution.json'
    if not path.is_file():
        path = Path(folder).parent / 'run-profile.json'
    if not path.is_file():
        return LEGACY_PROFILE  # Historical native fixtures predate execution receipts.
    execution = json.loads(path.read_text())
    profile = execution.get('profile_id')
    if execution.get('producer') not in SUPPORTED_PRODUCERS or profile not in {LEGACY_PROFILE, PROFILE}:
        raise ValueError('Unknown plant execution profile')
    expected = {LEGACY_PROFILE: LEGACY_PROFILE_SHA256, PROFILE: PROFILE_SHA256}[profile]
    if (profile == PROFILE or 'profile_sha256' in execution) and execution.get('profile_sha256') != expected:
        raise ValueError('Plant execution profile digest differs')
    return profile


def read_native(original,folder,case=None):
 folder=Path(folder)
 try:
  profile_id=recorded_profile(folder)
  completion=json.loads((folder/'native-completion.json').read_text())
  execution=json.loads((folder.parent/'native-exit.json').read_text())
  assembled = completion.get('schema') == 'clusterweave-plant-record-merge-v1'
  if assembled:
   from plantismash_shards import validate_join
   expected_searches=validate_join(original,folder,completion)
  else:
   expected_searches=93*((sum(len(r['CDS']) for r in original['records'])+9999)//10000)
  if not (execution['exit_code']==0 and execution['producer'] in SUPPORTED_PRODUCERS):raise ValueError("Invalid native completion")
  if not (completion['schema'] in {'plantismash-private-completion-v1','clusterweave-plant-record-merge-v1'} and completion['completed'] is True):raise ValueError("Invalid native completion")
  if not (completion['producer']==execution['producer']):raise ValueError("Invalid native completion")
  if not (completion['successful_hmm_searches']==expected_searches and expected_searches>0):raise ValueError("Invalid native completion")
  links=completion['records']
  evaluated_original=[r for r in original['records'] if r['CDS']]
  if len(links)!=len(evaluated_original):raise ValueError('Native record count differs')
  if not (len({x['original_id'] for x in links})==len(links)==len({x['native_id'] for x in links})):raise ValueError("Invalid native completion")
  if not (completion['evaluated_records']==[x['native_id'] for x in links]):raise ValueError("Invalid native completion")
  for old in evaluated_original:
   match=[x for x in links if x['original_id']==old['original_id'] and x['sequence_sha256']==old['sequence_sha256'] and x['CDS_count']==len(old['CDS'])]
   if not (len(match)==1):raise ValueError("Invalid native completion")
 except (OSError,ValueError,KeyError,AssertionError,TypeError):
  return {'valid':False,'reasons':['missing_or_invalid_successful_native_completion'],'outcome':'FAILED_OUTPUT_CONTRACT'}
 full=list(folder.glob('*.final.gbk'))
 if len(full)!=1:return {'valid':False,'reasons':['missing_or_multiple_full_native_GBK'],'outcome':'FAILED_OUTPUT_CONTRACT'}
 raw=full[0].read_text()
 if not raw.rstrip().endswith('//'):return {'valid':False,'reasons':['truncated_full_native_GBK'],'outcome':'FAILED_OUTPUT_CONTRACT'}
 try:native=list(SeqIO.parse(str(full[0]),'genbank'))
 except Exception as ex:return {'valid':False,'reasons':['native_parse_error:'+type(ex).__name__],'outcome':'FAILED_OUTPUT_CONTRACT'}
 cw=crosswalk(original,native,completion['records'],profile=profile_id);reasons=list(cw['reasons']);calls=[];expected=[]
 byrecord={r['native_record_index']:r for r in cw['records']}
 for ni,r in enumerate(native):
  if ni not in byrecord:continue
  owner=byrecord[ni]
  for f in r.features:
   if f.type!='cluster':continue
   a,b=int(f.location.start),int(f.location.end)
   if not 0<=a<b<=len(r):reasons.append('cluster_outside_native_parent')
   members=[x['original_feature_key'] for x in owner['CDS'] if min(y['start'] for y in x['location']['parts'])>=a and max(y['end'] for y in x['location']['parts'])<=b]
   calls.append({'original_record_ordinal':owner['original_record_ordinal'],'original_record_id':owner['original_id'],'native_record_id':r.id,'start_0':a,'end_0':b,'start_1':a+1,'end_1':b,'types':f.qualifiers.get('product',[]),'members':sorted(members),'qualifiers':f.qualifiers,'sequence_sha256':sha(str(r.seq[a:b]))})
   expected.append((r,a,b))
 clusterfiles=sorted(folder.glob('*.cluster*.gbk'))
 if len(clusterfiles)!=len(calls):reasons.append('extracted_cluster_file_count_mismatch')
 clusterchecks=[];used=set()
 for file in clusterfiles:
  try:rr=list(SeqIO.parse(str(file),'genbank'))
  except Exception:reasons.append('malformed_extracted_cluster');continue
  if len(rr)!=1:reasons.append('invalid_cluster_record_count');continue
  cr=rr[0];hits=[(i,r,a,b) for i,(r,a,b) in enumerate(expected) if i not in used and cr.id==r.id and str(cr.seq)==str(r.seq[a:b])]
  if len(hits)!=1:reasons.append('ambiguous_extracted_cluster_owner');continue
  i,r,a,b=hits[0];used.add(i)
  try:parity=extracted_feature_parity(r,cr,a,b)
  except (ValueError,TypeError,AttributeError):
   reasons.append('malformed_extracted_cluster_feature');continue
  if not parity['valid']:reasons.append('extracted_cluster_feature_mismatch:'+file.name)
  clusterchecks.append({'file':file.name,'internal_record_id':cr.id,'parent_start_0':a,'parent_end_0':b,'verified_from_sequence':True,'feature_parity':parity})
 calls.sort(key=lambda x:(x['original_record_ordinal'],x['start_0'],x['end_0'],x['types']))
 if reasons:return {'valid':False,'reasons':sorted(set(reasons)),'outcome':'FAILED_OUTPUT_CONTRACT'}
 for call in calls:
  matches=[x for x in clusterchecks if x['internal_record_id']==call['native_record_id'] and x['parent_start_0']==call['start_0'] and x['parent_end_0']==call['end_0']]
  if len(matches)!=1:return {'valid':False,'reasons':['ambiguous_cluster_file_join'],'outcome':'FAILED_OUTPUT_CONTRACT'}
  call['native_cluster_gbk']=matches[0]['file']
  call['cluster_key']=sha(json.dumps({k:call[k] for k in ('original_record_id','start_0','end_0','types','members')},sort_keys=True))
 try:payloads=validate_archive(folder, nested_archives=assembled)
 except (OSError,ValueError,zipfile.BadZipFile) as exc:return {'valid':False,'reasons':['archive_validation:'+str(exc)],'outcome':'FAILED_OUTPUT_CONTRACT'}
 return {'valid':True,'reasons':[],'producer':PRODUCER,'profile_id':profile_id,'identity':cw,'calls':calls,'extracted_clusters':clusterchecks,'payloads':payloads,'outcome':'SUCCESS_WITH_CALLS' if calls else 'SUCCESSFUL_EMPTY'}


def validate_archive(folder, nested_archives=False):
    folder = Path(folder)
    files = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('Native payload contains a symbolic link')
        if path.is_file():
            files[path.relative_to(folder).as_posix()] = path
    archives = [name for name in files if name.endswith('.zip') and (not nested_archives or '/' not in name)]
    if len(archives) != 1 or 'index.html' not in files or 'native-completion.json' not in files:
        raise ValueError('Incomplete native folder, archive or completion receipt')
    payloads = {name: path for name, path in files.items() if name not in (archives[0], 'native-completion.json')}
    with zipfile.ZipFile(files[archives[0]]) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or names != sorted(names) or set(names) != set(payloads):
            raise ValueError('Native archive does not cover the complete folder')
        for entry in archive.infolist():
            if entry.date_time != (1980,1,1,0,0,0) or entry.create_system != 3 or entry.external_attr != 0o100644 << 16 or entry.compress_type != zipfile.ZIP_DEFLATED or entry.extra or entry.comment:
                raise ValueError('Native archive metadata differs from accepted producer')
            with archive.open(entry) as packed, payloads[entry.filename].open('rb') as actual:
                while True:
                    block = packed.read(1024 * 1024)
                    if block != actual.read(1024 * 1024):
                        raise ValueError('Native archive payload mismatch')
                    if not block:
                        break
    result = {}
    for name, path in files.items():
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(block)
        result[name] = {'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}
    return result


def original_inventory(path, genome_id, fasta=None):
    import sys
    web = str(Path(__file__).resolve().parents[1] / 'web')
    if web not in sys.path:
        sys.path.insert(0, web)
    from plant_annotation import inspect_plant_annotation_path
    admission = inspect_plant_annotation_path(path, fasta)
    records = []
    for ri, record in enumerate(SeqIO.parse(str(path), 'genbank'), 1):
        features = []
        for fi, feature in enumerate(record.features):
            if feature.type != 'CDS':
                continue
            peptide = feature.qualifiers['translation'][0]
            features.append({'feature_key': f'{genome_id}:R{ri:06d}:F{fi:06d}', 'feature_ordinal': fi, 'location': loc(feature), 'tuple': feature_tuple(feature), 'translation_sha256': sha(peptide), 'qualifiers': copy.deepcopy(feature.qualifiers)})
        records.append({'original_record_ordinal': ri, 'original_id': record.id, 'original_name': record.name, 'sequence_sha256': sha(str(record.seq)), 'length': len(record), 'CDS': features})
    return {'admitted': True, 'records': records, 'source_file_sha256': admission['source_sha256'], 'admission': admission}


def complete_native_archive(root):
    """Package the complete native folder, original annotation and identity maps."""
    root = Path(root)
    inventory = json.loads((root / 'original-identity.json').read_text())
    result = read_native(inventory, root / 'native')
    if not result['valid']:
        raise ValueError('Cannot export incomplete native plant evidence')
    if hashlib.sha256((root / 'original.gbk').read_bytes()).hexdigest() != inventory['source_file_sha256']:
        raise ValueError('Original annotation identity differs')
    paths = {f'native/{name}': root / 'native' / name for name in result['payloads']}
    for name in ('original.gbk', 'original-identity.json', 'native-exit.json', 'validation.json', 'outcome.json'):
        paths[name] = root / name
    for name in ('plantismash_native.py', 'plantismash_shards.py', 'verify_native_download.py'):
        paths[name] = Path(__file__).with_name(name)
    for name in ('LICENSE', 'THIRD_PARTY.md'):
        paths[name] = Path(__file__).resolve().parents[1] / name
    contents = {}
    for name, path in paths.items():
        if path.is_symlink():
            raise ValueError('Unsafe complete native payload')
        h = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                h.update(block)
        contents[name] = {'sha256': h.hexdigest(), 'bytes': path.stat().st_size}
    profile_id = result['profile_id']
    profile_hash = {LEGACY_PROFILE: LEGACY_PROFILE_SHA256, PROFILE: PROFILE_SHA256}[profile_id]
    profile_bytes = (json.dumps({'producer': PRODUCER, 'profile_id': profile_id, 'profile_sha256': profile_hash}, sort_keys=True) + '\n').encode()
    contents['run-profile.json'] = {'sha256': hashlib.sha256(profile_bytes).hexdigest(), 'bytes': len(profile_bytes)}
    receipt = {'schema':'complete-native-plant-v1','producer':PRODUCER,'profile_id':recorded_profile(root / 'native'),'payloads':contents,'scope':'Full original/native annotation and identity maps; comparison selection is separate. Source assertions are not independent biological truth.'}
    target = root / 'complete-native.zip'
    temporary = root / '.complete-native.zip.tmp'
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for name, path in sorted(paths.items()):
            info = zipfile.ZipInfo(name, (1980,1,1,0,0,0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open('rb') as source, archive.open(info,'w',force_zip64=True) as destination:
                import shutil
                shutil.copyfileobj(source,destination,1024*1024)
        info = zipfile.ZipInfo('run-profile.json', (1980,1,1,0,0,0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, profile_bytes)
        archive.writestr('manifest.json',json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    temporary.replace(target)
    return target
