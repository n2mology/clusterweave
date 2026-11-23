"""Bootstrap versions: distinguish configured pins from selected-runtime observations."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import shutil

VERSION = re.compile(r"v?([0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9._+-]+)?)\Z")

def field(path, key):
    try:
        text = path.read_text()
    except OSError:
        return None
    match = re.search(r"(?m)^" + re.escape(key) + r":\s*[\"']?([^\"'\n]+)", text)
    return match.group(1).strip() if match else None


def project_identity(source):
    citation = field(source / "CITATION.cff", "version")
    if not citation or not VERSION.fullmatch(citation):
        citation = None
    active = citation
    try:
        candidate = (source / "config" / "project-version.txt").read_text().strip()
        if isinstance(candidate, str) and VERSION.fullmatch(candidate):
            active = candidate
    except (OSError, ValueError, AttributeError):
        pass
    return {"active": active, "citation": citation,
            "doi": field(source / "CITATION.cff", "doi") or "10.11578/PMI/dc.20260608.2"}


def citation_lines(source):
    identity = project_identity(source)
    active = "v" + identity["active"] if identity["active"] else "version unavailable"
    citation = "v" + identity["citation"] if identity["citation"] else "version unavailable"
    return [f"ClusterWeave {active}",
            f"Cosner, Martin & Rush | released citation record {citation}",
            "Please cite: https://doi.org/" + identity["doi"]]


def match_file(source, name, pattern):
    try:
        match = re.search(pattern, (source / name).read_text(), re.MULTILINE)
        return match.group(1) if match else None
    except OSError:
        return None


def image_version(reference):
    tag = reference.split("@", 1)[0].rsplit(":", 1)[-1].split("--", 1)[0]
    match = VERSION.fullmatch(tag)
    return match.group(1) if match else None


def bootstrap_catalogue(source, env=None):
    env = dict(os.environ if env is None else env)
    # Reuse the selected source's defaults without executing preparation.
    from prepare_runtime import local_image_specs, FASTTREE_SHA256, NPLINKER_VERSION, MIBIG_VERSION
    def row(tool, version=None, basis="not observed"):
        return {"tool": tool, "version": version, "basis": basis}
    def configured(tool, version):
        return row(tool, version, "configured pin") if version else row(tool)
    worker = match_file(source, "Dockerfile.worker", r"^FROM antismash/standalone:([^\s]+)")
    docker = match_file(source, "Dockerfile.worker", r"^FROM docker:([0-9.]+)-cli")
    catalogue = {
        "worker_components": [configured("Docker CLI", docker), row("Worker Python"), row("R"),
                              configured("antiSMASH", worker), row("Prodigal"), row("HMMER")],
        "antismash": [configured("antiSMASH", worker), row("antiSMASH databases", basis="dataset release not observed")],
        "pfam": [row("Pfam-A", basis="dataset release not observed")],
        "ncbi_cli": [row("NCBI Datasets"), row("NCBI Dataformat")],
        "fasttree": [row("FastTree", basis="version not observed; configured SHA256 " + FASTTREE_SHA256[:12])],
        "mibig": [configured("MIBiG", env.get("MIBIG_VERSION", MIBIG_VERSION))],
        "nplinker_environment": [configured("NPLinker", env.get("NPLINKER_VERSION", NPLINKER_VERSION))],
    }
    titles = {"clinker_image": "clinker", "bigscape_image": "BiG-SCAPE", "funbgcex_image": "FunBGCeX",
              "braker3_image": "BRAKER3", "funannotate_image": "funannotate", "nplinker_image": "NPLinker Python image"}
    for spec in local_image_specs(env, source):
        version = image_version(spec.reference)
        if spec.key == "funbgcex_image" and spec.reference == "clusterweave-funbgcex:latest":
            version = match_file(source, "software/funbgcex/Dockerfile", r"funbgcex==([0-9.]+)")
        if spec.key == "funannotate_image" and spec.reference == "clusterweave-funannotate:v1.8.17-busco":
            version = match_file(source, "software/funannotate/Dockerfile", r"^ARG FUNANNOTATE_BASE_IMAGE=nextgenusfs/funannotate:v([0-9.]+)")
        catalogue[spec.key] = [configured(titles[spec.key], version)]
    return catalogue


def label(row):
    version = "v" + row["version"] if row["version"] else "version not observed"
    return f"{row['tool']} {version} [{row['basis']}]"


def observe_catalogue(catalogue, source, env=None, scope="all"):
    """Run fixed, bounded read-only probes; missing tools remain explicitly unknown."""
    env = dict(os.environ if env is None else env)
    sys.path[:0] = [str(source / "web"), "/app"]
    from tool_runtime import observe, bounded_run, version_from_text
    from prepare_runtime import local_image_specs
    specs = {spec.key: spec for spec in local_image_specs(env, source)}
    software = Path(env.get("CLUSTERWEAVE_SOFTWARE_ROOT", str(source / "software")))
    ncbi = Path(env.get("NCBI_CLI_ROOT", str(software / "ncbi_cli")))
    datasets = str(ncbi / "datasets") if (ncbi / "datasets").is_file() else (shutil.which("datasets") or str(ncbi / "datasets"))
    dataformat = str(ncbi / "dataformat") if (ncbi / "dataformat").is_file() else (shutil.which("dataformat") or str(ncbi / "dataformat"))
    observed = {}
    for phase, rows in catalogue.items():
        for item in rows:
            tool = item["tool"]
            if tool in {"antiSMASH databases", "Pfam-A", "MIBiG"}:
                continue
            if tool in observed:
                result = observed[tool]
            elif phase in specs:
                spec = specs[phase]
                if scope == "startup" and spec.scope != "startup":
                    continue
                target = "Python" if tool == "NPLinker Python image" else tool
                result = observe(target, backend="docker", runtime=spec.reference)
            elif tool in {"Docker CLI", "NCBI Dataformat"}:
                command = ["docker", "--version"] if tool == "Docker CLI" else [dataformat, "version"]
                try:
                    code, output = bounded_run(command)
                    result = {"version": version_from_text(output) if code == 0 else None}
                except (OSError, ValueError, subprocess.SubprocessError):
                    result = None
            elif tool == "Worker Python":
                result = observe("Python", python=sys.executable)
            elif tool == "NCBI Datasets":
                result = observe(tool, executable=datasets)
            elif tool == "NPLinker":
                if scope == "startup":
                    continue
                result = observe(tool, python=str(software / "nplinker" / "venv" / "bin" / "python"))
            elif tool == "FastTree":
                if scope == "startup":
                    continue
                result = observe(tool, executable=env.get("FASTTREE_HOST", str(software / "big_scape" / "bin" / "fasttree")))
            else:
                result = observe(tool)
            observed[tool] = result
            if result and result.get("version"):
                item.update(version=result["version"], basis="observed in selected runtime")
    return catalogue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--observe", action="store_true", help="probe selected installed runtimes without pulling or preparing assets")
    parser.add_argument("--scope", choices=("startup", "all"), default="all")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    catalogue = bootstrap_catalogue(source)
    if args.observe:
        catalogue = observe_catalogue(catalogue, source, scope=args.scope)
    rows = catalogue[args.phase] if args.phase else [row for phase in catalogue.values() for row in phase]
    if args.json:
        print(json.dumps({"project": project_identity(source), "components": catalogue}, indent=2))
    else:
        print("\n".join(citation_lines(source)))
        for item in rows:
            print(label(item))

if __name__ == "__main__":
    main()
