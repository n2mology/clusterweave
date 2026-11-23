from pathlib import Path
import hashlib
import importlib.util
import io
import tempfile
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('plant_preparation',Path(__file__).resolve().parents[1]/'software/plantismash/prepare.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Response(io.BytesIO):
    url='https://example.org/source'

class AcquisitionTests(unittest.TestCase):
    def test_verified_atomic_promotion_and_reuse(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'asset';body=b'complete public source';expected=hashlib.sha256(body).hexdigest()
            with mock.patch.object(module.urllib.request,'urlopen',return_value=Response(body)) as get:
                self.assertEqual(module.acquire(Response.url,expected,target),'acquired')
                self.assertEqual(module.acquire(Response.url,expected,target),'reused')
                self.assertEqual(get.call_count,1)
            self.assertEqual(target.read_bytes(),body);self.assertFalse(target.with_name('asset.partial').exists())
    def test_checksum_failure_never_promotes(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'asset'
            with mock.patch.object(module.urllib.request,'urlopen',return_value=Response(b'truncated')):
                with self.assertRaisesRegex(ValueError,'checksum'):module.acquire(Response.url,'0'*64,target)
            self.assertFalse(target.exists());self.assertEqual(len(list(Path(root).glob('asset.partial-failed-*'))),1)
    def test_interrupted_download_is_preserved_then_recovers(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'asset';partial=target.with_name('asset.partial');partial.write_bytes(b'interrupted');body=b'complete'
            with mock.patch.object(module.urllib.request,'urlopen',return_value=Response(body)):
                module.acquire(Response.url,hashlib.sha256(body).hexdigest(),target)
            self.assertEqual(target.read_bytes(),body)
            self.assertEqual(next(Path(root).glob('asset.partial-interrupted-*')).read_bytes(),b'interrupted')
    def test_corrupt_existing_file_is_quarantined(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'asset';target.write_bytes(b'corrupt');body=b'complete'
            with mock.patch.object(module.urllib.request,'urlopen',return_value=Response(body)):
                module.acquire(Response.url,hashlib.sha256(body).hexdigest(),target)
            self.assertEqual(next(Path(root).glob('asset.corrupt-*')).read_bytes(),b'corrupt')
    def test_transfer_bound_and_https(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'asset'
            with self.assertRaisesRegex(ValueError,'HTTPS'):module.acquire('http://example.org/x','0'*64,target)
            with mock.patch.object(module.urllib.request,'urlopen',return_value=Response(b'1234')):
                with self.assertRaisesRegex(ValueError,'size bound'):module.acquire(Response.url,'0'*64,target,max_bytes=3)
            self.assertFalse(target.exists())

if __name__=='__main__':unittest.main()
