#!/usr/bin/env python3
"""Export relocatable clinker panels with an exact input/helper/output inventory."""
from pathlib import Path
import csv,io,json,hashlib,zipfile,re

def package_panels(results):
    outputs=[]
    for tool in ('clinker','clinker_shared_family'):
        for runner in sorted((Path(results)/tool).rglob('run_panel.sh')):
            panel=runner.parent
            payloads={}
            for path in sorted(panel.rglob('*')):
                if path.is_symlink():raise ValueError('Linked portable panel payload')
                if not path.is_file():continue
                rel=path.relative_to(panel).as_posix()
                if rel.startswith('inputs/') and path.suffix.lower()=='.gbk' or rel in {'run_panel.sh','clinker_cli.py','postprocess_clinker_html.py','panel.html','session.json','alignments.tsv','panel_manifest.tsv'}:
                    data=path.read_bytes()
                    if rel=='run_panel.sh':
                        text=data.decode()
                        text=re.sub(r'^PROJECT_ROOT=.*$', 'PROJECT_ROOT="${SCRIPT_DIR}"', text, flags=re.M)
                        text=re.sub(r'^REPO_ROOT=.*$', 'REPO_ROOT="${CLUSTERWEAVE_ROOT:-${SCRIPT_DIR}}"', text, flags=re.M)
                        data=text.encode()
                    if rel=='panel_manifest.tsv':
                        reader=csv.DictReader(io.StringIO(data.decode()),delimiter='\t');rows=list(reader);out=io.StringIO();writer=csv.DictWriter(out,reader.fieldnames,delimiter='\t');writer.writeheader()
                        for row in rows:
                            for key in ('source_gbk_path','staged_gbk_path'):
                                if row.get(key):row[key]=('inputs/' if key=='staged_gbk_path' else '')+Path(row[key]).name
                            writer.writerow(row)
                        data=out.getvalue().encode()
                    payloads[rel]=data
            missing={'run_panel.sh','clinker_cli.py','postprocess_clinker_html.py','panel_manifest.tsv'}-payloads.keys()
            if missing:
                (panel/'portable-status.json').write_text(json.dumps({'state':'missing_dependencies','missing':sorted(missing),'action':'Regenerate the panel with the current staging helper before portable execution.'},indent=2)+'\n')
                (panel/'portable-clinker.zip').unlink(missing_ok=True)
                continue
            for name in ('LICENSE', 'THIRD_PARTY.md'):
                payloads[name]=(Path(__file__).resolve().parents[1]/name).read_bytes()
            input_count=sum(name.startswith('inputs/') and name.endswith('.gbk') for name in payloads)
            manifest={'schema':'portable-clinker-v1','rendered':'panel.html' in payloads,'alignment_state':('not_applicable_single_cluster' if input_count==1 else 'complete' if 'alignments.tsv' in payloads else 'missing'),'dependencies':{'clinker':'0.0.32','python':'3.10+','prepared_image':'quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0'},'run':'bash run_panel.sh; supply a prepared local clinker or CLINKER_DOCKER_IMAGE/CLINKER_ENGINE. No acquisition is performed.','payloads':{n:{'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)} for n,b in payloads.items()}}
            target=panel/'portable-clinker.zip'
            with zipfile.ZipFile(target.with_suffix('.tmp'),'w',compression=zipfile.ZIP_DEFLATED) as z:
                for name,data in sorted(payloads.items()):z.writestr(name,data)
                z.writestr('portable-manifest.json',json.dumps(manifest,indent=2)+'\n')
            target.with_suffix('.tmp').replace(target);outputs.append(target)
    return outputs

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('results',type=Path)
    for path in package_panels(p.parse_args().results):print(path)
