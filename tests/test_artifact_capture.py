import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "capture_external_artifacts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("capture_external_artifacts", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArtifactCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_sha256_file_reports_digest_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "artifact.txt"
            path.write_bytes(b"clusterweave\n")
            digest, size = self.module.sha256_file(path)
        self.assertEqual(digest, hashlib.sha256(b"clusterweave\n").hexdigest())
        self.assertEqual(size, len(b"clusterweave\n"))

    def test_digest_and_tag_parse_container_sources(self) -> None:
        source = "docker://example/tool:1.2.3@sha256:abc123"
        self.assertEqual(self.module.tag_from_source(source), "1.2.3")
        self.assertEqual(self.module.digest_from_source(source), "sha256:abc123")


if __name__ == "__main__":
    unittest.main()
