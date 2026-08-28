#!/usr/bin/env python3
"""Read-only audit of signed generated HTML/JavaScript viewer templates."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


FUNBGCEX_BGC_NAME = re.compile(r"^BGC[0-9]+\.(?:html|js)$", re.IGNORECASE)
BIGSCAPE_CONTROL_PLACEHOLDER = "href='##'"
BIGSCAPE_CONTROL_PLACEHOLDER_COUNT = 13
BIGSCAPE_SINGLETON_TREE_SIGNATURE = """    var treeDrawer = new PhylogramTreeDrawer();
    treeDrawer.Init(treeData, { svg_id: 'det_fam_tree', height: ((treeData.num_leaves - 1) * 40), width: 400 });
    treeDrawer.draw_scale_bar = false;
    treeDrawer.CalcCoordinates();
    treeDrawer.Draw();"""
BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM = '(1,eval)("this")'
BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT = 2


def classify_html(relative: str) -> str:
    path = relative.replace("\\", "/")
    name = path.rsplit("/", 1)[-1].lower()
    if "/antismash/" in f"/{path}":
        return "antismash-index" if name == "index.html" else "antismash-nested"
    if "/funbgcex/" in f"/{path}":
        if name == "allbgcs.html":
            return "funbgcex-all-bgcs"
        if name == "results.html":
            return "funbgcex-results"
        if re.fullmatch(r"bgc[0-9]+\.html", name):
            return "funbgcex-bgc-detail"
        if name == "classification.html":
            return "funbgcex-classification"
        if name == "protfam.html":
            return "funbgcex-protfam"
        return "funbgcex-other"
    if name == "panel.html" and any(part in path.lower() for part in ("clinker", "synteny")):
        return "clinker-panel"
    if name == "index.html" and any(part in path.lower() for part in ("big_scape", "bigscape", "big-scape")):
        return "bigscape-index"
    return "unknown"


def require_exact(text: str, needle: str, path: str) -> None:
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(f"{path}: expected one compatibility signature {needle!r}, found {count}")


def audit(root: Path, index_path: Path) -> dict[str, object]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    prefix = f"data/results/{root.name}/"
    indexed = {}
    for item in index.get("files", []):
        path = str(item.get("path", ""))
        if path.startswith(prefix):
            indexed[path[len(prefix):]] = item

    html_paths = sorted(root.rglob("*.html"))
    js_paths = sorted(root.rglob("*.js"))
    classes: Counter[str] = Counter()
    checked_bytes = 0
    checked_files = 0
    funbgcex_bgc_scripts = 0
    antismash_runtime_scripts = 0
    bigscape_runtime_scripts = 0
    bigscape_kinetic_scripts = 0

    for path in [*html_paths, *js_paths]:
        relative = path.relative_to(root).as_posix()
        entry = indexed.get(relative)
        if not entry:
            raise RuntimeError(f"{relative}: missing from signed result index")
        payload = path.read_bytes()
        if len(payload) != int(entry.get("bytes", -1)):
            raise RuntimeError(f"{relative}: signed byte length mismatch")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry.get("sha256"):
            raise RuntimeError(f"{relative}: signed SHA-256 mismatch")
        checked_files += 1
        checked_bytes += len(payload)

    for path in html_paths:
        relative = path.relative_to(root).as_posix()
        template_class = classify_html(relative)
        classes[template_class] += 1
        if template_class == "unknown" or template_class.endswith("-other"):
            raise RuntimeError(f"{relative}: unclassified generated HTML template")
        if template_class in {
            "antismash-index",
            "funbgcex-all-bgcs",
            "funbgcex-results",
            "funbgcex-bgc-detail",
            "clinker-panel",
            "bigscape-index",
        }:
            text = path.read_text(encoding="utf-8", errors="strict")
        else:
            continue
        if template_class == "antismash-index":
            for marker in ("antismash.js", "download-svg"):
                if marker not in text:
                    raise RuntimeError(f"{relative}: missing antiSMASH marker {marker!r}")
        elif template_class in {"funbgcex-all-bgcs", "funbgcex-results"}:
            if "filter" not in text.lower():
                raise RuntimeError(f"{relative}: missing FunBGCeX filter controls")
        elif template_class == "funbgcex-bgc-detail":
            for marker in ('id="canvas"', 'id="aaseq"', "copyToClipboard()"):
                if marker not in text:
                    raise RuntimeError(f"{relative}: missing FunBGCeX gene-detail marker {marker!r}")
        elif template_class == "clinker-panel":
            for marker in ("btn-save-svg", "clinker.json", "URL.createObjectURL"):
                if marker not in text:
                    raise RuntimeError(f"{relative}: missing clinker export marker {marker!r}")
        elif template_class == "bigscape-index":
            for marker in ("downloadAbPresTsv", "download-selection", "sendDownload"):
                if marker not in text:
                    raise RuntimeError(f"{relative}: missing BiG-SCAPE export marker {marker!r}")

    for path in js_paths:
        relative = path.relative_to(root).as_posix()
        name = path.name
        if "/funbgcex/" in f"/{relative}" and FUNBGCEX_BGC_NAME.fullmatch(name):
            text = path.read_text(encoding="utf-8", errors="strict")
            require_exact(text, "const x = event.clientX - rect.left;", relative)
            require_exact(text, "const y = event.clientY - rect.top;", relative)
            funbgcex_bgc_scripts += 1
        elif "/antismash/" in f"/{relative}" and name.lower() == "antismash.js":
            text = path.read_text(encoding="utf-8", errors="strict")
            for marker in ("clipboard-copy", "navigator.clipboard.writeText"):
                if marker not in text:
                    raise RuntimeError(f"{relative}: missing antiSMASH clipboard marker {marker!r}")
            require_exact(
                text,
                'function T(){const t=window.location.hash.substring(1);return t||"overview"}',
                relative,
            )
            require_exact(text, 'function k(){setTimeout((()=>{$(".page").hide()', relative)
            antismash_runtime_scripts += 1
        elif any(part in relative.lower() for part in ("big_scape", "bigscape", "big-scape")):
            if name.lower() == "bigscape.js":
                text = path.read_text(encoding="utf-8", errors="strict")
                count = text.count(BIGSCAPE_CONTROL_PLACEHOLDER)
                if count != BIGSCAPE_CONTROL_PLACEHOLDER_COUNT:
                    raise RuntimeError(
                        f"{relative}: expected {BIGSCAPE_CONTROL_PLACEHOLDER_COUNT} "
                        f"BiG-SCAPE placeholder controls, found {count}"
                    )
                require_exact(text, BIGSCAPE_SINGLETON_TREE_SIGNATURE, relative)
                bigscape_runtime_scripts += 1
            elif name.lower() == "kinetic-v5.1.0.min.js":
                text = path.read_text(encoding="utf-8", errors="strict")
                count = text.count(BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM)
                if count != BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT:
                    raise RuntimeError(
                        f"{relative}: expected {BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT} "
                        f"Kinetic eval shims, found {count}"
                    )
                bigscape_kinetic_scripts += 1

    return {
        "status": "pass",
        "generation": index.get("generation"),
        "signed_file_count": len(index.get("files", [])),
        "audited_html_count": len(html_paths),
        "audited_javascript_count": len(js_paths),
        "audited_file_count": checked_files,
        "audited_bytes": checked_bytes,
        "html_template_classes": dict(sorted(classes.items())),
        "funbgcex_bgc_compatibility_scripts": funbgcex_bgc_scripts,
        "antismash_runtime_compatibility_scripts": antismash_runtime_scripts,
        "bigscape_runtime_compatibility_scripts": bigscape_runtime_scripts,
        "bigscape_kinetic_compatibility_scripts": bigscape_kinetic_scripts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("index", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.root, args.index), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
