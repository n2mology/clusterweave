from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "bin"))
from accession_catalog import Catalog, CatalogUnavailable, catalog_path, manifest_row
from accession_cache import Store, canonical, identity_key, sha256
from cache_status import job_inventory, owner_provenance, RequestBudget, catalog_jobs, refresh_catalog
from test_accession_cache import identity, payload, validate


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        os.environ.pop("DATA_DIR", None)
        self.root = Path(self.tmp.name) / "cache"
        self.root.mkdir(mode=0o700)
        self.store = Store(self.root)
        self.key = identity_key(identity())
        self.catalog = Catalog(catalog_path(self.root))

    def populated(self):
        self.assertEqual(self.store.publish(identity(), payload(), validate), "published")
        self.store.reconcile_catalog()

    def query(self, accession=None, **kwargs):
        return self.catalog.availability([accession or identity()["accession"]], stage="preparation", **kwargs)

    def test_exact_candidates_and_mismatched_identity(self):
        self.populated()
        result = self.query(keys={identity()["accession"]: self.key})
        self.assertTrue(result["advisory"])
        self.assertEqual(result["results"][0]["status"], "candidate_available")
        self.assertEqual(result["results"][0]["candidates"][0]["key"], self.key)
        self.assertEqual(self.query(keys={identity()["accession"]: "f" * 64})["results"][0]["status"], "incompatible")
        self.assertEqual(self.query("GCF_999999999.2")["results"][0]["status"], "absent")

    def test_operator_cli_refresh_and_query_in_fresh_process(self):
        self.populated()
        data = Path(self.tmp.name) / "data"
        data.mkdir()
        env = dict(os.environ, DATA_DIR=str(data), CLUSTERWEAVE_ROOT=str(ROOT),
                   CLUSTERWEAVE_ACCESSION_CACHE_ROOT=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-B", str(ROOT / "bin/inspect_accession_cache.py")]
        refreshed = subprocess.run(command + ["refresh"], env=env, capture_output=True, check=True)
        self.assertEqual(json.loads(refreshed.stdout)["catalog"], "refreshed")
        queried = subprocess.run(command + ["query", "--accession", identity()["accession"],
                                              "--stage", "preparation", "--key", self.key],
                                 env=env, capture_output=True, check=True)
        self.assertEqual(json.loads(queried.stdout)["results"][0]["status"], "candidate_available")
        self.assertEqual(refreshed.stderr + queried.stderr, b"")

    def test_discovery_does_not_read_scientific_payload(self):
        self.populated()
        with mock.patch("accession_cache.regular_bytes", side_effect=AssertionError("payload read")):
            self.assertEqual(self.query()["results"][0]["status"], "candidate_available")

    def test_failed_index_update_recovers_without_recomputing(self):
        with mock.patch("os.posix_spawn", side_effect=OSError("offline")):
            self.assertEqual(self.store.publish(identity(), payload(), validate), "published")
        with self.assertRaises((CatalogUnavailable, OSError, sqlite3.Error)):
            self.query()
        self.store.reconcile_catalog()
        self.assertEqual(self.query()["results"][0]["status"], "candidate_available")
        self.assertEqual(self.store.lookup(identity(), validate)[0], payload())

    def test_corrupt_index_cannot_change_authoritative_hit(self):
        self.populated()
        self.catalog.path.write_bytes(b"corrupt catalog")
        self.assertEqual(self.store.lookup(identity(), validate)[0], payload())
        with self.assertRaises((CatalogUnavailable, sqlite3.Error)):
            self.query()

    def test_payload_corruption_quarantines_and_updates_metadata(self):
        self.populated()
        (self.root / "entries" / self.key / "prepared.gbk").write_bytes(b"corrupt biology")
        self.assertIsNone(self.store.lookup(identity(), validate)[0])
        self.assertEqual(self.query()["results"][0]["status"], "quarantined")

    def test_rebuild_recovers_quarantine_without_reusing_its_payload(self):
        self.populated()
        broken = payload(); broken["prepared.gbk"] += b"changed"
        self.assertEqual(self.store.publish(identity(), broken, lambda _: None), "conflicting_outputs")
        self.catalog.path.unlink()
        self.store.reconcile_catalog()
        self.assertEqual(self.query()["results"][0]["status"], "quarantined")
        self.assertFalse((self.root / "entries" / self.key).exists())

    def test_expiry_and_deletion_are_not_available(self):
        self.populated()
        self.store.max_age = 1
        entry = self.root / "entries" / self.key
        os.utime(entry, (time.time() - 2, time.time() - 2))
        self.store.reconcile_catalog()
        self.assertEqual(self.query()["results"][0]["status"], "expired")
        self.store.inspect(delete=self.key)
        self.assertEqual(self.query()["results"][0]["status"], "absent")

    def test_legacy_and_in_progress_are_not_verified_hits(self):
        self.store.reconcile_catalog(legacy=[(identity()["accession"], "detection")])
        result = self.catalog.availability([identity()["accession"]])["results"][0]
        self.assertEqual(result["status"], "legacy_unverified")
        self.store.reconcile_catalog(active=[(self.key, identity()["accession"], "preparation")])
        self.assertEqual(self.query()["results"][0]["status"], "in_progress")
        self.store.reconcile_catalog(complete=False)
        self.assertEqual(self.query()["results"][0]["status"], "unknown")

    def test_structured_population_failure_and_recovery(self):
        self.store.reconcile_catalog()
        def rejected(_):
            from accession_cache import Unavailable
            raise Unavailable("payload_map")
        with self.assertRaises(ValueError):
            self.store.publish(identity(), payload(), rejected)
        result = self.query()["results"][0]
        self.assertEqual((result["status"], result["reason"]), ("population_failed", "payload_map"))
        self.populated()
        self.assertEqual(self.query()["results"][0]["status"], "candidate_available")

    def test_stale_catalog_is_unknown_instead_of_absent(self):
        self.populated()
        with self.catalog.connection(write=True) as con:
            con.execute("UPDATE metadata SET value='1' WHERE name='refreshed_at'")
        with self.assertRaisesRegex(CatalogUnavailable, "stale"):
            self.query()

    def test_symlink_and_permissions_refused_without_changing_store(self):
        self.populated()
        target = self.root / "outside"
        self.catalog.path.rename(target)
        self.catalog.path.symlink_to(target)
        with self.assertRaises(CatalogUnavailable):
            self.query()
        self.assertEqual(self.store.lookup(identity(), validate)[0], payload())
        self.catalog.path.unlink(); target.rename(self.catalog.path)
        self.catalog.path.chmod(0o644)
        with self.assertRaises(CatalogUnavailable):
            self.query()

    def test_read_queries_cannot_mutate_or_create_catalog(self):
        with self.assertRaises(OSError):
            self.query()
        self.assertFalse(self.catalog.path.exists())
        self.populated()
        with self.catalog.connection() as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM entries")

    def test_exact_key_is_found_beyond_display_variant_limit(self):
        self.populated()
        rows = []
        for number in range(25):
            copy = identity()
            copy["parameters"]["genome_label_sha256"] = f"{number:064x}"
            key = identity_key(copy)
            m = {"key": key, "identity": copy}
            rows.append(manifest_row(m, digest="a" * 64, populated=time.time(), max_age=86400))
        _, store_id = self.store._catalog()
        self.catalog.reconcile(store_id, rows)
        key = sorted(r["key"] for r in rows)[0]
        result = self.query(keys={identity()["accession"]: key})["results"][0]
        self.assertEqual(result["status"], "candidate_available")
        self.assertEqual(result["candidates"][0]["key"], key)

    def test_inputs_are_bounded_and_versioned(self):
        self.populated()
        for accessions in ([], [identity()["accession"]] * 51, ["GCF_999999999"], ["../../private"], [{}]):
            with self.subTest(accessions=accessions), self.assertRaises((ValueError, TypeError)):
                self.catalog.availability(accessions)

    def test_metadata_does_not_change_fresh_preparation_native_identity(self):
        script = '''
import sys
from pathlib import Path
sys.path.insert(0, ROOT + '/bin')
import cached_genbank as c
from accession_cache import Store
store=Store(Path(STORE))
before=c.runtime_digest('bacteria')
store.lookup(IDENTITY,lambda _:None)
after=c.runtime_digest('bacteria')
assert before==after,'Metadata changed the scientific runtime'
'''.replace('ROOT', repr(str(ROOT))).replace('STORE', repr(str(self.root))).replace('IDENTITY', repr(identity()))
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_worker_reconciles_shared_metadata_without_reading_payloads(self):
        data = Path(self.tmp.name) / "data"
        job = data / "jobs/legacy"
        result = job / "data/results/example"
        (result / "summary_tables").mkdir(parents=True)
        (job / "job_summary.v1.json").write_text(json.dumps({"id": "legacy", "status": "success"}))
        (result / "summary_tables/genome_taxon_manifest.tsv").write_text(
            "input_key\tsource_accession\ttaxon_source\ttaxon_group\troute_status\n"
            "GCF_999999998.1\tGCF_999999998.1\tncbi\tbacteria\taccepted\n")
        with mock.patch.dict(os.environ, {"DATA_DIR": str(data), "CLUSTERWEAVE_ROOT": str(ROOT),
                                          "CLUSTERWEAVE_ACCESSION_CACHE_ROOT": str(self.root)}):
            self.assertEqual(self.store.publish(identity(), payload(), validate), "published")
            original = __import__("accession_cache").regular_bytes
            def metadata_only(path, *args, **kwargs):
                self.assertIn(path.name, {"manifest.json", ".catalog-id"})
                return original(path, *args, **kwargs)
            with mock.patch("accession_cache.regular_bytes", side_effect=metadata_only):
                refresh_catalog(catalog_jobs(data), lambda jid: data / "jobs" / jid)
            shared = Catalog(catalog_path(data_dir=data))
            self.assertEqual(shared.availability([identity()["accession"]], stage="preparation")["results"][0]["status"],
                             "candidate_available")
            self.assertEqual(shared.availability(["GCF_999999998.1"])["results"][0]["status"], "legacy_unverified")
            self.assertFalse((self.root / "catalog.sqlite").exists())
            self.assertNotIn(b"jobs/legacy", shared.path.read_bytes())


class JobCacheProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.result = self.base / "data/results/example"
        self.records = self.result / "reproducibility/accession_cache"
        self.records.mkdir(parents=True)
        self.job = {"id": "example", "status": "success", "result_root": "data/results/example"}

    def test_owner_projection_excludes_paths_keys_images_and_other_job_context(self):
        value = {"identity": identity(), "outcome": "miss", "reason": "/private/job/token",
                 "population": "rejected:/private/job", "worker_image": "private-image",
                 "producer_job": "other-job", "token": "private-token", "key": "f" * 64}
        (self.records / "one.json").write_text(json.dumps(value))
        report = owner_provenance(self.job, self.base)
        encoded = json.dumps(report)
        for private in ("/private", "private-image", "other-job", "private-token", "f" * 64):
            self.assertNotIn(private, encoded)
        self.assertEqual(report["records"][0]["population"], "rejected")
        self.assertEqual(report["scope"], "this_job")

    def test_owner_projection_rejects_links_and_oversized_records(self):
        outside = self.base / "secret.json"
        outside.write_text(json.dumps({"token": "private-token"}))
        link = self.records / "one.json"; link.symlink_to(outside)
        self.assertFalse(owner_provenance(self.job, self.base)["records_complete"])
        link.unlink(); link.write_bytes(b" " * 65537)
        self.assertFalse(owner_provenance(self.job, self.base)["records_complete"])

    def test_historical_inventory_has_no_job_identifiers_or_uploaded_inputs(self):
        path = self.result / "summary_tables/genome_taxon_manifest.tsv"
        path.parent.mkdir()
        columns = ["input_key", "source_accession", "taxon_source", "taxon_group", "route_status"]
        with path.open("w") as f:
            writer = csv.DictWriter(f, fieldnames=columns, delimiter="\t"); writer.writeheader()
            writer.writerow(dict(zip(columns, [identity()["accession"], identity()["accession"], "ncbi", "bacteria", "accepted"])))
            writer.writerow(dict(zip(columns, ["upload", identity()["accession"], "upload", "bacteria", "accepted"])))
        legacy, active, failures, complete = job_inventory([self.job], lambda _: self.base)
        self.assertEqual(legacy, {(identity()["accession"], "detection")})
        self.assertFalse(active); self.assertFalse(failures); self.assertTrue(complete)
        self.assertNotIn("example", repr(legacy))

    def test_rejected_identity_is_indexed_without_job_context(self):
        ident = identity()
        key = identity_key(ident)
        (self.records / "one.json").write_text(json.dumps({"identity": ident, "key": key,
            "outcome": "miss", "population": "rejected", "reason": "bundle_private_context"}))
        legacy, active, failures, complete = job_inventory([self.job], lambda _: self.base)
        self.assertTrue(complete)
        self.assertEqual(failures, {(key, ident["accession"], "preparation", "bundle_private_context")})
        self.assertFalse(active)
        root = self.base / "cache"; root.mkdir(mode=0o700)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATA_DIR", None)
            store = Store(root)
            store.reconcile_catalog(failures=failures)
            status = Catalog(catalog_path(root)).availability([ident["accession"]], stage="preparation")
        self.assertEqual(status["results"][0]["status"], "population_failed")
        self.assertNotIn("example", json.dumps(status))

    def test_old_rejection_without_identity_is_visible_only_via_public_route(self):
        path = self.result / "summary_tables/genome_taxon_manifest.tsv"
        path.parent.mkdir()
        path.write_text("genome_id\tinput_key\tsource_accession\ttaxon_source\ttaxon_group\troute_status\n"
                        "Public\tGCF_999999999.1\tGCF_999999999.1\tncbi\tbacteria\taccepted\n")
        record = self.records / "Public.detection.json"
        record.write_text(json.dumps({"identity": None, "key": None, "outcome": "miss",
                                      "population": "rejected", "reason": "bundle_private_context"}))
        report = owner_provenance(self.job, self.base)
        self.assertTrue(report["records_complete"])
        self.assertEqual(report["records"][0]["accession"], "GCF_999999999.1")
        self.assertEqual(report["records"][0]["population"], "rejected")
        self.assertFalse(report["records"][0]["identity_recorded"])
        self.assertNotIn("Public", json.dumps(report))
        path.write_text(path.read_text().replace("\tncbi\t", "\tupload\t"))
        self.assertEqual(owner_provenance(self.job, self.base)["records"], [])

    def test_budget_is_bounded_and_counts_only_authenticated_principals(self):
        budget = RequestBudget(limit=2, capacity=2)
        self.assertTrue(budget.take("one")); self.assertTrue(budget.take("one"))
        self.assertFalse(budget.take("one"))
        budget.take("two"); budget.take("three")
        self.assertEqual(len(budget.principals), 2)

    def test_job_overrides_cannot_redirect_shared_catalog_metadata(self):
        from canonical_pipeline import _parse_raw_env
        self.assertEqual(_parse_raw_env("DATA_DIR=/tmp/other\ndata_dir=/tmp/another\nLABEL=example"), {"LABEL": "example"})


if __name__ == "__main__":
    unittest.main()
