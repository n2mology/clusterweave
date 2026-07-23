from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from taxon_routing import (  # noqa: E402
    MAX_ASSIGNMENT_BYTES,
    TaxonRoutingError,
    build_taxon_routes,
    merge_assignments,
    normalize_analysis_scope,
    parse_assignment_json,
    parse_assignment_tsv,
    parse_genbank_taxonomy,
    summarize_taxon_routes,
)


class TaxonRoutingTests(unittest.TestCase):
    def test_scope_normalization_preserves_historical_fungal_default(self) -> None:
        self.assertEqual(normalize_analysis_scope(None), "fungi")
        self.assertEqual(normalize_analysis_scope(""), "fungi")
        self.assertEqual(normalize_analysis_scope("  "), "fungi")
        self.assertEqual(normalize_analysis_scope("FUNGI"), "fungi")
        self.assertEqual(normalize_analysis_scope("Bacteria"), "bacteria")
        self.assertEqual(normalize_analysis_scope("both"), "both")
        with self.assertRaisesRegex(TaxonRoutingError, "fungi, bacteria, both"):
            normalize_analysis_scope("archaea")

    def test_assignment_json_accepts_bounded_map_or_rows(self) -> None:
        self.assertEqual(
            parse_assignment_json('{"Fungus_A":"fungi","Bacterium_B":"bacteria"}'),
            {"Bacterium_B": "bacteria", "Fungus_A": "fungi"},
        )
        self.assertEqual(
            parse_assignment_json(
                [
                    {"input_key": "Fungus_A", "taxon_group": "fungi"},
                    {"input_key": "Bacterium_B", "taxon_group": "bacteria"},
                ]
            ),
            {"Bacterium_B": "bacteria", "Fungus_A": "fungi"},
        )
        with self.assertRaisesRegex(TaxonRoutingError, "routing metadata limit"):
            parse_assignment_json("x" * (MAX_ASSIGNMENT_BYTES + 1))
        with self.assertRaisesRegex(TaxonRoutingError, "fungi or bacteria"):
            parse_assignment_json('{"demo":"archaea"}')
        with self.assertRaisesRegex(TaxonRoutingError, "duplicate JSON key"):
            parse_assignment_json('{"demo":"fungi","demo":"bacteria"}')

    def test_exact_assignment_tsv_and_merge_reject_contradictions(self) -> None:
        parsed = parse_assignment_tsv(
            b"input_key\ttaxon_group\nFungus_A\tfungi\nBacterium_B\tbacteria\n"
        )
        self.assertEqual(
            parsed, {"Bacterium_B": "bacteria", "Fungus_A": "fungi"}
        )
        with self.assertRaisesRegex(TaxonRoutingError, "start with exactly"):
            parse_assignment_tsv(b"genome\ttaxon\nA\tfungi\n")
        with self.assertRaisesRegex(TaxonRoutingError, "Contradictory"):
            parse_assignment_tsv(
                b"input_key\ttaxon_group\nDemo\tfungi\ndemo\tbacteria\n"
            )
        with self.assertRaisesRegex(TaxonRoutingError, "Contradictory"):
            merge_assignments({"Demo": "fungi"}, {"demo": "bacteria"})

    def test_genbank_lineage_is_authoritative_without_name_guessing(self) -> None:
        fungal = parse_genbank_taxonomy(
            """LOCUS       fungal
  ORGANISM  Aspergillus demo
            Eukaryota; Fungi; Dikarya; Ascomycota.
FEATURES             Location/Qualifiers
     source          1..10
                     /organism="Aspergillus demo"
                     /db_xref="taxon:12345"
ORIGIN
//
"""
        )
        bacterial = parse_genbank_taxonomy(
            """LOCUS       bacterial
  ORGANISM  Escherichia demo
            Bacteria; Pseudomonadota; Gammaproteobacteria.
FEATURES             Location/Qualifiers
     source          1..10
                     /organism="Escherichia demo"
                     /db_xref="taxon:511145"
ORIGIN
//
"""
        )
        unsupported = parse_genbank_taxonomy(
            """LOCUS       animal
  ORGANISM  Demo animal
            Eukaryota; Metazoa; Chordata.
FEATURES             Location/Qualifiers
ORIGIN
//
"""
        )
        ambiguous = parse_genbank_taxonomy(
            """LOCUS       mystery
FEATURES             Location/Qualifiers
     source          1..10
                     /organism="Bacteria-looking filename only"
ORIGIN
//
"""
        )
        self.assertEqual(fungal["taxon_group"], "fungi")  # type: ignore[index]
        self.assertEqual(fungal["taxid"], 12345)  # type: ignore[index]
        self.assertEqual(bacterial["taxon_group"], "bacteria")  # type: ignore[index]
        self.assertEqual(unsupported["taxon_group"], "unsupported")  # type: ignore[index]
        self.assertIsNone(ambiguous)
        with self.assertRaisesRegex(TaxonRoutingError, "conflicting"):
            parse_genbank_taxonomy(
                """LOCUS       mixed
  ORGANISM  mixed source
            Eukaryota; Fungi; Metazoa.
FEATURES             Location/Qualifiers
ORIGIN
//
"""
            )

    def test_single_domain_declaration_and_both_assignment(self) -> None:
        logical_inputs = [
            {"input_key": "Genome_A", "has_annotated_genbank": False}
        ]
        fungal = build_taxon_routes("", logical_inputs, [])
        self.assertEqual(len(fungal), 1)
        self.assertEqual(fungal[0]["taxon_group"], "fungi")
        self.assertEqual(fungal[0]["taxon_source"], "user_declaration")
        self.assertEqual(fungal[0]["prediction_method"], "funannotate")

        bacterial = build_taxon_routes("bacteria", logical_inputs, [])
        self.assertEqual(bacterial[0]["taxon_group"], "bacteria")
        self.assertEqual(bacterial[0]["prediction_method"], "prodigal")
        self.assertEqual(bacterial[0]["detector_profile"], "antismash")

        with self.assertRaisesRegex(TaxonRoutingError, "Both scope requires"):
            build_taxon_routes("both", logical_inputs, [])
        assigned = build_taxon_routes(
            "both", logical_inputs, [], {"Genome_A": "bacteria"}
        )
        self.assertEqual(assigned[0]["taxon_group"], "bacteria")
        self.assertEqual(
            assigned[0]["route_reason"], "explicit_both_mode_assignment"
        )

    def test_authoritative_genbank_and_ncbi_cannot_be_spoofed(self) -> None:
        logical_inputs = [
            {
                "input_key": "Genome_A",
                "has_annotated_genbank": True,
                "authoritative_taxonomy": {
                    "taxon_group": "fungi",
                    "taxid": 12345,
                    "organism_name": "Demo fungus",
                },
            }
        ]
        routes = build_taxon_routes("both", logical_inputs, [])
        self.assertEqual(routes[0]["taxon_group"], "fungi")
        self.assertEqual(routes[0]["taxon_source"], "genbank_source")
        self.assertEqual(routes[0]["prediction_method"], "existing_cds")

        with self.assertRaisesRegex(TaxonRoutingError, "authoritative GenBank"):
            build_taxon_routes(
                "both", logical_inputs, [], {"Genome_A": "bacteria"}
            )
        with self.assertRaisesRegex(TaxonRoutingError, "unknown input_key"):
            build_taxon_routes(
                "both", logical_inputs, [], {"Missing": "fungi"}
            )

        ncbi = [
            {
                "accession": "GCF_000005845.2",
                "genome_id": "Escherichia_coli_K-12",
                "taxon_group": "bacteria",
                "tax_id": 511145,
                "organism_name": "Escherichia coli",
            }
        ]
        accepted_ncbi = build_taxon_routes("both", [], ncbi)
        self.assertEqual(accepted_ncbi[0]["input_key"], "GCF_000005845.2")
        self.assertEqual(accepted_ncbi[0]["source_accession"], "GCF_000005845.2")
        self.assertEqual(
            accepted_ncbi[0]["genome_id"], "Escherichia_coli_K-12"
        )
        with self.assertRaisesRegex(TaxonRoutingError, "cannot override"):
            build_taxon_routes(
                "both", [], ncbi, {"GCF_000005845.2": "fungi"}
            )
        with self.assertRaisesRegex(TaxonRoutingError, "outside selected fungi"):
            build_taxon_routes("fungi", [], ncbi)

        duplicate_ids = [
            {
                "accession": f"GCA_00000000{index}.1",
                "genome_id": "Aspergillus_nidulans_FGSC_A4",
                "taxon_group": "fungi",
                "tax_id": 227321,
                "organism_name": "Aspergillus nidulans FGSC A4",
            }
            for index in (1, 2)
        ]
        disambiguated = build_taxon_routes("fungi", [], duplicate_ids)
        self.assertEqual(
            [route["genome_id"] for route in disambiguated],
            [
                "Aspergillus_nidulans_FGSC_A4",
                "Aspergillus_nidulans_FGSC_A4_GCA_000000002.1",
            ],
        )

        with self.assertRaisesRegex(TaxonRoutingError, "distinct upload IDs"):
            build_taxon_routes(
                "fungi",
                [{"input_key": "Aspergillus_nidulans_FGSC_A4"}],
                [duplicate_ids[0]],
            )

    def test_route_summaries_are_safe_counts(self) -> None:
        routes = build_taxon_routes(
            "both",
            [{"input_key": "Fungus_A", "has_annotated_genbank": True}],
            [
                {
                    "accession": "GCF_000005845.2",
                    "taxon_group": "bacteria",
                    "tax_id": 511145,
                    "organism_name": "Escherichia coli",
                }
            ],
            {"Fungus_A": "fungi"},
        )
        taxon_counts, applicability = summarize_taxon_routes(routes)
        self.assertEqual(taxon_counts, {"fungi": 1, "bacteria": 1, "total": 2})
        self.assertEqual(applicability["antismash"], 2)
        self.assertEqual(applicability["funbgcex"], 1)
        self.assertEqual(applicability["funbgcex_not_applicable_taxon"], 1)
        self.assertEqual(applicability["prodigal"], 1)

    def test_later_ncbi_id_collision_gets_stable_accession_suffix(self) -> None:
        records = [
            {
                "accession": "GCA_000002.1",
                "taxon_group": "fungi",
                "tax_id": 4751,
                "organism_name": "Fixtureus example",
                "genome_id": "Fixtureus_example",
            },
            {
                "accession": "GCA_000001.1",
                "taxon_group": "fungi",
                "tax_id": 4751,
                "organism_name": "Fixtureus example",
                "genome_id": "Fixtureus_example",
            },
        ]
        routes = build_taxon_routes("fungi", [], records)
        self.assertEqual(
            [(row["input_key"], row["genome_id"]) for row in routes],
            [
                ("GCA_000001.1", "Fixtureus_example"),
                ("GCA_000002.1", "Fixtureus_example_GCA_000002.1"),
            ],
        )
        self.assertEqual(
            routes,
            build_taxon_routes("fungi", [], list(reversed(records))),
        )


if __name__ == "__main__":
    unittest.main()
