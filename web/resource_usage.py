"""Bounded observations of one native stage and its labelled tool containers."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import quote


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def docker_json(path):
    connection = DockerConnection("localhost", timeout=0.4)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 2 * 1024 * 1024:
            raise ValueError("Resource observation unavailable")
        return json.loads(raw)
    finally:
        connection.close()


def controller_image():
    name = os.environ.get("HOSTNAME", "")
    if (os.environ.get("CLUSTERWEAVE_RESOURCE_DOCKER_OBSERVATION", "1") != "1"
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)
            or not Path("/var/run/docker.sock").exists()):
        return None
    try:
        image = docker_json("/containers/" + name + "/json").get("Image", "")
        return image if re.fullmatch(r"sha256:[0-9a-f]{64}", image) else None
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return None


def process_group_rss(group, proc=Path("/proc")):
    total, count = 0, 0
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        count += 1
        if count > 8192:
            raise ValueError("Process observation bound exceeded")
        try:
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == group:
                total += int(fields[21]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue
    return total


class StageSampler:
    def __init__(self, job_id, group, *, interval=1.0):
        self.job_id, self.group, self.interval = job_id, group, interval
        self.stop = threading.Event()
        self.thread = None
        self.started = time.time()
        self.cpu, self.baseline = {}, {}
        self.images = set()
        self.samples, self.native_peak, self.combined_peak = 0, 0, 0
        self.docker_observed = False
        self.incomplete = False

    def sample(self):
        native = process_group_rss(self.group)
        self.native_peak = max(native, self.native_peak)
        container_memory = 0
        if os.environ.get("CLUSTERWEAVE_RESOURCE_DOCKER_OBSERVATION", "1") == "1" and Path("/var/run/docker.sock").exists():
            try:
                filters = quote(json.dumps({"label": ["clusterweave.job_id=" + self.job_id]}))
                containers = docker_json("/containers/json?filters=" + filters)
                if not isinstance(containers, list) or len(containers) > 32:
                    raise ValueError("Container observation bound exceeded")
                for row in containers:
                    if row.get("Labels", {}).get("clusterweave.job_id") != self.job_id:
                        continue
                    identifier = row["Id"]
                    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
                        continue
                    image = row.get("ImageID", "").removeprefix("sha256:")
                    if len(image) == 64 and all(c in "0123456789abcdef" for c in image):
                        self.images.add(image)
                    stats = docker_json("/containers/" + identifier + "/stats?stream=false&one-shot=true")
                    cpu = int(stats["cpu_stats"]["cpu_usage"]["total_usage"])
                    if identifier not in self.baseline:
                        self.baseline[identifier] = cpu if row.get("Created", 0) <= int(self.started) else 0
                    self.cpu[identifier] = max(self.cpu.get(identifier, 0), max(0, cpu - self.baseline[identifier]))
                    container_memory += max(0, int(stats.get("memory_stats", {}).get("usage", 0)))
                self.docker_observed = True
            except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException):
                self.incomplete = True
        self.combined_peak = max(self.combined_peak, native + container_memory)
        self.samples += 1

    def _run(self):
        while not self.stop.is_set():
            try:
                self.sample()
            except (OSError, ValueError):
                self.incomplete = True
            self.stop.wait(self.interval)

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=16)
        return {"sample_interval_seconds": self.interval, "samples": self.samples,
                "native_sampled_peak_sum_rss_bytes": self.native_peak if self.samples else None,
                "sampled_peak_rss_plus_container_usage_bytes": self.combined_peak if self.samples else None,
                "container_sampled_cpu_seconds": sum(self.cpu.copy().values()) / 1e9 if self.docker_observed else None,
                "container_count_observed": len(self.cpu),
                "observed_container_image_sha256s": sorted(self.images.copy()),
                "container_observation": "sampled" if self.docker_observed else "unavailable",
                "sampling_incomplete": self.incomplete or self.thread.is_alive(),
                "memory_method": "sampled sum of native process RSS and labelled container cgroup usage; shared pages/cache may be counted; not an exact physical-memory peak",
                "container_cpu_method": "sampled cumulative CPU; short-lived containers and final intervals can be missed"}
