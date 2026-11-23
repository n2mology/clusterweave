from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from scientific_profiles import (  # noqa: E402
    default_detector_profile,
    default_prediction_method,
    summarize_profiles,
)
from taxon_routing import summarize_taxon_routes  # noqa: E402
from canonical_pipeline import _route_summaries  # noqa: E402


class ScientificProfileTests(unittest.TestCase):
    def test_accession_defaults_and_uploaded_cds_choices(self) -> None:
        for group, annotated, method, detectors in (
            ("fungi", False, "funannotate", "antismash+funbgcex"),
            ("fungi", True, "existing_cds", "antismash+funbgcex"),
            ("bacteria", False, "prodigal", "antismash"),
            ("bacteria", True, "prodigal", "antismash"),
        ):
            with self.subTest(group=group, annotated=annotated):
                self.assertEqual(default_prediction_method(group),
                                 "prodigal" if group == "bacteria" else "funannotate")
                self.assertEqual(
                    default_prediction_method(group, has_annotated_genbank=annotated),
                    method,
                )
                self.assertEqual(default_detector_profile(group), detectors)

    def test_counts_do_not_infer_annotation_from_taxon_or_detector_profile(self) -> None:
        self.assertEqual(
            summarize_profiles(
                iter(["fungi", "fungi", "bacteria", None, "FUNGI", []]),
                iter(["existing_cds", "custom", "prodigal", "funannotate", "FUNANNOTATE", []]),
            ),
            (
                {"fungi": 2, "bacteria": 1, "total": 3},
                {"funannotate": 1, "prodigal": 1, "antismash": 3, "funbgcex": 2,
                 "funbgcex_not_applicable_taxon": 1, "bigscape": 3, "taxon_tree_figure": 3},
            ),
        )
        self.assertEqual(
            summarize_taxon_routes([{}, {"prediction_method": "funannotate"}]),
            (
                {"fungi": 0, "bacteria": 0, "total": 0},
                {"funannotate": 1, "prodigal": 0, "antismash": 0, "funbgcex": 0,
                 "funbgcex_not_applicable_taxon": 0, "bigscape": 0, "taxon_tree_figure": 0},
            ),
        )
        with self.assertRaises(KeyError):
            _route_summaries([{}])
        self.assertEqual(_route_summaries([{"route_status": "invalid"}]),
                         summarize_profiles([], []))
        self.assertEqual(summarize_taxon_routes([]), summarize_profiles([], []))

    def test_declared_flat_image_imports_without_repository_or_site_packages(self) -> None:
        for service in ("web", "worker"):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as tmp:
                flat = Path(tmp)
                for line in (REPO_ROOT / f"Dockerfile.{service}").read_text().splitlines():
                    if not line.startswith("COPY "):
                        continue
                    fields = shlex.split(line)
                    if not fields[-1].startswith("/app/"):
                        continue
                    for source in fields[1:-1]:
                        path = REPO_ROOT / source
                        if path.suffix == ".py":
                            shutil.copyfile(path, flat / path.name)
                script = '''
import pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd()))
import scientific_profiles, taxon_routing
assert pathlib.Path(scientific_profiles.__file__).parent == pathlib.Path.cwd()
assert pathlib.Path(taxon_routing.__file__).parent == pathlib.Path.cwd()
assert taxon_routing.build_taxon_routes("fungi", [{"input_key": "x", "has_annotated_genbank": True}], [])[0]["prediction_method"] == "existing_cds"
'''
                if service == "worker":
                    script += '''
import canonical_pipeline
assert pathlib.Path(canonical_pipeline.__file__).parent == pathlib.Path.cwd()
rows = canonical_pipeline._normalize_taxon_routes({"taxon_routes": [{"input_key": "x", "taxon_group": "bacteria"}]})
assert rows[0]["prediction_method"] == "prodigal"
assert rows[0]["detector_profile"] == "antismash"
assert canonical_pipeline._route_summaries(rows)[1]["prodigal"] == 1
'''
                result = subprocess.run(
                    [sys.executable, "-I", "-S", "-B", "-c", script], cwd=flat,
                    env={"PATH": os.defpath, "DATA_DIR": str(flat / "data")},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
