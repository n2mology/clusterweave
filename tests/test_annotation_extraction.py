from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from annotation_source import MODULES, ROOT

sys.path.insert(0, str(ROOT / 'bin'))
import accession_cache
import cached_accession
import cached_genbank


class AnnotationExtractionTests(unittest.TestCase):
    def test_flat_runner_loads_modules_outside_repository_working_directory(self):
        with tempfile.TemporaryDirectory(prefix='flat runtime ') as tmp:
            root = Path(tmp)
            for name in ('run_annotation_and_detection.sh', *MODULES, 'detection_plantismash.sh'):
                shutil.copyfile(ROOT / name, root / name)
            result = subprocess.run(['bash', str(root / 'run_annotation_and_detection.sh'), '-h'],
                                    cwd='/', env=dict(os.environ, ENGINE='docker'), capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Usage:', result.stdout)

    def test_each_module_changes_scientific_source_and_preparation_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ('bin', 'web'):
                shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('run_annotation_and_detection.sh', *MODULES, 'detection_plantismash.sh'):
                shutil.copyfile(ROOT / name, root / name)
            acquired = root / 'acquired'
            acquired.mkdir()
            fasta = acquired / 'genome.fa'
            fasta.write_text('>seq\nATGAAA\n')
            args = argparse.Namespace(route_manifest=root / 'routes.tsv', genome_id='Public',
                                      operation='bacteria', input=fasta, acquired_root=acquired,
                                      min_record_bp=1, max_record_bp=10000)
            with mock.patch.object(cached_accession, 'ROOT', root), mock.patch.object(cached_genbank, 'ROOT', root), \
                 mock.patch.object(cached_genbank, 'public_accession', return_value='GCF_999999999.1'), \
                 mock.patch.object(cached_genbank, 'runtime_digest', return_value='3' * 64):
                original = cached_accession.source_digest()
                identity = cached_genbank.make_identity(args)
                original_key = accession_cache.identity_key(identity)
                for name in MODULES:
                    with self.subTest(module=name):
                        path = root / name
                        before = path.read_bytes()
                        path.write_bytes(before + b'\n# changed scientific source\n')
                        self.assertNotEqual(cached_accession.source_digest(), original)
                        changed = cached_genbank.make_identity(args)
                        self.assertNotEqual(changed['source_sha256'], identity['source_sha256'])
                        self.assertNotEqual(accession_cache.identity_key(changed), original_key)
                        path.unlink()
                        with self.assertRaises((OSError, ValueError)):
                            cached_accession.source_digest()
                        with self.assertRaises((OSError, ValueError)):
                            cached_genbank.make_identity(args)
                        path.write_bytes(before)
                        self.assertEqual(cached_accession.source_digest(), original)
                        self.assertEqual(cached_genbank.make_identity(args), identity)


    def test_input_reader_is_a_detection_dependency_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ('bin', 'web'):
                shutil.copytree(ROOT / directory, root / directory,
                                ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('run_annotation_and_detection.sh', *MODULES, 'detection_plantismash.sh'):
                shutil.copyfile(ROOT / name, root / name)
            acquired = root / 'acquired'
            acquired.mkdir()
            fasta = acquired / 'genome.fa'
            fasta.write_text('>seq\nATGAAA\n')
            args = argparse.Namespace(route_manifest=root / 'routes.tsv', genome_id='Public',
                                      operation='bacteria', input=fasta, acquired_root=acquired,
                                      min_record_bp=1, max_record_bp=10000)
            with mock.patch.object(cached_accession, 'ROOT', root), \
                 mock.patch.object(cached_genbank, 'ROOT', root), \
                 mock.patch.object(cached_genbank, 'public_accession', return_value='GCF_999999999.1'), \
                 mock.patch.object(cached_genbank, 'runtime_digest', return_value='3' * 64):
                source = cached_accession.source_digest()
                identity = cached_genbank.make_identity(args)
                key = accession_cache.identity_key(identity)
                reader = root / 'bin' / 'annotation_input.py'
                before = reader.read_bytes()
                reader.write_bytes(before + b'\n# changed input reader\n')
                self.assertNotEqual(cached_accession.source_digest(), source)
                self.assertEqual(cached_genbank.make_identity(args), identity)
                self.assertEqual(accession_cache.identity_key(cached_genbank.make_identity(args)), key)
                reader.unlink()
                with self.assertRaises((OSError, ValueError)):
                    cached_accession.source_digest()
                self.assertEqual(cached_genbank.make_identity(args), identity)
                reader.write_bytes(before)
                self.assertEqual(cached_accession.source_digest(), source)


    def test_profile_policy_is_a_detection_dependency_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ('bin', 'web'):
                shutil.copytree(ROOT / directory, root / directory,
                                ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('run_annotation_and_detection.sh', *MODULES, 'detection_plantismash.sh'):
                shutil.copyfile(ROOT / name, root / name)
            acquired = root / 'acquired'
            acquired.mkdir()
            fasta = acquired / 'genome.fa'
            fasta.write_text('>seq\nATGAAA\n')
            args = argparse.Namespace(route_manifest=root / 'routes.tsv', genome_id='Public',
                                      operation='bacteria', input=fasta, acquired_root=acquired,
                                      min_record_bp=1, max_record_bp=10000)
            with mock.patch.object(cached_accession, 'ROOT', root), \
                 mock.patch.object(cached_genbank, 'ROOT', root), \
                 mock.patch.object(cached_genbank, 'public_accession', return_value='GCF_999999999.1'), \
                 mock.patch.object(cached_genbank, 'runtime_digest', return_value='3' * 64):
                source = cached_accession.source_digest()
                identity = cached_genbank.make_identity(args)
                key = accession_cache.identity_key(identity)
                policy = root / 'web/scientific_profiles.py'
                before = policy.read_bytes()
                policy.write_bytes(before + b'\n# changed profile policy\n')
                self.assertNotEqual(cached_accession.source_digest(), source)
                self.assertEqual(cached_genbank.make_identity(args), identity)
                self.assertEqual(accession_cache.identity_key(cached_genbank.make_identity(args)), key)
                policy.unlink()
                with self.assertRaises((OSError, ValueError)):
                    cached_accession.source_digest()
                self.assertEqual(cached_genbank.make_identity(args), identity)
                policy.write_bytes(before)
                self.assertEqual(cached_accession.source_digest(), source)

    def test_copied_cli_helper_imports_profile_policy_without_app_or_site_packages(self):
        with tempfile.TemporaryDirectory(prefix='copied CLI runtime ') as tmp:
            root = Path(tmp)
            for line in (ROOT / 'Dockerfile.worker').read_text().splitlines():
                if not line.startswith('COPY '):
                    continue
                fields = shlex.split(line)
                if not fields or fields[0] != 'COPY' or not fields[-1].startswith('/clusterweave/'):
                    continue
                destination = root / fields[-1].removeprefix('/clusterweave/')
                for source in fields[1:-1]:
                    path = ROOT / source
                    if path.is_dir():
                        shutil.copytree(path, destination, ignore=shutil.ignore_patterns('__pycache__'))
                    elif path.is_file():
                        target = destination / path.name if fields[-1].endswith('/') else destination
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
            helper = root / 'bin/annotation_input.py'
            command = [sys.executable, '-I', '-S', '-B', str(helper), 'profile-defaults']
            result = subprocess.run(command, cwd='/', env={'PATH': os.defpath},
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'fungi\tfunannotate\tantismash+funbgcex\nbacteria\tprodigal\tantismash\nplants\tannotation_required\tplantismash\n')
            policy = root / 'web/scientific_profiles.py'
            policy.write_text('def default_prediction_method(group): return "custom_prediction"\n'
                              'def default_detector_profile(group): return "custom_detector"\n')
            result = subprocess.run(command, cwd='/', env={'PATH': os.defpath},
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'fungi\tcustom_prediction\tcustom_detector\nbacteria\tcustom_prediction\tcustom_detector\nplants\tcustom_prediction\tcustom_detector\n')
            policy.unlink()
            result = subprocess.run(command, cwd='/', env={'PATH': os.defpath},
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('scientific_profiles', result.stderr)
