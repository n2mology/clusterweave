from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"


class ProgressProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        self.inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            self.inserted_web_path = True
        for name in ["app", "job_store", "notifications"]:
            sys.modules.pop(name, None)
        self.app = importlib.import_module("app")

    def tearDown(self) -> None:
        for name in ["app", "job_store", "notifications"]:
            sys.modules.pop(name, None)
        if self.inserted_web_path:
            sys.path.remove(str(WEB_DIR))
        if self.old_data_dir is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.old_data_dir
        self.tmp.cleanup()

    @staticmethod
    def mixed_job(status: str = "running") -> dict[str, object]:
        return {
            "id": "projection-job",
            "status": status,
            "taxon_routes": [
                {
                    "genome_id": "fungus_one",
                    "taxon_group": "fungi",
                    "taxon_source": "user_declaration",
                    "prediction_method": "funannotate",
                },
                {
                    "genome_id": "bacteria_Bacillus_subtilis_168",
                    "taxon_group": "bacteria",
                    "taxon_source": "ncbi",
                    "organism_name": "Bacillus subtilis 168",
                    "source_accession": "GCF_000009045.1",
                },
                {
                    "genome_id": "fungus_existing_cds",
                    "taxon_group": "fungi",
                    "taxon_source": "ncbi",
                    "prediction_method": "existing_cds",
                },
            ],
        }

    def test_plant_annotation_rejection_is_terminal_without_success_and_resets(self):
        job = {'id':'rejection', 'status':'running', 'taxon_routes':[
            {'genome_id':'Arabidopsis_thaliana','taxon_group':'plants','taxon_source':'ncbi'}]}
        start = 'GENOME_PROGRESS genome=Arabidopsis_thaliana stage=annotation percent=0 bar=[] message="Starting genome"'
        for detail in ['Supplied plant annotation incompatible: NC_003070.9 / CDS 3258 / TPS3 / NP_173143.4: unexplained_translation_mismatch', 'Annotation required: supply matching translated GenBank']:
            failure = 'GENOME_PROGRESS genome=Arabidopsis_thaliana stage=annotation percent=100 bar=[] message="'+detail+'"'
            state = self.app.public_genome_progress(job,[start,failure])[0]
            self.assertEqual(state['status'],'warning')
            self.assertTrue(state['terminal'])
            self.assertEqual(state['stage'],'plantismash')
            self.assertIn('plantiSMASH not run',state['message'])
            self.assertEqual(state['stage_states']['plantismash']['status'],'failed')
            self.assertEqual(state['stage_states']['complete']['status'],'queued')
            self.assertEqual(state['progress_label'],'')
            restarted = self.app.public_genome_progress(job,[start,failure,start,
                'TOOL_RAW genome=Arabidopsis_thaliana tool=plantismash stream=stderr Supplied plant annotation incompatible'])[0]
            self.assertEqual(restarted['status'],'running')
            self.assertEqual(restarted['percent'],0)
            self.assertFalse(restarted['terminal'])

    def test_terminal_annotation_failure_closes_actual_fungal_annotator(self):
        job={'id':'annotation-failure','status':'running','taxon_routes':[
            {'genome_id':'Fungus','taxon_group':'fungi','taxon_source':'ncbi'}]}
        lines=['GENOME_ANNOTATION_DECISION genome=Fungus required=yes method=funannotate message="Preparing annotation"',
               'TOOL_PROGRESS genome=Fungus tool=funannotate phase=annotation message="Training gene models"',
               'GENOME_PROGRESS genome=Fungus stage=annotation percent=100 bar=[] message="Dropped: annotation_fallbacks_failed"']
        state=self.app.public_genome_progress(job,lines)[0]
        self.assertEqual(state['status'],'warning')
        self.assertTrue(state['terminal'])
        self.assertEqual(state['stage_states']['funannotate']['status'],'failed')
        self.assertEqual(state['stage_states']['complete']['status'],'queued')

    def test_figure_notification_does_not_expose_private_context(self):
        lines=['[08:00:00] Stage 4/4: running run_figures.sh',
               '[08:00:01] Wrote figure outputs /analysis/local_only/v1.1.0/private-repair/figure.svg',
               '[08:00:02] TOOL_RAW genome=plant tool=plantismash stream=stderr private-repeat2 /analysis/local_only/context']
        result=self.app.public_progress_projection(self.mixed_job(),lines)
        visible=json.dumps(result.public_events)
        self.assertIn('Generated analysis figures',visible)
        for token in ['local_only','v1.1.0','private-repeat2','Updated figure outputs','TOOL_RAW']:
            self.assertNotIn(token,visible)

    def test_sparse_context_preserves_taxon_identity_across_restart(self):
        store = importlib.import_module("job_store")
        job = self.mixed_job()
        job["taxon_routes"][1]["organism_name"] = "Bacillus subtilis"
        genome = "bacteria_Bacillus_subtilis_168"
        route = f'TAXON_ROUTE genome={genome} taxon=bacteria source=ncbi status=accepted message="prediction=prodigal detector=antismash"'
        start = f'GENOME_PROGRESS genome={genome} stage=annotation percent=0 bar=[----------] message="Starting genome"'
        record = lambda name, ordinal, message: f'ANTISMASH_RECORD_PROGRESS genome={genome} record={name} ordinal={ordinal}/2 percent=50 bar=[#####-----] message="{message}"'
        lines = [route, start, record("R2", 2, "antiSMASH record shard complete")]
        restarted = lines + [
            record("R1", 1, "antiSMASH record shard complete"),
            f'GENOME_PROGRESS genome={genome} stage=annotation percent=100 bar=[##########] message="Genome workflow complete"',
            start,
            record("R2", 2, "antiSMASH record shard running"),
            record("R1", 1, "antiSMASH record shard complete"),
        ]
        for history in [lines, restarted]:
            with self.subTest(restarted=history is restarted):
                checkpoints = {}
                for index, line in enumerate(history[:-1]):
                    store._remember_progress(checkpoints, line, index)
                context = {row["index"]: row["line"] for row in checkpoints.values()}
                context[len(history) - 1] = history[-1]
                sparse = [line for _, line in sorted(context.items())]
                full_rows = self.app.public_genome_progress(job, history)
                self.assertEqual(full_rows, self.app.public_genome_progress(job, sparse))
                state = next(row for row in full_rows if row["genome_id"] == genome)
                self.assertEqual(state["display_label"], "Bacillus subtilis 168")
                self.assertFalse(state["terminal"])
                self.assertEqual(state["region_progress"]["processed"], 1)
                if history is restarted:
                    self.assertEqual(state["region_progress"]["active"], 1)

    @staticmethod
    def mixed_lines() -> list[str]:
        return [
            "[08:00:00] Stage 1/4: running run_annotation_and_detection.sh",
            "[08:00:01] Genomes to process (3): fungus_one, bacteria_Bacillus_subtilis_168, fungus_existing_cds",
            "[08:00:02] [1/3] genome=fungus_one",
            "[08:00:03] fungus_one: running antiSMASH (outdir=/data/jobs/private)",
            '[08:00:04] GENOME_ANNOTATION_DECISION genome=fungus_one required=yes method=funannotate message="Prediction required"',
            '[08:00:05] TOOL_PROGRESS genome=fungus_one tool=antismash phase=detect message="Scanning protein domains"',
            "[08:00:06] TOOL_HEARTBEAT genome=fungus_one tool=antismash phase=detect elapsed=600s",
            '[08:00:07] ANTISMASH_RECORD_PROGRESS genome=fungus_one record=private_record ordinal=1/2 percent=40 bar=[########------------] message="antiSMASH record shard complete"',
            '[08:00:08] GENOME_PROGRESS genome=fungus_one stage=funbgcex percent=100 bar=[####################] message="FunBGCeX complete"',
            '[08:00:09] NCBI_DOWNLOAD_PROGRESS accession=GCF_000009045.1 taxon=bacteria status=complete percent=8 message="NCBI genome download complete"',
            '[08:00:10] GENOME_PROGRESS genome=bacteria_Bacillus_subtilis_168 stage=antismash percent=100 bar=[####################] message="BGC detection complete"',
            "[08:00:11] fungus_one: antiSMASH OK",
        ]

    def test_input_adapter_classifies_structured_and_legacy_records(self) -> None:
        events = self.app.public_progress_events(self.mixed_lines())
        self.assertEqual(
            [event.kind for event in events],
            [
                "stage",
                "genomes_queued",
                "genome_started",
                "tool_started",
                "annotation_decision",
                "tool",
                "tool",
                "antismash_record",
                "genome_progress",
                "download",
                "genome_progress",
                "tool_finished",
            ],
        )
        self.assertEqual(events[0].values, {"stage": "annotation"})
        self.assertEqual(events[4].values["method"], "funannotate")
        self.assertEqual(events[5].values["kind"], "progress")
        self.assertEqual(events[6].values["kind"], "heartbeat")
        error_events = self.app.public_activity_from_logs(
            "projection-job",
            ['[08:00:00] GENOME_ANNOTATION_DECISION genome=fungus_one required=yes method=funannotate message="FAILED annotation"'],
        )
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["title"], "Run reported an error")

    def test_verified_cache_and_retrieval_labels_follow_real_work(self):
        job = self.mixed_job()
        job["taxon_routes"][2]["source_accession"] = "GCA_999999997.1"
        lines = [
            'ACCESSION_CACHE genome=fungus_one stage=annotation_detection outcome=hit',
            'GENOME_PROGRESS genome=fungus_one stage=annotation percent=100 bar=[##########] message="Reused verified annotation and BGC detection"',
            'NCBI_DOWNLOAD_PROGRESS accession=GCF_000009045.1 taxon=bacteria status=complete percent=8 message="NCBI genome download complete"',
            'NCBI_DOWNLOAD_PROGRESS accession=GCF_000009045.1 taxon=bacteria status=complete percent=8 message="Accession snapshot ready"',
            'ACCESSION_CACHE genome=GCA_999999997.1 stage=retrieval outcome=hit',
        ]
        def rows(): return {r["genome_id"]: r for r in self.app.public_genome_progress(job, lines)}
        states = rows()
        self.assertEqual(states["fungus_one"]["progress_label"], "CACHED")
        self.assertTrue(states["fungus_one"]["terminal"])
        self.assertEqual(states["bacteria_Bacillus_subtilis_168"]["progress_label"], "GENOME DOWNLOADED")
        self.assertFalse(states["bacteria_Bacillus_subtilis_168"]["terminal"])
        self.assertEqual(states["fungus_existing_cds"]["progress_label"], "GENOME READY")
        self.assertIn("input ready", states["fungus_existing_cds"]["message"])
        lines += ['TOOL_PROGRESS genome=bacteria_Bacillus_subtilis_168 tool=prodigal phase=predict message="Predicting genes"']
        self.assertEqual(rows()["bacteria_Bacillus_subtilis_168"]["progress_label"], "ANNOTATING")
        lines += ['TOOL_PROGRESS genome=bacteria_Bacillus_subtilis_168 tool=antismash phase=detect message="Scanning domains"']
        self.assertEqual(rows()["bacteria_Bacillus_subtilis_168"]["progress_label"], "DETECTING")
        lines += ['GENOME_PROGRESS genome=bacteria_Bacillus_subtilis_168 stage=annotation percent=100 bar=[##########] message="Genome workflow complete"']
        self.assertEqual(rows()["bacteria_Bacillus_subtilis_168"]["progress_label"], "COMPLETE")
        lines += ['GENOME_PROGRESS genome=fungus_one stage=annotation percent=0 bar=[----------] message="Starting genome"']
        self.assertEqual(rows()["fungus_one"]["progress_label"], "ANNOTATING")
        self.assertFalse(rows()["fungus_one"]["terminal"])
        lines += ['GENOME_PROGRESS genome=fungus_one stage=annotation percent=100 bar=[##########] message="Genome dropped: annotation failed"']
        self.assertEqual(rows()["fungus_one"]["progress_label"], "")
        self.assertEqual(rows()["fungus_one"]["status"], "warning")

    def test_rerun_and_advisory_cache_presence_do_not_claim_a_hit(self):
        job = self.mixed_job()
        lines = ['ACCESSION_CACHE genome=fungus_one stage=annotation_detection outcome=hit',
                 'Re-queued existing job with selected stage rerun settings.']
        job["last_rerun_settings"] = {"run_annotation": True}
        states = self.app.public_genome_progress(job, lines)
        self.assertTrue(all(r["progress_label"] == "" for r in states))
        job["last_rerun_settings"] = {"run_annotation": False}
        self.assertEqual(self.app.public_genome_progress(job, lines)[0]["progress_label"], "CACHED")
        lines = ['ACCESSION_CACHE genome=fungus_one stage=annotation_detection outcome=miss',
                 'candidate_available genome=fungus_one',
                 'TOOL_RAW genome=fungus_one tool=antismash phase=detect message="ACCESSION_CACHE genome=fungus_one stage=annotation_detection outcome=hit"']
        self.assertTrue(all(r["progress_label"] != "CACHED" for r in self.app.public_genome_progress(job, lines)))

    def test_sparse_context_preserves_job_rerun_boundary(self):
        store = importlib.import_module("job_store")
        for run_annotation in (True, False):
            for stage_restarted in (True, False):
                with self.subTest(run_annotation=run_annotation, stage_restarted=stage_restarted):
                    job = self.mixed_job()
                    job["last_rerun_settings"] = {"run_annotation": run_annotation}
                    history = [
                        "Stage 1/4: running annotation",
                        "ACCESSION_CACHE genome=fungus_one stage=annotation_detection outcome=hit",
                        "Stage 1/4: complete",
                        "Re-queued existing job with selected stage rerun settings.",
                    ]
                    if stage_restarted:
                        history.append("Stage 1/4: running annotation")
                    history += ["ordinary diagnostic"] * 21
                    context = {}
                    for index, line in enumerate(history[:-20]):
                        store._remember_progress(context, line, index)
                    sparse = [row["line"] for row in sorted(context.values(), key=lambda row: row["index"])] + history[-20:]
                    self.assertEqual(self.app.public_genome_progress(job, history), self.app.public_genome_progress(job, sparse))
                    state = self.app.public_genome_progress(job, sparse)[0]
                    self.assertEqual(state["progress_label"], "" if run_annotation else "CACHED")
                    self.assertIn("Stage 1/4: complete", sparse)
                    self.assertLess(sparse.index("Stage 1/4: complete"), sparse.index("Re-queued existing job with selected stage rerun settings."))
        context = {}
        store._remember_progress(context, "TOOL_RAW Re-queued existing job with selected stage rerun settings.", 0)
        self.assertEqual(context, {})

    def test_combined_projection_matches_both_compatibility_delegates(self) -> None:
        job = self.mixed_job()
        lines = self.mixed_lines()
        projection = self.app.public_progress_projection(job, lines)

        self.assertEqual(
            projection.public_events,
            self.app.public_activity_from_logs("projection-job", lines),
        )
        self.assertEqual(
            projection.genome_progress,
            self.app.public_genome_progress(job, lines),
        )
        genomes = {row["genome_id"]: row for row in projection.genome_progress}
        self.assertEqual(genomes["fungus_one"]["status"], "complete")
        self.assertEqual(genomes["fungus_one"]["annotation_method"], "funannotate")
        self.assertEqual(genomes["bacteria_Bacillus_subtilis_168"]["tool"], "antiSMASH")
        self.assertEqual(
            genomes["bacteria_Bacillus_subtilis_168"]["display_label"],
            "Bacillus subtilis 168",
        )
        self.assertEqual(genomes["fungus_existing_cds"]["annotation_method"], "existing_cds")
        rendered = json.dumps(
            {
                "public_events": projection.public_events,
                "genome_progress": projection.genome_progress,
            }
        )
        self.assertNotIn("/data/jobs", rendered)
        self.assertNotIn("private_record", rendered)

    def test_duplicate_limit_restart_and_failure_semantics_are_preserved(self) -> None:
        job = self.mixed_job()
        lines = [
            '[08:00:00] GENOME_PROGRESS genome=fungus_one stage=funbgcex percent=100 bar=[####################] message="Dropped: old /data/jobs/private failure"',
            '[09:00:00] GENOME_PROGRESS genome=fungus_one stage=annotation percent=0 bar=[--------------------] message="Starting annotation and BGC prediction"',
            '[09:00:01] GENOME_PROGRESS genome=fungus_one stage=annotation percent=25 bar=[#####---------------] message="Predicting genes"',
            "[09:00:02] FATAL failed with exit code 2 at /data/jobs/private",
        ]
        lines.extend(f"[09:01:{index % 60:02d}] Wrote summary table {index}" for index in range(45))
        lines.append("[09:02:00] Wrote summary table 44")

        projection = self.app.public_progress_projection(job, lines)
        genome = next(row for row in projection.genome_progress if row["genome_id"] == "fungus_one")
        self.assertEqual(genome["status"], "running")
        self.assertEqual(genome["percent"], 25)
        self.assertNotIn("warning_tool", genome)
        self.assertEqual(len(projection.public_events), 2)
        self.assertEqual(
            [event["title"] for event in projection.public_events],
            ["Run reported an error", "Generated summary tables"],
        )
        self.assertNotIn(
            "/data/jobs",
            json.dumps({"public_events": projection.public_events, "genome_progress": projection.genome_progress}),
        )

        bounded = self.app.public_progress_projection(
            job,
            [
                f"[10:00:{index % 60:02d}] Staged genome input: /data/jobs/private/input_{index:02d}.fna"
                for index in range(45)
            ],
        ).public_events
        self.assertEqual(len(bounded), self.app.PUBLIC_ACTIVITY_LIMIT)
        self.assertEqual(bounded[0]["meta"], "input_05")
        self.assertEqual(bounded[-1]["meta"], "input_44")
        self.assertNotIn("/data/jobs", json.dumps(bounded))

    def test_job_payload_decodes_one_event_sequence(self) -> None:
        job = self.mixed_job()
        lines = self.mixed_lines()
        with (
            mock.patch.object(self.app, "public_activity_projection_lines", return_value=lines),
            mock.patch.object(
                self.app,
                "public_progress_events",
                wraps=self.app.public_progress_events,
            ) as decode,
        ):
            payload = self.app.job_payload(
                job,
                admin=False,
                include_public_events=True,
                include_results=False,
            )

        self.assertEqual(decode.call_count, 1)
        self.assertEqual(payload["public_events"], self.app.public_progress_projection(job, lines).public_events)
        self.assertEqual(payload["genome_progress"], self.app.public_progress_projection(job, lines).genome_progress)


if __name__ == "__main__":
    unittest.main()
