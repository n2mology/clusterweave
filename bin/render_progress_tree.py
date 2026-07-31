#!/usr/bin/env python3
"""Render canonical ClusterWeave output as an interactive terminal stage tree."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import json
import locale
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from typing import Any, Iterable, TextIO


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "web" / "static" / "assets" / "progress-tree-contract.json"
TERMINAL_STATES = {"complete", "failed", "warning_terminal", "skipped"}
STATE_ALIASES = {
    "complete": "complete",
    "completed": "complete",
    "done": "complete",
    "ok": "complete",
    "success": "complete",
    "succeeded": "complete",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "fatal": "failed",
    "skipped": "skipped",
    "skip": "skipped",
    "not_applicable": "skipped",
    "not-applicable": "skipped",
    "not applicable": "skipped",
    "warning_terminal": "warning_terminal",
    "complete_with_warning": "warning_terminal",
    "warning": "warning",
    "warn": "warning",
    "rerun": "rerun",
    "retry": "rerun",
    "queued": "running",
    "ready": "running",
    "running": "running",
    "active": "running",
    "processing": "running",
}


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "clusterweave.progress-tree.v1":
        raise ValueError("Unsupported ClusterWeave progress-tree contract")
    return value


def normalize_line(value: object) -> str:
    text = str(value or "").strip()
    while True:
        updated = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", text)
        updated = re.sub(r"^\[\d{4}-\d{2}-\d{2}[^\]]*\]\s*", "", updated)
        updated = re.sub(
            r"^\[(?:INFO|WARN|WARNING|ERROR|FAIL|FATAL|OK)\]\s*",
            "",
            updated,
            flags=re.IGNORECASE,
        )
        updated = updated.strip()
        if updated == text:
            return text
        text = updated


def normalize_tool(value: object) -> str:
    raw = str(value or "").strip()
    key = raw.lower().replace("_", "").replace("-", "")
    return {
        "antismash": "antiSMASH",
        "funbgcex": "FunBGCeX",
        "funannotate": "funannotate",
        "prodigal": "Prodigal",
        "ncbidatasets": "NCBI Datasets",
    }.get(key, raw)


def normalize_state(value: object, default: str = "running") -> str:
    key = str(value or "").strip().lower()
    return STATE_ALIASES.get(key, default)


def _matched_values(rule: dict[str, Any], match: re.Match[str]) -> dict[str, str]:
    fields = list(rule.get("fields") or [])
    return {
        field_name: (match.group(index + 1) or "")
        for index, field_name in enumerate(fields)
        if index < len(match.groups())
    }


def _state_from_patterns(
    contract: dict[str, Any],
    message: str,
    *,
    allow_complete: bool,
) -> tuple[str | None, bool]:
    for rule in contract.get("state_patterns") or []:
        state = str(rule.get("state") or "")
        if state == "complete" and not allow_complete:
            continue
        if re.search(str(rule.get("pattern") or r"(?!x)x"), message, re.IGNORECASE):
            return state, bool(rule.get("permanent"))
    return None, False


def classify_progress_line(
    contract: dict[str, Any],
    line: object,
    raw_line_index: int,
    current_stage: str = "prep",
) -> dict[str, Any]:
    """Return the shared semantic fields for one untouched canonical line."""

    raw = str(line or "").rstrip("\r\n")
    message = normalize_line(raw)
    base: dict[str, Any] = {
        "workflow_stage": current_stage or "prep",
        "genome": "",
        "tool": "",
        "percentage": None,
        "state": "running",
        "display_message": message or "Running",
        "elapsed_activity": None,
        "canonical_raw_line_index": max(0, int(raw_line_index)),
        "node_level": "activity",
        "kind": "unknown",
        "heartbeat": False,
        "permanent": False,
        "stage_transition": False,
    }

    for rule in contract.get("records") or []:
        match = re.search(str(rule.get("pattern") or r"(?!x)x"), message, re.IGNORECASE)
        if not match:
            continue
        values = _matched_values(rule, match)
        event = dict(base)
        event.update(
            {
                "kind": str(rule.get("kind") or "structured"),
                "workflow_stage": str(rule.get("workflow_stage") or current_stage or "prep"),
                "node_level": str(rule.get("node_level") or "activity"),
                "genome": values.get("genome", ""),
                "tool": normalize_tool(rule.get("tool") or values.get("tool", "")),
                "display_message": str(
                    values.get("display_message")
                    or rule.get("message")
                    or message
                    or "Running"
                ),
                "heartbeat": bool(rule.get("heartbeat")),
                "permanent": bool(rule.get("permanent")),
            }
        )
        tool_from_field = str(rule.get("tool_from_field") or "")
        if tool_from_field:
            raw_tool = values.get(tool_from_field, "")
            mapped = (rule.get("tool_map") or {}).get(str(raw_tool).lower(), raw_tool)
            event["tool"] = normalize_tool(mapped)
            if event["tool"]:
                event["node_level"] = "tool"
        raw_percent = values.get("percentage", "")
        if str(raw_percent).isdigit():
            event["percentage"] = min(100, max(0, int(raw_percent)))
        raw_elapsed = values.get("elapsed_activity", "")
        if str(raw_elapsed).isdigit():
            event["elapsed_activity"] = max(0, int(raw_elapsed))
        state_field = str(rule.get("state_field") or "")
        event["state"] = normalize_state(
            values.get(state_field, "") if state_field else rule.get("state", "running")
        )
        allow_complete = bool(rule.get("terminal_on_percent"))
        pattern_state, pattern_permanent = _state_from_patterns(
            contract,
            f"{raw} {event['display_message']}",
            allow_complete=allow_complete,
        )
        if pattern_state and pattern_state != "complete":
            event["state"] = pattern_state
            event["permanent"] = event["permanent"] or pattern_permanent
        if (
            allow_complete
            and event["percentage"] == 100
            and event["state"] == "running"
        ):
            event["state"] = "complete"
            event["permanent"] = True
        if event["state"] in TERMINAL_STATES:
            event["permanent"] = True
        return event

    for rule in contract.get("stage_markers") or []:
        match = re.search(str(rule.get("pattern") or r"(?!x)x"), message, re.IGNORECASE)
        if not match:
            continue
        action = match.group(1).lower() if match.groups() else ""
        state = str(rule.get("state") or ("skipped" if action == "skipped" else "running"))
        display_message = {
            "complete": "Complete",
            "failed": "Failed",
            "skipped": "Skipped",
            "warning_terminal": "Complete with warning",
        }.get(state, "Running")
        return {
            **base,
            "kind": "stage_transition",
            "workflow_stage": str(rule.get("workflow_stage") or current_stage or "prep"),
            "node_level": "stage",
            "state": state,
            "display_message": display_message,
            "permanent": True,
            "stage_transition": True,
        }

    for rule in contract.get("legacy_records") or []:
        match = re.search(str(rule.get("pattern") or r"(?!x)x"), message, re.IGNORECASE)
        if not match:
            continue
        values = _matched_values(rule, match)
        event = {
            **base,
            "kind": str(rule.get("kind") or "legacy"),
            "workflow_stage": str(rule.get("workflow_stage") or current_stage or "prep"),
            "node_level": str(rule.get("node_level") or "activity"),
            "genome": values.get("genome", ""),
            "tool": normalize_tool(rule.get("tool") or values.get("tool", "")),
            "state": normalize_state(rule.get("state", "running")),
            "display_message": str(rule.get("message") or message or "Running"),
            "permanent": bool(rule.get("permanent")),
        }
        return event

    pattern_state, pattern_permanent = _state_from_patterns(
        contract,
        raw,
        allow_complete=True,
    )
    if pattern_state:
        base["state"] = pattern_state
        base["permanent"] = pattern_permanent
    return base


def event_node_key(event: dict[str, Any]) -> str:
    stage = str(event.get("workflow_stage") or "prep")
    level = str(event.get("node_level") or "activity")
    genome = str(event.get("genome") or "")
    tool = str(event.get("tool") or "")
    if level == "stage":
        return f"stage:{stage}"
    if level == "tool":
        return f"tool:{stage}:{genome}:{tool}"
    if level == "genome":
        return f"genome:{stage}:{genome}"
    return f"activity:{stage}"


@dataclass
class TreeNode:
    key: str
    stage: str
    level: str
    label: str
    state: str = "waiting"
    percentage: int | None = None
    message: str = "Waiting"
    elapsed: int | None = None
    raw_index: int = -1
    order: int = 0
    parent_key: str = ""


@dataclass
class ProgressTreeModel:
    contract: dict[str, Any]
    nodes: dict[str, TreeNode] = field(default_factory=dict)
    permanent_events: list[TreeNode] = field(default_factory=list)
    observed_optional_stages: set[str] = field(default_factory=set)
    current_stage: str = "prep"
    next_order: int = 0

    def __post_init__(self) -> None:
        for item in self.contract.get("workflow") or []:
            if item.get("optional"):
                continue
            self._ensure_stage(str(item["key"]))

    def workflow_item(self, stage: str) -> dict[str, Any]:
        for item in self.contract.get("workflow") or []:
            if item.get("key") == stage:
                return item
        return {"key": stage, "label": stage.replace("_", " ").title(), "optional": True}

    def _ensure_stage(self, stage: str) -> TreeNode:
        key = f"stage:{stage}"
        if key not in self.nodes:
            item = self.workflow_item(stage)
            self.nodes[key] = TreeNode(
                key=key,
                stage=stage,
                level="stage",
                label=str(item.get("label") or stage),
                order=self.next_order,
            )
            self.next_order += 1
        if self.workflow_item(stage).get("optional"):
            self.observed_optional_stages.add(stage)
        return self.nodes[key]

    def _label_for_event(self, event: dict[str, Any]) -> str:
        level = event.get("node_level")
        if level == "stage":
            return str(self.workflow_item(str(event["workflow_stage"])).get("label"))
        if level == "tool":
            return str(event.get("tool") or "Tool")
        if level == "genome":
            return str(event.get("genome") or "Genome").replace("_", " ")
        return "Activity"

    def _parent_for_event(self, event: dict[str, Any]) -> str:
        stage = str(event.get("workflow_stage") or "prep")
        genome = str(event.get("genome") or "")
        if event.get("node_level") == "tool" and genome:
            genome_key = f"genome:{stage}:{genome}"
            if genome_key not in self.nodes:
                self.nodes[genome_key] = TreeNode(
                    key=genome_key,
                    stage=stage,
                    level="genome",
                    label=genome.replace("_", " "),
                    state="running",
                    message="Running",
                    order=self.next_order,
                    parent_key=f"stage:{stage}",
                )
                self.next_order += 1
            return genome_key
        return f"stage:{stage}"

    def _reset_stage(self, stage: str) -> None:
        for key in [
            key
            for key, node in self.nodes.items()
            if node.stage == stage and node.level != "stage"
        ]:
            self.nodes.pop(key, None)
        stage_node = self._ensure_stage(stage)
        stage_node.state = "running"
        stage_node.percentage = None
        stage_node.message = "Running"
        stage_node.elapsed = None

    def apply(self, event: dict[str, Any]) -> None:
        stage = str(event.get("workflow_stage") or self.current_stage or "prep")
        event["workflow_stage"] = stage
        stage_node = self._ensure_stage(stage)
        if event.get("stage_transition"):
            self.current_stage = stage
        if event.get("state") == "rerun":
            self._reset_stage(stage)
            self._append_permanent_event(event)
            return
        if stage_node.state == "waiting":
            stage_node.state = "running"
            stage_node.message = "Running"
        if event.get("permanent") and event.get("node_level") == "activity":
            self._append_permanent_event(event)
            return

        key = event_node_key(event)
        node = self.nodes.get(key)
        if node is None:
            node = TreeNode(
                key=key,
                stage=stage,
                level=str(event.get("node_level") or "activity"),
                label=self._label_for_event(event),
                state="running",
                message="Running",
                order=self.next_order,
                parent_key=self._parent_for_event(event),
            )
            self.next_order += 1
            self.nodes[key] = node

        incoming_state = str(event.get("state") or "running")
        if stage_node.state in TERMINAL_STATES and incoming_state == "running":
            incoming_state = stage_node.state
        if node.state in TERMINAL_STATES and incoming_state == "running":
            return
        previous_message = node.message
        node.state = incoming_state
        if event.get("percentage") is not None:
            node.percentage = int(event["percentage"])
        display_message = str(event.get("display_message") or "").strip()
        if event.get("heartbeat") and previous_message not in {"", "Waiting", "Running"}:
            display_message = previous_message
        node.message = display_message or previous_message or "Running"
        if event.get("elapsed_activity") is not None:
            node.elapsed = int(event["elapsed_activity"])
        node.raw_index = int(event.get("canonical_raw_line_index") or 0)

        if (
            event.get("kind") == "download"
            and node.level == "tool"
            and node.parent_key
            and incoming_state in TERMINAL_STATES
        ):
            parent = self.nodes.get(node.parent_key)
            if parent is not None:
                parent.state = incoming_state
                parent.percentage = node.percentage
                parent.message = node.message
                parent.raw_index = node.raw_index

        if node.level == "stage" and incoming_state in TERMINAL_STATES:
            stage_node.state = incoming_state
            stage_node.percentage = 100 if incoming_state == "complete" else None
            stage_node.message = node.message
            for child in self.nodes.values():
                if (
                    child.stage == stage
                    and child.level != "stage"
                    and child.state not in TERMINAL_STATES
                ):
                    child.state = incoming_state
                    child.percentage = 100 if incoming_state == "complete" else None
                    child.message = node.message

    def _append_permanent_event(self, event: dict[str, Any]) -> None:
        raw_index = int(event.get("canonical_raw_line_index") or 0)
        self.permanent_events.append(
            TreeNode(
                key=f"event:{raw_index}",
                stage=str(event.get("workflow_stage") or "prep"),
                level="event",
                label=str(event.get("display_message") or "Run update"),
                state=str(event.get("state") or "running"),
                message=str(event.get("display_message") or "Run update"),
                elapsed=event.get("elapsed_activity"),
                raw_index=raw_index,
                order=self.next_order,
                parent_key=f"stage:{event.get('workflow_stage') or 'prep'}",
            )
        )
        self.next_order += 1

    def ordered_nodes(self) -> list[TreeNode]:
        output: list[TreeNode] = []
        all_events = {event.key: event for event in self.permanent_events}
        for item in self.contract.get("workflow") or []:
            stage = str(item["key"])
            if item.get("optional") and stage not in self.observed_optional_stages:
                continue
            stage_key = f"stage:{stage}"
            stage_node = self.nodes.get(stage_key)
            if stage_node is None:
                continue
            output.append(stage_node)
            genomes = sorted(
                (
                    node
                    for node in self.nodes.values()
                    if node.stage == stage and node.level == "genome"
                ),
                key=lambda node: node.order,
            )
            for genome in genomes:
                output.append(genome)
                output.extend(
                    sorted(
                        (
                            node
                            for node in self.nodes.values()
                            if node.parent_key == genome.key
                        ),
                        key=lambda node: node.order,
                    )
                )
            output.extend(
                sorted(
                    (
                        node
                        for node in self.nodes.values()
                        if node.stage == stage
                        and node.level in {"tool", "activity"}
                        and node.parent_key == stage_key
                    ),
                    key=lambda node: node.order,
                )
            )
            output.extend(
                sorted(
                    (
                        node
                        for node in all_events.values()
                        if node.stage == stage
                    ),
                    key=lambda node: node.order,
                )
            )
        return output


def build_progress_tree(
    contract: dict[str, Any],
    records: Iterable[tuple[int, str]],
) -> ProgressTreeModel:
    model = ProgressTreeModel(contract)
    for raw_index, line in records:
        event = classify_progress_line(contract, line, raw_index, model.current_stage)
        model.apply(event)
    return model


def format_elapsed(seconds: int | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds}s active"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s active"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m active"


def progress_status(node: TreeNode) -> str:
    state_labels = {
        "complete": "Complete",
        "failed": "Failed",
        "warning_terminal": "Complete with warning",
        "skipped": "Skipped",
        "warning": "Warning",
        "waiting": "Waiting",
        "running": node.message or "Running",
    }
    label = state_labels.get(node.state, node.message or "Running")
    elapsed = format_elapsed(node.elapsed)
    if elapsed and elapsed.lower() not in label.lower():
        label = f"{label} · {elapsed}"
    if node.state == "complete":
        return "[##########] 100% - Complete"
    if node.state == "skipped":
        return "[----------]   -- - Skipped"
    if node.percentage is not None:
        percent = min(100, max(0, int(node.percentage)))
        filled = percent * 10 // 100
        return f"[{'#' * filled}{'-' * (10 - filled)}] {percent:3d}% - {label}"
    if node.state == "waiting":
        return "[----------]   0% - Waiting"
    return f"[          ]  --% - {label}"


def unicode_terminal_supported(stream: TextIO) -> bool:
    locale_value = next(
        (str(os.environ.get(name) or "") for name in ("LC_ALL", "LC_CTYPE", "LANG") if os.environ.get(name)),
        "",
    )
    if locale_value.upper() in {"C", "POSIX"} and not re.search(
        r"UTF-?8", locale_value, re.IGNORECASE
    ):
        return False
    encoding = stream.encoding or locale.getpreferredencoding(False) or ""
    try:
        "╲╱├─".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def read_release_version(root: Path = REPO_ROOT) -> str:
    try:
        text = (root / "CITATION.cff").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


class TerminalTreeRenderer:
    def __init__(
        self,
        contract: dict[str, Any],
        project_name: str,
        stream: TextIO = sys.stdout,
    ) -> None:
        self.contract = contract
        self.project_name = project_name
        self.stream = stream
        self.unicode = unicode_terminal_supported(stream)
        self.records: list[tuple[int, str]] = []
        self.body_lines = 0

    def start(self) -> None:
        if self.unicode:
            mark = ("╲╱  CLUSTER", "╱╲  WEAVE")
        else:
            mark = ("\\/  CLUSTER", "/\\  WEAVE")
        version = read_release_version()
        info = [
            f"Project: {self.project_name or 'ClusterWeave'}",
            f"Started: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        ]
        if version:
            info.append(f"Version: {version}")
        self.stream.write("\n".join((*mark, "  ".join(info))) + "\n")
        self.stream.write("\x1b[?25l")
        self.stream.flush()
        self.render()

    def accept(self, line: str) -> None:
        self.records.append((len(self.records), line.rstrip("\r\n")))
        self.render()

    def render(self) -> None:
        model = build_progress_tree(self.contract, self.records)
        branch = {
            "stage_live": "├─" if self.unicode else "|-",
            "stage_terminal": "└─" if self.unicode else "`-",
            "child_live": "│  ├─" if self.unicode else "|  |-",
            "child_terminal": "│  └─" if self.unicode else "|  `-",
            "tool_live": "│     ├─" if self.unicode else "|     |-",
            "tool_terminal": "│     └─" if self.unicode else "|     `-",
        }
        lines: list[str] = []
        for node in model.ordered_nodes():
            terminal = node.state in TERMINAL_STATES
            if node.level == "stage":
                glyph = branch["stage_terminal" if terminal else "stage_live"]
            elif node.level == "tool":
                glyph = branch["tool_terminal" if terminal else "tool_live"]
            else:
                glyph = branch["child_terminal" if terminal else "child_live"]
            lines.append(f"{glyph} {node.label} {progress_status(node)}")
        if not lines:
            lines = ["Waiting for canonical workflow output."]
        if self.body_lines:
            self.stream.write(f"\x1b[{self.body_lines}A\r")
        for line in lines:
            self.stream.write("\x1b[2K" + line + "\n")
        if self.body_lines > len(lines):
            for _ in range(self.body_lines - len(lines)):
                self.stream.write("\x1b[2K\n")
            self.stream.write(f"\x1b[{self.body_lines - len(lines)}A")
        self.body_lines = len(lines)
        self.stream.flush()

    def finish(self) -> None:
        self.render()
        self.stream.write("\x1b[?25h")
        self.stream.flush()


def run_rendered(
    command: list[str],
    project_name: str,
    contract: dict[str, Any],
) -> int:
    renderer = TerminalTreeRenderer(contract, project_name)
    proc: subprocess.Popen[str] | None = None
    presentation_active = False
    raw_output_available = True

    def forward_signal(signum: int, _frame: object) -> None:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signum)
            except ProcessLookupError:
                pass

    previous_handlers = {
        signum: signal.signal(signum, forward_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        try:
            renderer.start()
            presentation_active = True
        except Exception:
            try:
                sys.stdout.write("\x1b[?25h")
                sys.stdout.flush()
            except (BrokenPipeError, OSError):
                raw_output_available = False
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if presentation_active:
                try:
                    renderer.accept(line)
                    continue
                except Exception:
                    presentation_active = False
                    try:
                        sys.stdout.write("\x1b[?25h\n")
                        for _raw_index, raw_line in renderer.records:
                            sys.stdout.write(raw_line + "\n")
                        sys.stdout.flush()
                    except (BrokenPipeError, OSError):
                        raw_output_available = False
                    continue
            if raw_output_available:
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except (BrokenPipeError, OSError):
                    raw_output_available = False
        proc.stdout.close()
        return proc.wait()
    finally:
        if presentation_active:
            try:
                renderer.finish()
            except Exception:
                try:
                    sys.stdout.write("\x1b[?25h")
                    sys.stdout.flush()
                except (BrokenPipeError, OSError):
                    pass
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project", default="")
    parser.add_argument("--help", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.help or not args.command:
        print("Usage: render_progress_tree.py --project NAME -- COMMAND [ARG ...]")
        return 0 if args.help else 2
    command = args.command[1:] if args.command[0] == "--" else args.command
    try:
        contract = load_contract()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ClusterWeave tree display unavailable: {exc}", file=sys.stderr)
        return subprocess.run(command, check=False).returncode
    return run_rendered(command, args.project, contract)


if __name__ == "__main__":
    raise SystemExit(main())
