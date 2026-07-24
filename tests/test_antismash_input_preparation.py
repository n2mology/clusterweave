from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

try:
    from Bio import SeqIO
    from Bio.Seq import Seq
    from Bio.SeqFeature import AfterPosition, CompoundLocation, FeatureLocation, SeqFeature
    from Bio.SeqRecord import SeqRecord
except ModuleNotFoundError as exc:
    BIO_AVAILABLE = False
else:
    BIO_AVAILABLE = True


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "prepare_antismash_input.py"
MODULE = None
if BIO_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("prepare_antismash_input", MODULE_PATH)
    assert SPEC and SPEC.loader
    MODULE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(BIO_AVAILABLE, "Biopython is required for antiSMASH input tests")
class AntiSmashInputPreparationTests(unittest.TestCase):
    def test_sanitize_drops_only_invalid_non_cds_compound_and_duplicate_cds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.gbk"
            sanitized = root / "sanitized.gbk"
            record = SeqRecord(Seq("A" * 2000), id="NC_TEST.1", name="NC_TEST.1")
            record.annotations["molecule_type"] = "DNA"
            malformed_mrna = SeqFeature(
                CompoundLocation(
                    [FeatureLocation(100, 300, strand=-1), FeatureLocation(200, 400, strand=-1)]
                ),
                type="mRNA",
                qualifiers={"gene": ["example"]},
            )
            valid_cds = SeqFeature(
                FeatureLocation(500, 800, strand=1),
                type="CDS",
                qualifiers={"locus_tag": ["TEST_1"], "translation": ["M" * 100]},
            )
            duplicate_cds = SeqFeature(
                FeatureLocation(500, 800, strand=1),
                type="CDS",
                qualifiers={"locus_tag": ["TEST_1_DUP"]},
            )
            record.features = [malformed_mrna, valid_cds, duplicate_cds]
            SeqIO.write([record], source, "genbank")

            summary = MODULE.sanitize(source, sanitized, "fungus")
            result = SeqIO.read(sanitized, "genbank")

            self.assertEqual(summary["dropped_invalid_non_cds_compound_features"], 1)
            self.assertEqual(summary["dropped_duplicate_cds"], 1)
            self.assertEqual([feature.type for feature in result.features], ["CDS"])
            self.assertEqual(result.features[0].qualifiers["locus_tag"], ["TEST_1"])

    def test_sanitize_removes_only_unsafe_compound_codon_start_from_antismash_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.gbk"
            sanitized = root / "sanitized.gbk"
            record = SeqRecord(Seq("A" * 2000), id="CM_TEST.1", name="CM_TEST.1")
            record.annotations["molecule_type"] = "DNA"
            location = CompoundLocation(
                [
                    FeatureLocation(
                        AfterPosition(1800),
                        AfterPosition(1801),
                        strand=-1,
                    ),
                    FeatureLocation(1500, 1750, strand=-1),
                ]
            )
            safe_location = CompoundLocation(
                [
                    FeatureLocation(1200, 1210, strand=-1),
                    FeatureLocation(1000, 1150, strand=-1),
                ]
            )
            record.features = [
                SeqFeature(
                    location,
                    type="CDS",
                    qualifiers={
                        "locus_tag": ["TEST_PARTIAL"],
                        "codon_start": ["3"],
                        "translation": ["M" + "A" * 70],
                    },
                ),
                SeqFeature(
                    safe_location,
                    type="CDS",
                    qualifiers={
                        "locus_tag": ["TEST_SAFE"],
                        "codon_start": ["3"],
                        "translation": ["M" + "G" * 40],
                    },
                ),
            ]
            SeqIO.write([record], source, "genbank")
            original = source.read_bytes()

            summary = MODULE.sanitize(source, sanitized, "fungus")
            result = SeqIO.read(sanitized, "genbank")
            cds = next(
                feature
                for feature in result.features
                if feature.qualifiers.get("locus_tag") == ["TEST_PARTIAL"]
            )
            safe_cds = next(
                feature
                for feature in result.features
                if feature.qualifiers.get("locus_tag") == ["TEST_SAFE"]
            )

            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(summary["removed_unsafe_codon_start_qualifiers"], 1)
            self.assertEqual(summary["dropped_duplicate_cds"], 0)
            self.assertEqual(
                summary["dropped_invalid_non_cds_compound_features"],
                0,
            )
            self.assertNotIn("codon_start", cds.qualifiers)
            self.assertEqual(cds.qualifiers["locus_tag"], ["TEST_PARTIAL"])
            self.assertIn("translation", cds.qualifiers)
            self.assertIsInstance(cds.location, CompoundLocation)
            self.assertEqual(len(cds.location.parts[0]), 1)
            self.assertEqual(safe_cds.qualifiers["codon_start"], ["3"])

    def test_split_records_writes_exactly_one_requested_record_per_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.gbk"
            records = []
            for record_id in ("recordA", "recordB", "recordC"):
                record = SeqRecord(Seq("A" * 1200), id=record_id, name=record_id)
                record.annotations["molecule_type"] = "DNA"
                records.append(record)
            SeqIO.write(records, source, "genbank")
            outputs = [root / "shards" / "a.gbk", root / "shards" / "b.gbk"]
            manifest = root / "manifest.tsv"
            manifest.write_text(
                f"recordA\t{outputs[0]}\nrecordB\t{outputs[1]}\n",
                encoding="utf-8",
            )

            self.assertEqual(MODULE.split_records(source, manifest), 2)
            self.assertEqual(
                [[record.id for record in SeqIO.parse(path, "genbank")] for path in outputs],
                [["recordA"], ["recordB"]],
            )


if __name__ == "__main__":
    unittest.main()
