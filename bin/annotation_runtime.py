#!/usr/bin/env python3
"""Bounded resource plans and exact argv for the annotation shell runner."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from resource_policy import ResourcePlan, ResourceRequest  # noqa: E402


def positive_int(value: object, default: int = 1) -> int:
    text = str(value)
    parsed = int(text) if text and all("0" <= char <= "9" for char in text) else default
    return parsed if parsed >= 1 else default


def nonnegative_int(value: object, default: int = 0) -> int:
    text = str(value)
    parsed = int(text) if text and all("0" <= char <= "9" for char in text) else default
    return max(0, parsed)


def count_cpuset_cpus(spec: str) -> int:
    total = 0
    for part in str(spec or "").split(","):
        if part.isdigit():
            total += 1
            continue
        first_text, separator, last_text = part.partition("-")
        if separator and first_text.isdigit() and last_text.isdigit():
            first = int(first_text)
            last = int(last_text)
            if last >= first:
                total += last - first + 1
    return total


def online_cpu_count() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def effective_cpu_count(
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    *,
    online_cpus: int | None = None,
) -> int:
    effective = positive_int(online_cpus if online_cpus is not None else online_cpu_count())
    for relative in ("cpuset.cpus.effective", "cpuset/cpuset.cpus"):
        path = cgroup_root / relative
        try:
            candidate = count_cpuset_cpus(path.read_text(encoding="utf-8").strip())
        except OSError:
            continue
        if candidate:
            effective = min(effective, candidate)
        break

    cpu_max = cgroup_root / "cpu.max"
    try:
        cpu_max_fields = cpu_max.read_text(encoding="utf-8").split()
    except OSError:
        cpu_max_fields = None
    if cpu_max_fields is not None:
        quota_text = cpu_max_fields[0] if cpu_max_fields else ""
        period_text = cpu_max_fields[1] if len(cpu_max_fields) >= 2 else ""
        if quota_text.isdigit() and period_text.isdigit() and int(period_text) >= 1:
            effective = min(effective, max(1, int(quota_text) // int(period_text)))
    else:
        try:
            quota_text = (cgroup_root / "cpu/cpu.cfs_quota_us").read_text(
                encoding="utf-8"
            ).strip()
            period_text = (cgroup_root / "cpu/cpu.cfs_period_us").read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            quota_text = period_text = ""
        if (
            quota_text.isdigit()
            and int(quota_text) >= 1
            and period_text.isdigit()
            and int(period_text) >= 1
        ):
            effective = min(effective, max(1, int(quota_text) // int(period_text)))
    return max(1, effective)


def effective_memory_mb(
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    *,
    meminfo_path: Path = Path("/proc/meminfo"),
) -> int:
    effective = 0
    try:
        for line in meminfo_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                candidate = int(line.split()[1]) // 1024
                effective = candidate if candidate >= 1 else 0
                break
    except (OSError, ValueError, IndexError):
        pass

    limit_path = cgroup_root / "memory.max"
    current_path = cgroup_root / "memory.current"
    try:
        limit_text = limit_path.read_text(encoding="utf-8").strip()
    except OSError:
        limit_path = cgroup_root / "memory/memory.limit_in_bytes"
        current_path = cgroup_root / "memory/memory.usage_in_bytes"
        try:
            limit_text = limit_path.read_text(encoding="utf-8").strip()
        except OSError:
            return effective
    try:
        limit = int(limit_text)
        current = int(current_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return effective
    if limit < 1152921504606846976:
        candidate = max(1, (limit - current) // 1048576)
        effective = min(effective, candidate) if effective else candidate
    return effective


@dataclass(frozen=True)
class AnnotationResourcePlan:
    plan: ResourcePlan
    effective_cpus: int
    effective_memory_mb: int
    memory_budget_mb: int

    @property
    def per_genome_cpu_budget(self) -> int:
        return max(1, self.plan.job_cpus // self.plan.genome_parallelism)

    def shell_fields(self) -> tuple[int, ...]:
        return (
            self.plan.job_cpus,
            self.plan.genome_parallelism,
            self.per_genome_cpu_budget,
            self.plan.anno_cpus,
            self.plan.funbgcex_workers,
            self.plan.antismash_record_parallelism,
            self.plan.antismash_shard_cpus,
            self.plan.antismash_legacy_cpus,
            self.effective_cpus,
            self.effective_memory_mb,
            self.memory_budget_mb,
            self.plan.annotation_cpu_slots,
            self.plan.funbgcex_cpu_slots,
            self.plan.antismash_sharded_cpu_slots,
            self.plan.antismash_legacy_cpu_slots,
        )


def build_annotation_resource_plan(
    *,
    mode: str,
    requested_cpus: object,
    cpus_explicit: bool,
    effective_cpus: object,
    effective_memory_mb: object,
    total_genomes: object,
    genome_parallelism: object,
    anno_cpus: object,
    funbgcex_workers: object,
    antismash_record_parallelism: object,
    antismash_shard_cpus: object | None,
    antismash_legacy_cpus: object | None,
    memory_budget_mb: object | None,
    auto_max_cpus: object,
    auto_max_genome_parallelism: object,
    auto_min_cpus_per_genome: object,
    auto_memory_percent: object,
    auto_memory_per_genome_mb: object,
    auto_max_anno_cpus: object,
    auto_max_funbgcex_workers: object,
    auto_max_antismash_record_parallelism: object,
) -> AnnotationResourcePlan:
    """Return the runner plan through the shared R02 ``ResourceRequest`` seam."""

    normalized_mode = "conservative" if mode == "manual" else mode
    if normalized_mode not in {"conservative", "auto"}:
        raise ValueError(f"unsupported annotation resource mode: {mode}")

    effective = positive_int(effective_cpus)
    effective_memory = nonnegative_int(effective_memory_mb)
    genomes = positive_int(total_genomes)
    cpus = positive_int(requested_cpus, 6)
    target_genomes = positive_int(genome_parallelism)
    target_anno = positive_int(anno_cpus)
    target_workers = positive_int(funbgcex_workers, 2)
    target_records = positive_int(antismash_record_parallelism)
    selected_memory_budget = 0

    if normalized_mode == "auto":
        if not cpus_explicit:
            cpus = effective
        cpus = min(cpus, effective, positive_int(auto_max_cpus, 32))
        max_genomes = positive_int(auto_max_genome_parallelism, 4)
        min_cpus = positive_int(auto_min_cpus_per_genome, 2)
        memory_percent = min(100, positive_int(auto_memory_percent, 70))
        memory_per_genome = positive_int(auto_memory_per_genome_mb, 8192)
        selected_memory_budget = effective_memory
        configured_memory = nonnegative_int(memory_budget_mb)
        if configured_memory:
            selected_memory_budget = (
                min(selected_memory_budget, configured_memory)
                if selected_memory_budget
                else configured_memory
            )
        cpu_genome_limit = max(1, cpus // min_cpus)
        memory_genome_limit = max_genomes
        if selected_memory_budget:
            usable_memory = selected_memory_budget * memory_percent // 100
            memory_genome_limit = max(1, usable_memory // memory_per_genome)
        target_genomes = min(
            genomes,
            max_genomes,
            cpu_genome_limit,
            memory_genome_limit,
        )
        target_anno = positive_int(auto_max_anno_cpus, 8)
        target_workers = positive_int(auto_max_funbgcex_workers, 2)
        target_records = positive_int(
            auto_max_antismash_record_parallelism,
            3,
        )
        target_shard_cpus = cpus
        target_legacy_cpus = cpus
    else:
        if not cpus_explicit:
            cpus = min(cpus, effective)
        target_shard_cpus = (
            positive_int(antismash_shard_cpus)
            if str(antismash_shard_cpus or "").strip()
            else cpus
        )
        target_legacy_cpus = (
            positive_int(antismash_legacy_cpus)
            if str(antismash_legacy_cpus or "").strip()
            else cpus
        )

    plan = ResourceRequest(
        job_cpus=cpus,
        genome_count=genomes,
        target_genome_parallelism=target_genomes,
        target_antismash_record_parallelism=target_records,
        target_antismash_shard_cpus=target_shard_cpus,
        target_antismash_legacy_cpus=target_legacy_cpus,
        target_anno_cpus=target_anno,
        target_funbgcex_workers=target_workers,
    ).bounded_plan()
    return AnnotationResourcePlan(
        plan=plan,
        effective_cpus=effective,
        effective_memory_mb=effective_memory,
        memory_budget_mb=selected_memory_budget,
    )


def braker3_argv(
    *,
    fasta: str,
    evidence_kind: str,
    evidence_path: str,
    working_dir: str,
    species: str,
    cpus: int,
) -> list[str]:
    evidence_option = "--bam" if evidence_kind == "bam" else "--prot_seq"
    return [
        "braker.pl",
        "--genome",
        fasta,
        evidence_option,
        evidence_path,
        "--workingdir",
        working_dir,
        "--species",
        species,
        "--fungus",
        "--gff3",
        "--threads",
        str(positive_int(cpus)),
    ]


def funannotate_sort_argv(command: str, input_path: str, output_path: str) -> list[str]:
    return [command, "sort", "-i", input_path, "-o", output_path, "--minlen", "500"]


def funannotate_clean_argv(command: str, input_path: str, output_path: str) -> list[str]:
    return [command, "clean", "-i", input_path, "-o", output_path, "-m", "500"]


def funannotate_predict_argv(
    *,
    command: str,
    input_path: str,
    output_dir: str,
    species: str,
    busco_db: str,
    cpus: int,
    name: str,
    temp_dir: str,
    extra: Sequence[str] = (),
) -> list[str]:
    return [
        command,
        "predict",
        "-i",
        input_path,
        "-o",
        output_dir,
        "--species",
        species,
        "--organism",
        "fungus",
        "--busco_db",
        busco_db,
        *extra,
        "--cpus",
        str(positive_int(cpus)),
        "--name",
        name,
        "--tmpdir",
        temp_dir,
        "--force",
    ]


def emit_argv(argv: Sequence[str]) -> None:
    sys.stdout.buffer.write(b"".join(item.encode("utf-8") + b"\0" for item in argv))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("resource-plan")
    plan.add_argument("--mode", required=True)
    plan.add_argument("--requested-cpus", required=True)
    plan.add_argument("--cpus-explicit", type=int, choices=(0, 1), required=True)
    plan.add_argument("--effective-cpus", required=True)
    plan.add_argument("--effective-memory-mb", required=True)
    plan.add_argument("--total-genomes", required=True)
    plan.add_argument("--genome-parallelism", required=True)
    plan.add_argument("--anno-cpus", required=True)
    plan.add_argument("--funbgcex-workers", required=True)
    plan.add_argument("--antismash-record-parallelism", required=True)
    plan.add_argument("--antismash-shard-cpus", default="")
    plan.add_argument("--antismash-legacy-cpus", default="")
    plan.add_argument("--memory-budget-mb", default="")
    plan.add_argument("--auto-max-cpus", required=True)
    plan.add_argument("--auto-max-genome-parallelism", required=True)
    plan.add_argument("--auto-min-cpus-per-genome", required=True)
    plan.add_argument("--auto-memory-percent", required=True)
    plan.add_argument("--auto-memory-per-genome-mb", required=True)
    plan.add_argument("--auto-max-anno-cpus", required=True)
    plan.add_argument("--auto-max-funbgcex-workers", required=True)
    plan.add_argument("--auto-max-antismash-record-parallelism", required=True)

    cpuset = subparsers.add_parser("count-cpuset")
    cpuset.add_argument("--spec", required=True)
    subparsers.add_parser("online-cpus")
    effective_cpus = subparsers.add_parser("effective-cpus")
    effective_cpus.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    effective_memory = subparsers.add_parser("effective-memory")
    effective_memory.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    effective_memory.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))

    braker = subparsers.add_parser("braker3")
    braker.add_argument("--fasta", required=True)
    braker.add_argument("--evidence-kind", choices=("bam", "prot_seq"), required=True)
    braker.add_argument("--evidence-path", required=True)
    braker.add_argument("--working-dir", required=True)
    braker.add_argument("--species", required=True)
    braker.add_argument("--cpus", type=int, required=True)

    sort = subparsers.add_parser("funannotate-sort")
    sort.add_argument("--tool-command", required=True)
    sort.add_argument("--input", required=True)
    sort.add_argument("--output", required=True)

    clean = subparsers.add_parser("funannotate-clean")
    clean.add_argument("--tool-command", required=True)
    clean.add_argument("--input", required=True)
    clean.add_argument("--output", required=True)

    predict = subparsers.add_parser("funannotate-predict")
    predict.add_argument("--tool-command", required=True)
    predict.add_argument("--input", required=True)
    predict.add_argument("--output-dir", required=True)
    predict.add_argument("--species", required=True)
    predict.add_argument("--busco-db", required=True)
    predict.add_argument("--cpus", type=int, required=True)
    predict.add_argument("--name", required=True)
    predict.add_argument("--temp-dir", required=True)
    predict.add_argument("extra", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "resource-plan":
        result = build_annotation_resource_plan(
            mode=args.mode,
            requested_cpus=args.requested_cpus,
            cpus_explicit=bool(args.cpus_explicit),
            effective_cpus=args.effective_cpus,
            effective_memory_mb=args.effective_memory_mb,
            total_genomes=args.total_genomes,
            genome_parallelism=args.genome_parallelism,
            anno_cpus=args.anno_cpus,
            funbgcex_workers=args.funbgcex_workers,
            antismash_record_parallelism=args.antismash_record_parallelism,
            antismash_shard_cpus=args.antismash_shard_cpus,
            antismash_legacy_cpus=args.antismash_legacy_cpus,
            memory_budget_mb=args.memory_budget_mb,
            auto_max_cpus=args.auto_max_cpus,
            auto_max_genome_parallelism=args.auto_max_genome_parallelism,
            auto_min_cpus_per_genome=args.auto_min_cpus_per_genome,
            auto_memory_percent=args.auto_memory_percent,
            auto_memory_per_genome_mb=args.auto_memory_per_genome_mb,
            auto_max_anno_cpus=args.auto_max_anno_cpus,
            auto_max_funbgcex_workers=args.auto_max_funbgcex_workers,
            auto_max_antismash_record_parallelism=(
                args.auto_max_antismash_record_parallelism
            ),
        )
        print("\t".join(str(value) for value in result.shell_fields()))
    elif args.command == "count-cpuset":
        print(count_cpuset_cpus(args.spec))
    elif args.command == "online-cpus":
        print(online_cpu_count())
    elif args.command == "effective-cpus":
        print(effective_cpu_count(args.cgroup_root))
    elif args.command == "effective-memory":
        print(effective_memory_mb(args.cgroup_root, meminfo_path=args.meminfo))
    elif args.command == "braker3":
        emit_argv(
            braker3_argv(
                fasta=args.fasta,
                evidence_kind=args.evidence_kind,
                evidence_path=args.evidence_path,
                working_dir=args.working_dir,
                species=args.species,
                cpus=args.cpus,
            )
        )
    elif args.command == "funannotate-sort":
        emit_argv(funannotate_sort_argv(args.tool_command, args.input, args.output))
    elif args.command == "funannotate-clean":
        emit_argv(funannotate_clean_argv(args.tool_command, args.input, args.output))
    else:
        extra = args.extra[1:] if args.extra[:1] == ["--"] else args.extra
        emit_argv(
            funannotate_predict_argv(
                command=args.tool_command,
                input_path=args.input,
                output_dir=args.output_dir,
                species=args.species,
                busco_db=args.busco_db,
                cpus=args.cpus,
                name=args.name,
                temp_dir=args.temp_dir,
                extra=extra,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
