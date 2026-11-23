from __future__ import annotations

import copy
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from canonical_pipeline import (  # noqa: E402
    Job,
    ProjectLayout,
    TAXON_ROUTE_FIELDS,
    _normalize_taxon_routes,
    _route_summaries,
    _write_taxon_manifests,
    _resolve_target_genome_alias,
    _stage_uploaded_inputs,
)
from taxon_routing import (  # noqa: E402
    build_taxon_routes,
    parse_genbank_taxonomy_stream,
    summarize_taxon_routes,
)


def route(input_key: str, genome_id: str, taxon_group: str) -> dict[str, object]:
    return {
        "input_key": input_key,
        "genome_id": genome_id,
        "taxon_group": taxon_group,
        "taxon_source": "user_declaration",
        "taxid": "",
        "organism_name": "",
        "source_accession": "",
        "prediction_method": "prodigal" if taxon_group == "bacteria" else "funannotate",
        "detector_profile": "antismash" if taxon_group == "bacteria" else "antismash+funbgcex",
        "input_path_key": input_key,
        "route_status": "accepted",
        "route_reason": "test_route",
    }


READY_GENBANK = """LOCUS       fixture                    9 bp    DNA
FEATURES             Location/Qualifiers
     CDS             1..9
                     /translation="MKT"
ORIGIN
        1 atgaaaact
//
"""


def write_genome_fixture(path: Path, *, translated: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".gb", ".gbk", ".gbff"}:
        content = READY_GENBANK if translated else READY_GENBANK.replace('"MKT"', '""')
    else:
        # Pair comparison is a separate policy; these inputs intentionally differ.
        content = ">different_record\nCCCCCC\n"
    path.write_text(content, encoding="utf-8")
    return path


class TaxonPipelineLayoutTests(unittest.TestCase):
    def test_frozen_defaults_explicit_profiles_statuses_and_manifest(self) -> None:
        raw_routes = [
            {
                "input_key": "legacy_f",
                "taxon_group": "FUNGI"
            },
            {
                "input_key": "legacy_b",
                "taxon_group": "bacteria",
                "prediction_method": "",
                "detector_profile": None
            },
            {
                "input_key": "existing",
                "taxon_group": "fungi",
                "prediction_method": "existing_cds",
                "detector_profile": "custom-profile"
            },
            {
                "input_key": "explicit",
                "taxon_group": "bacteria",
                "prediction_method": "HistoricalMethod",
                "detector_profile": "historical-detector"
            },
            {
                "input_key": "inactive_failed",
                "taxon_group": "bacteria",
                "prediction_method": "funannotate",
                "route_status": "failed"
            },
            {
                "input_key": "inactive_INVALID",
                "taxon_group": "fungi",
                "prediction_method": "funannotate",
                "route_status": "INVALID"
            },
            {
                "input_key": "inactive_rejected",
                "taxon_group": "bacteria",
                "prediction_method": "funannotate",
                "route_status": "rejected"
            },
            {
                "input_key": "inactive_unresolved",
                "taxon_group": "fungi",
                "prediction_method": "funannotate",
                "route_status": "unresolved"
            },
            {
                "input_key": "inactive_unsupported",
                "taxon_group": "bacteria",
                "prediction_method": "funannotate",
                "route_status": "unsupported"
            },
            {
                "input_key": "tolerated",
                "taxon_group": "fungi",
                "route_status": "unknown"
            }
        ]
        expected = [
            {
                "input_key": "legacy_f",
                "genome_id": "legacy_f",
                "taxon_group": "fungi",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "funannotate",
                "detector_profile": "antismash+funbgcex",
                "input_path_key": "",
                "route_status": "routed",
                "route_reason": ""
            },
            {
                "input_key": "legacy_b",
                "genome_id": "legacy_b",
                "taxon_group": "bacteria",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "prodigal",
                "detector_profile": "antismash",
                "input_path_key": "",
                "route_status": "routed",
                "route_reason": ""
            },
            {
                "input_key": "existing",
                "genome_id": "existing",
                "taxon_group": "fungi",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "existing_cds",
                "detector_profile": "custom-profile",
                "input_path_key": "",
                "route_status": "routed",
                "route_reason": ""
            },
            {
                "input_key": "explicit",
                "genome_id": "explicit",
                "taxon_group": "bacteria",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "HistoricalMethod",
                "detector_profile": "historical-detector",
                "input_path_key": "",
                "route_status": "routed",
                "route_reason": ""
            },
            {
                "input_key": "inactive_failed",
                "genome_id": "inactive_failed",
                "taxon_group": "bacteria",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "funannotate",
                "detector_profile": "antismash",
                "input_path_key": "",
                "route_status": "failed",
                "route_reason": ""
            },
            {
                "input_key": "inactive_INVALID",
                "genome_id": "inactive_INVALID",
                "taxon_group": "fungi",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "funannotate",
                "detector_profile": "antismash+funbgcex",
                "input_path_key": "",
                "route_status": "invalid",
                "route_reason": ""
            },
            {
                "input_key": "inactive_rejected",
                "genome_id": "inactive_rejected",
                "taxon_group": "bacteria",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "funannotate",
                "detector_profile": "antismash",
                "input_path_key": "",
                "route_status": "rejected",
                "route_reason": ""
            },
            {
                "input_key": "inactive_unresolved",
                "genome_id": "inactive_unresolved",
                "taxon_group": "fungi",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "funannotate",
                "detector_profile": "antismash+funbgcex",
                "input_path_key": "",
                "route_status": "unresolved",
                "route_reason": ""
            },
            {
                "input_key": "inactive_unsupported",
                "genome_id": "inactive_unsupported",
                "taxon_group": "bacteria",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "funannotate",
                "detector_profile": "antismash",
                "input_path_key": "",
                "route_status": "unsupported",
                "route_reason": ""
            },
            {
                "input_key": "tolerated",
                "genome_id": "tolerated",
                "taxon_group": "fungi",
                "taxon_source": "legacy_default",
                "taxid": "",
                "organism_name": "",
                "source_accession": "",
                "prediction_method": "funannotate",
                "detector_profile": "antismash+funbgcex",
                "input_path_key": "",
                "route_status": "unknown",
                "route_reason": ""
            }
        ]
        actual = _normalize_taxon_routes({"taxon_routes": raw_routes})
        self.assertEqual(actual, expected)
        self.assertEqual([list(row) for row in actual], [list(row) for row in expected])
        self.assertEqual(
            _route_summaries(actual),
            (
                {
                    "fungi": 3,
                    "bacteria": 2,
                    "total": 5
                },
                {
                    "funannotate": 2,
                    "prodigal": 1,
                    "antismash": 5,
                    "funbgcex": 3,
                    "funbgcex_not_applicable_taxon": 2,
                    "bigscape": 5,
                    "taxon_tree_figure": 5
                },
            ),
        )
        self.assertEqual(
            summarize_taxon_routes(actual),
            (
                {
                    "fungi": 5,
                    "bacteria": 5,
                    "total": 10
                },
                {
                    "funannotate": 7,
                    "prodigal": 1,
                    "antismash": 10,
                    "funbgcex": 5,
                    "funbgcex_not_applicable_taxon": 5,
                    "bigscape": 10,
                    "taxon_tree_figure": 10
                },
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            layout = self.make_layout(Path(tmp))
            _write_taxon_manifests(layout, actual)
            self.assertEqual(
                (layout.results_root / "summary_tables/genome_taxon_manifest.tsv").read_bytes(),
                (
                    b'input_key\tgenome_id\ttaxon_group\ttaxon_source\ttaxid\torganism_name\tsource_accession\tprediction_method\tdetector_profile\tinput_path_key\troute_status\troute_reason\r\n'
                    b'legacy_f\tlegacy_f\tfungi\tlegacy_default\t\t\t\tfunannotate\tantismash+funbgcex\t\trouted\t\r\n'
                    b'legacy_b\tlegacy_b\tbacteria\tlegacy_default\t\t\t\tprodigal\tantismash\t\trouted\t\r\n'
                    b'existing\texisting\tfungi\tlegacy_default\t\t\t\texisting_cds\tcustom-profile\t\trouted\t\r\n'
                    b'explicit\texplicit\tbacteria\tlegacy_default\t\t\t\tHistoricalMethod\thistorical-detector\t\trouted\t\r\n'
                    b'inactive_failed\tinactive_failed\tbacteria\tlegacy_default\t\t\t\tfunannotate\tantismash\t\tfailed\t\r\n'
                    b'inactive_INVALID\tinactive_INVALID\tfungi\tlegacy_default\t\t\t\tfunannotate\tantismash+funbgcex\t\tinvalid\t\r\n'
                    b'inactive_rejected\tinactive_rejected\tbacteria\tlegacy_default\t\t\t\tfunannotate\tantismash\t\trejected\t\r\n'
                    b'inactive_unresolved\tinactive_unresolved\tfungi\tlegacy_default\t\t\t\tfunannotate\tantismash+funbgcex\t\tunresolved\t\r\n'
                    b'inactive_unsupported\tinactive_unsupported\tbacteria\tlegacy_default\t\t\t\tfunannotate\tantismash\t\tunsupported\t\r\n'
                    b'tolerated\ttolerated\tfungi\tlegacy_default\t\t\t\tfunannotate\tantismash+funbgcex\t\tunknown\t\r\n'
                ),
            )

    def make_layout(self, root: Path) -> ProjectLayout:
        data = root / "data"
        return ProjectLayout(
            project_name="demo",
            repo_root=REPO_ROOT,
            data_root=data,
            fungi_genome_root=data / "genomes" / "fungi" / "demo",
            bacteria_genome_root=data / "genomes" / "bacteria" / "demo",
            results_root=data / "results" / "demo",
            software_root=root / "software",
            work_root=root / "work",
            downloads_root=root / "downloads",
        )

    def test_mixed_uploads_stage_to_explicit_roots_from_immutable_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload_root = root / "uploads"
            upload_root.mkdir()
            fungus = upload_root / "fungus_sample.fna"
            bacterium = upload_root / "bacterium_sample.fna"
            fungus.write_text(">fungal_contig\nACGT\n", encoding="utf-8")
            bacterium.write_text(">bacterial_contig\nACGT\n", encoding="utf-8")
            settings: dict[str, object] = {
                "analysis_scope": "both",
                "taxon_routes": [
                    route("fungus_sample", "Fungus_A", "fungi"),
                    route("bacterium_sample", "Bacterium_A", "bacteria"),
                ],
            }
            layout = self.make_layout(root)

            _stage_uploaded_inputs(
                [fungus, bacterium], layout, settings, Job(id="job", name="demo")
            )

            self.assertTrue((layout.fungi_genome_root / "Fungus_A.fna").is_file())
            self.assertTrue((layout.bacteria_genome_root / "Bacterium_A.fna").is_file())
            self.assertEqual(layout.genome_root, layout.fungi_genome_root)
            self.assertEqual(
                settings["taxon_counts"],
                {"fungi": 1, "bacteria": 1, "total": 2},
            )
            self.assertEqual(settings["applicability_counts"]["funbgcex"], 1)
            self.assertEqual(
                settings["applicability_counts"]["funbgcex_not_applicable_taxon"],
                1,
            )

            manifest_path = layout.results_root / "summary_tables" / "genome_taxon_manifest.tsv"
            with manifest_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(
                {(row["genome_id"], row["taxon_group"]) for row in rows},
                {("Fungus_A", "fungi"), ("Bacterium_A", "bacteria")},
            )
            manifest_text = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn(str(root), manifest_text)
            self.assertNotIn("/tmp/", manifest_text)
            self.assertIn("genomes/fungi/demo/Fungus_A", manifest_text)
            self.assertIn("genomes/bacteria/demo/Bacterium_A", manifest_text)
            routing_logs = sorted(
                (layout.results_root / "logs").glob("taxon_routing.*.log")
            )
            self.assertEqual(len(routing_logs), 1)
            routing_text = routing_logs[0].read_text(encoding="utf-8")
            self.assertEqual(routing_text.count("TAXON_ROUTE "), 2)
            self.assertIn(
                "TAXON_SUMMARY scope=both fungi=1 bacteria=1 unresolved=0",
                routing_text,
            )
            self.assertNotIn(str(root), routing_text)

    def test_fungal_only_without_ecology_keeps_neutral_metadata_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload = root / "fungus.fna"
            upload.write_text(">contig\nACGT\n", encoding="utf-8")
            settings: dict[str, object] = {
                "analysis_scope": "fungi",
                "run_ecology_analysis": False,
                "taxon_routes": [route("fungus", "Fungus_A", "fungi")],
            }
            layout = self.make_layout(root)

            _stage_uploaded_inputs([upload], layout, settings, Job(id="job", name="demo"))

            tables = layout.results_root / "summary_tables"
            self.assertTrue((tables / "fungal_id_legend.tsv").is_file())
            self.assertFalse((tables / "bacteria_id_legend.tsv").exists())
            self.assertFalse((tables / "ecofun_metadata_normalized.tsv").exists())
            self.assertFalse((tables / "ecofun_metadata_template.tsv").exists())
            self.assertEqual(layout.metadata_file, layout.work_root / "routing" / "ecofun_metadata_normalized.tsv")
            self.assertTrue(layout.metadata_file.is_file())

    def test_bacterial_only_without_ecology_omits_fungal_and_ecobac_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload = root / "bacterium.fna"
            upload.write_text(">contig\nACGT\n", encoding="utf-8")
            settings: dict[str, object] = {
                "analysis_scope": "bacteria",
                "run_ecology_analysis": False,
                "taxon_routes": [route("bacterium", "Bacterium_A", "bacteria")],
            }
            layout = self.make_layout(root)

            _stage_uploaded_inputs([upload], layout, settings, Job(id="job", name="demo"))

            tables = layout.results_root / "summary_tables"
            self.assertTrue((tables / "bacteria_id_legend.tsv").is_file())
            self.assertFalse((tables / "fungal_id_legend.tsv").exists())
            self.assertFalse((tables / "ecobac_metadata_normalized.tsv").exists())
            self.assertEqual(layout.metadata_file, layout.work_root / "routing" / "ecobac_metadata_normalized.tsv")
            self.assertTrue(layout.metadata_file.is_file())

    def test_selected_ecology_publishes_only_the_applicable_metadata_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload = root / "fungus.fna"
            upload.write_text(">contig\nACGT\n", encoding="utf-8")
            settings: dict[str, object] = {
                "analysis_scope": "fungi",
                "run_ecology_analysis": True,
                "taxon_routes": [route("fungus", "Fungus_A", "fungi")],
            }
            layout = self.make_layout(root)

            _stage_uploaded_inputs([upload], layout, settings, Job(id="job", name="demo"))

            tables = layout.results_root / "summary_tables"
            self.assertEqual(layout.metadata_file, tables / "ecofun_metadata_normalized.tsv")
            self.assertTrue(layout.metadata_file.is_file())
            self.assertFalse((tables / "ecobac_metadata_normalized.tsv").exists())
            self.assertFalse((tables / "bacteria_id_legend.tsv").exists())

    def test_fasta_and_genbank_with_same_stem_share_one_bacterial_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload_root = root / "uploads"
            upload_root.mkdir()
            fasta = upload_root / "paired.fna"
            genbank = upload_root / "paired.gbk"
            fasta.write_text(">contig\nACGT\n", encoding="utf-8")
            genbank.write_text("LOCUS       contig 4 bp DNA\n//\n", encoding="utf-8")
            settings: dict[str, object] = {
                "analysis_scope": "bacteria",
                "taxon_routes": [route("paired", "Paired_Bacterium", "bacteria")],
            }
            layout = self.make_layout(root)

            _stage_uploaded_inputs(
                [fasta, genbank], layout, settings, Job(id="job", name="demo")
            )

            self.assertTrue(
                (layout.bacteria_genome_root / "Paired_Bacterium.fna").is_file()
            )
            self.assertTrue(
                (layout.bacteria_genome_root / "Paired_Bacterium.gbk").is_file()
            )
            self.assertEqual(len(settings["taxon_routes"]), 1)

    def test_direct_same_kind_duplicates_reject_before_staging_in_either_order(self) -> None:
        cases = (
            ("pair.fa", "pair.fna", "FASTA"),
            ("pair.fasta", "pair.fsa", "FASTA"),
            ("PAIR.FNA", "pair.FA", "FASTA"),
            ("pair.gbk", "pair.gb", "GenBank"),
            ("pair.gbff", "PAIR.GBK", "GenBank"),
            ("pair.fna", "pair.fna", "FASTA"),
            ("pair.gbk", "pair.gbk", "GenBank"),
        )
        for left_name, right_name, kind in cases:
            for group in ("fungi", "bacteria"):
                for frozen in (False, True):
                    for reverse in (False, True):
                        with self.subTest(left=left_name, right=right_name, group=group,
                                          frozen=frozen, reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                            root = Path(tmp)
                            left = write_genome_fixture(root / "left" / left_name)
                            right = write_genome_fixture(root / "right" / right_name, translated=False)
                            files = [right, left] if reverse else [left, right]
                            before_bytes = [path.read_bytes() for path in files]
                            settings = {"analysis_scope": group}
                            if frozen:
                                settings["taxon_routes"] = [route("pair", "Frozen_Genome", group)]
                            before_settings = copy.deepcopy(settings)
                            layout = self.make_layout(root)
                            job = Job(id="job", name="demo")
                            with self.assertRaisesRegex(ValueError, f"duplicate {kind}"):
                                _stage_uploaded_inputs(files, layout, settings, job)
                            self.assertEqual(settings, before_settings)
                            self.assertEqual(layout.genome_inputs, [])
                            self.assertEqual(
                                [path for directory in layout.genome_roots
                                 for path in directory.rglob("*") if path.is_file()], [],
                            )
                            self.assertFalse((layout.results_root / "summary_tables/genome_taxon_manifest.tsv").exists())
                            self.assertEqual([path.read_bytes() for path in files], before_bytes)

    def test_repeated_genome_path_is_a_duplicate_with_or_without_frozen_routes(self) -> None:
        for suffix, kind in ((".fna", "FASTA"), (".gbk", "GenBank")):
            for frozen in (False, True):
                with self.subTest(suffix=suffix, frozen=frozen), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    source = write_genome_fixture(root / ("pair" + suffix))
                    settings = {"analysis_scope": "fungi"}
                    if frozen:
                        settings["taxon_routes"] = [route("pair", "pair", "fungi")]
                    layout = self.make_layout(root)
                    with self.assertRaisesRegex(ValueError, f"duplicate {kind}"):
                        _stage_uploaded_inputs([source, source], layout, settings, Job(id="job", name="demo"))
                    self.assertEqual(layout.genome_inputs, [])
                    self.assertEqual(list(layout.fungi_genome_root.glob("*")), [])

    def test_frozen_filename_aliases_share_one_duplicate_kind_limit(self) -> None:
        for names, kind in ((("upload.fna", "Canonical.fa"), "FASTA"),
                            (("alias.gbff", "upload.gbk"), "GenBank")):
            for reverse in (False, True):
                with self.subTest(names=names, reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    files = [write_genome_fixture(root / name) for name in names]
                    if reverse:
                        files.reverse()
                    frozen = route("upload", "Canonical", "fungi")
                    frozen["input_path_key"] = "genomes/fungi/demo/alias"
                    settings = {"analysis_scope": "fungi", "taxon_routes": [frozen]}
                    layout = self.make_layout(root)
                    with self.assertRaisesRegex(ValueError, f"duplicate {kind}"):
                        _stage_uploaded_inputs(files, layout, settings, Job(id="job", name="demo"))
                    self.assertEqual(layout.genome_inputs, [])
                    self.assertEqual(list(layout.fungi_genome_root.glob("*")), [])

    def test_one_fasta_and_genbank_pair_preserves_routes_counts_bytes_and_order(self) -> None:
        pairs = ((".fa", ".gb"), (".fna", ".gbk"), (".fsa", ".gbff"),
                 (".fasta", ".gbk"), (".FNA", ".GBFF"))
        for fasta_suffix, gbk_suffix in pairs:
            for group in ("fungi", "bacteria"):
                for frozen in (False, True):
                    for reverse in (False, True):
                        with self.subTest(pair=(fasta_suffix, gbk_suffix), group=group,
                                          frozen=frozen, reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                            root = Path(tmp)
                            files = [write_genome_fixture(root / ("pair" + suffix))
                                     for suffix in (fasta_suffix, gbk_suffix)]
                            if reverse:
                                files.reverse()
                            settings = {"analysis_scope": group}
                            genome_id = "Canonical_Pair" if frozen else "pair"
                            expected = route("pair", genome_id, group)
                            if frozen:
                                settings["taxon_routes"] = [copy.deepcopy(expected)]
                            else:
                                expected["prediction_method"] = "existing_cds" if group == "fungi" else "prodigal"
                                expected["route_reason"] = f"selected_{group}_scope_declaration"
                            expected["input_path_key"] = f"genomes/{group}/demo/{genome_id}"
                            layout = self.make_layout(root)
                            _stage_uploaded_inputs(files, layout, settings, Job(id="job", name="demo"))
                            self.assertEqual(settings["taxon_routes"], [expected])
                            self.assertEqual(
                                settings["taxon_counts"],
                                {"fungi": int(group == "fungi"), "bacteria": int(group == "bacteria"), "total": 1},
                            )
                            self.assertEqual(
                                settings["applicability_counts"],
                                {"funannotate": int(expected["prediction_method"] == "funannotate"),
                                 "prodigal": int(group == "bacteria"), "antismash": 1,
                                 "funbgcex": int(group == "fungi"),
                                 "funbgcex_not_applicable_taxon": int(group == "bacteria"),
                                 "bigscape": 1, "taxon_tree_figure": 1},
                            )
                            with (layout.results_root / "summary_tables/genome_taxon_manifest.tsv").open(newline="") as handle:
                                self.assertEqual(list(csv.DictReader(handle, delimiter="\t")), [expected])
                            self.assertEqual([path.suffix for path in layout.genome_inputs],
                                             [path.suffix.lower() for path in files])
                            self.assertEqual([path.read_bytes() for path in layout.genome_inputs],
                                             [path.read_bytes() for path in files])

    def test_distinct_genomes_and_duplicate_auxiliary_names_remain_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            genomes = [write_genome_fixture(root / name) for name in ("one.fna", "two.fa")]
            auxiliary = []
            for label in ("left", "right"):
                path = root / label / "readme.notes"
                path.parent.mkdir()
                path.write_text(label, encoding="utf-8")
                auxiliary.append(path)
            settings = {"analysis_scope": "fungi"}
            layout = self.make_layout(root)
            _stage_uploaded_inputs([*genomes, *auxiliary], layout, settings, Job(id="job", name="demo"))
            self.assertEqual(len(layout.genome_inputs), 2)
            self.assertEqual([row["genome_id"] for row in settings["taxon_routes"]], ["one", "two"])
            self.assertEqual((layout.downloads_root / "unclassified/readme.notes").read_text(), "left")
            self.assertEqual((layout.downloads_root / "unclassified/readme_2.notes").read_text(), "right")

    def test_direct_safe_name_collapse_retains_its_existing_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [write_genome_fixture(root / name) for name in ("pair one.fna", "pair_one.fa")]
            with self.assertRaisesRegex(ValueError, "collapse to the same safe input_key"):
                _stage_uploaded_inputs(files, self.make_layout(root), {"analysis_scope": "fungi"}, Job(id="job", name="demo"))

    def test_cross_domain_duplicate_immutable_genome_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate genome_id"):
            _normalize_taxon_routes(
                {
                    "taxon_routes": [
                        route("fungal_input", "Shared_ID", "fungi"),
                        route("bacterial_input", "Shared_ID", "bacteria"),
                    ]
                }
            )

    def test_alias_resolution_searches_both_roots_and_rejects_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self.make_layout(Path(tmp))
            layout.fungi_genome_root.mkdir(parents=True)
            layout.bacteria_genome_root.mkdir(parents=True)
            (layout.fungi_genome_root / "accessions_fungusID_taxonomyID.txt").write_text(
                "GCA_000001.1\tFungus_A\t4751\n", encoding="utf-8"
            )
            (
                layout.bacteria_genome_root
                / "accessions_bacteriaID_taxonomyID.txt"
            ).write_text("GCA_000001.1\tBacterium_A\t2\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                _resolve_target_genome_alias(layout, "GCA_000001")

    def test_missing_scope_keeps_historical_fungal_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload = root / "legacy.fna"
            upload.write_text(">legacy\nACGT\n", encoding="utf-8")
            settings: dict[str, object] = {}
            layout = self.make_layout(root)

            _stage_uploaded_inputs(
                [upload], layout, settings, Job(id="job", name="demo")
            )

            self.assertTrue((layout.fungi_genome_root / "legacy.fna").is_file())
            self.assertEqual(settings["analysis_scope"], "fungi")
            self.assertEqual(
                settings["taxon_routes"][0]["taxon_source"], "legacy_default"
            )

    def test_direct_staging_rejects_authoritative_genbank_scope_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload = root / "authoritative_bacterium.gbk"
            upload.write_text(
                """LOCUS       bacterial_record       12 bp    DNA
  ORGANISM  Fixture bacterium
            Bacteria; Bacillota.
FEATURES             Location/Qualifiers
     source          1..12
                     /organism="Fixture bacterium"
                     /db_xref="taxon:2"
     CDS             1..12
                     /translation="MKK"
ORIGIN
        1 atgaaaaaataa
//
""",
                encoding="utf-8",
            )
            settings: dict[str, object] = {"analysis_scope": "fungi"}
            layout = self.make_layout(root)

            with self.assertRaisesRegex(
                ValueError,
                "resolves to bacteria, outside selected fungi scope",
            ):
                _stage_uploaded_inputs(
                    [upload], layout, settings, Job(id="job", name="demo")
                )

            self.assertEqual(
                [
                    file_path
                    for root_path in layout.genome_roots
                    for file_path in root_path.rglob("*")
                    if file_path.is_file()
                ],
                [],
            )

    def test_direct_fungal_staging_uses_translation_readiness_for_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete_gbk = root / "complete_fungus.gbk"
            complete_fasta = root / "complete_fungus.fna"
            fallback_gbk = root / "fallback_fungus.gbk"
            fallback_fasta = root / "fallback_fungus.fna"
            common = """LOCUS       fungal_record          30 bp    DNA
  ORGANISM  Fixture fungus
            Eukaryota; Fungi; Ascomycota.
FEATURES             Location/Qualifiers
     source          1..30
                     /organism="Fixture fungus"
                     /db_xref="taxon:4751"
     CDS             1..9
{qualifier}ORIGIN
        1 atgaaaactatgaaaactatgaaaact
//
"""
            complete_gbk.write_text(
                common.format(qualifier='                     /translation="MKT"\n'),
                encoding="utf-8",
            )
            fallback_gbk.write_text(
                common.format(qualifier='                     /translation=""\n'),
                encoding="utf-8",
            )
            complete_fasta.write_text(">record\nATGAAAACTATGAAAACT\n", encoding="utf-8")
            fallback_fasta.write_text(">record\nATGAAAACTATGAAAACT\n", encoding="utf-8")
            settings: dict[str, object] = {"analysis_scope": "fungi"}
            layout = self.make_layout(root)

            _stage_uploaded_inputs(
                [complete_gbk, complete_fasta, fallback_gbk, fallback_fasta],
                layout,
                settings,
                Job(id="job", name="demo"),
            )

            methods = {
                row["input_key"]: row["prediction_method"]
                for row in settings["taxon_routes"]
            }
            self.assertEqual(methods["complete_fungus"], "existing_cds")
            self.assertEqual(methods["fallback_fungus"], "funannotate")

    def test_direct_staging_routes_same_stem_pair_with_shared_authority_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fasta = root / "bacterial_pair.fna"
            genbank = root / "bacterial_pair.gbk"
            fasta.write_text(">record\nATGAAAAAATAA\n", encoding="utf-8")
            genbank.write_text(
                """LOCUS       bacterial_record       12 bp    DNA
  ORGANISM  Fixture bacterium
            Bacteria; Bacillota.
FEATURES             Location/Qualifiers
     source          1..12
                     /organism="Fixture bacterium"
                     /db_xref="taxon:2"
     CDS             1..12
                     /translation="MKK"
ORIGIN
        1 atgaaaaaataa
//
""",
                encoding="utf-8",
            )
            with genbank.open("rb") as handle:
                authority = parse_genbank_taxonomy_stream(handle)
            expected = _normalize_taxon_routes(
                {
                    "taxon_routes": build_taxon_routes(
                        "bacteria",
                        [
                            {
                                "input_key": "bacterial_pair",
                                "has_annotated_genbank": True,
                                "authoritative_taxonomy": authority,
                            }
                        ],
                        [],
                    )
                }
            )[0]
            settings: dict[str, object] = {"analysis_scope": "bacteria"}
            layout = self.make_layout(root)

            _stage_uploaded_inputs(
                [fasta, genbank], layout, settings, Job(id="job", name="demo")
            )

            self.assertEqual(len(settings["taxon_routes"]), 1)
            actual = settings["taxon_routes"][0]
            expected["input_path_key"] = actual["input_path_key"]
            self.assertEqual(actual, expected)
            self.assertEqual(actual["taxon_source"], "genbank_source")
            self.assertEqual(actual["prediction_method"], "prodigal")
            self.assertTrue(
                (layout.bacteria_genome_root / "bacterial_pair.fna").is_file()
            )
            self.assertTrue(
                (layout.bacteria_genome_root / "bacterial_pair.gbk").is_file()
            )

    def test_authoritative_ranked_taxonomy_and_mapping_lineage_reach_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload_root = root / "uploads"
            upload_root.mkdir()
            filenames = ("authoritative.fna", "GCA_000002.1.fna", "declared.fna")
            uploads = []
            for filename in filenames:
                path = upload_root / filename
                path.write_text(f">{path.stem}\nACGT\n", encoding="utf-8")
                uploads.append(path)

            layout = self.make_layout(root)
            layout.fungi_genome_root.mkdir(parents=True)
            (
                layout.fungi_genome_root
                / "accessions_fungusID_taxonomyID.txt"
            ).write_text(
                "GCA_000002.1\tMapped_Fungus\t222\t40.0\tMapped fungus\t"
                "1,2759,4751,4890\tEukaryota|Fungi|Ascomycota|Eurotiomycetes\n",
                encoding="utf-8",
            )
            authoritative = route(
                "authoritative", "Ranked_Fungus", "fungi"
            )
            authoritative.update(
                {
                    "taxon_source": "ncbi",
                    "source_accession": "GCA_000001.1",
                    "taxid": "111",
                    "organism_name": "Ranked fungus",
                }
            )
            mapped = route("GCA_000002.1", "Mapped_Fungus", "fungi")
            mapped.update(
                {
                    "taxon_source": "ncbi",
                    "source_accession": "GCA_000002.1",
                    "taxid": "222",
                    "organism_name": "Mapped fungus",
                }
            )
            declared = route("declared", "Declared_Fungus", "fungi")
            settings: dict[str, object] = {
                "analysis_scope": "fungi",
                "taxon_routes": [authoritative, mapped, declared],
                "taxonomy_metadata": [
                    {
                        "input_key": "authoritative",
                        "source_accession": "GCA_000001.1",
                        "taxid": "111",
                        "organism_name": "Ranked fungus",
                        "taxon_group": "fungi",
                        "taxon_source": "ncbi",
                        "domain": "Eukaryota",
                        "kingdom": "Fungi",
                        "phylum": "Ascomycota",
                        "class": "Eurotiomycetes",
                        "order": "Eurotiales",
                        "family": "Aspergillaceae",
                        "genus": "Fixtureus",
                        "species": "Fixtureus rankedii",
                        "lineage_names": (
                            "Eukaryota|Fungi|Ascomycota|Eurotiomycetes|"
                            "Eurotiales|Aspergillaceae|Fixtureus|"
                            "Fixtureus rankedii"
                        ),
                    }
                ],
            }

            _stage_uploaded_inputs(
                uploads, layout, settings, Job(id="job", name="demo")
            )

            manifest = (
                layout.results_root
                / "summary_tables"
                / "genome_taxon_manifest.tsv"
            )
            taxonomy = (
                layout.results_root
                / "summary_tables"
                / "taxonomy_metadata_normalized.tsv"
            )
            self.assertEqual(
                manifest.read_text(encoding="utf-8").splitlines()[0],
                "\t".join(TAXON_ROUTE_FIELDS),
            )
            self.assertNotIn("lineage_names", manifest.read_text(encoding="utf-8"))
            with taxonomy.open(newline="", encoding="utf-8") as handle:
                taxonomy_rows = {
                    row["genome_id"]: row
                    for row in csv.DictReader(handle, delimiter="\t")
                }
            self.assertEqual(
                taxonomy_rows["Ranked_Fungus"]["family"], "Aspergillaceae"
            )
            self.assertIn(
                "Fixtureus rankedii",
                taxonomy_rows["Ranked_Fungus"]["lineage_names"],
            )
            self.assertEqual(
                taxonomy_rows["Mapped_Fungus"]["lineage_ids"],
                "1,2759,4751,4890",
            )
            self.assertIn(
                "Eurotiomycetes",
                taxonomy_rows["Mapped_Fungus"]["lineage_names"],
            )
            self.assertEqual(
                taxonomy_rows["Declared_Fungus"]["lineage_names"], ""
            )

            output = root / "tree"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "render_phylo_taxon_profile.py"),
                    "--manifest",
                    str(manifest),
                    "--taxonomy",
                    str(taxonomy),
                    "--output-dir",
                    str(output),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with (
                output / "clusterweave_taxon_tree_leaf_profiles.tsv"
            ).open(newline="", encoding="utf-8") as handle:
                profiles = {
                    row["genome_id"]: row
                    for row in csv.DictReader(handle, delimiter="\t")
                }
            self.assertEqual(
                profiles["Ranked_Fungus"]["taxonomy_resolution"],
                "saved_lineage",
            )
            self.assertEqual(
                profiles["Mapped_Fungus"]["taxonomy_resolution"],
                "saved_lineage",
            )
            self.assertEqual(
                profiles["Declared_Fungus"]["taxonomy_resolution"],
                "unresolved_polytomy",
            )
            newick = (
                output / "clusterweave_taxon_tree.nwk"
            ).read_text(encoding="utf-8")
            self.assertIn("Aspergillaceae", newick)

    def test_ambiguous_authoritative_taxonomy_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload = root / "sample.fna"
            upload.write_text(">sample\nACGT\n", encoding="utf-8")
            authoritative = route("sample", "Sample_Fungus", "fungi")
            authoritative["taxon_source"] = "ncbi"
            settings: dict[str, object] = {
                "analysis_scope": "fungi",
                "taxon_routes": [authoritative],
                "taxonomy_metadata": [
                    {
                        "input_key": "sample",
                        "taxon_group": "fungi",
                        "taxon_source": "ncbi",
                        "taxid": "111",
                        "lineage_names": "Eukaryota|Fungi",
                    },
                    {
                        "input_key": "SAMPLE",
                        "taxon_group": "fungi",
                        "taxon_source": "ncbi",
                        "taxid": "222",
                        "lineage_names": "Eukaryota|Fungi",
                    },
                ],
            }

            with self.assertRaisesRegex(ValueError, "Ambiguous taxonomy_metadata"):
                _stage_uploaded_inputs(
                    [upload],
                    self.make_layout(root),
                    settings,
                    Job(id="job", name="demo"),
                )


if __name__ == "__main__":
    unittest.main()
