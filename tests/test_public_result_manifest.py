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

from canonical_pipeline import Job, ProjectLayout, _collect_result_files  # noqa: E402


class PublicResultManifestTests(unittest.TestCase):
    def test_collector_indexes_only_public_safe_outputs_and_public_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results_root = job_root / "data" / "results" / "demo"
            files = {
                "figures/bgc_overlap.svg": "<svg></svg>\n",
                "figures/bigscape_network.graphml": "<graphml />\n",
                "summary/all_tools_shared_unshared_summary.csv": "genome,count\n",
                "summary/family_atlas_shortlist.md": "# shortlist\n",
                "summary/family_atlas_shortlist.tsv": "rank\tgenome\n",
                "summary_tables/ecofun_metadata_normalized.tsv": "accession\tgenome_id_current\n",
                "antismash/raw/index.html": "raw antismash\n",
                "funbgcex/raw.tsv": "raw funbgcex\n",
                "big_scape/output_files/network.db": "sqlite bytes\n",
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
            self.assertIn("data/results/demo/summary/all_tools_shared_unshared_summary.csv", public_files)
            self.assertNotIn("data/results/demo/antismash/raw/index.html", public_files)
            self.assertNotIn("data/results/demo/clinker/panel/inputs/raw.gbk", public_files)
            self.assertNotIn("data/results/demo/reproducibility/external_artifacts.tsv", public_files)

            joined = "\n".join(sorted(public_files))
            for private_marker in [
                "antismash/",
                "funbgcex/",
                "big_scape/",
                "input_gbks/",
                "summary_tables/logs/",
                "external_artifacts",
                "panel_manifest",
                "run_panel.sh",
                "/inputs/",
            ]:
                self.assertNotIn(private_marker, joined)

            archive_path = job_root / "downloads" / "demo_public_results.zip"
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
            self.assertIn("data/results/demo/figures/bgc_overlap.svg", names)
            self.assertIn("data/results/demo/summary/family_atlas_shortlist.tsv", names)
            self.assertNotIn("data/results/demo/antismash/raw/index.html", names)
            self.assertNotIn("data/results/demo/clinker/panel/inputs/raw.gbk", names)
            self.assertNotIn("data/results/demo/reproducibility/external_artifacts.tsv", names)


if __name__ == "__main__":
    unittest.main()
