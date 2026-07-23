from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import canonical_pipeline  # noqa: E402
from canonical_pipeline import Job, JobStatus, ProjectLayout, _collect_result_files  # noqa: E402


class CanonicalPhylogenyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_evidence_settings_are_fallback_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=root / "data",
                genome_root=root / "data" / "genomes" / "fungi" / "demo",
                results_root=root / "data" / "results" / "demo",
                software_root=root / "software",
                work_root=root / "work",
                downloads_root=root / "downloads",
            )
            legacy = canonical_pipeline._base_env(
                layout,
                {"run_hgt_evidence": True, "hgt_evidence_max_candidates": 7},
                4,
            )
            self.assertEqual(legacy["RUN_CROSS_KINGDOM_EVIDENCE"], "1")
            self.assertEqual(
                legacy["CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES"], "7"
            )
            self.assertNotIn("RUN_HGT_EVIDENCE", legacy)

            canonical = canonical_pipeline._base_env(
                layout,
                {
                    "run_cross_kingdom_evidence": False,
                    "cross_kingdom_evidence_max_candidates": 11,
                    "run_hgt_evidence": True,
                    "hgt_evidence_max_candidates": 7,
                },
                4,
            )
            self.assertEqual(canonical["RUN_CROSS_KINGDOM_EVIDENCE"], "0")
            self.assertEqual(
                canonical["CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES"], "11"
            )

    async def test_child_process_env_and_stored_logs_exclude_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Job(id="job", name="security")
            probe = (
                "import os; "
                "keys=['CLUSTERWEAVE_JOB_TOKEN_SECRET','CLUSTERWEAVE_SMTP_PASSWORD',"
                "'CLUSTERWEAVE_ADMIN_TOKEN','CLUSTERWEAVE_SUBMIT_TOKEN','CUSTOM_API_KEY',"
                "'AWS_ACCESS_KEY_ID','DOCKER_AUTH_CONFIG']; "
                "print('inherited=' + ','.join(k for k in keys if k in os.environ)); "
                "print('Authorization: Basic fake-basic-value'); "
                "print('Cookie: session=fake-cookie-value'); "
                "print('https://example.invalid/x?x-amz-signature=fake-signature-value'); "
                "print('password=fake-password-value'); "
                "print('--token fake-cli-token-value'); "
                "print('https://user:fake-userinfo-value@example.invalid'); "
                "print('input=/data/jobs/job/private/input.gbk'); "
                "print('A' * 60); "
                "print('MKWVTFISLLFLFSSAYSRGVFRRDTHKSEIAHRFKDLGE' * 2); "
                "pem_edge = chr(45) * 5; "
                "print(pem_edge + 'BEGIN ' + 'PRIVATE' + ' KEY' + pem_edge); "
                "print('synthetic-key-material'); "
                "print(pem_edge + 'END ' + 'PRIVATE' + ' KEY' + pem_edge); "
            )
            secrets = {
                "CLUSTERWEAVE_JOB_TOKEN_SECRET": "fake-job-secret",
                "CLUSTERWEAVE_SMTP_PASSWORD": "fake-smtp-secret",
                "CLUSTERWEAVE_ADMIN_TOKEN": "fake-admin-secret",
                "CLUSTERWEAVE_SUBMIT_TOKEN": "fake-submit-secret",
                "AWS_ACCESS_KEY_ID": "fake-access-key",
                "DOCKER_AUTH_CONFIG": "fake-docker-auth",
            }
            with mock.patch.dict(os.environ, secrets, clear=False):
                rc = await canonical_pipeline._stream_cmd(
                    [sys.executable, "-c", probe],
                    Path(tmp),
                    job,
                    {
                        "CUSTOM_API_KEY": "fake-api-secret",
                        "SAFE_STAGE_VALUE": "kept",
                    },
                )
            self.assertEqual(rc, 0)
            rendered = "\n".join(job.log_lines)
            self.assertIn("inherited=", rendered)
            self.assertNotIn("inherited=CLUSTERWEAVE", rendered)
            self.assertNotIn("inherited=CUSTOM_API_KEY", rendered)
            for marker in (
                "fake-job-secret",
                "fake-smtp-secret",
                "fake-admin-secret",
                "fake-submit-secret",
                "fake-api-secret",
                "fake-access-key",
                "fake-docker-auth",
                "fake-basic-value",
                "fake-cookie-value",
                "fake-signature-value",
                "fake-password-value",
                "fake-cli-token-value",
                "fake-userinfo-value",
                "ZmFrZS1wcml2YXRlLWtleS1ib2R5",
            ):
                self.assertNotIn(marker, rendered)
            self.assertIn("Authorization: [redacted]", rendered)
            self.assertIn("Cookie: [redacted]", rendered)
            self.assertIn("password=[redacted]", rendered)
            self.assertIn("--token [redacted]", rendered)
            self.assertIn("input=[private job path]", rendered)
            self.assertNotIn("/data/jobs", rendered)
            self.assertIn("[raw nucleotide sequence redacted]", rendered)
            self.assertIn("[raw protein sequence redacted]", rendered)
            self.assertIn("[private key redacted]", rendered)

    async def test_requested_phylogeny_runs_after_core_and_remains_nonfatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            for name in ("run_clusterweave.sh", "run_phylogeny.sh"):
                (repo / name).write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            (repo / "bin").mkdir()
            (repo / "bin" / "capture_external_artifacts.py").write_text(
                "#!/usr/bin/env python3\n", encoding="utf-8"
            )
            upload = root / "fungus.fna"
            upload.write_text(">contig\nACGT\n", encoding="utf-8")
            job_dir = root / "job"
            job = Job(id="job", name="demo")
            settings: dict[str, object] = {
                "project_name": "demo",
                "clusterweave_root": str(repo),
                "analysis_scope": "fungi",
                "run_genome_prep": False,
                "run_figures": False,
                "run_phylogeny": True,
                "phylogeny_required": False,
                "phylogeny_cpus": 99,
                "phylogeny_parallelism": 3,
                "phylogeny_max_families": 999,
                "phylogeny_max_sequences_per_family": 9999,
                "phylogeny_max_alignment_bytes": 999_999_999,
                "phylogeny_timeout_seconds": 999_999,
                "env_overrides": (
                    "RUN_PHYLOGENY=0\n"
                    "PHYLOGENY_CPUS=88\n"
                    "PHYLOGENY_PARALLELISM=77\n"
                    "PHYLOGENY_MAX_FAMILIES=9999\n"
                    "CLUSTERWEAVE_CHILD_DOCKER_CPUS=66\n"
                ),
            }
            events: list[tuple[str, str, list[str], dict[str, str]]] = []

            async def required(job, stage, cmd, cwd, env):
                events.append(("required", stage, list(cmd), dict(env)))

            async def optional(job, stage, cmd, cwd, env):
                events.append(("optional", stage, list(cmd), dict(env)))
                return False

            original_required = canonical_pipeline._run_required_stage
            original_optional = canonical_pipeline._run_optional_stage
            original_collect = canonical_pipeline._collect_result_files
            original_software = canonical_pipeline.GLOBAL_SOFTWARE_ROOT
            canonical_pipeline._run_required_stage = required
            canonical_pipeline._run_optional_stage = optional
            canonical_pipeline._collect_result_files = lambda *args, **kwargs: None
            canonical_pipeline.GLOBAL_SOFTWARE_ROOT = root / "software"
            try:
                await canonical_pipeline.run_pipeline(
                    job,
                    [upload],
                    job_dir,
                    cpus=6,
                    settings=settings,
                )
            finally:
                canonical_pipeline._run_required_stage = original_required
                canonical_pipeline._run_optional_stage = original_optional
                canonical_pipeline._collect_result_files = original_collect
                canonical_pipeline.GLOBAL_SOFTWARE_ROOT = original_software

            self.assertEqual(job.status, JobStatus.SUCCESS)
            self.assertEqual(
                [event[0] for event in events],
                ["required", "optional", "optional"],
            )
            self.assertEqual(events[0][1], "Running canonical ClusterWeave workflow")
            self.assertEqual(events[1][1], "Running optional sequence phylogeny")
            self.assertEqual(
                events[2][1], "Refreshing external artifact provenance"
            )
            self.assertTrue(events[1][2][-1].endswith("run_phylogeny.sh"))
            phylogeny_env = events[1][3]
            self.assertEqual(phylogeny_env["RUN_PHYLOGENY"], "1")
            self.assertEqual(phylogeny_env["PHYLOGENY_PARALLELISM"], "1")
            self.assertEqual(phylogeny_env["PHYLOGENY_AUTO_PREPARE"], "1")
            self.assertTrue(
                phylogeny_env["PHYLOGENY_PREPARE_HELPER"].endswith(
                    "/bin/prepare_phylogeny_families.py"
                )
            )
            self.assertTrue(
                phylogeny_env["PHYLOGENY_TOPOLOGY_RESULTS_TSV"].endswith(
                    "/data/results/demo/phylogeny/topology_comparison.tsv"
                )
            )
            self.assertEqual(phylogeny_env["PHYLOGENY_CPUS"], "6")
            self.assertEqual(phylogeny_env["CLUSTERWEAVE_CHILD_DOCKER_CPUS"], "6")
            self.assertEqual(phylogeny_env["PHYLOGENY_MAX_FAMILIES"], "100")
            self.assertEqual(
                phylogeny_env["PHYLOGENY_MAX_SEQUENCES_PER_FAMILY"], "1000"
            )
            self.assertEqual(
                phylogeny_env["PHYLOGENY_MAX_ALIGNMENT_BYTES"], "200000000"
            )
            self.assertEqual(phylogeny_env["PHYLOGENY_TIMEOUT_SECONDS"], "86400")
            self.assertTrue(
                phylogeny_env["PHYLOGENY_FAMILY_MANIFEST"].endswith(
                    "/data/results/demo/phylogeny_inputs/families.tsv"
                )
            )

    async def test_explicitly_required_phylogeny_failure_fails_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            for name in ("run_clusterweave.sh", "run_phylogeny.sh"):
                (repo / name).write_text(
                    "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
                )
            (repo / "bin").mkdir()
            (repo / "bin" / "capture_external_artifacts.py").write_text(
                "#!/usr/bin/env python3\n", encoding="utf-8"
            )
            upload = root / "fungus.fna"
            upload.write_text(">contig\nACGT\n", encoding="utf-8")
            job = Job(id="required-job", name="demo")
            events: list[str] = []

            async def required(job, stage, cmd, cwd, env):
                events.append(stage)
                if stage == "Running required sequence phylogeny":
                    raise RuntimeError("required phylogeny failed")

            async def optional(job, stage, cmd, cwd, env):
                self.assertEqual(
                    stage, "Refreshing external artifact provenance"
                )
                events.append(stage)
                return False

            original_required = canonical_pipeline._run_required_stage
            original_optional = canonical_pipeline._run_optional_stage
            original_collect = canonical_pipeline._collect_result_files
            original_software = canonical_pipeline.GLOBAL_SOFTWARE_ROOT
            canonical_pipeline._run_required_stage = required
            canonical_pipeline._run_optional_stage = optional
            canonical_pipeline._collect_result_files = lambda *args, **kwargs: None
            canonical_pipeline.GLOBAL_SOFTWARE_ROOT = root / "software"
            try:
                await canonical_pipeline.run_pipeline(
                    job,
                    [upload],
                    root / "job",
                    cpus=4,
                    settings={
                        "project_name": "demo",
                        "clusterweave_root": str(repo),
                        "analysis_scope": "fungi",
                        "run_genome_prep": False,
                        "run_figures": False,
                        "run_phylogeny": True,
                        "phylogeny_required": True,
                    },
                )
            finally:
                canonical_pipeline._run_required_stage = original_required
                canonical_pipeline._run_optional_stage = original_optional
                canonical_pipeline._collect_result_files = original_collect
                canonical_pipeline.GLOBAL_SOFTWARE_ROOT = original_software

            self.assertEqual(
                events,
                [
                    "Running canonical ClusterWeave workflow",
                    "Running required sequence phylogeny",
                    "Refreshing external artifact provenance",
                ],
            )
            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertEqual(job.error, "required phylogeny failed")

    async def test_integrated_evidence_is_terminal_bounded_and_nonfatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "bin").mkdir()
            for name in (
                "run_clusterweave.sh",
                "run_phylogeny.sh",
                "run_nplinker.sh",
                "run_integrated_evidence.sh",
            ):
                (repo / name).write_text(
                    "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
                )
            upload = root / "fungus.fna"
            upload.write_text(">contig\nACGT\n", encoding="utf-8")
            job = Job(id="evidence-job", name="demo")
            events: list[tuple[str, str, dict[str, str]]] = []

            async def required(job, stage, cmd, cwd, env):
                events.append(("required", stage, dict(env)))

            async def optional(job, stage, cmd, cwd, env):
                events.append(("optional", stage, dict(env)))
                return False

            original_required = canonical_pipeline._run_required_stage
            original_optional = canonical_pipeline._run_optional_stage
            original_collect = canonical_pipeline._collect_result_files
            original_software = canonical_pipeline.GLOBAL_SOFTWARE_ROOT
            canonical_pipeline._run_required_stage = required
            canonical_pipeline._run_optional_stage = optional
            canonical_pipeline._collect_result_files = lambda *args, **kwargs: None
            canonical_pipeline.GLOBAL_SOFTWARE_ROOT = root / "software"
            try:
                await canonical_pipeline.run_pipeline(
                    job,
                    [upload],
                    root / "job",
                    cpus=4,
                    settings={
                        "project_name": "demo",
                        "clusterweave_root": str(repo),
                        "analysis_scope": "fungi",
                        "run_genome_prep": False,
                        "run_figures": False,
                        "run_phylogeny": True,
                        "run_nplinker": True,
                        "target_genome": "fungus",
                        "run_cross_kingdom_evidence": True,
                        "cross_kingdom_evidence_max_candidates": 999,
                        "env_overrides": (
                            "RUN_CROSS_KINGDOM_EVIDENCE=0\n"
                            "CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES=1\n"
                            "CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV=/private/canonical.tsv\n"
                            "RUN_HGT_EVIDENCE=0\n"
                            "HGT_EVIDENCE_MAX_CANDIDATES=1\n"
                            "HGT_EVIDENCE_CANDIDATES_TSV=/private/input.tsv\n"
                            "HGT_EVIDENCE_OUTPUT_DIR=/private/output\n"
                        ),
                    },
                )
            finally:
                canonical_pipeline._run_required_stage = original_required
                canonical_pipeline._run_optional_stage = original_optional
                canonical_pipeline._collect_result_files = original_collect
                canonical_pipeline.GLOBAL_SOFTWARE_ROOT = original_software

            self.assertEqual(job.status, JobStatus.SUCCESS)
            self.assertEqual(
                [(kind, stage) for kind, stage, _ in events],
                [
                    ("required", "Running canonical ClusterWeave workflow"),
                    ("optional", "Running optional sequence phylogeny"),
                    ("required", "Running optional NPLinker follow-up"),
                    ("optional", "Running optional cross-kingdom evidence"),
                ],
            )
            evidence_env = events[-1][2]
            self.assertEqual(evidence_env["RUN_CROSS_KINGDOM_EVIDENCE"], "1")
            self.assertEqual(
                evidence_env["CROSS_KINGDOM_EVIDENCE_MAX_CANDIDATES"], "100"
            )
            self.assertEqual(evidence_env["CROSS_KINGDOM_EVIDENCE_AUTO_SELECT"], "1")
            self.assertTrue(
                evidence_env["CROSS_KINGDOM_EVIDENCE_CANDIDATES_TSV"].endswith(
                    "/data/results/demo/summary/cross_kingdom_candidates.tsv"
                )
            )
            self.assertTrue(
                evidence_env["CROSS_KINGDOM_EVIDENCE_CROSSWALK_TSV"].endswith(
                    "/data/results/demo/summary/candidate_bgc_gcf_crosswalk.tsv"
                )
            )
            self.assertTrue(
                evidence_env["CROSS_KINGDOM_EVIDENCE_OUTPUT_DIR"].endswith(
                    "/data/results/demo/integrated_evidence"
                )
            )
            self.assertTrue(
                evidence_env["CROSS_KINGDOM_EVIDENCE_TOPOLOGY_TSV"].endswith(
                    "/data/results/demo/phylogeny/topology_comparison.tsv"
                )
            )
            self.assertTrue(
                evidence_env["CROSS_KINGDOM_EVIDENCE_TOPOLOGY_MERGER"].endswith(
                    "/bin/merge_topology_evidence.py"
                )
            )
            self.assertNotIn("RUN_HGT_EVIDENCE", evidence_env)

    def test_canonical_collector_uses_exact_shared_phylogeny_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / "job"
            results = job_root / "data" / "results" / "demo"
            files = {
                "figures/phylogeny/clusterweave_taxon_tree.svg": "<svg />\n",
                "figures/phylogeny/clusterweave_tree_bundle.zip": "PK fixture\n",
                "figures/phylogeny/clusterweave_taxon_tree_extra.svg": "<svg />\n",
                "figures/phylogeny/alignment.fasta": ">private\nACGT\n",
                "phylogeny/topology_comparison.tsv": "gcf_id\ttopology_discordance\nGCF_1\tsupported\n",
                "phylogeny_inputs/families.tsv": "family_id\tinput_path\nprivate\t/private/family.faa\n",
                "phylogeny_inputs/sequence_taxon_map.tsv": "sequence_id\tgenome_id\nseq1\tprivate\n",
                "summary_tables/genome_taxon_manifest.tsv": "genome_id\n",
                "antismash/genome/raw.antismash.json": '{"records":[]}\n',
                "integrated_evidence/cross_kingdom_evidence.tsv": "candidate_id\n",
                "integrated_evidence/cross_kingdom_evidence.json": '{"candidates":[]}\n',
                "integrated_evidence/cross_kingdom_evidence_cards.txt": "cards\n",
                "integrated_evidence/putative_transfer_evidence.tsv": "historical\n",
                "integrated_evidence/putative_transfer_evidence.json": '{"historical":true}\n',
                "integrated_evidence/putative_transfer_evidence_cards.txt": "historical cards\n",
                "integrated_evidence/putative_transfer_evidence-copy.json": "{}\n",
            }
            for relative, content in files.items():
                path = results / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            layout = ProjectLayout(
                project_name="demo",
                repo_root=REPO_ROOT,
                data_root=job_root / "data",
                genome_root=job_root / "data" / "genomes" / "fungi" / "demo",
                results_root=results,
                software_root=job_root / "software",
                work_root=job_root / "work",
                downloads_root=job_root / "downloads",
            )
            job = Job(id="job", name="demo")

            _collect_result_files(job, job_root, layout)

            public = set(job.result_files)
            prefix = "data/results/demo/"
            self.assertIn(
                prefix + "figures/phylogeny/clusterweave_taxon_tree.svg", public
            )
            self.assertIn(
                prefix + "figures/phylogeny/clusterweave_tree_bundle.zip", public
            )
            self.assertIn(
                prefix + "summary_tables/genome_taxon_manifest.tsv", public
            )
            self.assertNotIn(
                prefix + "figures/phylogeny/clusterweave_taxon_tree_extra.svg",
                public,
            )
            self.assertNotIn(
                prefix + "figures/phylogeny/alignment.fasta", public
            )
            self.assertNotIn(prefix + "phylogeny/topology_comparison.tsv", public)
            self.assertNotIn(prefix + "phylogeny_inputs/families.tsv", public)
            self.assertNotIn(
                prefix + "phylogeny_inputs/sequence_taxon_map.tsv", public
            )
            self.assertNotIn(
                prefix + "antismash/genome/raw.antismash.json", public
            )
            for filename in (
                "cross_kingdom_evidence.tsv",
                "cross_kingdom_evidence.json",
                "cross_kingdom_evidence_cards.txt",
                "putative_transfer_evidence.tsv",
                "putative_transfer_evidence.json",
                "putative_transfer_evidence_cards.txt",
            ):
                self.assertIn(prefix + "integrated_evidence/" + filename, public)
            self.assertNotIn(
                prefix
                + "integrated_evidence/putative_transfer_evidence-copy.json",
                public,
            )

    def test_worker_and_web_images_copy_shared_result_policy(self) -> None:
        for dockerfile in ("Dockerfile.worker", "Dockerfile.web"):
            text = (REPO_ROOT / dockerfile).read_text(encoding="utf-8")
            self.assertIn("COPY web/result_policy.py /app/result_policy.py", text)


if __name__ == "__main__":
    unittest.main()
