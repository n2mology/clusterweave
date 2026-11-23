"""Read host and local Docker capacity without changing allocation or services."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

GIB = 1024**3


def _read(path):
    try:
        with Path(path).open() as handle:
            return handle.read(65536).strip()
    except (OSError, UnicodeError):
        return ""


def _number(path):
    text = _read(path)
    return int(text) if text.isascii() and text.isdigit() and 0 <= int(text) < 1 << 60 else None


def _run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=True)
    return result.stdout.strip()


def _cgroups(proc_root, cgroup_root):
    roots = {cgroup_root, cgroup_root / "memory", cgroup_root / "cpu"}
    for line in _read(proc_root / "self/cgroup").splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3 or ".." in Path(parts[2]).parts:
            continue
        controllers = parts[1].split(",") if parts[1] else [""]
        for controller in controllers:
            if controller not in {"", "cpu", "memory"}:
                continue
            base = cgroup_root / controller
            current = base / parts[2].lstrip("/")
            # Parent quotas can be tighter than the process's own group.
            for _ in range(64):
                roots.add(current)
                if current == base:
                    break
                current = current.parent
    return sorted(roots)


def host_resources(*, proc_root=Path("/proc"), cgroup_root=Path("/sys/fs/cgroup")):
    logical = os.cpu_count()
    cpu_limits = [logical] if logical and logical > 0 else []
    try:
        cpu_limits.append(len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    total = available = None
    availability_source = "unavailable"
    memory = {}
    for line in _read(proc_root / "meminfo").splitlines():
        match = re.fullmatch(r"(MemTotal|MemAvailable):\s+(\d+)\s+kB", line)
        if match:
            memory[match[1]] = int(match[2]) * 1024
    total, available = memory.get("MemTotal"), memory.get("MemAvailable")
    if available is not None:
        availability_source = "Linux MemAvailable"
    if total is None:
        try:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (AttributeError, OSError, ValueError):
            pass
    if platform.system() == "Darwin":
        try:
            total = int(_run(["sysctl", "-n", "hw.memsize"]))
            text = _run(["vm_stat"])
            page_size = re.search(r"page size of (\d+) bytes", text)
            pages = re.findall(r"Pages (?:free|inactive|speculative):\s+(\d+)\.", text)
            if page_size and pages:
                available = int(page_size[1]) * sum(map(int, pages))
                availability_source = "macOS free/inactive/speculative page estimate"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    memory_limits = [total] if total and total > 0 else []
    remaining = [available] if available is not None else []
    for directory in _cgroups(proc_root, cgroup_root):
        quota = _read(directory / "cpu.max").split()
        try:
            if len(quota) == 2 and quota[0] != "max" and int(quota[1]) > 0:
                cpu_limits.append(int(quota[0]) // int(quota[1]))
        except ValueError:
            pass
        quota_v1, period = _number(directory / "cpu.cfs_quota_us"), _number(directory / "cpu.cfs_period_us")
        if quota_v1 is not None and period:
            cpu_limits.append(quota_v1 // period)
        for limit_name, current_name in [("memory.max", "memory.current"), ("memory.limit_in_bytes", "memory.usage_in_bytes")]:
            limit, current = _number(directory / limit_name), _number(directory / current_name)
            if limit is not None:
                memory_limits.append(limit)
                if current is not None:
                    remaining.append(max(0, limit - current))
    effective_memory = min(memory_limits) if memory_limits else None
    available_memory = min(remaining + memory_limits) if remaining else None
    return {
        "logical_cpus": logical, "effective_cpus": min(cpu_limits) if cpu_limits else None,
        "total_memory_bytes": total, "effective_memory_bytes": effective_memory,
        "available_memory_bytes": available_memory, "availability_source": availability_source,
    }


def docker_resources():
    endpoint = "" if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST", "")
    try:
        if not endpoint:
            endpoint = json.loads(_run(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"]))
        if not isinstance(endpoint, str) or not endpoint.startswith(("unix://", "npipe://")):
            return {"state": "remote", "cpus": None, "memory_bytes": None}
        info = json.loads(_run(["docker", "info", "--format", "{{json .}}"]))
        cpus, memory = info.get("NCPU"), info.get("MemTotal")
        if type(cpus) is not int or type(memory) is not int or cpus <= 0 or memory <= 0:
            raise ValueError("Incomplete Docker capacity")
        return {"state": "available", "cpus": cpus, "memory_bytes": memory}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return {"state": "unavailable", "cpus": None, "memory_bytes": None}


def scan_resources(source_root):
    from local_setup import assess_resources
    observation = {"host": host_resources(), "docker": docker_resources(),
                   "disk_free_bytes": shutil.disk_usage(source_root).free,
                   "observed_at": int(time.time())}
    return assess_resources(observation)
