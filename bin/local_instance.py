#!/usr/bin/env python3
"""Set up ClusterWeave, prepare a local instance, or return to your work."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from local_resources import scan_resources
from bootstrap_versions import citation_lines
from local_setup import CACHE_ROOT, DEFAULTS, PREFIX, describe, positive, validate_resources

ENV_FILE = ROOT / ".env"
KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def read_config():
    if ENV_FILE.is_symlink():
        raise ValueError("The private .env must be a regular file, not a link.")
    if not ENV_FILE.exists():
        return "", {}
    info = ENV_FILE.stat()
    if not ENV_FILE.is_file() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Keep .env owned by your account with mode 0600 before using the assistant.")
    text = ENV_FILE.read_text()
    values = {}
    for line in text.splitlines():
        match = KEY.fullmatch(line.strip())
        if match:
            key, value = match.groups()
            if key in values:
                raise ValueError("Duplicate configuration keys require review in a private text editor.")
            if value.startswith(('"', "'")) and value.endswith(value[:1]):
                value = value[1:-1]
            values[key] = value
    return text, values


def local_only(values):
    if (values.get(PREFIX + "ACCESS_PROFILE") != "local-owner"
            or values.get(PREFIX + "BIND_ADDRESS") not in {"127.0.0.1", "::1"}):
        raise ValueError("This assistant supports the loopback local-owner profile. Keep hosted/external configuration under operator control.")


def write_config(original, changes):
    # Serialize compare-and-replace; cancellation and concurrent edits retain the old file.
    lock = os.open(ROOT, os.O_RDONLY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current, _ = read_config()
        if current != original:
            raise ValueError("Configuration changed during review. Run the assistant again.")
        pending = dict(changes)
        lines = []
        for line in original.splitlines():
            match = KEY.fullmatch(line.strip())
            if match and match[1] in pending:
                lines.append(f"{match[1]}={pending.pop(match[1])}")
            else:
                lines.append(line)
        if not original:
            lines.append("# Private local configuration; never share this file.")
        lines.extend(f"{key}={value}" for key, value in pending.items())
        fd, name = tempfile.mkstemp(prefix=".env.setup-", dir=ROOT)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write("\n".join(lines) + "\n")
                handle.flush(); os.fsync(handle.fileno())
            os.replace(name, ENV_FILE)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    finally:
        os.close(lock)


def show_banner():
    """Display the owner's exact final artwork when it fits, then the citation."""
    columns = shutil.get_terminal_size().columns
    selected = ROOT / "visuals" / "ascii_clusterweave.txt"
    if selected.is_file():
        artwork = selected.read_text()
        if columns >= max(map(len, artwork.splitlines()), default=0):
            print(artwork, end="")
    for line in citation_lines(ROOT):
        print(line)
    print("Let's get your local workbench ready.\n")


def ask(label, default):
    return input(f"{label} [{default}]: ").strip() or str(default)


def yes(label, default=False):
    while True:
        answer = ask(label + " (yes/no)", "yes" if default else "no").lower()
        if answer in {"yes", "y", "no", "n"}:
            return answer in {"yes", "y"}
        print("A quick yes or no will do. Your settings haven't changed.")


def docker_environment(values):
    env = os.environ.copy()
    # The reviewed file is authoritative, including over inherited shell values.
    for key in list(env):
        if key.startswith(("CLUSTERWEAVE_", "COMPOSE_")) or key in values:
            env.pop(key, None)
    return env


def compose(values, *args, capture=False, timeout=180):
    return subprocess.run(["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(ENV_FILE),
                           "-f", str(ROOT / "docker-compose.yml"), "-p", "clusterweave", *args],
                          env=docker_environment(values), check=True, timeout=timeout,
                          stdout=subprocess.PIPE if capture else None, text=True)


def resources():
    return scan_resources(ROOT)


def print_resources(report):
    host, docker = report["host"], report["docker"]
    gib = lambda value: "unknown" if value is None else f"{value / 1024**3:.1f} GiB"
    print("\nQuick scan. Let's find some elbow room.")
    print(f"CPU: {host['effective_cpus'] if host['effective_cpus'] is not None else 'unknown'} usable / {host['logical_cpus'] if host['logical_cpus'] is not None else 'unknown'} logical")
    print(f"RAM: {gib(host['total_memory_bytes'])} total / {gib(host['available_memory_bytes'])} available now")
    if host['effective_memory_bytes'] != host['total_memory_bytes']:
        print(f"Process memory ceiling: {gib(host['effective_memory_bytes'])}")
    if docker['state'] == 'available':
        print(f"Docker allocation: {docker['cpus']} CPUs / {gib(docker['memory_bytes'])} RAM")
    else:
        print(f"Docker: {docker['state']}; its allocation is unverified")
    labels = {"ready": "LOCAL BASELINE FITS", "needs_docker": "HOST FITS; CHECK DOCKER NEXT",
              "blocked": "BELOW THE LOCAL BASELINE", "busy": "NOT ENOUGH HEADROOM RIGHT NOW", "unknown": "SCAN INCOMPLETE"}
    print(labels[report['verdict']])
    for reason in report['reasons']:
        print(reason)
    if report['can_configure']:
        recommended = report['recommended']
        maximum = report['maximum']
        print(f"Conservative: {recommended['worker_cpus']} CPUs / {recommended['worker_memory_gib']} GiB. More room for other work.")
        print(f"Maximum available: {maximum['worker_cpus']} CPUs / {maximum['worker_memory_gib']} GiB. Put this machine to work.")
        print("Both leave room for the host and web service. Available RAM can change; we'll check again before saving.")
    print(f"Source disk: {gib(report['disk_free_bytes'])} free. Check Docker's virtual disk separately.")
    print("Large annotations may need more. This is a capacity check, not a benchmark.")


def review(values):
    settings = describe(values)
    print("\nHere's the plan. Secrets stay private.")
    print(f"Local browser: {settings['url']} | local-owner access")
    print(f"Worker: {settings['worker_cpus']} CPUs / {settings['worker_memory_gib']} GiB | job limit: {settings['job_cpus']} CPUs")
    print(f"Jobs: {settings['job_retention']}. Up to {settings['concurrent_jobs']} concurrent; {settings['genome_parallelism']} genomes/job and {settings['record_parallelism']} detector records/genome, bounded by CPU/RAM.")
    print(f"Inputs per web job: {values.get(PREFIX + 'MAX_ACCESSIONS', '50')} accessions / {values.get(PREFIX + 'MAX_GENOME_FILES', '50')} uploaded genomes.")
    print(f"Cache: {'on' if settings['cache_enabled'] else 'off'} | {settings['cache_max_bytes'] / 1024**3:g} GiB / {settings['cache_max_entries']} entries / {settings['cache_max_age_seconds'] / 86400:g} days since population")
    print(f"Storage: {settings['storage']}. Compatible public accession results can be reused.")
    print("Cache eviction means recomputation. Retained jobs stay put; leave disk for results and prepared assets.")
    print(f"Start after Docker starts: {'yes' if settings['automatic_startup'] else 'no'} | open browser on launcher start: {'yes' if settings['open_browser'] else 'no'}")
    print("Docker starts first; services get ready next; browser opening needs a signed-in desktop. No host hooks are installed.")
    return settings


def initialize(args):
    original, existing = read_config()
    interactive = not args.non_interactive and sys.stdin.isatty()
    if existing:
        local_only(existing)
    report = resources()
    print_resources(report)
    if existing:
        review(existing)
        if not args.reconfigure:
            print("Existing configuration kept unchanged. To review changes: ./bin/init_local_instance.sh --reconfigure")
            if args.defaults:
                print("Already set up? Return with ./bin/local_instance.sh start. Saved settings but not prepared yet? ./bin/local_instance.sh weave")
            return
    elif args.reconfigure:
        raise ValueError("No existing configuration. Run initialization without --reconfigure.")
    if args.reconfigure and not interactive and not args.apply:
        raise ValueError("Noninteractive reconfiguration requires --apply after reviewing the intended options.")
    if not report["can_configure"]:
        raise ValueError(" ".join(report["reasons"]))
    recommended = report["recommended"]
    changes = {} if existing else {
        **DEFAULTS, PREFIX + "BIND_ADDRESS": "127.0.0.1", PREFIX + "DOCKER_PLATFORM": "linux/amd64",
        PREFIX + "PUBLIC_MODE": "1", PREFIX + "ACCESS_PROFILE": "local-owner",
        PREFIX + "JOB_RETENTION_DAYS": "never", PREFIX + "ALLOW_NEVER_EXPIRE_JOBS": "1",
        PREFIX + "SUBMISSIONS_OPEN": "1", PREFIX + "MAX_ACCESSIONS": "50", PREFIX + "MAX_GENOME_FILES": "50",
        PREFIX + "WORKER_CPU_LIMIT": str(recommended["worker_cpus"]),
        PREFIX + "MAX_CPUS_PER_JOB": str(recommended["job_cpus"]), "PIPELINE_CPUS": str(recommended["job_cpus"]),
        PREFIX + "WORKER_MEM_LIMIT": str(recommended["worker_memory_gib"]) + "g",
    }
    values = {**existing, **changes}
    choice = "1"
    if interactive:
        print("\nHow shall we weave?")
        print("1. Conservative: keep some elbow room for other work")
        print("2. Maximum available: give ClusterWeave the measured safe capacity")
        print("3. Customize: choose each setting with me")
        print("4. Cancel: leave everything as it is")
        while True:
            choice = ask("Pick your pace", "2" if args.recommendation == "maximum" else "1")
            if choice in {"1", "2", "3", "4"}:
                break
            print("Pick 1, 2, 3 or 4. We can take this one step at a time.")
        if choice == "4":
            print("All right. Configuration and data unchanged."); return
    selected = report["maximum"] if choice == "2" or (not interactive and args.recommendation == "maximum") else recommended
    if not existing or interactive and choice in {"1", "2"} or args.recommendation is not None:
        changes.update({PREFIX + "WORKER_CPU_LIMIT": str(selected["worker_cpus"]),
                        PREFIX + "MAX_CPUS_PER_JOB": str(selected["job_cpus"]),
                        PREFIX + "WORKER_MEM_LIMIT": str(selected["worker_memory_gib"]) + "g"})
        values.update(changes)
    fields = [
        ("worker_cpus", PREFIX + "WORKER_CPU_LIMIT", f"How many CPUs shall the worker use? (up to {report['limits']['worker_cpus']}; Conservative {recommended['worker_cpus']})"),
        ("job_cpus", PREFIX + "MAX_CPUS_PER_JOB", "How many CPUs may one job use?"),
        ("concurrent_jobs", "WORKER_CONCURRENCY", "How many jobs may run concurrently?"),
        ("genome_parallelism", PREFIX + "PUBLIC_GENOME_PARALLELISM", "Maximum simultaneous genomes per job?"),
        ("record_parallelism", PREFIX + "PUBLIC_ANTISMASH_RECORD_PARALLELISM", "Maximum detector record shards per genome?"),
        ("memory_gib", PREFIX + "WORKER_MEM_LIMIT", f"How much RAM for the worker, in GiB? (16..{report['limits']['worker_memory_gib']}; Conservative {recommended['worker_memory_gib']})"),
        ("port", "HOST_PORT", "Which local web port shall we use?"),
        ("cache_gib", PREFIX + "ACCESSION_CACHE_MAX_BYTES", "How much room for reusable accession results, in GiB?"),
        ("cache_entries", PREFIX + "ACCESSION_CACHE_MAX_ENTRIES", "How many accession results may the cache keep?"),
        ("cache_days", PREFIX + "ACCESSION_CACHE_MAX_AGE_SECONDS", "Keep cached results for how many days since population?"),
        ("max_accessions", PREFIX + "MAX_ACCESSIONS", "How many accessions may one web job accept?"),
        ("max_genome_files", PREFIX + "MAX_GENOME_FILES", "How many uploaded genomes may one web job accept?"),
    ]
    for attr, key, label in fields:
        value = getattr(args, attr)
        current = values.get(key, DEFAULTS.get(key, "50" if attr in {"max_accessions", "max_genome_files"} else "4"))
        if attr == "job_cpus" and int(current) > int(values[PREFIX + "WORKER_CPU_LIMIT"]):
            current = values[PREFIX + "WORKER_CPU_LIMIT"]
            changes[key] = current
            values[key] = current
        if attr == "memory_gib": current = current.removesuffix("g")
        if attr == "cache_gib": current = int(current) // 1024**3
        if attr == "cache_days": current = int(current) // 86400
        if interactive and choice == "3":
            while True:
                value = ask(label, current)
                try:
                    parsed = positive(value, label)
                    ceiling = {"worker_cpus": report["limits"]["worker_cpus"],
                               "job_cpus": int(values[PREFIX + "WORKER_CPU_LIMIT"]),
                               "memory_gib": report["limits"]["worker_memory_gib"], "port": 65535}.get(attr)
                    if ceiling is not None and parsed > ceiling:
                        raise ValueError(f"Let's keep that at or below {ceiling} for this setup.")
                    if attr == "memory_gib" and parsed < 16:
                        raise ValueError("The worker needs at least 16 GiB. Larger annotations may need more.")
                    break
                except ValueError as exc:
                    print(f"{exc} Try another value, or press Ctrl-C to leave setup.")
        if value is not None:
            parsed = positive(value, label)
            if attr == "memory_gib": value = str(parsed) + "g"
            elif attr == "cache_gib": value = str(parsed * 1024**3)
            elif attr == "cache_days": value = str(parsed * 86400)
            else: value = str(parsed)
            changes[key] = value
            values[key] = value
    if interactive and choice == "3":
        print("Give the cache its own shelf: a separate worker-only Docker volume.")
        print("Advanced bind mounts/external executors require operator configuration; see docs/ACCESSION_CACHE.md.")
        if not yes("Shall Docker look after the storage volumes?", True):
            print("Cancelled. Review the advanced storage instructions before configuring Compose."); return
    enabled = args.cache
    if interactive and choice == "3": enabled = yes("Keep a bounded cache to reuse compatible public accession results?", bool(values.get(PREFIX + "ACCESSION_CACHE_ROOT")))
    if enabled is not None:
        if existing.get(PREFIX + "ACCESSION_CACHE_ROOT", "") not in {"", CACHE_ROOT}:
            raise ValueError("Keep custom cache storage under operator control; no automatic cache migration is supported.")
        changes[PREFIX + "ACCESSION_CACHE_ROOT"] = CACHE_ROOT if enabled else ""
    startup, opening = args.autostart, args.open_browser
    if interactive:
        print("Automatic startup waits for Docker. A deliberate stop stays stopped.")
        print("Desktop Docker may wait for sign-in. Browser opening happens only when you use the launcher.")
        startup = yes("Start ClusterWeave when Docker starts?", values.get(PREFIX + "LOCAL_RESTART_POLICY", "unless-stopped") == "unless-stopped")
        opening = yes("Open the browser when you use the start launcher?", values.get(PREFIX + "LOCAL_OPEN_BROWSER", "0") == "1")
    if startup is not None: changes[PREFIX + "LOCAL_RESTART_POLICY"] = "unless-stopped" if startup else "no"
    if opening is not None: changes[PREFIX + "LOCAL_OPEN_BROWSER"] = "1" if opening else "0"
    values.update(changes)
    if "HOST_PORT" in changes or not existing:
        host = urlsplit(existing.get(PREFIX + "PUBLIC_BASE_URL", "http://127.0.0.1/")).hostname
        host = "[::1]" if host == "::1" else host
        values[PREFIX + "PUBLIC_BASE_URL"] = f"http://{host}:{values['HOST_PORT']}/"
        changes[PREFIX + "PUBLIC_BASE_URL"] = values[PREFIX + "PUBLIC_BASE_URL"]
    if PREFIX + "WORKER_CPU_LIMIT" in changes or PREFIX + "MAX_CPUS_PER_JOB" in changes:
        changes["PIPELINE_CPUS"] = values[PREFIX + "MAX_CPUS_PER_JOB"]
    for name in ("MAX_ACCESSIONS", "MAX_GENOME_FILES"):
        if PREFIX + name in values:
            positive(values[PREFIX + name], name)
    validate_resources(values, report)
    review(values)
    if interactive and not yes("Shall I save these settings?", True):
        print("All right. Nothing moved."); return
    # Available RAM and Docker allocation can change while the user reviews.
    validate_resources(values, resources())
    if not existing:
        changes[PREFIX + "JOB_TOKEN_SECRET"] = secrets.token_hex(32)
        changes[PREFIX + "ADMIN_TOKEN"] = secrets.token_hex(24)
    if changes:
        write_config(original, changes)
    print("Settings saved. Credentials and retained results stay put.")
    if interactive or args.weave:
        print("\nNext I'll build the images, offer the browser progress screen, and prepare the scientific runtimes.")
        print("The first run downloads images and reference data and can take a while. Keep this terminal open.")
        if args.weave or yes("READY TO WEAVE?", True):
            weave(args)
            return
    print("Ready when you are. Continue with: ./bin/local_instance.sh weave")
    print("Returning to a prepared instance? ./bin/local_instance.sh start")


def docker_available():
    try:
        subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Docker is unavailable. Start Docker Desktop (Windows/macOS) or the Linux Docker daemon, then retry. No services were started.") from exc


def wait_web(settings, timeout):
    """The progress screen can open before worker preparation starts."""
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(settings["url"], timeout=min(3, max(0.1, deadline - time.monotonic()))) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise ValueError(f"The web service hasn't answered within {timeout:g} seconds. Check the port and Docker logs, then retry ./bin/local_instance.sh weave. Saved settings and data are kept.")


def weave(args):
    _, values = read_config()
    if not values:
        raise ValueError("Let's choose your settings first: ./bin/init_local_instance.sh")
    local_only(values)
    report = resources()
    settings = validate_resources(values, report)
    if report["docker"]["state"] != "available":
        raise ValueError("Start local Docker, then try ./bin/local_instance.sh weave again. I need to verify its allocation before building.")
    docker_available()
    if compose(values, "ps", "--status", "running", "--quiet", "worker", capture=True).stdout.strip():
        raise ValueError("A worker is already running. Let its jobs finish before stopping it with ./bin/local_instance.sh stop. Use start to return to a prepared instance; weave builds and prepares it.")
    print("\nLet's weave. First, the image build. Docker's progress follows below.", flush=True)
    compose(values, "build", timeout=None)
    compose(values, "run", "--rm", "--no-deps", "--pull", "never", "worker", "setup-status", "prepare")
    worker_started = False
    try:
        compose(values, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "web")
        wait_web(settings, args.timeout)
        print(f"\nThe browser progress screen is ready: {settings['url']}")
        print("I'll keep showing progress here too. Stay in this terminal until preparation finishes.")
        opening = args.open_browser
        if opening is None and not args.non_interactive and sys.stdin.isatty():
            opening = yes("Want to open the browser progress screen?", True)
        if opening:
            open_browser(settings["url"])
        print("\nNow for the scientific runtimes and reference data. Prepared assets will be checked and reused.", flush=True)
        compose(values, "run", "--rm", "--no-deps", "--pull", "never", "worker", "prepare-runtime",
                "--status-file", "/data/worker/status.json", timeout=None)
        print("\nOne more check before the worker starts.", flush=True)
        compose(values, "run", "--rm", "--no-deps", "--pull", "never", "worker", "check-runtime", timeout=None)
        compose(values, "up", "-d", "--no-build", "--pull", "never", "worker")
        worker_started = True
        wait_ready(settings, values, args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt, EOFError):
        try:
            if not worker_started:
                compose(values, "run", "--rm", "--no-deps", "--pull", "never", "worker", "setup-status", "error")
        except (OSError, subprocess.SubprocessError):
            pass
        if worker_started:
            print("Runtimes are prepared; the worker hasn't reported readiness yet. Check docker compose logs --tail=100 worker, then use ./bin/local_instance.sh open. Settings and data are kept.", file=sys.stderr)
        else:
            print("Preparation stopped. Settings and data are kept. Fix the reported problem, then run ./bin/local_instance.sh weave again.", file=sys.stderr)
        raise
    print(f"\nRoom to weave. ClusterWeave is ready: {settings['url']}")
    print("Try your first job in the browser. Later, use ./bin/local_instance.sh start to return without rebuilding.")


def wait_ready(settings, values, timeout):
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"X-ClusterWeave-Admin-Token": values.get(PREFIX + "ADMIN_TOKEN", "")}
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(settings["url"].rstrip("/") + "/api/system/status", headers=headers)
            with opener.open(request, timeout=min(3, max(0.1, deadline - time.monotonic()))) as response:
                payload = json.load(response)
            if payload.get("ready") is True and not payload.get("stale"):
                return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise ValueError(f"Service/worker not ready within {timeout:g} seconds. Inspect docker compose ps and docker compose logs --tail=100 web worker; check runtime preparation and port conflicts. Return manually to {settings['url']} when ready.")


def open_browser(url):
    system = platform.system()
    if system == "Darwin": command = ["open", url]
    elif system == "Linux" and "microsoft" in platform.release().lower():
        command = ["wslview", url] if shutil.which("wslview") else None
    elif system == "Linux" and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        command = ["xdg-open", url]
    else: command = None
    if command:
        try:
            subprocess.run(command, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    print(f"Browser integration unavailable here. In your signed-in desktop session, open {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "weave", "scan", "start", "open", "stop", "disable-autostart", "status"])
    parser.add_argument("--json", action="store_true", help="print a scan as JSON")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--defaults", action="store_true",
                        help="fresh setup without questions: conservative budget, cache, autostart, browser, build and prepare")
    parser.add_argument("--reconfigure", action="store_true")
    parser.add_argument("--recommendation", choices=["conservative", "maximum"], default=None,
                        help="choose a scan-based budget; fresh scripted setup defaults to conservative")
    parser.add_argument("--weave", action="store_true", help="after saving, explicitly build and acquire runtimes (also for scripts)")
    parser.add_argument("--apply", action="store_true", help="explicitly apply noninteractive reconfiguration")
    for name in ("worker-cpus", "job-cpus", "concurrent-jobs", "genome-parallelism", "record-parallelism", "memory-gib", "port", "cache-gib", "cache-entries", "cache-days", "max-accessions", "max-genome-files"):
        parser.add_argument("--" + name)
    for name in ("cache", "autostart", "open-browser"):
        parser.add_argument("--" + name, action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    scripted = args.non_interactive
    try:
        if args.defaults:
            if args.command != "init" or args.reconfigure:
                raise ValueError("Use --defaults for fresh initialization. To change a saved setup, run ./bin/init_local_instance.sh --reconfigure.")
            args.non_interactive = True
            args.recommendation = args.recommendation or "conservative"
            for name in ("cache", "autostart", "open_browser"):
                if getattr(args, name) is None:
                    setattr(args, name, True)
            args.weave = True
        if sys.stdin.isatty() and sys.stdout.isatty() and not scripted and not args.json:
            show_banner()
        if not 0 < args.timeout <= 600:
            raise ValueError("Readiness timeout must be between 0 and 600 seconds.")
        if args.command == "scan":
            report = resources()
            if args.json: print(json.dumps(report, sort_keys=True))
            else: print_resources(report)
            return 0
        if args.command == "init":
            initialize(args); return 0
        if args.command == "weave":
            weave(args); return 0
        original, values = read_config()
        if not values: raise ValueError("Initialize first: ./bin/init_local_instance.sh")
        local_only(values)
        settings = describe(values)
        if args.command == "status":
            review(values); return 0
        if args.command == "disable-autostart":
            write_config(original, {PREFIX + "LOCAL_RESTART_POLICY": "no", PREFIX + "LOCAL_OPEN_BROWSER": "0"})
            docker_available()
            ids = compose(values, "ps", "--all", "--quiet", "web", "worker", capture=True).stdout.split()
            if ids:
                subprocess.run(["docker", "update", "--restart=no", *ids], check=True, timeout=30, stdout=subprocess.DEVNULL)
            print("Automatic startup and launcher browser opening disabled. Data is retained; stopped services remain stopped.")
            return 0
        docker_available()
        if args.command == "stop":
            compose(values, "stop"); print("Stopped. Explicitly run start to return; volumes and results are retained."); return 0
        if args.command == "start":
            images = compose(values, "config", "--images", capture=True).stdout.split()
            try:
                subprocess.run(["docker", "image", "inspect", *images], check=True, timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.SubprocessError as exc:
                raise ValueError("Local service images are missing. Follow the explicit build/preparation instructions before starting; the launcher will not build or pull images.") from exc
            compose(values, "run", "--rm", "--no-deps", "--pull", "never", "worker", "check-runtime")
            compose(values, "up", "-d", "--no-build", "--pull", "never")
        print("Docker is available. Waiting for the web service and worker readiness...")
        wait_ready(settings, values, args.timeout)
        print(f"ClusterWeave is ready: {settings['url']}")
        if args.command == "open" or (args.open_browser if args.open_browser is not None else settings["open_browser"]):
            open_browser(settings["url"])
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nStopped here. Any saved settings and retained data are kept. Run setup again, or use ./bin/local_instance.sh weave to resume preparation.", file=sys.stderr); return 130
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Setup could not finish: {exc}", file=sys.stderr)
        if args.command == "disable-autostart":
            print("If the saved policy was updated while Docker was unavailable, rerun disable-autostart once Docker is available to update existing containers.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
