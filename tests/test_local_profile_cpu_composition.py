from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
INIT_SCRIPT = REPO_ROOT / "bin" / "init_local_instance.sh"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


class LocalProfileCpuCompositionTests(unittest.TestCase):
    def test_every_initialized_public_plan_fits_worker_admission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_root = Path(tmp) / "clusterweave"
            local_bin = local_root / "bin"
            local_bin.mkdir(parents=True)
            local_init = local_bin / INIT_SCRIPT.name
            shutil.copy2(INIT_SCRIPT, local_init)
            subprocess.run(
                ["bash", str(local_init)],
                cwd=local_root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            generated_env = local_root / ".env"
            initialized = read_dotenv(generated_env)
            compose_environment = os.environ.copy()
            for key in initialized:
                compose_environment.pop(key, None)

            rendered = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    str(generated_env),
                    "-f",
                    str(COMPOSE_FILE),
                    "config",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                env=compose_environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            composition = json.loads(rendered.stdout)

        web_environment = composition["services"]["web"]["environment"]
        worker_service = composition["services"]["worker"]
        worker_environment = worker_service["environment"]
        worker_cpu_limit = int(worker_service["cpus"])
        worker_memory_limit_mb = int(worker_service["mem_limit"]) // (1024 * 1024)

        local_template = read_dotenv(REPO_ROOT / "config" / "local.env.template")
        self.assertEqual(local_template["CLUSTERWEAVE_MAX_CPUS_PER_JOB"], "4")
        self.assertEqual(local_template["CLUSTERWEAVE_WORKER_CPU_LIMIT"], "4")

        self.assertEqual(initialized["CLUSTERWEAVE_MAX_CPUS_PER_JOB"], "4")
        self.assertEqual(initialized["CLUSTERWEAVE_WORKER_CPU_LIMIT"], "4")
        self.assertEqual(web_environment["CLUSTERWEAVE_MAX_CPUS_PER_JOB"], "4")
        self.assertEqual(worker_cpu_limit, 4)
        self.assertEqual(worker_environment["PIPELINE_CPUS"], "4")

        defaults = (REPO_ROOT / "config" / "defaults.env").read_text(
            encoding="utf-8"
        )
        self.assertIn("# CLUSTERWEAVE_MAX_CPUS_PER_JOB=4", defaults)
        self.assertIn("# CLUSTERWEAVE_WORKER_CPU_LIMIT=4", defaults)
        self.assertIn(
            'CLUSTERWEAVE_MAX_CPUS_PER_JOB: "${CLUSTERWEAVE_MAX_CPUS_PER_JOB:-4}"',
            COMPOSE_FILE.read_text(encoding="utf-8"),
        )

        module_names = ["app", "job_store", "notifications", "worker"]
        old_modules = {name: sys.modules.get(name) for name in module_names}
        inserted_web_path = False
        if str(WEB_DIR) not in sys.path:
            sys.path.insert(0, str(WEB_DIR))
            inserted_web_path = True
        for name in module_names:
            sys.modules.pop(name, None)

        runtime_tmp = tempfile.TemporaryDirectory()
        process_environment = {
            **{key: str(value) for key, value in web_environment.items()},
            **{key: str(value) for key, value in worker_environment.items()},
            "DATA_DIR": runtime_tmp.name,
        }
        try:
            with mock.patch.dict(os.environ, process_environment, clear=False):
                app = importlib.import_module("app")
                worker = importlib.import_module("worker")
                with mock.patch.object(app.os, "cpu_count", return_value=64):
                    accepted_cpu_limit = app.public_cpu_limit()
                    self.assertEqual(accepted_cpu_limit, worker_cpu_limit)

                    maximum_genomes = app.MAX_ACCESSIONS + app.MAX_GENOME_FILES
                    for cpus in range(1, accepted_cpu_limit + 1):
                        for genome_count in range(1, maximum_genomes + 1):
                            for run_phylogeny in (False, True):
                                plan = app.hosted_resource_plan(
                                    cpus,
                                    genome_count,
                                    {
                                        "run_phylogeny": run_phylogeny,
                                        "phylogeny_cpus": cpus,
                                    },
                                )
                                estimate = worker.estimate_job_resources(
                                    cpus,
                                    plan.as_settings(),
                                    genome_count,
                                    memory_formula=worker.WORKER_MEMORY_FORMULA,
                                )
                                reservation = worker.JobResourceReservation(
                                    cpu_slots=max(cpus, estimate.cpu_slots),
                                    memory_mb=estimate.memory_mb,
                                )
                                admission = worker.ResourceAdmission(
                                    cpu_budget=worker_cpu_limit,
                                    memory_budget_mb=worker_memory_limit_mb,
                                    max_jobs=1,
                                )
                                reason = admission.capacity_reason(reservation)
                                self.assertIsNone(
                                    reason,
                                    (
                                        f"{cpus} CPU, {genome_count} genome, "
                                        f"phylogeny={run_phylogeny}: {reason}"
                                    ),
                                )
                                self.assertTrue(
                                    admission.reserve(
                                        "synthetic-composition-job", reservation
                                    )
                                )
        finally:
            for name in module_names:
                sys.modules.pop(name, None)
                previous = old_modules[name]
                if previous is not None:
                    sys.modules[name] = previous
            if inserted_web_path:
                sys.path.remove(str(WEB_DIR))
            runtime_tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
