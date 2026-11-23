"""Bounded local setup settings shared by the terminal and browser guide."""
from __future__ import annotations

from urllib.parse import urlsplit

PREFIX = "CLUSTERWEAVE_"
CACHE_ROOT = "/var/cache/clusterweave/accessions"
DEFAULTS = {
    "WORKER_CONCURRENCY": "1",
    PREFIX + "PUBLIC_GENOME_PARALLELISM": "2",
    PREFIX + "PUBLIC_ANTISMASH_RECORD_PARALLELISM": "2",
    "HOST_PORT": "8080",
    PREFIX + "WORKER_CPU_LIMIT": "4",
    PREFIX + "MAX_CPUS_PER_JOB": "4",
    PREFIX + "WORKER_MEM_LIMIT": "16g",
    PREFIX + "ACCESSION_CACHE_ROOT": CACHE_ROOT,
    PREFIX + "ACCESSION_CACHE_MAX_BYTES": str(10 * 1024**3),
    PREFIX + "ACCESSION_CACHE_MAX_ENTRIES": "256",
    PREFIX + "ACCESSION_CACHE_MAX_AGE_SECONDS": str(30 * 86400),
    PREFIX + "LOCAL_RESTART_POLICY": "no",
    PREFIX + "LOCAL_OPEN_BROWSER": "0",
    PREFIX + "LOCAL_PREPARED_ONLY": "1",
}


def positive(value, label, maximum=2**63 - 1):
    text = str(value)
    if not text.isascii() or not text.isdigit() or not 0 < int(text) <= maximum:
        raise ValueError(f"{label} requires a positive integer up to {maximum}.")
    return int(text)


def describe(values):
    """Return only allowlisted settings; never expose credentials or host paths."""
    cpus = positive(values.get(PREFIX + "WORKER_CPU_LIMIT", "4"), "Worker CPUs", 1024)
    job_cpus = positive(values.get(PREFIX + "MAX_CPUS_PER_JOB", "4"), "Job CPUs", cpus)
    memory = str(values.get(PREFIX + "WORKER_MEM_LIMIT", "16g"))
    if not memory.endswith("g"):
        raise ValueError("Worker memory requires an integer GiB value followed by g, for example 16g. Use the advanced configuration documentation for other formats.")
    memory_gib = positive(memory[:-1], "Worker memory GiB", 1048576)
    if memory_gib < 16:
        raise ValueError("Allow at least 16 GiB for the worker; larger annotations can require more.")
    url = values.get(PREFIX + "PUBLIC_BASE_URL", "http://127.0.0.1:8080/")
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Local setup requires an HTTP loopback URL without credentials or a path.")
    port = positive(values.get("HOST_PORT", str(parsed.port or 80)), "Web port", 65535)
    if (parsed.port or 80) != port:
        raise ValueError("Web port and local browser URL must match.")
    restart = values.get(PREFIX + "LOCAL_RESTART_POLICY", "unless-stopped")
    opening = values.get(PREFIX + "LOCAL_OPEN_BROWSER", "0")
    if restart not in {"no", "unless-stopped"} or opening not in {"0", "1"}:
        raise ValueError("Choose no/unless-stopped for automatic startup and 0/1 for browser opening.")
    return {
        "concurrent_jobs": positive(values.get("WORKER_CONCURRENCY", "1"), "Concurrent jobs", cpus),
        "genome_parallelism": positive(values.get(PREFIX + "PUBLIC_GENOME_PARALLELISM", "2"), "Genome parallelism"),
        "record_parallelism": positive(values.get(PREFIX + "PUBLIC_ANTISMASH_RECORD_PARALLELISM", "2"), "Record parallelism"),
        "url": url, "worker_cpus": cpus, "job_cpus": job_cpus, "worker_memory_gib": memory_gib,
        "cache_enabled": bool(values.get(PREFIX + "ACCESSION_CACHE_ROOT", "")),
        "cache_max_bytes": positive(values.get(PREFIX + "ACCESSION_CACHE_MAX_BYTES", DEFAULTS[PREFIX + "ACCESSION_CACHE_MAX_BYTES"]), "Cache bytes"),
        "cache_max_entries": positive(values.get(PREFIX + "ACCESSION_CACHE_MAX_ENTRIES", "256"), "Cache entries"),
        "cache_max_age_seconds": positive(values.get(PREFIX + "ACCESSION_CACHE_MAX_AGE_SECONDS", str(30 * 86400)), "Cache age"),
        "automatic_startup": restart == "unless-stopped", "open_browser": opening == "1",
        "job_retention": "Until manual deletion" if values.get(PREFIX + "JOB_RETENTION_DAYS") == "never" else "Existing expiry policy",
        "storage": "Separate worker-only Docker volume" if values.get(PREFIX + "ACCESSION_CACHE_ROOT", "") in {"", CACHE_ROOT} else "Existing operator-managed cache storage",
    }


def assess_resources(observation):
    """Plan the local baseline; capacity does not establish scientific fitness."""
    gib = 1024**3
    host, docker = observation["host"], observation["docker"]
    cpus = host.get("effective_cpus")
    total = host.get("effective_memory_bytes")
    available = host.get("available_memory_bytes")
    reasons = []
    unknown = cpus is None or total is None or available is None
    blocked = (cpus is not None and cpus < 4) or (total is not None and total < 20 * gib)
    if cpus is not None and cpus < 4:
        reasons.append("The local baseline needs 4 usable CPUs. Use a larger machine or a separately configured external executor.")
    if total is not None and total < 20 * gib:
        reasons.append("The local baseline needs 20 GiB of host RAM: 16 for the worker, 2 for web and 2 for the host.")
    cpu_max = max(0, cpus - 1) if cpus is not None else 0
    memory_bounds = [max(0, total - 4 * gib)] if total is not None else []
    if available is not None:
        memory_bounds.append(max(0, available - 4 * gib))
    else:
        reasons.append("Available RAM could not be measured. Total RAM is a ceiling; check current headroom before starting services.")
    if docker["state"] == "available":
        cpu_max = min(cpu_max, max(0, docker["cpus"] - 1))
        memory_bounds.append(max(0, docker["memory_bytes"] - 2 * gib))
        if docker["cpus"] < 4 or docker["memory_bytes"] < 18 * gib:
            blocked = True
            reasons.append("Docker needs at least 4 CPUs and 18 GiB of RAM allocated. Increase its allocation, then scan again.")
    elif docker["state"] == "remote":
        reasons.append("The Docker endpoint is remote. This local scan does not inspect it; select a local Docker context before starting.")
    else:
        reasons.append("Docker is not available yet. You can save host-based settings; start local Docker and scan again before preparation.")
    if unknown:
        reasons.append("CPU or RAM availability could not be measured. Check host access before choosing a configuration.")
    memory_max = min(memory_bounds) // gib if memory_bounds else 0
    busy = not blocked and not unknown and memory_max < 16
    if busy:
        reasons.append("There is not enough RAM available right now. Close other work or wait, then scan again. Swap is not counted as RAM.")
    verdict = "blocked" if blocked else "unknown" if unknown else "busy" if busy else "needs_docker" if docker["state"] != "available" else "ready"
    if verdict == "ready":
        reasons.insert(0, "Room to weave. The local CPU/RAM baseline fits.")
    if observation.get("disk_free_bytes", 0) < 20 * gib:
        reasons.append("Source filesystem space is low. Check room for images, databases, cache and results; Docker's virtual disk is separate.")
    can_configure = verdict in {"ready", "needs_docker"}
    return {**observation, "verdict": verdict, "can_configure": can_configure,
            "reasons": reasons, "limits": {"worker_cpus": cpu_max, "worker_memory_gib": memory_max},
            "maximum": {"worker_cpus": min(1024, cpu_max), "job_cpus": min(1024, cpu_max),
                        "worker_memory_gib": min(1048576, memory_max)} if can_configure else None,
            "recommended": {"worker_cpus": min(4, cpu_max), "job_cpus": min(4, cpu_max),
                            "worker_memory_gib": min(32, max(16, (memory_max // 2 // 4) * 4))} if can_configure else None}


def validate_resources(values, report):
    if not report["can_configure"]:
        raise ValueError(" ".join(report["reasons"]))
    settings = describe(values)
    if settings["worker_cpus"] > report["limits"]["worker_cpus"]:
        raise ValueError(f"Worker CPUs exceed the current safe limit of {report['limits']['worker_cpus']}. Leave one CPU for the host/web service, or scan again after changing Docker allocation.")
    if settings["worker_memory_gib"] > report["limits"]["worker_memory_gib"]:
        raise ValueError(f"Worker RAM exceeds the current {report['limits']['worker_memory_gib']} GiB limit. Keep room for web, the host and other work; scan again if availability changes.")
    return settings
