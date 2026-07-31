#!/usr/bin/env python3
"""Fail closed on common source-archive leaks and broken local Markdown links."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MAX_PUBLIC_FILE_BYTES = 20 * 1024 * 1024
FORBIDDEN_PATH_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "clusterweave_ops",
    "credentials",
    "local_only",
    "node_modules",
    "playwright-report",
    "private",
    "secrets",
    "test-results",
    "venv",
}
FORBIDDEN_SUFFIXES = {
    ".7z", ".bak", ".backup", ".bz2", ".class", ".db", ".exe", ".fa",
    ".faa", ".fasta", ".fna", ".gb", ".gbff", ".gbk", ".gff", ".gff3",
    ".gz", ".jar", ".log", ".o", ".old", ".orig", ".pyc", ".rej",
    ".sif", ".so", ".sqlite", ".sqlite3", ".swo", ".swp", ".tar",
    ".tmp", ".wasm", ".xz", ".zip",
}
FORBIDDEN_NAMES = {".DS_Store", ".env"}
FORBIDDEN_ROOT_FILES = {Path("package-lock.json"), Path("package.json")}
RUNTIME_PATH_PARTS = {"jobs", "queue", "uploads", "worker"}
ALLOWED_RUNTIME_PLACEHOLDERS = {
    Path("data/genomes/fungi/.gitkeep"),
    Path("data/results/.gitkeep"),
}
TEXT_SUFFIXES = {
    ".cff", ".css", ".csv", ".def", ".env", ".html", ".js", ".json", ".md",
    ".py", ".sh", ".svg", ".toml", ".tsv", ".txt", ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {"Dockerfile", "Dockerfile.web", "Dockerfile.worker", "LICENSE"}
TEXT_PATTERNS = {
    "private home path": re.compile(r"/" + r"home/cloud" + r"(?:/|\b)"),
    "private macOS user path": re.compile(r"/Users/[A-Za-z0-9._-]+(?:/|\b)"),
    "production IP": re.compile(r"\b128\.219\.184\.28\b"),
    "private IPv4 address": re.compile(
        r"\b(?:10\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}"
        r"|192\.168\.(?:[0-9]{1,3}\.)[0-9]{1,3}"
        r"|172\.(?:1[6-9]|2[0-9]|3[01])\.(?:[0-9]{1,3}\.)[0-9]{1,3})\b"
    ),
    "private result route": re.compile(r"#/job/[0-9a-f]{8}/[A-Za-z0-9_-]{20,}"),
    "internal job workspace": re.compile(
        r"(?:data/jobs|api/jobs)/[0-9a-f]{8}(?:/|\b)", re.IGNORECASE
    ),
    "bearer credential": re.compile(r"Bearer\s+[A-Za-z0-9._~-]{20,}"),
    "private-key material": re.compile(
        r"-{5}BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-{5}"
    ),
    "common access-token shape": re.compile(
        r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,})\b"
    ),
}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def tracked_files() -> list[Path]:
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        candidates = [ROOT / name for name in result.stdout.split("\0") if name]
    else:
        candidates = [
            path
            for path in ROOT.rglob("*")
            if path.is_symlink() or not path.is_dir()
        ]
    return [path for path in candidates if path.exists() or path.is_symlink()]


def local_link_target(source: Path, raw: str) -> Path | None:
    target = raw.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return (source.parent / target).resolve()


def public_release_errors(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            errors.append("escaping public source manifest member")
            continue
        if rel.is_absolute() or ".." in rel.parts or rel == Path("."):
            errors.append("escaping public source manifest member")
            continue
        rel_text = rel.as_posix()
        if rel_text in seen:
            errors.append(f"duplicate public source manifest member: {rel}")
            continue
        seen.add(rel_text)
        if path.is_symlink():
            errors.append(f"public source symlink is not allowed: {rel}")
            continue
        if not path.exists():
            errors.append(f"missing public source manifest member: {rel}")
            continue
        if not path.is_file():
            errors.append(f"non-regular public source manifest member: {rel}")
            continue
        lower_parts = {part.lower() for part in rel.parts}
        if lower_parts & FORBIDDEN_PATH_PARTS:
            errors.append(f"forbidden public path: {rel}")
            continue
        if rel in FORBIDDEN_ROOT_FILES:
            errors.append(f"private browser QA manifest is not public source: {rel}")
        if path.name in FORBIDDEN_NAMES or path.name.endswith("~"):
            errors.append(f"forbidden public artifact name: {rel}")
        if (lower_parts & RUNTIME_PATH_PARTS) and rel not in ALLOWED_RUNTIME_PLACEHOLDERS:
            errors.append(f"runtime artifact path is not public source: {rel}")
        size = path.stat().st_size
        if size > MAX_PUBLIC_FILE_BYTES:
            errors.append(f"oversized public file: {rel} ({size} bytes)")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden public artifact type: {rel}")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in TEXT_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{label}: {rel}")
        if path.suffix.lower() == ".md":
            for raw_link in LINK_RE.findall(text):
                target = local_link_target(path, raw_link)
                if target is not None and (ROOT not in target.parents or not target.exists()):
                    errors.append(f"broken or escaping link in {rel}: {raw_link}")
    return sorted(set(errors))


def report_errors(errors: list[str]) -> None:
    print("Public release safety check failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)


def public_source_manifest_bytes(paths: list[Path]) -> bytes:
    relative = sorted(path.relative_to(ROOT).as_posix() for path in paths)
    return b"".join(name.encode("utf-8") + b"\0" for name in relative)


def main() -> int:
    errors = public_release_errors(tracked_files())
    if errors:
        report_errors(errors)
        return 1
    print("Public release safety and local Markdown links: OK")
    return 0


def cli(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return main()
    if args == ["--list-files0"]:
        paths = tracked_files()
        errors = public_release_errors(paths)
        if errors:
            report_errors(errors)
            return 1
        sys.stdout.buffer.write(public_source_manifest_bytes(paths))
        return 0
    print("usage: check_public_release.py [--list-files0]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())
