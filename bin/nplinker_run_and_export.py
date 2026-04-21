#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import httpx
from nplinker import NPLinker


def _obj_id(obj):
    for attr in ("id", "name", "spectrum_id", "gcf_id", "bgc_id"):
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            if val is not None:
                return str(val)
    return str(obj)


def _obj_type(obj):
    return obj.__class__.__name__


def _obj_strains(obj):
    out = []
    strains = getattr(obj, "strains", None)
    if strains:
        for s in strains:
            sid = getattr(s, "id", None)
            out.append(str(sid) if sid is not None else str(s))
    strain = getattr(obj, "strain", None)
    if strain is not None:
        sid = getattr(strain, "id", None)
        out.append(str(sid) if sid is not None else str(strain))
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return ";".join(seen)


def _score_value(score_obj):
    if score_obj is None:
        return ""
    for attr in ("value", "score"):
        if hasattr(score_obj, attr):
            v = getattr(score_obj, attr)
            if v is not None:
                return v
    return score_obj


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_genomic(obj):
    return _obj_type(obj) == "GCF"


def _bgc_source(genomic_obj):
    strains = _obj_strains(genomic_obj)
    if "BGC" in strains:
        return "MiBIG"
    if strains:
        return strains
    return "Local"


def _pretty_bgc_label(genomic_obj):
    genomic_id = _obj_id(genomic_obj)
    strains = _obj_strains(genomic_obj)
    aliases = [x.strip() for x in strains.split(";") if x.strip()]
    mibig_aliases = [x for x in aliases if x.startswith("BGC")]
    if mibig_aliases:
        return f"{mibig_aliases[0]} (MiBIG)"
    return f"GCF:{genomic_id}"


def _has_target(obj, target):
    target_l = target.lower()
    if target_l in _obj_id(obj).lower():
        return True
    strains = _obj_strains(obj).lower()
    if target_l and target_l in strains:
        return True
    return False


def main():
    config_file = Path(os.environ["NPLINKER_CONFIG"])
    out_table = Path(os.environ["OUT_TABLE"])
    summary_table = Path(os.environ["SUMMARY_TABLE"])
    target = os.environ.get("TARGET_STRAIN", "").strip()
    methods = [x.strip() for x in os.environ.get("NPLINKER_METHODS", "metcalf").split(",") if x.strip()]
    primary_method = methods[0] if methods else "metcalf"
    max_pairs = int(os.environ.get("MAX_LINKS", "5000"))
    http_timeout = float(os.environ.get("NPLINKER_HTTP_TIMEOUT", "180"))
    load_retries = int(os.environ.get("NPLINKER_LOAD_RETRIES", "3"))
    retry_sleep = int(os.environ.get("NPLINKER_RETRY_SLEEP", "20"))
    filter_target_only = os.environ.get("FILTER_TARGET_ONLY", "0").strip().lower() in {"1", "true", "yes", "on"}
    allow_filter_fallback = os.environ.get("ALLOW_FILTER_FALLBACK", "1").strip().lower() in {"1", "true", "yes", "on"}
    metcalf_standardised = os.environ.get("METCALF_STANDARDISED", "1").strip().lower() in {"1", "true", "yes", "on"}

    out_table.parent.mkdir(parents=True, exist_ok=True)
    summary_table.parent.mkdir(parents=True, exist_ok=True)

    # NPLinker internals call httpx.get() without an explicit timeout in some paths.
    # Patch the default timeout to reduce transient GNPS/PODP timeout failures.
    _orig_httpx_get = httpx.get
    def _patched_httpx_get(*args, **kwargs):
        if "timeout" not in kwargs or kwargs["timeout"] is None:
            kwargs["timeout"] = http_timeout
        return _orig_httpx_get(*args, **kwargs)
    httpx.get = _patched_httpx_get

    npl = NPLinker(str(config_file))
    last_exc = None
    for attempt in range(1, load_retries + 1):
        try:
            npl.load_data()
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < load_retries:
                print(f"[WARN] npl.load_data() failed on attempt {attempt}/{load_retries}: {type(exc).__name__}: {exc}")
                print(f"[WARN] sleeping {retry_sleep}s before retry")
                time.sleep(retry_sleep)
    if last_exc is not None:
        raise last_exc

    sources = npl.gcfs
    scoring_params = {}
    if primary_method == "metcalf":
        scoring_params["standardised"] = metcalf_standardised
    link_graph = npl.get_links(sources, primary_method, **scoring_params)
    if primary_method == "metcalf" and metcalf_standardised and len(link_graph.links) == 0:
        print("[WARN] standardised Metcalf produced 0 links; falling back to raw Metcalf")
        link_graph = npl.get_links(sources, primary_method, standardised=False)
    pairs = list(link_graph.links)

    rows_all = []
    rows_target = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        left, right = pair[0], pair[1]
        is_target_pair = bool(target) and (_has_target(left, target) or _has_target(right, target))
        data = link_graph.get_link_data(left, right)
        row = {
            "left_type": _obj_type(left),
            "left_id": _obj_id(left),
            "left_strains": _obj_strains(left),
            "right_type": _obj_type(right),
            "right_id": _obj_id(right),
            "right_strains": _obj_strains(right),
        }
        for method in methods:
            row[f"{method}_score"] = _score_value(data.get(method, None)) if hasattr(data, "get") else ""
        rows_all.append(row)
        if is_target_pair:
            rows_target.append(row)

    rows = rows_target if filter_target_only else rows_all
    if filter_target_only and len(rows) == 0 and allow_filter_fallback:
        print("[WARN] target-only filtering produced 0 links; falling back to unfiltered links")
        rows = rows_all

    score_key = f"{methods[0]}_score" if methods else "metcalf_score"
    rows.sort(key=lambda r: _as_float(r.get(score_key, 0.0) or 0.0), reverse=True)
    if max_pairs > 0:
        rows = rows[:max_pairs]

    fields = [
        "left_type",
        "left_id",
        "left_strains",
        "right_type",
        "right_id",
        "right_strains",
    ] + [f"{m}_score" for m in methods]

    with out_table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    summary_rows = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        left, right = pair[0], pair[1]
        genomic_obj = left if _is_genomic(left) else right
        metabolomic_obj = right if _is_genomic(left) else left
        if target and not (_has_target(left, target) or _has_target(right, target)):
            if filter_target_only and not allow_filter_fallback:
                continue
        data = link_graph.get_link_data(left, right)
        metcalf_value = _score_value(data.get(primary_method, None)) if hasattr(data, "get") else ""
        summary_rows.append(
            {
                "Class": "",
                "SM": f"{_obj_type(metabolomic_obj)}:{_obj_id(metabolomic_obj)}",
                "BGC": _pretty_bgc_label(genomic_obj),
                "Metcalf score": metcalf_value,
                "BGC source": _bgc_source(genomic_obj),
                "Bioactivity": "",
                "Status": "putative",
            }
        )

    deduped_summary = {}
    for row in summary_rows:
        key = (row["SM"], row["BGC"])
        existing = deduped_summary.get(key)
        if existing is None or _as_float(row["Metcalf score"]) > _as_float(existing["Metcalf score"]):
            deduped_summary[key] = row

    summary_rows = list(deduped_summary.values())
    summary_rows.sort(key=lambda r: _as_float(r.get("Metcalf score", 0.0) or 0.0), reverse=True)
    if max_pairs > 0:
        summary_rows = summary_rows[:max_pairs]

    summary_fields = ["Class", "SM", "BGC", "Metcalf score", "BGC source", "Bioactivity", "Status"]
    with summary_table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Wrote {len(rows)} links to {out_table}")
    print(f"Wrote {len(summary_rows)} summary rows to {summary_table}")


if __name__ == "__main__":
    main()
