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
            ["Run reported an error", "Updated summary outputs"],
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
