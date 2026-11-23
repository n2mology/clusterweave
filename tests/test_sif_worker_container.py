import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sif_worker_container',ROOT/'bin/sif_worker_container.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ConfinedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.image={'Id':'sha256:'+'a'*64,'Config':{'Env':['PATH=/usr/bin'],'Entrypoint':['/app/entrypoint.sh']}}
        self.model={'name':'fixture','networks':{'default':{'name':'fixture_default'}},'volumes':{},'services':{'worker':{
            'image':self.image['Id'],'container_name':'fixture-worker','user':'65534:65534','read_only':True,
            'cap_drop':['ALL'],'labels':{'org.clusterweave.runtime':'confined-sif-v1'},
            'devices':[{'source':'/dev/fuse','target':'/dev/fuse','permissions':'rw'}],
            'security_opt':['no-new-privileges:true','apparmor:clusterweave-sif-worker','seccomp:./config/security/apptainer-worker-seccomp.json'],
            'environment':{'ENGINE':'apptainer','CLUSTERWEAVE_ENABLE_DOCKER_SOCKET':'0','CLUSTERWEAVE_LOCAL_PREPARED_ONLY':'1','WORKER_CONCURRENCY':'1'},
            'cpus':'4','mem_limit':'16g','pids_limit':1024,'tmpfs':['/tmp:rw,exec,nosuid,nodev,size=4g'],'volumes':[]}}}
        self.worker=self.model['services']['worker']
        for key,target,readonly in [('job_data','/data',False),('software','/data/software',True),('accession_cache','/var/cache/clusterweave',False),('antismash_db','/databases/antismash',True),('pfam_db','/databases/pfam',True)]:
            self.model['volumes'][key]={'name':'fixture_'+key}
            self.worker['volumes'].append({'type':'volume','source':key,'target':target,'read_only':readonly})
    def render(self):return module.render(self.model,self.image,ROOT/'config/security')
    def test_valid_has_no_host_authority(self):
        result=self.render();host=result['HostConfig']
        self.assertEqual(result['User'],'65534:65534')
        self.assertEqual(host['CapDrop'],['ALL']);self.assertTrue(host['ReadonlyRootfs'])
        self.assertEqual(host['MemorySwap'],host['Memory'])
        self.assertTrue(host['Init'])
        self.assertTrue(all(x['Type']=='volume' for x in host['Mounts']))
        self.assertEqual(host['MaskedPaths'],['/sys/devices/virtual/powercap','/sys/firmware'])
    def test_socket_bind_rejected(self):
        self.worker['volumes'].append({'type':'bind','source':'/var/run/docker.sock','target':'/var/run/docker.sock'})
        with self.assertRaises((ValueError,KeyError)):self.render()
    def test_foreign_writable_data_rejected(self):
        self.model['volumes']['job_data']['name']='production_job_data'
        with self.assertRaises(ValueError):self.render()
    def test_writable_references_rejected(self):
        self.worker['volumes'][-1]['read_only']=False
        with self.assertRaises(ValueError):self.render()
    def test_privilege_rejected(self):
        self.worker['privileged']=True
        with self.assertRaises(ValueError):self.render()
    def test_unconfined_profile_rejected(self):
        self.worker['security_opt'][1]='apparmor:unconfined'
        with self.assertRaises(ValueError):self.render()
    def test_remote_daemon_rejected(self):
        self.worker['environment']['DOCKER_HOST']='tcp://host:2375'
        with self.assertRaises(ValueError):self.render()
    def test_operator_capacity_is_preserved_without_smoke_ceiling(self):
        self.worker.update(cpus='63', mem_limit='112g', pids_limit=4096)
        self.worker['environment']['WORKER_CONCURRENCY']='3'
        result=self.render()
        self.assertEqual(result['HostConfig']['NanoCpus'],63000000000)
        self.assertEqual(result['HostConfig']['Memory'],112*1024**3)
        self.assertIn('WORKER_CONCURRENCY=3',result['Env'])
    def test_invalid_or_unbounded_resources_rejected(self):
        for value in ['0','-1','nan','inf']:
            self.worker['cpus']=value
            with self.assertRaises(ValueError):self.render()
    def test_tagged_image_rejected(self):
        self.worker['image']='worker:latest'
        with self.assertRaises(ValueError):self.render()
    def test_host_network_rejected(self):
        self.model['networks']['default']['name']='host'
        with self.assertRaises(ValueError):self.render()

if __name__=='__main__':unittest.main()
