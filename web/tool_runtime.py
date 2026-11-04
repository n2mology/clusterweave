"""Bounded, fixed version observations in explicitly selected local runtimes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

VERSION = re.compile(r"(?<![A-Za-z0-9.])(?:[vV])?([0-9]+(?:\.[0-9]+){1,3}(?:[ab][0-9]+|[-+][A-Za-z0-9][A-Za-z0-9._+-]*|\.[A-Za-z][A-Za-z0-9._+-]*)?)(?![A-Za-z0-9.])")
DIGEST = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
TAG = re.compile(r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|v?[0-9]+(?:\.[0-9]+){1,3}(?:[ab][0-9]+|[-+][A-Za-z0-9._+-]+|\.[A-Za-z][A-Za-z0-9._+-]*)?)\Z")
COMMANDS = {
    "R": ["Rscript", "--version"],
    "antiSMASH": ["antismash", "--version"], "Prodigal": ["prodigal", "-v"],
    "BiG-SCAPE": ["/opt/conda/bin/python", "/home/mambauser/BiG-SCAPE/bigscape.py", "--version"],
    "funannotate": ["funannotate", "--version"], "BRAKER3": ["braker.pl", "--version"],
    "clinker": ["clinker", "--version"], "MAFFT": ["mafft", "--version"],
    "IQ-TREE": ["iqtree2", "--version"], "trimAl": ["trimal", "--version"],
    "FastTree": ["FastTree", "-help"],
    "NCBI Datasets": ["datasets", "--version"],
    "AUGUSTUS": ["augustus", "--version"], "BUSCO": ["busco", "--version"],
    "GeneMark": ["gmes_petap.pl", "--version"], "SNAP": ["snap"],
    "DIAMOND": ["diamond", "version"], "HMMER": ["hmmscan", "-h"],
    "Exonerate": ["exonerate", "--version"], "BLAST+": ["blastp", "-version"],
}
DISTRIBUTIONS = {"FunBGCeX": "funbgcex", "NPLinker": "nplinker", "CairoSVG": "CairoSVG", "ETE4": "ete4"}


def version_from_text(text):
    found = VERSION.search(text)
    return found.group(1) if found else None


def bounded_run(command, timeout=8):
    # Tool output is never copied to the record or held without a size bound.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        output.seek(0)
        return result.returncode, output.read(8192).decode(errors="replace")


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_observation(value):
    if not isinstance(value, dict) or value.get("tool") not in COMMANDS.keys() | DISTRIBUTIONS.keys() | {"Python"}:
        return None
    if value.get("backend") not in {"native", "docker", "singularity", "apptainer"}:
        return None
    record = {"tool": value["tool"], "backend": value["backend"], "version": None}
    version = value.get("version")
    if isinstance(version, str) and TAG.fullmatch(version):
        record["version"] = version
    for key in ("runtime_sha256", "executable_sha256"):
        if isinstance(value.get(key), str) and DIGEST.fullmatch(value[key]):
            record[key] = value[key]
    tag = value.get("configured_tag")
    if isinstance(tag, str) and (TAG.fullmatch(tag) or tag == "latest"):
        record["configured_tag"] = tag
    identity_key = "executable_sha256" if record["backend"] == "native" else "runtime_sha256"
    if identity_key not in record:
        record["version"] = None
    record["version_observation"] = "selected runtime version probe" if record["version"] else "unavailable from selected runtime"
    return record


def observe(tool, backend="native", runtime="", python="python3", executable=None, observed_text=None):
    record = {"tool": tool, "backend": backend, "version": None}
    command = COMMANDS.get(tool)
    if tool in DISTRIBUTIONS:
        command = [python, "-c", "from importlib.metadata import version; print(version(" + repr(DISTRIBUTIONS[tool]) + "))"]
    elif tool == "Python":
        command = [python, "--version"]
    if not command:
        return None
    command = list(command)
    if executable and tool in COMMANDS:
        command[0] = executable
    prefix = []
    identity_path = None
    probe_directory = None
    try:
        if backend == "docker":
            code, identity = bounded_run(["docker", "image", "inspect", "--format", "{{.Id}}", runtime])
            identity = identity.strip()
            if code or not DIGEST.fullmatch(identity):
                return safe_observation(record)
            record["runtime_sha256"] = identity
            tag = runtime.rsplit(":", 1)[-1]
            if TAG.fullmatch(tag) or tag == "latest":
                record["configured_tag"] = tag
            probe_directory = tempfile.TemporaryDirectory(prefix="clusterweave-version-")
            # Phylogeny activates its environment in the image entrypoint.
            prefix = ["docker", "run", "--cidfile", str(Path(probe_directory.name) / "container.id"), "--rm", "--pull", "never", "--network", "none", "--read-only",
                      "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--cpus", "1", "--memory", "1g",
                      "--pids-limit", "128", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                      "-e", "MPLCONFIGDIR=/tmp/matplotlib", "-e", "PYTHONDONTWRITEBYTECODE=1",
                      "-e", "OMP_NUM_THREADS=1", "-e", "OPENBLAS_NUM_THREADS=1", "-e", "MKL_NUM_THREADS=1",
                      *([] if tool in {"MAFFT", "trimAl", "IQ-TREE", "ETE4"} else ["--entrypoint", ""]), identity]
        elif backend in {"singularity", "apptainer"}:
            identity_path = Path(runtime)
            record["runtime_sha256"] = file_digest(identity_path)
            prefix = [backend, "exec", "--cleanenv", runtime]
        elif backend == "native":
            resolved = shutil.which(command[0])
            if not resolved:
                return safe_observation(record)
            command[0] = resolved
            identity_path = Path(resolved)
            record["executable_sha256"] = file_digest(identity_path)
        else:
            return None
        if tool == "funannotate" and backend in {"singularity", "apptainer"} and not executable:
            code, _ = bounded_run(prefix + ["test", "-x", "/venv/bin/funannotate"])
            if code == 0:
                command[0] = "/venv/bin/funannotate"
        code, output = (0, observed_text) if observed_text is not None else bounded_run(prefix + command)
        # Prodigal and FastTree print their version with a nonzero help status.
        if tool == "funannotate" and code == 1:
            # The supported funannotate CLI exits 1 after printing its version.
            banner = re.search(r"(?im)^funannotate\s+v?[0-9]+(?:\.[0-9]+)+\s*$", output)
            if banner: record["version"] = version_from_text(banner.group())
        if code == 0 or tool in {"Prodigal", "FastTree", "SNAP"} and code == 1:
            record["version"] = version_from_text(output)
            if tool == "SNAP":
                released = re.search(r"\bversion\s+([0-9]{4}-[0-9]{2}-[0-9]{2})\b", output, re.I)
                if released: record["version"] = released.group(1)
        key = "executable_sha256" if backend == "native" else "runtime_sha256"
        if identity_path and file_digest(identity_path) != record[key]:
            record.pop(key, None)
            record["version"] = None
    except subprocess.TimeoutExpired:
        if probe_directory:
            try:
                identifier = (Path(probe_directory.name) / "container.id").read_text().strip()
                if re.fullmatch(r"[0-9a-f]{64}", identifier):
                    bounded_run(["docker", "rm", "--force", identifier], timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    finally:
        if probe_directory:
            probe_directory.cleanup()
    return safe_observation(record)



# Match execution records, never dependency inventories or installation checks.
DEPENDENCY_COMMANDS = {
    "AUGUSTUS": "augustus", "BUSCO": "busco", "GeneMark": "gmes_petap.pl",
    "SNAP": "snap", "DIAMOND": "diamond", "HMMER": "(?:hmmscan|hmmsearch)",
    "Exonerate": "exonerate", "BLAST+": "(?:blastp|blastn|tblastn)",
}


def annotation_dependencies(result, work, genome, parent):
    """Bounded tool-specific command logs establish dependency use."""
    if parent not in {"funannotate", "BRAKER3"} or not isinstance(genome, str) or genome in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]{1,240}", genome):
        return set()
    names = set()
    candidates = [(work / "logs" / (genome + (".funannotate.log" if parent == "funannotate" else ".braker3.log")), work)]
    directory = result / ("funannotate" if parent == "funannotate" else "braker3") / genome
    candidates.extend((p, result) for p in list(directory.glob("logfiles/*.log"))[:16])
    for path, base in candidates:
        try:
            path.relative_to(base)
            if any(p.is_symlink() for p in (path, *path.parents)): continue
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 4 * 1024 * 1024: continue
                raw = os.read(fd, 4 * 1024 * 1024 + 1)
                after = os.fstat(fd)
                if len(raw) != before.st_size or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns): continue
                text = raw.decode(errors="replace")
            finally:
                os.close(fd)
        except (OSError, ValueError):
            continue
        for name, command in DEPENDENCY_COMMANDS.items():
            # Commands logged after DEBUG/CMD/command or as absolute argv lines.
            if re.search(r"(?im)^(?:.*?(?:\bDEBUG\b|\bCMD(?: ERROR)?:|\bcommand:)[ \]:-]*|\[[^\]\n]{1,64}\]:\s*|\s*)(?:/[^\s]+/)?" + command + r"[ \t]+(?!-+(?:version|help)\b|-(?:v|h)\b)(\S[^\n]*)", text):
                names.add(name)
    return names


def write_observation(directory, record):
    if record is None:
        return
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {**record, "observation_run": os.environ.get("CLUSTERWEAVE_OBSERVATION_RUN", "")}
    name = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest() + ".json"
    fd, temporary = tempfile.mkstemp(prefix=".observation-", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(record, handle, sort_keys=True)
        os.replace(temporary, directory / name)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tool", choices=sorted(COMMANDS.keys() | DISTRIBUTIONS.keys() | {"Python"}), required=True)
    parser.add_argument("--backend", choices=["native", "docker", "singularity", "apptainer"], default="native")
    parser.add_argument("--runtime", default="")
    parser.add_argument("--python", default="python3")
    parser.add_argument("--executable")
    parser.add_argument("--version-stdin", action="store_true")
    parser.add_argument("--configured-tag", default="")
    args = parser.parse_args()
    import sys
    observed_text = sys.stdin.buffer.read(8192).decode(errors="replace") if args.version_stdin else None
    record = observe(args.tool, args.backend, args.runtime, args.python, args.executable, observed_text)
    if record and (TAG.fullmatch(args.configured_tag) or args.configured_tag == "latest"):
        record["configured_tag"] = args.configured_tag
    write_observation(args.output, record)
    if record and args.backend == "docker" and record.get("runtime_sha256"):
        print(record["runtime_sha256"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        pass  # Missing provenance must not change scientific execution.
