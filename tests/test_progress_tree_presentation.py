from __future__ import annotations

import base64
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = REPO_ROOT / "bin" / "render_progress_tree.py"
CONTRACT_PATH = REPO_ROOT / "web" / "static" / "assets" / "progress-tree-contract.json"
BROWSER_TREE_PATH = REPO_ROOT / "web" / "static" / "assets" / "progress-tree.js"
RUNNER_PATH = REPO_ROOT / "run_clusterweave.sh"
NODE = shutil.which("node")
SCRIPT = shutil.which("script")

SPEC = importlib.util.spec_from_file_location("render_progress_tree", RENDERER_PATH)
assert SPEC and SPEC.loader
TREE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TREE
SPEC.loader.exec_module(TREE)


def semantic_fixture() -> list[str]:
    return [
        "[08:00:00] === Stage: Preparing genomes from accessions ===",
        '[08:00:01] NCBI_DOWNLOAD_PROGRESS accession=fixture_accession taxon=fungi status=complete percent=8 message="NCBI genome download complete"',
        "[08:00:02] Input preparation complete.",
        "[08:00:03] [INFO] Stage 1/4: running run_annotation_and_detection.sh",
        "[08:00:04] [1/2] genome=fungus_one taxon=fungi prediction=funannotate",
        '[08:00:05] TAXON_ROUTE genome=fungus_one taxon=fungi source=fixture status=ready message="prediction=funannotate detector=both"',
        '[08:00:06] ANTISMASH_RECORD_PROGRESS genome=fungus_one record=record_a ordinal=1/2 percent=60 bar=[############--------] message="Record analysis in progress"',
        '[08:00:07] TOOL_PROGRESS genome=fungus_one tool=antismash phase=detect message="Scanning protein domains"',
        "[08:00:08] TOOL_HEARTBEAT genome=fungus_one tool=antismash phase=detect elapsed=600s",
        "[08:00:09] TOOL_HEARTBEAT genome=fungus_one tool=antismash phase=detect elapsed=1200s",
        '[08:00:10] GENOME_PROGRESS genome=fungus_one stage=funbgcex percent=100 bar=[####################] message="FunBGCeX complete"',
        '[08:00:11] GENOME_PROGRESS genome=fungus_one stage=annotation percent=100 bar=[####################] message="Genome workflow complete"',
        "[08:00:12] [2/2] genome=bacterium_one taxon=bacteria prediction=prodigal",
        '[08:00:13] TAXON_ROUTE genome=bacterium_one taxon=bacteria source=fixture status=ready message="prediction=prodigal detector=antismash"',
        '[08:00:14] GENOME_PROGRESS genome=bacterium_one stage=antismash percent=100 bar=[####################] message="BGC detection complete"',
        '[08:00:15] GENOME_PROGRESS genome=bacterium_one stage=annotation percent=100 bar=[####################] message="Genome workflow complete"',
        "[08:00:16] [WARN] Optional annotation note",
        "[08:00:17] [INFO] Stage 1/4: complete",
        "[08:00:18] [INFO] Stage 2/4: skipped",
        "[08:00:19] [INFO] Stage 3/4: running summarize_clusterweave.sh",
        "[08:00:20] Wrote summary crosswalk",
        "[08:00:21] [INFO] Stage 3/4: complete",
        "[08:00:22] [INFO] Stage 4/4: skipped",
        "[08:00:23] === Stage: Rendering summary figures ===",
        "[08:00:24] run_figures.sh complete",
        "[08:00:25] Wrote run provenance: fixture.tsv",
        "[08:00:26] Canonical workflow complete.",
        "[08:00:27] === Stage: Collecting result files ===",
        "[08:00:28] Canonical ClusterWeave workflow finished successfully.",
    ]


def run_node_json(source: str) -> object:
    if NODE is None:
        raise unittest.SkipTest("Node.js is required for shared classifier tests")
    completed = subprocess.run(
        [NODE, "--input-type=module"],
        cwd=REPO_ROOT,
        input=source,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Progress-tree Node probe failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


class SharedProgressTreeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = TREE.load_contract(CONTRACT_PATH)

    def test_python_and_browser_classifiers_share_exact_semantic_fields(self) -> None:
        lines = semantic_fixture()
        python_events = []
        current_stage = "prep"
        for index, line in enumerate(lines):
            event = TREE.classify_progress_line(
                self.contract,
                line,
                index,
                current_stage,
            )
            python_events.append(event)
            if event["stage_transition"]:
                current_stage = event["workflow_stage"]

        encoded_module = base64.b64encode(BROWSER_TREE_PATH.read_bytes()).decode("ascii")
        module_uri = f"data:text/javascript;base64,{encoded_module}"
        source = f"""
import {{ classifyProgressTreeLine }} from {json.dumps(module_uri)};
const contract = {json.dumps(self.contract)};
const lines = {json.dumps(lines)};
let currentStage = 'prep';
const events = lines.map((line, index) => {{
  const event = classifyProgressTreeLine(contract, line, index, currentStage);
  if (event.stage_transition) currentStage = event.workflow_stage;
  return event;
}});
process.stdout.write(JSON.stringify(events));
"""
        browser_events = run_node_json(source)
        semantic_fields = [
            "workflow_stage",
            "genome",
            "tool",
            "percentage",
            "state",
            "display_message",
            "elapsed_activity",
            "canonical_raw_line_index",
        ]
        self.assertEqual(
            [
                {field: event[field] for field in semantic_fields}
                for event in python_events
            ],
            [
                {field: event[field] for field in semantic_fields}
                for event in browser_events
            ],
        )
        self.assertEqual(lines, semantic_fixture(), "classification must not alter canonical lines")

    def test_heartbeats_update_one_branch_and_retain_measured_progress(self) -> None:
        model = TREE.build_progress_tree(
            self.contract,
            enumerate(semantic_fixture()[:10]),
        )
        antismash_nodes = [
            node
            for node in model.nodes.values()
            if node.level == "tool"
            and node.label == "antiSMASH"
            and node.stage == "annotation"
            and node.parent_key.endswith(":fungus_one")
        ]
        self.assertEqual(1, len(antismash_nodes))
        node = antismash_nodes[0]
        self.assertEqual(60, node.percentage)
        self.assertEqual(1200, node.elapsed)
        self.assertEqual("Scanning protein domains", node.message)
        self.assertIn("[######----]  60%", TREE.progress_status(node))

    def test_mixed_taxa_terminal_states_unknown_lines_and_optional_stage(self) -> None:
        lines = semantic_fixture()
        model = TREE.build_progress_tree(self.contract, enumerate(lines))
        tool_labels = {
            (node.parent_key, node.label)
            for node in model.nodes.values()
            if node.level == "tool"
        }
        self.assertTrue(any(parent.endswith(":fungus_one") and label == "FunBGCeX" for parent, label in tool_labels))
        self.assertFalse(any(parent.endswith(":bacterium_one") and label == "FunBGCeX" for parent, label in tool_labels))
        self.assertEqual("complete", model.nodes["stage:prep"].state)
        self.assertEqual("complete", model.nodes["stage:annotation"].state)
        self.assertEqual("skipped", model.nodes["stage:bigscape"].state)
        self.assertEqual("complete", model.nodes["stage:summary"].state)
        self.assertEqual("skipped", model.nodes["stage:clinker"].state)
        self.assertEqual("complete", model.nodes["stage:figures"].state)
        self.assertEqual("complete", model.nodes["stage:package"].state)
        self.assertEqual(
            "complete",
            model.nodes["genome:prep:fixture_accession"].state,
        )
        self.assertFalse(
            any(
                node.state == "running"
                for node in model.nodes.values()
                if node.stage in {"prep", "annotation", "summary", "figures"}
            )
        )
        self.assertNotIn("stage:phylogeny", model.nodes)
        self.assertNotIn("stage:nplinker", model.nodes)
        self.assertNotIn("stage:cross_kingdom_evidence", model.nodes)
        self.assertTrue(any(event.state == "warning" for event in model.permanent_events))

        with_optional = TREE.build_progress_tree(
            self.contract,
            enumerate(
                lines
                + [
                    "[08:01:00] === Stage: Running optional sequence phylogeny ===",
                    "[08:01:01] Sequence phylogeny follow-up complete.",
                    "[08:01:02] === Stage: Running optional NPLinker follow-up ===",
                    "[08:01:03] NPLinker follow-up complete.",
                    "[08:01:04] === Stage: Running optional cross-kingdom evidence ===",
                    "[08:01:05] Cross-kingdom evidence follow-up complete with warning.",
                ]
            ),
        )
        self.assertEqual("complete", with_optional.nodes["stage:phylogeny"].state)
        self.assertEqual("complete", with_optional.nodes["stage:nplinker"].state)
        self.assertEqual(
            "warning_terminal",
            with_optional.nodes["stage:cross_kingdom_evidence"].state,
        )

    def test_package_waits_for_explicit_collection_boundary(self) -> None:
        early = [
            "[08:00:00] Wrote run provenance: fixture.tsv",
            "[08:00:01] Wrote external artifact manifest: fixture.tsv",
            "[08:00:02] Canonical workflow complete.",
        ]
        model = TREE.build_progress_tree(self.contract, enumerate(early))
        self.assertEqual("waiting", model.nodes["stage:package"].state)

        collecting = TREE.build_progress_tree(
            self.contract,
            enumerate(early + ["[08:00:03] === Stage: Collecting result files ==="]),
        )
        self.assertEqual("running", collecting.nodes["stage:package"].state)

        finished = TREE.build_progress_tree(
            self.contract,
            enumerate(
                early
                + [
                    "[08:00:03] === Stage: Collecting result files ===",
                    "[08:00:04] Canonical ClusterWeave workflow finished successfully.",
                ]
            ),
        )
        self.assertEqual("complete", finished.nodes["stage:package"].state)

    def test_rerun_resets_live_children_but_keeps_reset_event(self) -> None:
        lines = [
            "[08:00:00] Stage 1/4: running run_annotation_and_detection.sh",
            '[08:00:01] GENOME_PROGRESS genome=fixture stage=antismash percent=100 bar=[####################] message="BGC detection complete"',
            "[08:00:02] Rerun annotation stage with corrected settings",
            '[08:00:03] GENOME_PROGRESS genome=fixture stage=antismash percent=0 bar=[--------------------] message="Starting BGC detection"',
        ]
        model = TREE.build_progress_tree(self.contract, enumerate(lines))
        node = model.nodes["tool:annotation:fixture:antiSMASH"]
        self.assertEqual("running", node.state)
        self.assertEqual(0, node.percentage)
        self.assertTrue(any(event.state == "rerun" for event in model.permanent_events))


@unittest.skipUnless(SCRIPT, "util-linux script is required for TTY behavior tests")
class CliProgressTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "fixture_project"
        self.project.mkdir()
        for name in [
            "run_annotation_and_detection.sh",
            "run_bigscape.sh",
            "summarize_clusterweave.sh",
            "run_clinker.sh",
        ]:
            path = self.project / name
            path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        self.env = {
            **os.environ,
            "PROJECT_DIR": str(self.project),
            "PROJECT_NAME": "fixture_project",
            "DATA_ROOT": str(self.project / "data"),
            "RESULTS_BASE": str(self.project / "data" / "results"),
            "RUN_STAGE_ANNOTATION": "0",
            "RUN_STAGE_BIGSCAPE": "0",
            "RUN_STAGE_SUMMARY": "0",
            "RUN_STAGE_CLINKER": "0",
            "CAPTURE_EXTERNAL_ARTIFACTS": "0",
            "TERM": "xterm-256color",
            "LC_ALL": "C.UTF-8",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_redirected(self, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(RUNNER_PATH), *arguments],
            cwd=REPO_ROOT,
            env=env or self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def run_tty(self, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        selected_env = env or self.env
        exported = [
            "env",
            *[f"{key}={value}" for key, value in selected_env.items() if key in {
                "PROJECT_DIR",
                "PROJECT_NAME",
                "DATA_ROOT",
                "RESULTS_BASE",
                "RUN_STAGE_ANNOTATION",
                "RUN_STAGE_BIGSCAPE",
                "RUN_STAGE_SUMMARY",
                "RUN_STAGE_CLINKER",
                "CAPTURE_EXTERNAL_ARTIFACTS",
                "TERM",
                "LC_ALL",
                "NO_COLOR",
            }],
            "bash",
            str(RUNNER_PATH),
        ]
        return subprocess.run(
            [SCRIPT, "-qefc", shlex.join(exported), "/dev/null"],
            cwd=REPO_ROOT,
            env=selected_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_redirected_and_explicit_raw_modes_preserve_raw_output(self) -> None:
        automatic = self.run_redirected()
        explicit = self.run_redirected("--raw")
        self.assertEqual(0, automatic.returncode)
        self.assertEqual(0, explicit.returncode)
        for output in [automatic.stdout, explicit.stdout]:
            self.assertNotIn("╲╱  CLUSTER", output)
            self.assertNotIn("\\/  CLUSTER", output)
            self.assertIn("Stage 1/4: skipped", output)
            self.assertIn("Canonical workflow complete.", output)

    def test_tty_selects_unicode_tree_and_honors_no_color(self) -> None:
        env = {**self.env, "NO_COLOR": "1"}
        completed = self.run_tty(env=env)
        self.assertEqual(0, completed.returncode, completed.stdout)
        self.assertIn("╲╱  CLUSTER", completed.stdout)
        self.assertIn("Annotation and BGC detection", completed.stdout)
        self.assertIn("[----------]   -- - Skipped", completed.stdout)
        self.assertIsNone(re.search(r"\x1b\[[0-9;]*m", completed.stdout))

    def test_term_dumb_uses_raw_and_non_unicode_locale_uses_ascii_tree(self) -> None:
        dumb = self.run_tty(env={**self.env, "TERM": "dumb"})
        self.assertEqual(0, dumb.returncode, dumb.stdout)
        self.assertNotIn("CLUSTER", dumb.stdout)
        self.assertIn("Stage 1/4: skipped", dumb.stdout)

        ascii_tree = self.run_tty(env={**self.env, "LC_ALL": "C"})
        self.assertEqual(0, ascii_tree.returncode, ascii_tree.stdout)
        self.assertIn("\\/  CLUSTER", ascii_tree.stdout)
        self.assertNotIn("╲╱  CLUSTER", ascii_tree.stdout)

    def test_renderer_preserves_failing_stage_exit_status(self) -> None:
        failing = self.project / "run_bigscape.sh"
        failing.write_text(
            "#!/usr/bin/env bash\nprintf '%s\\n' '[ERROR] fixture stage failed' >&2\nexit 7\n",
            encoding="utf-8",
        )
        failing.chmod(0o755)
        env = {**self.env, "RUN_STAGE_BIGSCAPE": "1"}
        completed = self.run_tty(env=env)
        self.assertEqual(7, completed.returncode, completed.stdout)
        self.assertIn("Failed", completed.stdout)

    def test_renderer_failure_falls_back_without_rerun_or_line_loss(self) -> None:
        command = [
            sys.executable,
            "-c",
            "print('canonical line one'); print('canonical line two'); raise SystemExit(7)",
        ]

        class FailingRenderer:
            def __init__(self, _contract: object, _project: str) -> None:
                self.records: list[tuple[int, str]] = []

            def start(self) -> None:
                pass

            def accept(self, line: str) -> None:
                self.records.append((len(self.records), line.rstrip("\r\n")))
                if len(self.records) == 2:
                    raise RuntimeError("fixture presentation failure")

            def finish(self) -> None:
                pass

        output = io.StringIO()
        contract = TREE.load_contract(CONTRACT_PATH)
        with mock.patch.object(TREE, "TerminalTreeRenderer", FailingRenderer):
            with redirect_stdout(output):
                status = TREE.run_rendered(command, "fixture", contract)

        self.assertEqual(7, status)
        self.assertEqual(1, output.getvalue().count("canonical line one"))
        self.assertEqual(1, output.getvalue().count("canonical line two"))


if __name__ == "__main__":
    unittest.main()
