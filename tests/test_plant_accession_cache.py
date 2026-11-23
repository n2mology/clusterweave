"""Plant snapshot reuse preserves annotation and rejects incomplete identities."""
import argparse
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'bin'), str(ROOT / 'web')]
import accession_cache as cache
import cached_accession as adapter
from test_cached_accession import identity
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord


def fixture():
    records = []
    for name in ['plant_record_a', 'plant_record_b']:
        r = SeqRecord(Seq('ATGAAATAA' + 'A' * 1200), id=name, name=name, description='public plant fixture')
        r.annotations['molecule_type'] = 'DNA'
        # A repeated protein identifier in different original records is valid.
        r.features = [SeqFeature(SimpleLocation(0, 9, 1), type='CDS', qualifiers={'protein_id': ['shared'], 'translation': ['MK']})]
        records.append(r)
    gb, fa = io.StringIO(), io.StringIO()
    SeqIO.write(records, gb, 'genbank'); SeqIO.write(records, fa, 'fasta')
    prefix = 'ncbi_dataset/data/GCF_999999999.1/'
    return {prefix + 'genomic.gbff': gb.getvalue().encode(), prefix + 'genomic.fna': fa.getvalue().encode(),
            'ncbi_dataset/data/assembly_data_report.jsonl': b'{"accession":"GCF_999999999.1"}\n'}


def plant_identity():
    value = identity(True)
    value['contract'] = adapter.CONTRACT_PLANT_SNAPSHOT
    value['route']['taxon'] = 'plants'
    return value


class PlantSnapshotTests(unittest.TestCase):
    def validate(self, files, ident=None):
        return adapter.validate_bundle({'bundle.tar': adapter.pack(files)}, ident or plant_identity())

    def test_complete_annotation_and_repeated_record_scoped_protein_identifiers(self):
        files = fixture()
        self.assertEqual(self.validate(files), files)
        self.assertEqual(len(cache.identity_key(plant_identity())), 64)

    def test_missing_annotation_wrong_accession_and_mismatched_fasta_rejected(self):
        for change, reason in [('missing', 'annotation_required'), ('accession', 'snapshot_accession'), ('fasta', 'annotation_incompatible'), ('translation', 'annotation_incompatible')]:
            files = fixture()
            gb = next(n for n in files if n.endswith('.gbff')); fa = next(n for n in files if n.endswith('.fna'))
            if change == 'missing': del files[gb]
            elif change == 'accession': files['ncbi_dataset/data/assembly_data_report.jsonl'] = b'{"accession":"GCF_999999999.2"}\n'
            elif change == 'fasta': files[fa] = files[fa].replace(b'ATGAAA', b'ATGCCC', 1)
            else: files[gb] = files[gb].replace(b'/translation="MK"', b'/translation="MP"', 1)
            with self.subTest(change=change), self.assertRaisesRegex(cache.Unavailable, reason): self.validate(files)

    def test_large_limit_is_only_available_to_plant_contract_and_is_bounded(self):
        files = fixture(); payload = {'bundle.tar': adapter.pack(files)}
        with mock.patch.object(adapter, 'MAX_FILE_BYTES', 100):
            self.assertEqual(adapter.validate_bundle(payload, plant_identity()), files)
            with self.assertRaisesRegex(cache.Unavailable, 'bundle_capacity'): adapter.validate_bundle(payload, identity(True))
        with mock.patch.object(adapter, 'PLANT_SNAPSHOT_BYTES', 100):
            with self.assertRaisesRegex(cache.Unavailable, 'bundle_capacity'): adapter.validate_bundle(payload, plant_identity())
        for contract, taxon in [(adapter.CONTRACT_SNAPSHOT, 'plants'), (adapter.CONTRACT_PLANT_SNAPSHOT, 'fungi'), (adapter.CONTRACT_DETECTION, 'plants')]:
            value = plant_identity(); value['contract'] = contract; value['route']['taxon'] = taxon
            with self.assertRaises(cache.Unavailable): cache.identity_key(value)

    def test_real_identity_stays_stable_after_plant_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            route = Path(directory) / 'routes.tsv'
            route.write_text('genome_id\tinput_key\tsource_accession\ttaxon_source\ttaxon_group\troute_status\n'
                             'Public\tGCF_999999999.1\tGCF_999999999.1\tncbi\tplants\trouted\n')
            args = argparse.Namespace(accession='GCF_999999999.1', genome_id='Public', taxon='plants',
                                      route_manifest=route, datasets='/usr/bin/true')
            # Identity hashing needs stable tool bytes, not host unzip installation.
            unzip = Path(directory) / 'unzip'
            unzip.write_text('#!/bin/sh\nexit 0\n')
            with mock.patch.object(adapter.shutil, 'which', return_value=str(unzip)):
                before = adapter.snapshot_identity(args)
                self.validate(fixture(), before)
                self.assertEqual(adapter.snapshot_identity(args), before)
            self.assertEqual(before['contract'], adapter.CONTRACT_PLANT_SNAPSHOT)

    def test_real_store_miss_population_hit_and_catalog_routing(self):
        from accession_catalog import CONTRACTS
        self.assertEqual(CONTRACTS[adapter.CONTRACT_PLANT_SNAPSHOT], 'retrieval')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source'; source.mkdir(); (root / 'store').mkdir(mode=0o700)
            files = fixture()
            for n, data in files.items():
                p = source / n; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
            args = argparse.Namespace(destination=root / 'first', provenance=root / 'receipt.json', command=['cp', '-r', str(source), str(root / 'first')])
            with mock.patch.dict(os.environ, {'CLUSTERWEAVE_ACCESSION_CACHE_ROOT': str(root / 'store')}, clear=True), mock.patch.object(adapter, 'snapshot_identity', return_value=plant_identity()):
                self.assertEqual(adapter.retrieve(args), 0)
                self.assertEqual(json.loads(args.provenance.read_text())['population'], 'published')
                args.destination = root / 'second'; args.command = ['false']
                self.assertEqual(adapter.retrieve(args), 0)
                self.assertEqual(json.loads(args.provenance.read_text())['outcome'], 'hit')
                for n, data in files.items(): self.assertEqual((args.destination / n).read_bytes(), data)
                # A forced request computes afresh and cannot claim a cache hit.
                with mock.patch.dict(os.environ, {'FORCE': '1'}): self.assertEqual(adapter.retrieve(args), 1)
