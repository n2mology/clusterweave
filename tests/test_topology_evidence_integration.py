from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPARATOR_PATH = REPO_ROOT / "software" / "phylogeny" / "compare_gene_tree_taxonomy.py"
MERGER = REPO_ROOT / "bin" / "merge_topology_evidence.py"
BUILDER = REPO_ROOT / "bin" / "build_cross_kingdom_evidence.py"
RUNNER = REPO_ROOT / "run_integrated_evidence.sh"


def load_comparator():
    spec = importlib.util.spec_from_file_location("clusterweave_topology_comparator", COMPARATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Node:
    def __init__(self, name: str = "", children: list["Node"] | None = None, support: float | None = None):
        self.name = name
        self.children = children or []
        self.support = support

    def traverse(self, strategy: str = "preorder"):
        yield self
        for child in self.children:
            yield from child.traverse(strategy)

    def leaf_names(self):
        if not self.children:
            yield self.name
            return
        for child in self.children:
            yield from child.leaf_names()


class TopologyEvidenceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.comparator = load_comparator()

    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def write_tsv(self, path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)

    def mapping(self) -> dict[str, str]:
        return {"f1": "fungi", "f2": "fungi", "b1": "bacteria", "b2": "bacteria"}

    def test_unrooted_domain_split_is_concordant_and_supported_mixing_is_cautious(self) -> None:
        concordant = Node(
            children=[
                Node(children=[Node("f1"), Node("f2")], support=99),
                Node(children=[Node("b1"), Node("b2")], support=98),
            ]
        )
        result = self.comparator.compare_nodes(concordant, self.mapping())
        self.assertEqual(result.status, "concordant_domain_split")
        self.assertEqual(result.topology_discordance, "not_supported")

        mixed = Node(
            children=[
                Node(children=[Node("f1"), Node("b1")], support=95),
                Node(children=[Node("f2"), Node("b2")], support=96),
            ]
        )
        result = self.comparator.compare_nodes(mixed, self.mapping())
        self.assertEqual(result.status, "supported_domain_topology_discordance")
        self.assertEqual(result.topology_discordance, "supported")
        self.assertEqual(result.support, 96)

        low_support = Node(
            children=[
                Node(children=[Node("f1"), Node("b1")], support=0.70),
                Node(children=[Node("f2"), Node("b2")], support=0.75),
            ]
        )
        result = self.comparator.compare_nodes(low_support, self.mapping())
        self.assertEqual(result.status, "domain_topology_discordance_low_support")
        self.assertEqual(result.topology_discordance, "not_supported")
        self.assertEqual(result.support, 75)

        under_sampled = Node(children=[Node("f1"), Node("b1"), Node("b2")])
        result = self.comparator.compare_nodes(
            under_sampled, {"f1": "fungi", "b1": "bacteria", "b2": "bacteria"}
        )
        self.assertEqual(result.status, "insufficient_domain_replication")
        self.assertEqual(result.topology_discordance, "insufficient_data")

    def test_comparator_writes_only_bounded_scalar_summary(self) -> None:
        root = self.workspace()
        tree = root / "family.treefile"
        tree.write_text("((f1,b1)95,(f2,b2)96);\n", encoding="utf-8")
        mapping = root / "mapping.tsv"
        self.write_tsv(
            mapping,
            ["sequence_id", "family_id", "taxon_group"],
            [
                {"sequence_id": sequence, "family_id": "family_1", "taxon_group": taxon}
                for sequence, taxon in self.mapping().items()
            ],
        )
        output = root / "topology.tsv"
        mixed = Node(
            children=[
                Node(children=[Node("f1"), Node("b1")], support=95),
                Node(children=[Node("f2"), Node("b2")], support=96),
            ]
        )
        args = argparse.Namespace(
            explicit_request=True,
            tree=tree,
            mapping=mapping,
            family_id="family_1",
            gcf_id="GCF_SHARED",
            tree_id="tree_1",
            output=output,
            support_threshold=80,
        )
        with mock.patch.object(self.comparator, "load_ete_tree", return_value=(mixed, "4.3.0")):
            result = self.comparator.run(args)
        self.assertEqual(result.topology_discordance, "supported")
        with output.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["gcf_id"], "GCF_SHARED")
        self.assertEqual(row["topology_support"], "96")
        self.assertEqual(row["outgroup_status"], "unrooted_no_directional_inference")
        rendered = json.dumps(row)
        self.assertNotIn(str(root), rendered)
        self.assertNotIn("((f1,b1)", rendered)
        self.assertNotIn("confirmed", rendered.casefold())

    def topology_row(self) -> dict[str, str]:
        return {
            "gcf_id": "GCF_SHARED",
            "gene_family_id": "family_1",
            "family_tree_id": "tree_1",
            "comparison_status": "supported_domain_topology_discordance",
            "topology_discordance": "supported",
            "topology_support": "96",
            "topology_support_method": "IQ-TREE_2_ultrafast_bootstrap_ETE4_unrooted_domain_split",
            "tree_method": "IQ-TREE_2_maximum_likelihood",
            "alignment_method": "MAFFT_7.526",
            "trimming_method": "trimAl_automated1",
            "model_selection": "MFP",
            "model": "LG+F+G4",
            "tree_sequence_count": "4",
            "tree_taxon_count": "2",
            "fungal_sequence_count": "2",
            "bacterial_sequence_count": "2",
            "outgroup_status": "unrooted_no_directional_inference",
            "tree_tool_version": "IQ-TREE_2.4.0",
            "alignment_tool_version": "MAFFT_7.526",
            "comparator_version": "ETE_4_4.3.0",
            "schema_version": "clusterweave-ete4-domain-topology-v1",
        }

    def test_safe_merge_precedes_existing_builder_and_never_copies_trees(self) -> None:
        root = self.workspace()
        candidates = root / "candidates.tsv"
        candidate = {
            "candidate_id": "GCF_SHARED",
            "gcf_id": "GCF_SHARED",
            "cross_domain_gcf": "yes",
            "taxon_groups": "fungi;bacteria",
            "synteny_gene_order_matches": "8",
            "synteny_gene_count": "10",
            "characterized_reference_id": "BGC0000001",
            "characterized_reference_similarity_percent": "80",
            "mobile_element_context": "present",
            "contamination_check": "passed",
            "assembly_check": "passed",
            "paralogy_check": "passed",
            "sampling_check": "adequate",
            "conserved_enzyme_risk": "no",
            "long_branch_attraction_risk": "no",
        }
        self.write_tsv(candidates, list(candidate), [candidate])
        topology = root / "topology.tsv"
        row = self.topology_row()
        self.write_tsv(topology, list(row), [row])
        merged = root / "merged.tsv"
        completed = subprocess.run(
            [
                sys.executable,
                str(MERGER),
                "--explicit-request",
                "--candidates",
                str(candidates),
                "--topology",
                str(topology),
                "--output",
                str(merged),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        evidence = root / "evidence"
        built = subprocess.run(
            [
                sys.executable,
                str(BUILDER),
                "--explicit-request",
                "--candidates",
                str(merged),
                "--output-dir",
                str(evidence),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(built.returncode, 0, built.stderr)
        payload = json.loads(
            (evidence / "cross_kingdom_evidence.json").read_text(encoding="utf-8")
        )
        record = payload["records"][0]
        self.assertEqual(record["input"]["topology_discordance"], "supported")
        self.assertEqual(record["input"]["topology_comparison_status"], "supported")
        self.assertEqual(record["input"]["family_tree_id"], "tree_1")
        self.assertTrue(record["supported_topology_discordance"])
        self.assertEqual(record["confidence"], "strong")
        public_text = "\n".join(path.read_text(encoding="utf-8") for path in evidence.iterdir())
        self.assertNotIn(str(root), public_text)
        self.assertNotIn("((f1,b1)", public_text)
        self.assertNotIn("confirmed", public_text.casefold())

    def test_terminal_runner_uses_available_topology_and_falls_back_nonfatally(self) -> None:
        root = self.workspace()
        results = root / "results" / "demo"
        candidates = root / "candidates.tsv"
        candidate = {
            "candidate_id": "GCF_SHARED",
            "gcf_id": "GCF_SHARED",
            "cross_domain_gcf": "yes",
            "taxon_groups": "fungi;bacteria",
        }
        self.write_tsv(candidates, list(candidate), [candidate])
        topology = results / "phylogeny" / "topology_comparison.tsv"
        row = self.topology_row()
        self.write_tsv(topology, list(row), [row])
        env = os.environ.copy()
        env.update(
            {
                "PROJECT_DIR": str(REPO_ROOT),
                "PROJECT_NAME": "demo",
                "RESULTS_ROOT": str(results),
                "WORK_ROOT": str(root / "work"),
                "RUN_CROSS_KINGDOM_EVIDENCE": "1",
                "CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV": str(candidates),
            }
        )
        completed = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("phase=topology", completed.stdout)
        output = results / "integrated_evidence" / "cross_kingdom_evidence.tsv"
        with output.open(newline="", encoding="utf-8") as handle:
            enriched = list(csv.DictReader(handle, delimiter="\t"))[0]
        self.assertEqual(enriched["topology_discordance"], "supported")
        self.assertEqual(enriched["family_tree_id"], "tree_1")

        topology.write_text("not-a-valid-tsv\n", encoding="utf-8")
        repeated = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("phase=topology_unavailable", repeated.stdout)
        with output.open(newline="", encoding="utf-8") as handle:
            fallback = list(csv.DictReader(handle, delimiter="\t"))[0]
        self.assertNotIn("topology_discordance", candidate)
        self.assertEqual(fallback.get("topology_discordance", ""), "")

    def test_pinned_runtime_contains_helper_and_job_path_has_no_downloads(self) -> None:
        dockerfile = (REPO_ROOT / "software" / "phylogeny" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        singularity = (REPO_ROOT / "software" / "phylogeny" / "Singularity.def").read_text(
            encoding="utf-8"
        )
        runner = (REPO_ROOT / "run_phylogeny.sh").read_text(encoding="utf-8")
        self.assertIn("clusterweave-compare-gene-tree-taxonomy", dockerfile)
        self.assertIn("clusterweave-compare-gene-tree-taxonomy", singularity)
        self.assertIn(
            "!software/phylogeny/compare_gene_tree_taxonomy.py",
            (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "!software/phylogeny/compare_gene_tree_taxonomy.py",
            (REPO_ROOT / ".gitignore").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'PHYLOGENY_AUTO_PREPARE="${PHYLOGENY_AUTO_PREPARE:-${RUN_PHYLOGENY}}"',
            runner,
        )
        self.assertIn("prepare_phylogeny_families.py", runner)
        for forbidden in ("pip install", "docker pull", "curl ", "wget "):
            self.assertNotIn(forbidden, runner)


if __name__ == "__main__":
    unittest.main()
