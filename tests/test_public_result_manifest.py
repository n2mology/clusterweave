from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import canonical_pipeline  # noqa: E402
from canonical_pipeline import Job, ProjectLayout, _collect_result_files, _resolve_target_genome_alias  # noqa: E402


class PublicResultManifestTests(unittest.TestCase):
    def manifest_paths(self, job_root: Path) -> set[str]:
        lines = (job_root / "downloads" / "public_results_manifest.tsv").read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 1)
        self.assertEqual(lines[0], "path\tbytes\tsha256")
        return {line.split("\t", 1)[0] for line in lines[1:] if line.strip()}

    def archive_names(self, archive_path: Path) -> set[str]:
        with zipfile.ZipFile(archive_path) as archive:
            return set(archive.namelist())

    def test_target_genome_accepts_accession_alias_from_prep_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            genome_root = job_root / "data" / "genomes" / "fungi" / "demo"
            genome_root.mkdir(parents=True)
            (genome_root / "accessions_fungusID_taxonomyID.txt").write_text(
                "GCA_017499595.2\tPsilocybe_cubensis_MGC-MH-2018\t181762\t46.39\n",
                encoding="utf-8",
            )
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=genome_root,
                results_root=job_root / "data" / "results" / "demo",
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )

            self.assertEqual(
                _resolve_target_genome_alias(layout, "GCA_017499595.2"),
                "Psilocybe_cubensis_MGC-MH-2018",
            )
            self.assertEqual(
                _resolve_target_genome_alias(layout, "GCA_017499595"),
                "Psilocybe_cubensis_MGC-MH-2018",
            )
            self.assertEqual(
                _resolve_target_genome_alias(layout, "Psilocybe_cubensis_MGC-MH-2018"),
                "Psilocybe_cubensis_MGC-MH-2018",
            )
            self.assertEqual(_resolve_target_genome_alias(layout, "unknown_target"), "unknown_target")

    def test_collector_indexes_only_public_safe_outputs_and_public_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results_root = job_root / "data" / "results" / "demo"
            files = {
                "figures/bgc_overlap.svg": "<svg></svg>\n",
                "figures/bigscape_network.graphml": "<graphml />\n",
                "summary/all_tools_bgc_comparison.csv": "genome,taxon_group,antismash_bgc_id\n",
                "summary/all_tools_shared_unshared_summary.csv": "genome,count\n",
                "summary/family_atlas_shortlist.md": "# shortlist\n",
                "summary/family_atlas_shortlist.tsv": "rank\tgenome\n",
                "summary_tables/ecofun_metadata_normalized.tsv": "accession\tgenome_id_current\n",
                "antismash/genome_a/index.html": "<html>antiSMASH</html>\n",
                "antismash/genome_a/style.css": "body{}\n",
                "antismash/genome_a/region001.gbk": "LOCUS raw\n",
                "funbgcex/genome_a/index.html": "<html>FunBGCeX</html>\n",
                "funbgcex/genome_a/raw.tsv": "raw funbgcex\n",
                "big_scape/output_files/index.html": "<html>BiG-SCAPE</html>\n",
                "big_scape/output_files/data_sqlite.db": "/data/jobs/private/input.gbk\n",
                "big_scape/public/clusterweave_viewer.sqlite": "web-only viewer bytes\n",
                "big_scape/output_files/network.gml": "graph bytes\n",
                "clinker/panel/panel.html": "<html>clinker</html>\n",
                "clinker/panel/panel.js": "window.CLINKER=1;\n",
                "clinker/panel/inputs/raw.gbk": "LOCUS raw\n",
                "clinker/panel/panel_manifest.tsv": "source_gbk_path\n/private/raw.gbk\n",
                "clinker/panel/run_panel.sh": "docker run private\n",
                "input_gbks/raw.gbk": "LOCUS raw\n",
                "summary_tables/logs/raw.log": "SECRET=1\n",
                "reproducibility/external_artifacts.tsv": "/private/path\n",
            }
            for rel, content in files.items():
                target = results_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            job = Job(id="jobone", name="demo")
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "demo",
                results_root=results_root,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )

            _collect_result_files(job, job_root, layout)

            public_files = set(job.result_files)
            self.assertIn("downloads/demo_public_results.zip", public_files)
            self.assertIn("downloads/public_results_manifest.tsv", public_files)
            self.assertIn("data/results/demo/figures/bgc_overlap.svg", public_files)
            self.assertIn("data/results/demo/summary/family_atlas_shortlist.md", public_files)
            self.assertIn("data/results/demo/summary/all_tools_bgc_comparison.csv", public_files)
            self.assertIn("data/results/demo/summary/all_tools_shared_unshared_summary.csv", public_files)
            self.assertIn("data/results/demo/antismash/genome_a/index.html", public_files)
            self.assertIn("data/results/demo/antismash/genome_a/style.css", public_files)
            self.assertIn("data/results/demo/funbgcex/genome_a/index.html", public_files)
            self.assertIn("data/results/demo/big_scape/output_files/index.html", public_files)
            self.assertNotIn("data/results/demo/big_scape/output_files/data_sqlite.db", public_files)
            self.assertNotIn("data/results/demo/big_scape/public/clusterweave_viewer.sqlite", public_files)
            self.assertIn("data/results/demo/clinker/panel/panel.html", public_files)
            self.assertIn("data/results/demo/clinker/panel/panel.js", public_files)
            self.assertNotIn("data/results/demo/antismash/genome_a/region001.gbk", public_files)
            self.assertNotIn("data/results/demo/funbgcex/genome_a/raw.tsv", public_files)
            self.assertNotIn("data/results/demo/big_scape/output_files/network.gml", public_files)
            self.assertNotIn("data/results/demo/clinker/panel/inputs/raw.gbk", public_files)
            self.assertNotIn("data/results/demo/reproducibility/external_artifacts.tsv", public_files)

            joined = "\n".join(sorted(public_files))
            for private_marker in [
                "input_gbks/",
                "summary_tables/logs/",
                "external_artifacts",
                "panel_manifest",
                "run_panel.sh",
                "/inputs/",
            ]:
                self.assertNotIn(private_marker, joined)

            manifest_paths = self.manifest_paths(job_root)
            analysis_paths = {rel for rel in public_files if not rel.startswith("downloads/")}
            self.assertEqual(manifest_paths, analysis_paths)

            archive_path = job_root / "downloads" / "demo_public_results.zip"
            names = self.archive_names(archive_path)
            self.assertEqual(names, manifest_paths | {"downloads/public_results_manifest.tsv"})
            self.assertIn("data/results/demo/figures/bgc_overlap.svg", names)
            self.assertIn("data/results/demo/summary/family_atlas_shortlist.tsv", names)
            self.assertIn("data/results/demo/antismash/genome_a/index.html", names)
            self.assertNotIn("data/results/demo/big_scape/output_files/data_sqlite.db", names)
            self.assertNotIn("data/results/demo/big_scape/public/clusterweave_viewer.sqlite", names)
            self.assertIn("data/results/demo/clinker/panel/panel.html", names)
            self.assertIn("downloads/public_results_manifest.tsv", names)
            self.assertNotIn("downloads/demo_public_results.zip", names)
            self.assertNotIn("data/results/demo/antismash/genome_a/region001.gbk", names)
            self.assertNotIn("data/results/demo/clinker/panel/inputs/raw.gbk", names)
            self.assertNotIn("data/results/demo/reproducibility/external_artifacts.tsv", names)

    def test_partial_failure_outputs_use_the_same_manifest_archive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results_root = job_root / "data" / "results" / "partial"
            files = {
                "antismash/genome_a/index.html": "<html>antiSMASH</html>\n",
                "antismash/genome_a/style.css": "body{}\n",
                "antismash/genome_a/region001.gbk": "LOCUS raw\n",
                "summary/family_atlas_shortlist.md": "# partial shortlist\n",
                "summary_tables/ecofun_metadata_normalized.tsv": "accession\tgenome_id_current\n",
                "clinker/panel/panel_manifest.tsv": "source_gbk_path\n/private/raw.gbk\n",
            }
            for rel, content in files.items():
                target = results_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            job = Job(id="partialjob", name="partial")
            layout = ProjectLayout(
                project_name="partial",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "partial",
                results_root=results_root,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )

            _collect_result_files(job, job_root, layout)

            expected_outputs = {
                "data/results/partial/antismash/genome_a/index.html",
                "data/results/partial/antismash/genome_a/style.css",
                "data/results/partial/summary/family_atlas_shortlist.md",
                "data/results/partial/summary_tables/ecofun_metadata_normalized.tsv",
            }
            self.assertEqual(self.manifest_paths(job_root), expected_outputs)
            self.assertEqual(
                set(job.result_files),
                expected_outputs | {"downloads/partial_public_results.zip", "downloads/public_results_manifest.tsv"},
            )
            self.assertEqual(
                self.archive_names(job_root / "downloads" / "partial_public_results.zip"),
                expected_outputs | {"downloads/public_results_manifest.tsv"},
            )
            self.assertNotIn("data/results/partial/antismash/genome_a/region001.gbk", job.result_files)
            self.assertNotIn("data/results/partial/clinker/panel/panel_manifest.tsv", job.result_files)

    def test_full_bigscape_export_remains_packaged_while_viewer_stays_web_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results_root = job_root / "data" / "results" / "demo"
            public_dir = results_root / "big_scape" / "public"
            public_dir.mkdir(parents=True)
            full = public_dir / "clusterweave_public.sqlite"
            viewer = public_dir / "clusterweave_viewer.sqlite"
            full.write_bytes(b"complete sanitized public export")
            viewer.write_bytes(b"compact web-only viewer")
            job = Job(
                id="viewerboundary",
                name="demo",
                bigscape_viewer_database=(
                    "data/results/demo/big_scape/public/clusterweave_viewer.sqlite"
                ),
            )
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "demo",
                results_root=results_root,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )

            _collect_result_files(
                job,
                job_root,
                layout,
                attested_bigscape_databases={full.resolve()},
            )

            full_rel = "data/results/demo/big_scape/public/clusterweave_public.sqlite"
            viewer_rel = "data/results/demo/big_scape/public/clusterweave_viewer.sqlite"
            self.assertIn(full_rel, job.result_files)
            self.assertNotIn(viewer_rel, job.result_files)
            self.assertIn(full_rel, self.manifest_paths(job_root))
            self.assertNotIn(viewer_rel, self.manifest_paths(job_root))
            names = self.archive_names(
                job_root / "downloads" / "demo_public_results.zip"
            )
            self.assertIn(full_rel, names)
            self.assertNotIn(viewer_rel, names)
            self.assertEqual(job.bigscape_viewer_database, viewer_rel)

    def test_collector_never_follows_allowlisted_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results_root = job_root / "data" / "results" / "demo"
            figures_root = results_root / "figures"
            figures_root.mkdir(parents=True)
            private = job_root / "job.json"
            private.write_text('{"read_token_hash":"private"}\n', encoding="utf-8")
            leak = figures_root / "leak.svg"
            leak.symlink_to(private)

            job = Job(id="jobone", name="demo")
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "demo",
                results_root=results_root,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )

            _collect_result_files(job, job_root, layout)

            leak_path = "data/results/demo/figures/leak.svg"
            self.assertNotIn(leak_path, job.result_files)
            self.assertNotIn(leak_path, self.manifest_paths(job_root))
            self.assertNotIn(
                leak_path,
                self.archive_names(job_root / "downloads" / "demo_public_results.zip"),
            )

    def test_collector_rejects_a_symlinked_results_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            private_root = job_root / "private-target"
            private_figure = private_root / "figures" / "leak.svg"
            private_figure.parent.mkdir(parents=True)
            private_figure.write_text("<svg>private</svg>\n", encoding="utf-8")
            results_root = job_root / "data" / "results" / "demo"
            results_root.parent.mkdir(parents=True)
            results_root.symlink_to(private_root, target_is_directory=True)

            job = Job(id="jobone", name="demo")
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "demo",
                results_root=results_root,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )

            _collect_result_files(job, job_root, layout)

            leak_path = "data/results/demo/figures/leak.svg"
            self.assertNotIn(leak_path, job.result_files)
            self.assertNotIn(leak_path, self.manifest_paths(job_root))
            self.assertNotIn(
                leak_path,
                self.archive_names(job_root / "downloads" / "demo_public_results.zip"),
            )

    def test_collector_preserves_previous_result_index_if_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results_root = job_root / "data" / "results" / "demo"
            figure = results_root / "figures" / "old.svg"
            figure.parent.mkdir(parents=True, exist_ok=True)
            figure.write_text("<svg></svg>\n", encoding="utf-8")

            previous_files = ["data/results/demo/figures/old.svg"]
            job = Job(id="jobone", name="demo", result_files=list(previous_files))
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "demo",
                results_root=results_root,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )

            original_writer = canonical_pipeline._write_public_manifest

            def fail_manifest(*args, **kwargs):
                raise RuntimeError("manifest refresh failed")

            canonical_pipeline._write_public_manifest = fail_manifest
            try:
                with self.assertRaises(RuntimeError):
                    _collect_result_files(job, job_root, layout)
            finally:
                canonical_pipeline._write_public_manifest = original_writer

            self.assertEqual(job.result_files, previous_files)

    def test_file_identity_includes_ctime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "result.svg"
            target.write_text("<svg />\n", encoding="utf-8")
            stat = target.stat()

            self.assertEqual(
                canonical_pipeline._file_identity(target),
                (
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                ),
            )

    def test_before_publish_veto_preserves_previous_manifest_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results_root = job_root / "data" / "results" / "demo"
            figure = results_root / "figures" / "result.svg"
            figure.parent.mkdir(parents=True, exist_ok=True)
            figure.write_text("<svg>first</svg>\n", encoding="utf-8")
            job = Job(id="jobone", name="demo")
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "demo",
                results_root=results_root,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )
            _collect_result_files(job, job_root, layout)
            previous_files = list(job.result_files)
            manifest = job_root / "downloads" / "public_results_manifest.tsv"
            archive = job_root / "downloads" / "demo_public_results.zip"
            previous_manifest = manifest.read_bytes()
            previous_archive = archive.read_bytes()
            figure.write_text("<svg>second</svg>\n", encoding="utf-8")
            callback_calls = []

            def veto() -> None:
                callback_calls.append(True)
                self.assertEqual(manifest.read_bytes(), previous_manifest)
                self.assertEqual(archive.read_bytes(), previous_archive)
                self.assertTrue(list((job_root / "downloads").glob(".*.tmp")))
                raise RuntimeError("job state changed")

            with self.assertRaisesRegex(RuntimeError, "job state changed"):
                _collect_result_files(
                    job,
                    job_root,
                    layout,
                    before_publish=veto,
                )

            self.assertEqual(callback_calls, [True])
            self.assertEqual(job.result_files, previous_files)
            self.assertEqual(manifest.read_bytes(), previous_manifest)
            self.assertEqual(archive.read_bytes(), previous_archive)
            self.assertFalse(list((job_root / "downloads").glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
