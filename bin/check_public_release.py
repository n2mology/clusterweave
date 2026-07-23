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
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        return [ROOT / line for line in result.stdout.splitlines() if line]
    return [path for path in ROOT.rglob("*") if path.is_file()]


def local_link_target(source: Path, raw: str) -> Path | None:
    target = raw.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return (source.parent / target).resolve()


def main() -> int:
    errors: list[str] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT)
        lower_parts = {part.lower() for part in rel.parts}
        if lower_parts & FORBIDDEN_PATH_PARTS:
            errors.append(f"forbidden public path: {rel}")
            continue
        if path.is_symlink():
            errors.append(f"public source symlink is not allowed: {rel}")
            continue
        if not path.is_file():
            continue
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
    if errors:
        print("Public release safety check failed:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Public release safety and local Markdown links: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
