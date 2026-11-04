"""Persistent browser sessions for the explicitly trusted loopback profile."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import hmac
from http.cookies import CookieError, SimpleCookie
import json
import os
from pathlib import Path
import secrets
import stat
import time
from urllib.parse import urlsplit

COOKIE = "clusterweave_local_owner"
LIFETIME = 30 * 86400
MAX_SESSIONS = 128


class LocalOwner:
    def __init__(self, data_dir, *, profile="hosted", origin="", bind="127.0.0.1", secret=""):
        self.enabled = profile == "local-owner"
        self.profile, self.origin, self.bind, self.secret = profile, origin.rstrip("/"), bind, secret
        self.directory = Path(data_dir) / "local_owner_sessions"

    def validate(self):
        if self.profile not in {"hosted", "local-owner"}:
            raise ValueError("Unknown access profile")
        if not self.enabled:
            return
        url = urlsplit(self.origin)
        if (url.scheme not in {"http", "https"} or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.path or url.query or url.fragment
                or self.bind not in {"127.0.0.1", "::1"} or len(self.secret) < 32):
            raise ValueError("Local-owner access requires a loopback binding, loopback origin and generated instance secret")
        url.port  # Reject malformed ports before accepting any browser sessions.

    def trusted_request(self, headers):
        if not self.enabled:
            return True
        expected = urlsplit(self.origin)
        if headers.get("Host", "").lower() != expected.netloc.lower():
            return False
        origin = headers.get("Origin")
        if origin is not None and origin != self.origin:
            return False
        return headers.get("Sec-Fetch-Site", "") not in {"cross-site"}

    def same_origin(self, headers):
        if not self.trusted_request(headers):
            return False
        if headers.get("Origin") == self.origin:
            return True
        try:
            referer = urlsplit(headers.get("Referer", ""))
            return f"{referer.scheme}://{referer.netloc}" == self.origin
        except ValueError:
            return False

    def _digest(self, value):
        return hmac.new(self.secret.encode(), value.encode(), hashlib.sha256).hexdigest()

    def token(self, headers):
        if not self.enabled or not self.trusted_request(headers):
            return ""
        try:
            cookies = SimpleCookie(headers.get("Cookie", ""))
            value = cookies[COOKIE].value
            return value if len(value) == 43 and all(c.isalnum() or c in "_-" for c in value) else ""
        except (KeyError, ValueError, CookieError):
            return ""

    def _safe_directory(self):
        if any(p.is_symlink() for p in (self.directory, *self.directory.parents)):
            raise ValueError("Local session directory cannot use links")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Local session directory requires private ownership")

    @contextmanager
    def locked(self):
        self._safe_directory()
        fd = os.open(self.directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError("Unsafe local session lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _read(self, token):
        if not token or not self.directory.is_dir():
            return None
        self._safe_directory()
        try:
            fd = os.open(self.directory / (self._digest(token) + ".json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > 1024):
                return None
            value = json.loads(os.read(fd, 1025))
            return value if set(value) == {"expires"} and isinstance(value["expires"], int) and value["expires"] > time.time() else None
        finally:
            os.close(fd)

    def authorized(self, headers):
        try:
            return self.enabled and self._read(self.token(headers)) is not None
        except (OSError, ValueError, TypeError):
            return False

    def csrf(self, token):
        return self._digest("csrf:" + token)

    def csrf_valid(self, headers):
        token = self.token(headers)
        return (bool(token) and self.same_origin(headers) and self.authorized(headers)
                and hmac.compare_digest(headers.get("X-ClusterWeave-CSRF", ""), self.csrf(token)))

    def pair(self, headers):
        if not self.enabled or not self.same_origin(headers):
            raise ValueError("Local pairing requires a same-origin browser request")
        with self.locked():
            token = self.token(headers)
            current = self._read(token)
            if current is None:
                records = sorted(self.directory.glob("*.json"), key=lambda p: p.lstat().st_mtime)
                for path in records[:max(0, len(records) - MAX_SESSIONS + 1)]:
                    path.unlink()
                token = secrets.token_urlsafe(32)
                current = {"expires": int(time.time()) + LIFETIME}
                fd = os.open(self.directory / (self._digest(token) + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as handle:
                    json.dump(current, handle)
                    handle.flush(); os.fsync(handle.fileno())
        cookie = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max(0, current['expires'] - int(time.time()))}"
        if self.origin.startswith("https:"):
            cookie += "; Secure"
        return {"enabled": True, "local_owner": True, "csrf_token": self.csrf(token)}, cookie

    def revoke(self, headers):
        if not self.csrf_valid(headers):
            raise ValueError("Local session revocation requires CSRF validation")
        with self.locked():
            (self.directory / (self._digest(self.token(headers)) + ".json")).unlink(missing_ok=True)
        return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if self.origin.startswith("https:") else "")
