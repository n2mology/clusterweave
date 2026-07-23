#!/usr/bin/env python3
"""Pure resource planning helpers shared by the web and worker processes.

The planner deliberately has no environment or filesystem dependencies.  Callers
provide operator targets and, when needed, a memory formula.  This keeps public
submission policy deterministic while allowing a worker to use the same shape
for admission estimates.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math


def _positive_int(value: object, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ResourceRequest:
    """Requested per-job execution shape before CPU-budget clamping."""

    job_cpus: int
    genome_count: int
    target_genome_parallelism: int
    target_antismash_record_parallelism: int
    target_antismash_shard_cpus: int
    target_antismash_legacy_cpus: int
    target_anno_cpus: int
    target_funbgcex_workers: int
    run_phylogeny: bool = False
    target_phylogeny_cpus: int = 1
    target_phylogeny_parallelism: int = 1

    @classmethod
    def from_settings(
        cls,
        job_cpus: int,
        settings: Mapping[str, object],
        genome_count: int | None = None,
    ) -> "ResourceRequest":
        """Build a request from persisted job settings.

        A zero/missing antiSMASH shard CPU value has the same meaning as the
        shell pipeline: divide the job CPU budget across requested record
        shards.  If a caller cannot provide a genome count, requested genome
        fan-out is used as a conservative upper bound rather than silently
        collapsing an existing job to one genome.
        """

        cpus = _positive_int(job_cpus)
        genome_parallelism = _positive_int(settings.get("genome_parallelism", 1))
        records = _positive_int(settings.get("antismash_record_parallelism", 1))
        raw_shard_cpus = settings.get("antismash_shard_cpus", 0)
        try:
            shard_cpus = int(raw_shard_cpus)
        except (TypeError, ValueError):
            shard_cpus = 0
        if shard_cpus <= 0:
            shard_cpus = max(1, cpus // records)

        if genome_count is None:
            configured_count = settings.get("genome_count")
            genome_count = (
                _positive_int(configured_count)
                if configured_count is not None
                else genome_parallelism
            )

        return cls(
            job_cpus=cpus,
            genome_count=_positive_int(genome_count),
            target_genome_parallelism=genome_parallelism,
            target_antismash_record_parallelism=records,
            target_antismash_shard_cpus=_positive_int(shard_cpus),
            target_antismash_legacy_cpus=_positive_int(
                settings.get("antismash_legacy_cpus", cpus),
                cpus,
            ),
            target_anno_cpus=_positive_int(settings.get("anno_cpus", cpus), cpus),
            target_funbgcex_workers=_positive_int(settings.get("workers", 2), 2),
            run_phylogeny=_enabled(settings.get("run_phylogeny", False)),
            target_phylogeny_cpus=_positive_int(
                settings.get("phylogeny_cpus", 1)
            ),
            target_phylogeny_parallelism=_positive_int(
                settings.get("phylogeny_parallelism", 1)
            ),
        )

    def bounded_plan(self) -> "ResourcePlan":
        return bounded_resource_plan(self)

    def estimate(self, memory_formula: "MemoryFormula | None" = None) -> "ResourceEstimate":
        return estimate_resource_request(self, memory_formula=memory_formula)


@dataclass(frozen=True)
class ResourcePlan:
    """A runnable shape whose concurrent stage demands fit ``job_cpus``."""

    job_cpus: int
    genome_count: int
    genome_parallelism: int
    antismash_record_parallelism: int
    antismash_shard_cpus: int
    antismash_legacy_cpus: int
    anno_cpus: int
    funbgcex_workers: int
    run_phylogeny: bool = False
    phylogeny_cpus: int = 1
    phylogeny_parallelism: int = 1

    @property
    def annotation_cpu_slots(self) -> int:
        return self.genome_parallelism * self.anno_cpus

    @property
    def funbgcex_cpu_slots(self) -> int:
        return self.genome_parallelism * self.funbgcex_workers

    @property
    def antismash_sharded_cpu_slots(self) -> int:
        return (
            self.genome_parallelism
            * self.antismash_record_parallelism
            * self.antismash_shard_cpus
        )

    @property
    def antismash_legacy_cpu_slots(self) -> int:
        return self.genome_parallelism * self.antismash_legacy_cpus

    @property
    def phylogeny_cpu_slots(self) -> int:
        if not self.run_phylogeny:
            return 0
        return self.phylogeny_parallelism * self.phylogeny_cpus

    @property
    def cpu_slots(self) -> int:
        """Declared job budget or the peak staged demand, whichever is larger."""

        return max(
            self.job_cpus,
            self.annotation_cpu_slots,
            self.funbgcex_cpu_slots,
            self.antismash_sharded_cpu_slots,
            self.antismash_legacy_cpu_slots,
            self.phylogeny_cpu_slots,
        )

    @property
    def concurrent_antismash_shards(self) -> int:
        return self.genome_parallelism * self.antismash_record_parallelism

    def as_settings(self) -> dict[str, int | bool]:
        return {
            "genome_count": self.genome_count,
            "genome_parallelism": self.genome_parallelism,
            "antismash_record_parallelism": self.antismash_record_parallelism,
            "antismash_shard_cpus": self.antismash_shard_cpus,
            "antismash_legacy_cpus": self.antismash_legacy_cpus,
            "anno_cpus": self.anno_cpus,
            "workers": self.funbgcex_workers,
            "run_phylogeny": self.run_phylogeny,
            "phylogeny_cpus": self.phylogeny_cpus,
            "phylogeny_parallelism": self.phylogeny_parallelism,
        }


@dataclass(frozen=True)
class MemoryFormula:
    """Configurable peak-memory safety estimate.

    Annotation and antiSMASH can overlap across genome fan-out workers, so the
    core terms are additive rather than assuming perfectly separated stages.
    Optional phylogeny runs after the core stages, so its peak is compared with
    the core peak instead of being added to it.
    """

    base_memory_mb: int = 1024
    per_genome_memory_mb: int = 2048
    per_antismash_shard_memory_mb: int = 2048
    per_annotation_cpu_memory_mb: int = 256
    per_funbgcex_worker_memory_mb: int = 128
    phylogeny_base_memory_mb: int = 1024
    per_phylogeny_cpu_memory_mb: int = 2048
    safety_factor: float = 1.25
    minimum_memory_mb: int = 2048

    def __post_init__(self) -> None:
        numeric_values = {
            "base_memory_mb": self.base_memory_mb,
            "per_genome_memory_mb": self.per_genome_memory_mb,
            "per_antismash_shard_memory_mb": self.per_antismash_shard_memory_mb,
            "per_annotation_cpu_memory_mb": self.per_annotation_cpu_memory_mb,
            "per_funbgcex_worker_memory_mb": self.per_funbgcex_worker_memory_mb,
            "phylogeny_base_memory_mb": self.phylogeny_base_memory_mb,
            "per_phylogeny_cpu_memory_mb": self.per_phylogeny_cpu_memory_mb,
        }
        for name, value in numeric_values.items():
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.minimum_memory_mb < 1:
            raise ValueError("minimum_memory_mb must be positive")
        if not math.isfinite(self.safety_factor) or self.safety_factor < 1.0:
            raise ValueError("safety_factor must be finite and at least 1.0")

    def estimate_mb(self, plan: ResourcePlan) -> int:
        core_memory_mb = (
            self.base_memory_mb
            + plan.genome_parallelism * self.per_genome_memory_mb
            + plan.concurrent_antismash_shards * self.per_antismash_shard_memory_mb
            + plan.annotation_cpu_slots * self.per_annotation_cpu_memory_mb
            + plan.funbgcex_cpu_slots * self.per_funbgcex_worker_memory_mb
        )
        phylogeny_memory_mb = 0
        if plan.run_phylogeny:
            phylogeny_memory_mb = (
                self.phylogeny_base_memory_mb
                + plan.phylogeny_cpu_slots * self.per_phylogeny_cpu_memory_mb
            )
        raw_memory_mb = max(core_memory_mb, phylogeny_memory_mb)
        return max(
            self.minimum_memory_mb,
            math.ceil(raw_memory_mb * self.safety_factor),
        )


@dataclass(frozen=True)
class ResourceEstimate:
    cpu_slots: int
    memory_mb: int
    plan: ResourcePlan


def bounded_resource_plan(request: ResourceRequest) -> ResourcePlan:
    """Return a positive plan bounded by job CPUs and available genomes."""

    cpus = _positive_int(request.job_cpus)
    genome_count = _positive_int(request.genome_count)
    genomes = min(
        _positive_int(request.target_genome_parallelism),
        genome_count,
        cpus,
    )
    per_genome_budget = max(1, cpus // genomes)

    records = min(
        _positive_int(request.target_antismash_record_parallelism),
        per_genome_budget,
    )
    per_shard_budget = max(1, cpus // (genomes * records))
    # The bounded runner executes one family child at a time.  Keep admission
    # and manifests truthful until a tested concurrent collector exists.
    phylogeny_parallelism = 1
    phylogeny_cpus = min(
        _positive_int(request.target_phylogeny_cpus),
        max(1, cpus // phylogeny_parallelism),
    )

    return ResourcePlan(
        job_cpus=cpus,
        genome_count=genome_count,
        genome_parallelism=genomes,
        antismash_record_parallelism=records,
        antismash_shard_cpus=min(
            _positive_int(request.target_antismash_shard_cpus),
            per_shard_budget,
        ),
        antismash_legacy_cpus=min(
            _positive_int(request.target_antismash_legacy_cpus),
            per_genome_budget,
        ),
        anno_cpus=min(_positive_int(request.target_anno_cpus), per_genome_budget),
        funbgcex_workers=min(
            _positive_int(request.target_funbgcex_workers),
            per_genome_budget,
        ),
        run_phylogeny=bool(request.run_phylogeny),
        phylogeny_cpus=phylogeny_cpus,
        phylogeny_parallelism=phylogeny_parallelism,
    )


def estimate_resource_request(
    request: ResourceRequest,
    *,
    memory_formula: MemoryFormula | None = None,
) -> ResourceEstimate:
    plan = bounded_resource_plan(request)
    formula = memory_formula or MemoryFormula()
    return ResourceEstimate(
        cpu_slots=plan.cpu_slots,
        memory_mb=formula.estimate_mb(plan),
        plan=plan,
    )


def estimate_job_resources(
    job_cpus: int,
    settings: Mapping[str, object],
    genome_count: int | None = None,
    *,
    memory_formula: MemoryFormula | None = None,
) -> ResourceEstimate:
    """Stable worker adapter for CPU/memory admission reservations."""

    request = ResourceRequest.from_settings(job_cpus, settings, genome_count)
    return estimate_resource_request(request, memory_formula=memory_formula)


def genome_count_from_input_summary(summary: Mapping[str, object] | None) -> int:
    """Count logical genomes, collapsing same-stem FASTA/GenBank pairs."""

    if not summary:
        return 1
    explicit_count = summary.get("genome_count")
    if explicit_count is not None:
        return _positive_int(explicit_count)

    try:
        accession_count = max(0, int(summary.get("accession_count", 0)))
    except (TypeError, ValueError):
        accession_count = 0

    stems: set[str] = set()
    readiness = summary.get("genome_readiness")
    if isinstance(readiness, list):
        for item in readiness:
            if not isinstance(item, Mapping):
                continue
            stem = str(item.get("stem") or "").strip().lower()
            if stem:
                stems.add(stem)

    if stems:
        uploaded_genome_count = len(stems)
    else:
        try:
            uploaded_genome_count = max(0, int(summary.get("genome_file_count", 0)))
        except (TypeError, ValueError):
            uploaded_genome_count = 0

    return max(1, accession_count + uploaded_genome_count)
