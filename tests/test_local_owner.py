from __future__ import annotations

from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
from local_owner import COOKIE, LocalOwner


class LocalOwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner = LocalOwner(self.root, profile="local-owner", origin="http://127.0.0.1:8080/", secret="s" * 64)
        self.headers = {"Host": "127.0.0.1:8080", "Origin": "http://127.0.0.1:8080"}

    def test_profile_rejects_shared_binding_remote_origin_and_missing_secret(self):
        self.owner.validate()
        for key, value in (("bind", "0.0.0.0"), ("origin", "https://example.invalid"), ("secret", ""), ("profile", "unknown")):
            args = dict(profile="local-owner", origin="http://127.0.0.1:8080", secret="s" * 64)
            args[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): LocalOwner(self.root, **args).validate()

    def test_expiry_secret_rotation_and_private_files(self):
        report, cookie = self.owner.pair(self.headers)
        headers = {**self.headers, "Cookie": cookie.split(";", 1)[0]}
        self.assertTrue(self.owner.authorized(headers))
        self.assertEqual(self.owner.directory.stat().st_mode & 0o777, 0o700)
        record = next(self.owner.directory.glob("*.json"))
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(cookie.split(";", 1)[0].split("=", 1)[1], record.read_text())
        rotated = LocalOwner(self.root, profile="local-owner", origin=self.owner.origin, secret="r" * 64)
        self.assertFalse(rotated.authorized(headers))
        record.write_text(json.dumps({"expires": int(time.time()) - 1}))
        self.assertFalse(self.owner.authorized(headers))

    def test_directory_links_do_not_grant_access_or_write_outside(self):
        other = self.root / "other"; other.mkdir()
        self.owner.directory.symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError): self.owner.pair(self.headers)
        self.assertEqual(list(other.iterdir()), [])

    def test_credentials_never_follow_file_links_or_insecure_modes(self):
        _, cookie = self.owner.pair(self.headers)
        headers = {**self.headers, "Cookie": cookie.split(";", 1)[0]}
        record = next(self.owner.directory.glob("*.json"))
        record.chmod(0o644)
        self.assertFalse(self.owner.authorized(headers))
        record.unlink(); outside = self.root / "secret"; outside.write_text('{"expires":9999999999}')
        record.symlink_to(outside)
        self.assertFalse(self.owner.authorized(headers))


if __name__ == "__main__": unittest.main()
