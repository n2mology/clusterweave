from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from genbank_readiness import inspect_genbank_translation_stream


def record(features: str, *, terminated: bool = True) -> bytes:
    ending = "//\n" if terminated else ""
    return (
        "LOCUS       demo 90 bp DNA\n"
        "FEATURES             Location/Qualifiers\n"
        "     source          1..90\n"
        f"{features}"
        "ORIGIN\n"
        "        1 atgaaaactatgaaaactatgaaaact\n"
        f"{ending}"
    ).encode()


class GenbankReadinessTests(unittest.TestCase):
    def inspect(self, payload: bytes):
        return inspect_genbank_translation_stream(io.BytesIO(payload))

    def test_all_non_pseudogene_cds_require_nonempty_translation(self) -> None:
        complete = self.inspect(
            record(
                "     CDS             1..9\n"
                '                     /translation="MKT"\n'
                "     CDS             10..18\n"
                '                     /translation="MNN"\n'
            )
        )
        self.assertTrue(complete.usable_translated_cds)
        self.assertEqual(complete.translated_cds, 2)
        self.assertEqual(complete.untranslated_cds, 0)

        partial = self.inspect(
            record(
                "     CDS             1..9\n"
                '                     /translation="MKT"\n'
                "     CDS             10..18\n"
                '                     /product="missing translation"\n'
            )
        )
        self.assertFalse(partial.usable_translated_cds)
        self.assertEqual(partial.translated_cds, 1)
        self.assertEqual(partial.untranslated_cds, 1)

    def test_empty_marker_is_not_a_translation_and_multiline_value_is(self) -> None:
        empty = self.inspect(
            record(
                "     CDS             1..9\n"
                '                     /translation=""\n'
            )
        )
        self.assertFalse(empty.usable_translated_cds)
        self.assertEqual(empty.translated_cds, 0)

        multiline = self.inspect(
            record(
                "     CDS             1..18\n"
                '                     /translation="MKT\n'
                '                     AAV"\n'
            )
        )
        self.assertTrue(multiline.usable_translated_cds)
        self.assertEqual(multiline.translated_cds, 1)

    def test_pseudogene_without_translation_does_not_force_reannotation(self) -> None:
        readiness = self.inspect(
            record(
                "     CDS             1..9\n"
                '                     /translation="MKT"\n'
                "     CDS             10..18\n"
                "                     /pseudo\n"
            )
        )
        self.assertTrue(readiness.usable_translated_cds)
        self.assertEqual(readiness.pseudogene_cds, 1)
        self.assertEqual(readiness.untranslated_cds, 0)

    def test_truncated_record_is_not_reusable(self) -> None:
        readiness = self.inspect(
            record(
                "     CDS             1..9\n"
                '                     /translation="MKT"\n',
                terminated=False,
            )
        )
        self.assertFalse(readiness.structurally_complete)
        self.assertFalse(readiness.usable_translated_cds)

    def test_unclosed_translation_does_not_consume_origin_or_sequence(self) -> None:
        readiness = self.inspect(
            record(
                "     CDS             1..9\n"
                '                     /translation="MKT\n'
            )
        )

        self.assertTrue(readiness.structurally_complete)
        self.assertFalse(readiness.usable_translated_cds)
        self.assertEqual(readiness.translated_cds, 0)
        self.assertEqual(readiness.untranslated_cds, 1)

    def test_each_record_must_be_structurally_complete(self) -> None:
        complete_first = record(
            "     CDS             1..9\n"
            '                     /translation="MKT"\n'
        )
        malformed_empty_second = b"LOCUS       empty 0 bp DNA\n//\n"

        readiness = self.inspect(complete_first + malformed_empty_second)

        self.assertEqual(readiness.record_count, 2)
        self.assertFalse(readiness.records_structurally_complete)
        self.assertFalse(readiness.structurally_complete)
        self.assertFalse(readiness.usable_translated_cds)


if __name__ == "__main__":
    unittest.main()
