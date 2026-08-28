from __future__ import annotations

import importlib
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"


class ResultAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "jobs" / "attested"
        self.base.mkdir(parents=True)
        self.old_secret = os.environ.get("CLUSTERWEAVE_JOB_TOKEN_SECRET")
        os.environ["CLUSTERWEAVE_JOB_TOKEN_SECRET"] = "test-result-index-secret"
        if str(WEB_ROOT) not in sys.path:
            sys.path.insert(0, str(WEB_ROOT))
            self.inserted = True
        else:
            self.inserted = False
        sys.modules.pop("result_attestation", None)
        self.module = importlib.import_module("result_attestation")

    def tearDown(self) -> None:
        sys.modules.pop("result_attestation", None)
        if self.inserted:
            sys.path.remove(str(WEB_ROOT))
        if self.old_secret is None:
            os.environ.pop("CLUSTERWEAVE_JOB_TOKEN_SECRET", None)
        else:
            os.environ["CLUSTERWEAVE_JOB_TOKEN_SECRET"] = self.old_secret
        self.tmp.cleanup()

    def write_manifest(self, rel_path: str = "data/results/demo/figures/result.svg") -> Path:
        target = self.base / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<svg/>", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest = self.base / "downloads/public_results_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            f"path\tbytes\tsha256\n{rel_path}\t{target.stat().st_size}\t{digest}\n",
            encoding="utf-8",
        )
        return target

    def test_persisted_index_validates_without_rehashing_result_payloads(self) -> None:
        self.write_manifest()
        written = self.module.write_result_attestation(
            self.base, "attested", verify_hashes=True
        )
        with mock.patch.object(
            self.module, "_file_digest", side_effect=AssertionError("interactive rehash")
        ):
            loaded = self.module.read_result_attestation(self.base, "attested")
        self.assertEqual(written, loaded)
        self.assertEqual(1, len(loaded.files))

    def test_manifest_or_signature_tampering_invalidates_index(self) -> None:
        target = self.write_manifest()
        self.module.write_result_attestation(
            self.base, "attested", verify_hashes=True
        )
        index = self.base / self.module.RESULT_ATTESTATION_PATH
        index.write_bytes(index.read_bytes().replace(b'"created_at"', b'"created_xx"', 1))
        self.assertIsNone(self.module.read_result_attestation(self.base, "attested"))

        self.module.write_result_attestation(
            self.base, "attested", verify_hashes=True
        )
        target.write_text("<svg>changed</svg>", encoding="utf-8")
        manifest = self.base / "downloads/public_results_manifest.tsv"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertIsNone(self.module.read_result_attestation(self.base, "attested"))

    def test_signed_archive_identity_loads_without_rehash_and_stales_closed(self) -> None:
        self.write_manifest()
        archive = self.base / "downloads/demo_public_results.zip"
        archive.write_bytes(b"PK signed package fixture")
        written = self.module.write_result_attestation(
            self.base,
            "attested",
            verify_hashes=True,
            archive_path="downloads/demo_public_results.zip",
        )
        self.assertEqual(written.archive_path, "downloads/demo_public_results.zip")
        self.assertEqual(written.archive_size, archive.stat().st_size)
        self.assertRegex(written.archive_sha256, r"^[0-9a-f]{64}$")

        with mock.patch.object(
            self.module, "_file_digest", side_effect=AssertionError("interactive rehash")
        ):
            loaded = self.module.read_result_attestation(self.base, "attested")
        self.assertEqual(written, loaded)

        archive.write_bytes(b"PK changed package fixture")
        stale = self.module.read_result_attestation(self.base, "attested")
        self.assertIsNotNone(stale)
        assert stale is not None
        self.assertEqual(stale.files, written.files)
        self.assertEqual(stale.archive_path, "")
        self.assertEqual(stale.archive_identity, ())

    def test_traversal_manifest_is_rejected(self) -> None:
        manifest = self.base / "downloads/public_results_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            "path\tbytes\tsha256\n../job.json\t1\t" + "0" * 64 + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.module.write_result_attestation(
                self.base, "attested", verify_hashes=False
            )

    def test_production_scale_manifest_and_attestation_share_bounded_envelope(self) -> None:
        manifest = self.base / "downloads/public_results_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        digest = "0" * 64
        rows = [
            (
                "data/results/demo/antismash/"
                f"genome_{index:05d}/assets/"
                f"clusterweave_bounded_bundle_{index:05d}_supporting_asset.js"
            )
            for index in range(30_000)
        ]
        manifest.write_text(
            "path\tbytes\tsha256\n"
            + "".join(f"{path}\t0\t{digest}\n" for path in rows),
            encoding="utf-8",
        )
        self.assertGreater(manifest.stat().st_size, 4 * 1024 * 1024)

        with mock.patch.object(self.module, "_validate_files"):
            written = self.module.write_result_attestation(
                self.base, "attested", verify_hashes=False
            )
        index = self.base / self.module.RESULT_ATTESTATION_PATH
        self.assertGreater(index.stat().st_size, 4 * 1024 * 1024)
        self.assertLessEqual(
            index.stat().st_size, self.module.PUBLIC_RESULT_INDEX_MAX_BYTES
        )
        self.assertEqual(30_000, len(written.files))
        self.assertEqual(written, self.module.read_result_attestation(self.base, "attested"))

        policy = importlib.import_module("result_policy")
        self.assertEqual(
            policy.PUBLIC_RESULT_INDEX_MAX_BYTES,
            self.module.PUBLIC_RESULT_INDEX_MAX_BYTES,
        )
        app_source = (WEB_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("_PUBLIC_MANIFEST_MAX_BYTES =", app_source)
        self.assertGreaterEqual(app_source.count("PUBLIC_RESULT_INDEX_MAX_BYTES"), 7)

    def test_manifest_and_attestation_remain_fail_closed_beyond_bound(self) -> None:
        manifest = self.base / "downloads/public_results_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("wb") as handle:
            handle.truncate(self.module.PUBLIC_RESULT_INDEX_MAX_BYTES + 1)
        with self.assertRaisesRegex(OSError, "exceeds the bounded size"):
            self.module.write_result_attestation(
                self.base, "attested", verify_hashes=False
            )

        self.write_manifest()
        output_bound = manifest.stat().st_size + 32
        with (
            mock.patch.object(self.module, "PUBLIC_RESULT_INDEX_MAX_BYTES", output_bound),
            self.assertRaisesRegex(OSError, "attestation exceeds the bounded size"),
        ):
            self.module.write_result_attestation(
                self.base, "attested", verify_hashes=True
            )
        self.assertFalse((self.base / self.module.RESULT_ATTESTATION_PATH).exists())


if __name__ == "__main__":
    unittest.main()
