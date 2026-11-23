"""Assemble validated plantiSMASH native presentations without running science."""
from pathlib import Path, PurePosixPath
from html.parser import HTMLParser
import html, json, re, hashlib, shutil, csv, copy, posixpath
VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
class Element:
 def __init__(self,tag='',attrs=(),raw=''):self.tag=tag;self.attrs=dict(attrs);self.raw=raw;self.children=[];self.end='';self.changed=False
 def set(self,k,v):self.attrs[k]=v;self.changed=True
 def render(self):
  start=self.raw if not self.changed else '<'+self.tag+''.join(' '+k+('="'+html.escape(str(v),quote=True)+'"' if v is not None else '') for k,v in self.attrs.items())+'>'
  return start+''.join(x.render() if isinstance(x,Element) else x for x in self.children)+self.end
 def walk(self):
  yield self
  for c in self.children:
   if isinstance(c,Element):yield from c.walk()
 def byid(self,id):return next(n for n in self.walk() if n.attrs.get('id')==id)
class Document(HTMLParser):
 def __init__(self,text):
  super().__init__(convert_charrefs=False);self.root=Element();self.stack=[self.root];self.feed(text)
 def handle_starttag(self,t,a):
  n=Element(t,a,self.get_starttag_text());self.stack[-1].children.append(n)
  if t not in VOID:self.stack.append(n)
 def handle_startendtag(self,t,a):self.stack[-1].children.append(Element(t,a,self.get_starttag_text()))
 def handle_endtag(self,t):
  for i in range(len(self.stack)-1,0,-1):
   if self.stack[i].tag==t:self.stack[i].end='</'+t+'>';del self.stack[i:];return
  self.stack[-1].children.append('</'+t+'>')
 def handle_data(self,s):self.stack[-1].children.append(s)
 def handle_entityref(self,s):self.handle_data('&'+s+';')
 def handle_charref(self,s):self.handle_data('&#'+s+';')
 def handle_comment(self,s):self.handle_data('<!--'+s+'-->')
 def handle_decl(self,s):self.handle_data('<!'+s+'>')
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def payload(path):
 m=re.fullmatch(r'\s*var geneclusters = ([\s\S]*);\s*var details_data = ([\s\S]*);\s*',path.read_text())
 if not m:raise ValueError('Unsupported native JSON presentation')
 return json.loads(m[1]),json.loads(m[2])
def assemble(root,dest):
 root=Path(root);dest=Path(dest);dest.mkdir(parents=True,exist_ok=False)
 inv=json.loads((root/'original-identity.json').read_text()); completion=json.loads((root/'native/native-completion.json').read_text())
 records=inv['records']; analyzed=sum(bool(r['CDS']) for r in records); validation=json.loads((root/'validation.json').read_text()) if (root/'validation.json').is_file() else {}; rows=completion.get('shards') or [{'ordinal':records[0]['original_record_ordinal'],'root':'.'}]
 reports=[]; assets=[]; mapped=[]; clusters={};details={}; tables=[];buttons=[];sections=[]; svg_data={}; collisions=[]; content_paths={}; path_maps={}
 for row in rows:
  old=next(r for r in records if r['original_record_ordinal']==row['ordinal']);native=root/'native'/row['root']/'native' if row['root']!='.' else root/'native'
  rid=old['original_id'];namespace=re.sub('[^A-Za-z0-9_.-]','_',rid)
  if any(x['namespace']==namespace for x in reports):raise ValueError('Ambiguous record asset namespace')
  report=Document((native/'index.html').read_text()).root;data,detail=payload(native/'geneclusters.js'); ids={k:f'cluster-{len(clusters)+i+1}' for i,k in enumerate(sorted(data,key=lambda k:int(k.split('-')[1])))}
  paths={}
  for p in sorted(native.rglob('*')):
   if not p.is_file():continue
   rel=p.relative_to(native).as_posix()
   if p.is_symlink():raise ValueError('Symlink in native report')
   if rel in {'index.html','geneclusters.js','native-completion.json'} or p.suffix=='.zip' or rel.endswith('.final.gbk'):continue
   parts=PurePosixPath(rel).parts
   target=rel if parts[0] in {'css','js','images'} or (len(parts)==1 and '.cluster' in p.name and p.suffix=='.gbk') else (str(PurePosixPath(parts[0],namespace,*parts[1:])) if len(parts)>1 else str(PurePosixPath('data',namespace,rel)))
   h=sha(p)
   if parts[0] not in {'css','js','images'} and not ('.cluster' in p.name and p.suffix=='.gbk'):
    target=content_paths.setdefault(h,target)
   q=dest/target
   if q.exists():
    if sha(q)!=h:raise ValueError('Nonidentical shared asset collision: '+target)
    collisions.append({'path':target,'record':rid,'sha256':h})
   else:q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
   paths[rel]=target;assets.append({'record':rid,'source':rel,'target':target,'sha256':h,'bytes':p.stat().st_size})
   if p.suffix=='.svg':svg_data[target]=p.read_text()
  path_maps[namespace]=paths
  def present_id(value):
   return re.sub(r'(?<![A-Za-z0-9_])(cluster|clusterblast|knownclusterblast|subclusterblast)-(\d+)(?=-|$)',lambda m:m[1]+'-'+ids.get('cluster-'+m[2],'cluster-'+m[2]).split('-')[1],value)
  def link(value):
   stripped=value.strip();base,sep,fragment=stripped.partition('#')
   if base in paths:return paths[base]+(sep+fragment if sep else '')
   if not base and sep:return '#'+present_id(fragment)
   return value
  def adapt(node):
   for n in node.walk():
    for k,v in list(n.attrs.items()):
     if v is None:continue
     value=present_id(v) if k in {'id','for','aria-controls'} else link(v) if k in {'href','src','value','data'} else v
     if value!=v:n.set(k,value)
   return node
  # Retain structured scientific fields; only native DOM display keys and local asset URLs change.
  def strings(obj):
   if isinstance(obj,dict):return {k:strings(v) for k,v in obj.items()}
   if isinstance(obj,list):return [strings(v) for v in obj]
   if isinstance(obj,str) and ('href=' in obj or 'src=' in obj):return adapt(Document(obj).root).render()
   return obj
  for k in ids:
   value=strings(copy.deepcopy(data[k]));value['idx']=int(ids[k].split('-')[1]);clusters[ids[k]]=value
   if k in detail:details[ids[k]]=strings(detail[k])
   owner_id, owner_ordinal, local_cluster = rid, row['ordinal'], int(k.split('-')[1])
   if not completion.get('shards') and analyzed > 1:
    section=report.byid(k)
    downloads=[n.attrs['href'] for n in section.walk() if n.tag=='a' and re.search(r'\.cluster[0-9]+\.gbk$',n.attrs.get('href',''))]
    matches=[c for c in validation.get('calls',[]) if c['native_cluster_gbk'] in downloads]
    if len(matches)!=1:raise ValueError('Ambiguous original identity in native genome report')
    call=matches[0];owner_id=call['original_record_id'];owner_ordinal=call['original_record_ordinal']
    local_cluster=int(re.search(r'\.cluster([0-9]+)\.gbk$',call['native_cluster_gbk'])[1])
   mapped.append({'display':value['idx'],'record':owner_id,'original_record_ordinal':owner_ordinal,'local_cluster':local_cluster,'native_key':k,'start':data[k]['start'],'end':data[k]['end']})
  table=next(n for n in report.byid('cluster-overview').walk() if n.tag=='tbody');adapt(table)
  for n in table.walk():
   if n.tag=='a' and n.attrs.get('href','').startswith('#cluster-'):n.children=['Cluster '+n.attrs['href'].split('-')[1]]
  if data:tables.extend(table.children)
  for n in report.byid('clusterbuttons').children:
   if isinstance(n,Element) and any(x.attrs.get('href') in {'#'+k for k in ids} for x in n.walk()):
    adapt(n)
    for a in n.walk():
     if a.tag=='a':a.children=[a.attrs['href'].split('-')[1]]
    buttons.append(n)
  for n in report.walk():
   if n.attrs.get('id') in ids:
    n.set('data-native-record', namespace)
    sections.append(adapt(n))
  reports.append({'namespace':namespace,'record':rid,'analyzed':True,'calls':len(data),'index_sha256':sha(native/'index.html'),'data_sha256':sha(native/'geneclusters.js'),'document':report})
 # Preserve native global code and template; replace only the assembled containers.
 base=reports[0]['document'];base.byid('overview').set('data-native-asset-map',json.dumps(path_maps,separators=(',',':')));base.byid('clusterbuttons').children=[Document('<li class="clbutton"><a href="#">Overview</a></li>').root,*buttons]
 next(n for n in base.byid('cluster-overview').walk() if n.tag=='tbody').children=tables
 body=next(n for n in base.walk() if n.tag=='body');body.children=[n for n in body.children if not (isinstance(n,Element) and re.fullmatch('cluster-\\d+',n.attrs.get('id','')))];i=body.children.index(base.byid('footer'));body.children[i:i]=sections
 next(n for n in base.walk() if n.tag=='title').children=[html.escape(root.name)+' - '+str(len(clusters))+' clusters - plantiSMASH results']
 downloads='<li><a href="records.final.gbk">Download GenBank summary file</a></li><li><a href="geneclusters.csv">Download cluster spreadsheet (CSV)</a></li><li><a href="record-cluster-map.tsv">Download original identity mapping</a></li>'
 base.byid('downloadoptions').children=[downloads]
 # Native SVG requests also work when an extracted report is opened with file://.
 loader='window.plantNativeSvg='+json.dumps(svg_data,separators=(',',':')).replace('<', r'\u003c')+';\n(function($){var get=$.get;$.get=function(url,success,type){if(Object.prototype.hasOwnProperty.call(window.plantNativeSvg,url)){var d=$.Deferred();success(window.plantNativeSvg[url]);d.resolve(window.plantNativeSvg[url]);return d.promise();}return get.apply(this,arguments);};})(jQuery);\n'
 (dest/'native-assets.js').write_text(loader)
 for i,n in enumerate(body.children):
  if isinstance(n,Element) and n.tag=='script' and n.attrs.get('src')=='geneclusters.js':body.children.insert(i+1,Document('<script src="native-assets.js"></script>').root);break
 # Include evaluated empty records and unevaluated no-CDS records without fabricating calls.
 status=[{'record':r['original_id'],'original_record_ordinal':r['original_record_ordinal'],'status':'analyzed' if r['CDS'] else 'not_evaluated_no_CDS','calls':sum(m['record']==r['original_id'] for m in mapped) if r['CDS'] else None} for r in records]
 summary='<details><summary>Record evaluation: '+str(analyzed)+' analyzed; '+str(len(records)-analyzed)+' not evaluated (no CDS)</summary><ul>'+''.join('<li>'+html.escape(r['record'])+': '+('not evaluated (no CDS)' if r['calls'] is None else str(r['calls'])+' calls')+'</li>' for r in status)+'</ul></details>'
 base.byid('overview').children.append(summary)
 for n in base.walk():
  if n.tag == 'script' and not n.attrs.get('src'):
   n.children=[x.replace('\"subgroup/tree_svg/\" + locusTag', '\"subgroup/\" + $(\".page:visible\").attr(\"data-native-record\") + \"/tree_svg/\" + locusTag') if isinstance(x,str) else x for x in n.children]
 for n in base.walk():
  if n.tag == 'script' and not n.attrs.get('src'):
   for i,x in enumerate(n.children):
    if not isinstance(x,str) or 'function openSvgInWindow' not in x:continue
    x=x.replace('    var svgUrl = ', '    var assetMap = JSON.parse(document.getElementById("overview").getAttribute("data-native-asset-map"));\n    var recordAssets = assetMap[$(".page:visible").attr("data-native-record")] || {};\n    var svgUrl = ',1)
    x=x.replace('    var windowTitle = ', '    svgUrl = recordAssets["subgroup/tree_svg/" + locusTag + ".svg"] || svgUrl;\n    legendUrl = recordAssets["subgroup/tree_svg/" + locusTag + "_legend.svg"] || legendUrl;\n    var windowTitle = ',1)
    n.children[i]=x
 (dest/'index.html').write_text(base.render());(dest/'geneclusters.js').write_text('var geneclusters = '+json.dumps(clusters,separators=(',',':'))+';\nvar details_data = '+json.dumps(details,separators=(',',':'))+';\n')
 combined=root/'native/records.final.gbk'
 if not combined.exists():combined,=(root/'native').glob('*.final.gbk')
 shutil.copyfile(combined,dest/'records.final.gbk')
 with (dest/'record-cluster-map.tsv').open('w') as f:
  writer=csv.DictWriter(f,fieldnames=list(mapped[0]) if mapped else ['display','record','local_cluster','start','end'],delimiter='\t');writer.writeheader();writer.writerows(mapped)
 with (dest/'geneclusters.csv').open('w') as f:
  w=csv.writer(f);w.writerow(['Display cluster','Original record','Local cluster','From','To','Type','Core domains','Subgroups','CD-HIT groups','Known cluster','MIBiG'])
  for m in mapped:
   c=clusters['cluster-'+str(m['display'])];w.writerow([m['display'],m['record'],m['local_cluster'],m['start'],m['end'],c.get('type'),'; '.join(c.get('domains',[])),'; '.join(c.get('substrates',[])),len(c.get('cdhitclusters',[])),c.get('knowncluster'),c.get('BGCid')])
 import sys
 sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'web'))
 from plant_identity import PUBLIC_PRODUCER
 profile_path=Path(__file__).resolve().parents[1]/'config/plantismash-profile.json'
 profile=json.loads(profile_path.read_text())
 PROFILE=profile['profile_id'];PROFILE_SHA256=sha(profile_path)
 execution=json.loads((root/'execution.json').read_text())
 provenance={'producer':PUBLIC_PRODUCER,'profile_id':PROFILE,'profile_sha256':PROFILE_SHA256,'runtime_sha256':execution.get('sif_sha256'),'input_sha256':inv['source_file_sha256'],'source_lock_sha256':sha(Path(__file__).resolve().parents[1]/'software/plantismash/sources.lock.json'),'schema':'clusterweave-native-plant-report-v1','tool':'plantiSMASH','version':'2.0.4','operation':'Assembly of validated native report state; scientific analysis was not repeated','records':status,'reports':[{k:v for k,v in r.items() if k!='document'} for r in reports],'assets':assets,'shared_assets_exact_duplicates':collisions,'cluster_mapping':mapped,'combined_genbank_sha256':sha(combined)}
 (dest/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
 return {'calls':len(mapped),'analyzed':analyzed,'not_evaluated':len(records)-analyzed,'assets':len(assets),'files':sum(p.is_file() for p in dest.rglob('*'))}
def publish_report(root):
 root=Path(root)
 destination=root / '.assembled-report'
 if destination.exists():
  raise ValueError('Incomplete earlier report assembly requires inspection')
 result=assemble(root,destination)
 for item in destination.iterdir():
  target=root/item.name
  if target.exists():
   raise ValueError('Native report export would overwrite an existing path: '+item.name)
  item.rename(target)
 destination.rmdir()
 return result

if __name__=='__main__':
 import sys
 print(json.dumps(assemble(sys.argv[1],sys.argv[2])))
