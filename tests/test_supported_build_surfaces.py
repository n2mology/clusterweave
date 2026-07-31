from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_DOCKERFILES = {
    "web": "Dockerfile.web",
    "worker": "Dockerfile.worker",
}
SERVICE_ENTRYPOINTS = {
    "web": "web/entrypoint-web.sh",
    "worker": "web/entrypoint-worker.sh",
}


def text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def public_paths() -> set[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(REPO_ROOT / "bin" / "check_public_release.py"),
            "--list-files0",
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        member.decode("utf-8")
        for member in result.stdout.split(b"\0")
        if member
    }


def worker_clusterweave_copy_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in text(SERVICE_DOCKERFILES["worker"]).splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "COPY" and fields[2].startswith(
            "/clusterweave/"
        ):
            pairs.append((fields[1], fields[2]))
    return pairs


class SupportedBuildSurfaceTests(unittest.TestCase):
    def test_retained_service_images_have_named_consumers(self) -> None:
        local_profile = text("docker-compose.yml")
        publish_workflow = text(".github/workflows/publish-ghcr.yml")
        external_profile = text("clusterweave.yml")

        self.assertEqual(
            set(re.findall(r"^\s+dockerfile:\s+(\S+)\s*$", local_profile, re.MULTILINE)),
            set(SERVICE_DOCKERFILES.values()),
        )
        self.assertEqual(
            set(re.findall(r"^\s+dockerfile:\s+(\S+)\s*$", publish_workflow, re.MULTILINE)),
            set(SERVICE_DOCKERFILES.values()),
        )
        self.assertEqual(
            set(
                re.findall(
                    r"^\s+image:\s+ghcr\.io/n2mology/clusterweave-(web|worker):",
                    external_profile,
                    re.MULTILINE,
                )
            ),
            set(SERVICE_DOCKERFILES),
        )

        release_paths = public_paths()
        for service, dockerfile in SERVICE_DOCKERFILES.items():
            with self.subTest(service=service):
                entrypoint = SERVICE_ENTRYPOINTS[service]
                dockerfile_text = text(dockerfile)
                self.assertIn(dockerfile, release_paths)
                self.assertIn(entrypoint, release_paths)
                self.assertIn(
                    f"COPY {entrypoint} /app/entrypoint.sh",
                    dockerfile_text,
                )
                self.assertIn("RUN chmod +x /app/entrypoint.sh", dockerfile_text)
                self.assertIn('ENTRYPOINT ["/app/entrypoint.sh"]', dockerfile_text)

        self.assertIn(
            "COPY web/legacy_job_results.py /app/legacy_job_results.py",
            text(SERVICE_DOCKERFILES["worker"]),
        )

    def test_worker_script_boundary_imports_canonical_resource_policy(self) -> None:
        copy_pairs = worker_clusterweave_copy_pairs()
        canonical_pair = (
            "web/resource_policy.py",
            "/clusterweave/web/resource_policy.py",
        )
        self.assertIn(canonical_pair, copy_pairs)
        self.assertEqual(
            [source for source, destination in copy_pairs if destination == canonical_pair[1]],
            [canonical_pair[0]],
        )

        with tempfile.TemporaryDirectory() as tmp:
            image_root = Path(tmp)
            for source, destination in copy_pairs:
                source_path = REPO_ROOT / source
                destination_path = image_root / destination.lstrip("/")
                if source.endswith("/") and source_path.is_dir():
                    shutil.copytree(source_path, destination_path)
                elif source_path.is_file():
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, destination_path)

            helper = image_root / "clusterweave" / "bin" / "annotation_runtime.py"
            result = subprocess.run(
                [sys.executable, "-B", str(helper), "--help"],
                cwd=image_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_worker_progress_tree_renderer_has_its_contract(self) -> None:
        copy_pairs = worker_clusterweave_copy_pairs()
        contract_pair = (
            "web/static/assets/progress-tree-contract.json",
            "/clusterweave/web/static/assets/progress-tree-contract.json",
        )
        self.assertIn(contract_pair, copy_pairs)

        with tempfile.TemporaryDirectory() as tmp:
            image_root = Path(tmp)
            for source, destination in copy_pairs:
                source_path = REPO_ROOT / source
                destination_path = image_root / destination.lstrip("/")
                if source.endswith("/") and source_path.is_dir():
                    shutil.copytree(source_path, destination_path)
                elif source_path.is_file():
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, destination_path)

            renderer = image_root / "clusterweave" / "bin" / "render_progress_tree.py"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(renderer),
                    "--project",
                    "worker-image-fixture",
                    "--",
                    sys.executable,
                    "-c",
                    "print('Stage 1/4: complete')",
                ],
                cwd=image_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "LC_ALL": "C.UTF-8"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("tree display unavailable", result.stderr.lower())
            self.assertIn("Input preparation", result.stdout)

    def test_retained_worker_preparation_commands_reach_one_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            capture = root / "capture.txt"
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"${CLUSTERWEAVE_TEST_CAPTURE}\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
                    "CLUSTERWEAVE_TEST_CAPTURE": str(capture),
                    "RUNTIME_PREPARATION": str(root / "prepare runtime.py"),
                    "RUNTIME_PREPARATION_MANIFEST": str(root / "runtime manifest.json"),
                    "CLUSTERWEAVE_RUNTIME_MODE": "lab-docker",
                }
            )

            for command, verb in [("prepare-runtime", "prepare"), ("check-runtime", "check")]:
                with self.subTest(command=command):
                    capture.write_text("", encoding="utf-8")
                    subprocess.run(
                        [
                            "bash",
                            str(REPO_ROOT / SERVICE_ENTRYPOINTS["worker"]),
                            command,
                            "--keep-going",
                        ],
                        cwd=REPO_ROOT,
                        env=env,
                        check=True,
                    )
                    argv = capture.read_text(encoding="utf-8").splitlines()
                    self.assertEqual(len(argv), 1)
                    self.assertEqual(
                        argv[0],
                        f"{root / 'prepare runtime.py'} {verb} --profile local-docker "
                        f"--manifest {root / 'runtime manifest.json'} --keep-going",
                    )

    def test_browser_qa_has_no_public_dependency_or_ci_surface(self) -> None:
        ci = text(".github/workflows/ci.yml")

        for relative in ["package.json", "package-lock.json", "tests/browser/README.md"]:
            with self.subTest(relative=relative):
                self.assertFalse((REPO_ROOT / relative).exists())

        for private_invocation in [
            "actions/setup-node",
            "npm ci",
            "npm install",
            "npm run",
            "npx playwright",
            "playwright install",
            "Run browser fixtures",
        ]:
            with self.subTest(private_invocation=private_invocation):
                self.assertNotIn(private_invocation, ci)

        for dockerfile in SERVICE_DOCKERFILES.values():
            with self.subTest(dockerfile=dockerfile):
                dockerfile_text = text(dockerfile)
                self.assertNotIn("npm ", dockerfile_text)

    def test_profiles_advertise_explicit_runtime_preparation(self) -> None:
        local_profile = text("docker-compose.yml")
        external_profile = text("clusterweave.yml")

        for command in [
            "docker compose build",
            "docker compose run --rm --no-deps worker prepare-runtime",
            "docker compose run --rm --no-deps worker check-runtime",
            "docker compose up -d",
        ]:
            with self.subTest(local_command=command):
                self.assertIn(command, local_profile)
        self.assertIn(
            "Normal service startup reuses the prepared assets and does not acquire them.",
            " ".join(local_profile.split()),
        )
        self.assertIn(
            "docker compose -f clusterweave.yml run --rm --no-deps worker check-runtime",
            external_profile,
        )
        self.assertIn(
            "Runtime preparation is check-only in this profile; site-managed assets must be pre-provisioned.",
            external_profile,
        )
        for profile in [local_profile, external_profile]:
            self.assertNotIn("first run (builds image, downloads DBs)", profile)
            self.assertNotIn("On first startup the container downloads", profile)

    def test_unsupported_build_and_install_surfaces_are_absent(self) -> None:
        advertised = "\n".join(
            text(relative)
            for relative in [
                "README.md",
                "docs/BEGINNER_SETUP.md",
                "docs/INSTALL.md",
                "docs/WEB_RUNTIME.md",
                "docker-compose.yml",
                "clusterweave.yml",
                ".github/workflows/ci.yml",
                ".github/workflows/publish-ghcr.yml",
                "Dockerfile.web",
                "Dockerfile.worker",
            ]
        )

        for unsupported_path in [
            "Dockerfile",
            "pyproject.toml",
            "web/entrypoint.sh",
            "web/requirements.txt",
        ]:
            with self.subTest(unsupported_path=unsupported_path):
                self.assertFalse((REPO_ROOT / unsupported_path).exists())
        for unsupported_reference in [
            "web/entrypoint.sh",
            "web/requirements.txt",
            "pip install .",
            "docker build -t clusterweave-web .",
        ]:
            with self.subTest(unsupported_reference=unsupported_reference):
                self.assertNotIn(unsupported_reference, advertised)


if __name__ == "__main__":
    unittest.main()
