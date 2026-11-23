#!/usr/bin/env python3
"""Package a local, verified source-build image using non-setuid Apptainer."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tarfile
import time


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

def package(image,worker,output,expected_sha256=None,max_export_bytes=None,min_free_bytes=0,source_date_epoch=315532800,tmpfs_build_gib=0,reuse_export=None,reuse_export_sha256=None):
    if not 0 <= tmpfs_build_gib <= 32:raise ValueError("Temporary build memory must be between 0 and 32 GiB")
    memory_bytes=(8+tmpfs_build_gib)*1024**3
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('Output exists; verify and reuse it or select a new destination')
    work=Path(tempfile.mkdtemp(prefix='plantismash-build-',dir=output.parent));work.chmod(0o777)
    identity=subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()
    worker_id=subprocess.check_output(['docker','image','inspect',worker,'--format','{{.Id}}'],text=True).strip()
    record={'image':identity,'builder_image':worker_id,'source_date_epoch':source_date_epoch,'temporary_build_memory_gib':tmpfs_build_gib,'started':time.time(),'state':'building','max_export_bytes':max_export_bytes,'minimum_free_bytes':min_free_bytes,'limits':{'cpus':2,'memory_bytes':memory_bytes,'pids':256,'timeout_seconds':1800,'compressor_memory':'512M'}}
    try:
        archive=work/'image.tar'
        if reuse_export is not None:
            prior=Path(reuse_export).resolve()
            if not reuse_export_sha256 or digest(prior)!=reuse_export_sha256:
                raise ValueError('Reused image export checksum mismatch')
            if max_export_bytes is not None and prior.stat().st_size>max_export_bytes:
                raise ValueError('Reused image export exceeds the prospective storage bound')
            with tarfile.open(prior) as saved:
                manifest=json.load(saved.extractfile('manifest.json'))
                if len(manifest)!=1:raise ValueError('Expected one image in reused export')
                config=saved.extractfile(manifest[0]['Config']).read()
                config_digest='sha256:'+hashlib.sha256(config).hexdigest()
                if config_digest!=identity:
                    # Containerd image stores identify an image by its OCI
                    # manifest rather than the older Docker config digest.
                    member='blobs/sha256/'+identity.removeprefix('sha256:')
                    payload=saved.extractfile(member).read()
                    if 'sha256:'+hashlib.sha256(payload).hexdigest()!=identity or json.loads(payload).get('config',{}).get('digest')!=config_digest:
                        raise ValueError('Reused export does not match the selected image')
            if shutil.disk_usage(work).free<min_free_bytes:
                raise ValueError('Reused export reached the minimum free-space floor')
            # A second directory entry preserves the failed export and avoids
            # duplicating it. Cross-filesystem reuse fails without copying.
            os.link(prior,archive)
            record['reused_export']={'path':str(prior),'sha256':reuse_export_sha256}
        else:
            with archive.open('wb') as f:
                process=subprocess.Popen(['docker','image','save',identity],stdout=subprocess.PIPE)
                total=0
                try:
                    for block in iter(lambda:process.stdout.read(1024*1024),b''):
                        total+=len(block)
                        if max_export_bytes is not None and total>max_export_bytes:
                            raise ValueError('Image export exceeds the prospective storage bound')
                        if shutil.disk_usage(work).free<min_free_bytes:
                            raise ValueError('Image export reached the minimum free-space floor')
                        f.write(block)
                    if process.wait()!=0:raise RuntimeError('Docker image export failed')
                except BaseException:
                    process.terminate();process.wait();raise
        archive.chmod(0o644);record['temporary_export_sha256']=digest(archive);record['temporary_export_bytes']=archive.stat().st_size
        cmd=['docker','run','--name','clusterweave-sif-'+work.name,'--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--cpus','2','--memory',str(memory_bytes),'--pids-limit','256','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=4g','--env','HOME=/tmp','--env','SOURCE_DATE_EPOCH=315532800','--env','APPTAINER_TMPDIR=/work/tmp','--mount','type=bind,source='+str(work)+',target=/work','--entrypoint','/usr/bin/apptainer',worker_id,'build','--disable-cache','--mksquashfs-args','-processors 2 -mem 512M','/work/plant.sif','docker-archive:/work/image.tar']
        # Some tools compare source/derived mtimes strictly; their prepared
        # image timestamps must survive packaging. Plant reproducibility keeps
        # its original fixed epoch unless this option is explicitly selected.
        if source_date_epoch is None:
            index=cmd.index('SOURCE_DATE_EPOCH=315532800');del cmd[index-1:index+1]
        else:
            cmd[cmd.index('SOURCE_DATE_EPOCH=315532800')]='SOURCE_DATE_EPOCH='+str(source_date_epoch)
        if tmpfs_build_gib:
            index=cmd.index('--entrypoint')
            cmd[index:index]=['--tmpfs',f'/work/tmp:rw,exec,nosuid,nodev,size={tmpfs_build_gib}g,uid=65534,gid=65534,mode=1777']
        (work/'tmp').mkdir(mode=0o777);(work/'tmp').chmod(0o777)
        record['argv']=cmd
        with (work/'build.log').open('w') as log:
            process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+1800
            try:
                while process.poll() is None:
                    if time.monotonic()>deadline:raise TimeoutError('SIF packaging exceeded 1800 seconds')
                    if shutil.disk_usage(work).free<min_free_bytes:raise ValueError('SIF packaging reached the minimum free-space floor')
                    time.sleep(1)
                if process.returncode:raise subprocess.CalledProcessError(process.returncode,cmd)
            except BaseException:
                # Only this invocation's uniquely named builder is targeted.
                subprocess.run(['docker','stop','--time','2','clusterweave-sif-'+work.name],stdout=log,stderr=subprocess.STDOUT)
                process.wait(timeout=30);raise
        result=work/'plant.sif';record.update(state='packaged_pending_acceptance',sif_sha256=digest(result),bytes=result.stat().st_size,finished=time.time(),argv=cmd)
        if expected_sha256 is not None and record['sif_sha256'] != expected_sha256:
            raise ValueError('Built SIF checksum differs from the accepted pin; retained for diagnosis, not promoted')
        if expected_sha256 is not None:record['state']='checksum_verified'
        os.replace(result,output)
        output.with_suffix('.build.json').write_text(json.dumps(record,indent=2)+'\n')
        shutil.copyfile(work/'build.log',output.with_suffix('.build.log'))
        # Only this successful temporary export is removed. Failed work is kept.
        shutil.rmtree(work)
        return record
    except BaseException as error:
        record.update(state='failed',finished=time.time(),error=repr(error));(work/'failure.json').write_text(json.dumps(record,indent=2)+'\n');raise

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image',required=True);parser.add_argument('--worker-image',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--expected-sha256');parser.add_argument('--max-export-bytes',type=int);parser.add_argument('--min-free-bytes',type=int,default=0);parser.add_argument('--preserve-image-timestamps',action='store_true',help='Keep prepared image file mtimes for tools with timestamp-based prerequisite checks; not the reproducible plant recipe');parser.add_argument('--tmpfs-build-gib',type=int,default=0,help='Bound unpacking in memory (0–32 GiB); builder memory limit is this value plus 8 GiB');parser.add_argument('--reuse-export',type=Path,help='Reuse a retained Docker export on the output filesystem');parser.add_argument('--reuse-export-sha256',help='Required checksum from the retained export receipt');args=parser.parse_args();print(json.dumps(package(args.image,args.worker_image,args.output,args.expected_sha256,args.max_export_bytes,args.min_free_bytes,None if args.preserve_image_timestamps else 315532800,args.tmpfs_build_gib,args.reuse_export,args.reuse_export_sha256),indent=2))
if __name__=='__main__':main()
